#!/usr/bin/env python3
"""Build a compact MapLibre GeoJSON railway layer from Osmium GeoJSON Sequence."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable


Point = tuple[float, float]
Line = list[Point]


def iter_features(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, 1):
            text = raw_line.lstrip("\x1e").strip()
            if not text:
                continue
            try:
                yield json.loads(text)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid GeoJSON sequence") from error


def squared_segment_distance(point: Point, start: Point, end: Point) -> float:
    x, y = start
    dx = end[0] - x
    dy = end[1] - y
    if dx or dy:
        t = ((point[0] - x) * dx + (point[1] - y) * dy) / (dx * dx + dy * dy)
        if t > 1:
            x, y = end
        elif t > 0:
            x += dx * t
            y += dy * t
    dx = point[0] - x
    dy = point[1] - y
    return dx * dx + dy * dy


def simplify(line: Line, tolerance: float) -> Line:
    if len(line) <= 2 or tolerance <= 0:
        return line

    threshold = tolerance * tolerance
    keep = [False] * len(line)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(line) - 1)]

    while stack:
        first, last = stack.pop()
        farthest_index = -1
        farthest_distance = threshold
        for index in range(first + 1, last):
            distance = squared_segment_distance(line[index], line[first], line[last])
            if distance > farthest_distance:
                farthest_index = index
                farthest_distance = distance
        if farthest_index >= 0:
            keep[farthest_index] = True
            stack.append((first, farthest_index))
            stack.append((farthest_index, last))

    return [point for index, point in enumerate(line) if keep[index]]


def line_length_km(line: Line) -> float:
    total = 0.0
    for start, end in zip(line, line[1:]):
        latitude = math.radians((start[1] + end[1]) / 2)
        dx = (end[0] - start[0]) * 111.32 * math.cos(latitude)
        dy = (end[1] - start[1]) * 110.57
        total += math.hypot(dx, dy)
    return total


def normalize_coordinates(raw_coordinates, precision: int) -> Line:
    result: Line = []
    for raw_point in raw_coordinates:
        point = (round(float(raw_point[0]), precision), round(float(raw_point[1]), precision))
        if not result or point != result[-1]:
            result.append(point)
    return result


def display_name(properties: dict) -> str:
    return (
        properties.get("name:zh-Hans")
        or properties.get("name:zh")
        or properties.get("name")
        or ""
    )


def speed_value(properties: dict) -> int:
    raw_speed = str(properties.get("maxspeed", ""))
    digits = "".join(character for character in raw_speed if character.isdigit())
    return int(digits) if digits else 0


def category(properties: dict) -> str:
    if properties.get("highspeed") == "yes" or speed_value(properties) >= 250:
        return "highspeed"
    return "conventional"


def merge_segments(segments: list[Line]) -> list[Line]:
    if not segments:
        return []

    endpoints: dict[Point, list[int]] = defaultdict(list)
    for index, segment in enumerate(segments):
        endpoints[segment[0]].append(index)
        endpoints[segment[-1]].append(index)

    unused = set(range(len(segments)))
    ordered_indices = sorted(
        unused,
        key=lambda index: (
            len(endpoints[segments[index][0]]) == 2
            and len(endpoints[segments[index][-1]]) == 2
        ),
    )
    merged: list[Line] = []

    for initial_index in ordered_indices:
        if initial_index not in unused:
            continue

        segment = segments[initial_index]
        start_degree = len(endpoints[segment[0]])
        end_degree = len(endpoints[segment[-1]])
        if start_degree == 2 and end_degree != 2:
            segment = list(reversed(segment))

        chain = list(segment)
        unused.remove(initial_index)

        while True:
            endpoint = chain[-1]
            if len(endpoints[endpoint]) != 2:
                break
            candidates = [index for index in endpoints[endpoint] if index in unused]
            if len(candidates) != 1:
                break

            next_index = candidates[0]
            next_segment = segments[next_index]
            if next_segment[0] == endpoint:
                chain.extend(next_segment[1:])
            elif next_segment[-1] == endpoint:
                chain.extend(reversed(next_segment[:-1]))
            else:
                break
            unused.remove(next_index)

        merged.append(chain)

    return merged


def build_layer(
    source_path: Path,
    tolerance: float,
    precision: int,
    min_length_km: float,
    snapshot: str,
) -> tuple[dict, dict]:
    grouped: dict[tuple[str, str], list[Line]] = defaultdict(list)
    input_features = 0
    selected_features = 0

    for feature in iter_features(source_path):
        input_features += 1
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        if geometry.get("type") != "LineString":
            continue
        if properties.get("railway") != "rail":
            continue
        if properties.get("usage") not in {"main", "branch"}:
            continue

        coordinates = normalize_coordinates(geometry.get("coordinates") or [], precision)
        if len(coordinates) < 2:
            continue
        coordinates = simplify(coordinates, tolerance)
        grouped[(category(properties), display_name(properties))].append(coordinates)
        selected_features += 1

    output_lines = []
    coordinate_count = 0
    for (line_category, name), segments in grouped.items():
        for line in merge_segments(segments):
            line = simplify(line, tolerance)
            if len(line) < 2 or line_length_km(line) < min_length_km:
                continue
            item = {
                "category": line_category,
                "coords": [[longitude, latitude] for longitude, latitude in line],
            }
            if name:
                item["name"] = name
            output_lines.append(item)
            coordinate_count += len(line)

    output_lines.sort(
        key=lambda item: (
            item["category"],
            item.get("name", ""),
            item["coords"][0],
        )
    )
    category_lines: dict[str, list[list[list[float]]]] = defaultdict(list)
    for line in output_lines:
        category_lines[line["category"]].append(line["coords"])

    document = {
        "type": "FeatureCollection",
        "schemaVersion": 2,
        "source": {
            "provider": "OpenStreetMap contributors",
            "license": "ODbL-1.0",
            "snapshot": snapshot,
            "filter": "railway=rail and usage in (main, branch)",
            "simplifyToleranceDegrees": tolerance,
            "coordinatePrecision": precision,
            "minimumLengthKm": min_length_km,
            "lineCount": len(output_lines),
            "coordinateCount": coordinate_count,
        },
        "features": [
            {
                "type": "Feature",
                "properties": {"category": line_category},
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": category_lines[line_category],
                },
            }
            for line_category in ("conventional", "highspeed")
            if category_lines[line_category]
        ],
    }
    stats = {
        "inputFeatures": input_features,
        "selectedFeatures": selected_features,
        "groups": len(grouped),
        "outputLines": len(output_lines),
        "outputCoordinates": coordinate_count,
    }
    return document, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.005)
    parser.add_argument("--precision", type=int, default=5)
    parser.add_argument("--min-length-km", type=float, default=2.0)
    parser.add_argument("--snapshot", default="unknown")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    document, stats = build_layer(
        args.input,
        args.tolerance,
        args.precision,
        args.min_length_km,
        args.snapshot,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(document, target, ensure_ascii=False, separators=(",", ":"))
        target.write("\n")

    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(
        f"Railway layer built: {stats['selectedFeatures']}/{stats['inputFeatures']} "
        f"features -> {stats['outputLines']} lines, "
        f"{stats['outputCoordinates']} coordinates, {size_mb:.2f} MB."
    )


if __name__ == "__main__":
    main()
