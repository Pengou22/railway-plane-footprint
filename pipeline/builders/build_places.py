#!/usr/bin/env python3
"""Bind project locations to OSM features and generate current coordinates."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Candidate:
    osm_id: str
    place_type: str
    name: str
    names: tuple[str, ...]
    normalized_names: tuple[str, ...]
    coordinates: tuple[float, float]
    geometry_type: str


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def write_json(path: Path, value, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as target:
        if compact:
            json.dump(value, target, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(value, target, ensure_ascii=False, indent=2)
        target.write("\n")


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


def ring_area_and_centroid(ring) -> tuple[float, tuple[float, float]]:
    area_twice = 0.0
    centroid_x = 0.0
    centroid_y = 0.0
    for start, end in zip(ring, ring[1:] + ring[:1]):
        cross = start[0] * end[1] - end[0] * start[1]
        area_twice += cross
        centroid_x += (start[0] + end[0]) * cross
        centroid_y += (start[1] + end[1]) * cross
    if abs(area_twice) < 1e-12:
        longitude = sum(point[0] for point in ring) / len(ring)
        latitude = sum(point[1] for point in ring) / len(ring)
        return 0.0, (longitude, latitude)
    return (
        abs(area_twice) / 2,
        (centroid_x / (3 * area_twice), centroid_y / (3 * area_twice)),
    )


def geometry_center(geometry: dict) -> tuple[float, float] | None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if not coordinates:
        return None
    if geometry_type == "Point":
        return float(coordinates[0]), float(coordinates[1])
    if geometry_type == "LineString":
        return (
            sum(point[0] for point in coordinates) / len(coordinates),
            sum(point[1] for point in coordinates) / len(coordinates),
        )
    if geometry_type == "Polygon":
        _, center = ring_area_and_centroid(coordinates[0])
        return center
    if geometry_type == "MultiPolygon":
        polygons = [ring_area_and_centroid(polygon[0]) for polygon in coordinates]
        return max(polygons, key=lambda item: item[0])[1]
    return None


def candidate_names(properties: dict) -> tuple[str, ...]:
    keys = (
        "name",
        "name:zh",
        "name:zh-Hans",
        "official_name",
        "short_name",
        "alt_name",
    )
    names = []
    for key in keys:
        value = properties.get(key)
        if not isinstance(value, str):
            continue
        for name in value.split(";"):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return tuple(names)


def load_candidates(path: Path) -> list[Candidate]:
    candidates = []
    for feature in iter_features(path):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        osm_id = feature.get("id")
        names = candidate_names(properties)
        center = geometry_center(geometry)
        if not osm_id or not names or center is None:
            continue

        if properties.get("aeroway") == "aerodrome":
            place_type = "airport"
        elif properties.get("railway") in {"station", "halt"}:
            if (
                properties.get("station")
                in {"subway", "light_rail", "monorail", "funicular", "tram"}
                or any(
                    properties.get(key) == "yes"
                    for key in ("subway", "light_rail", "monorail", "tram")
                )
                or properties.get("train") == "no"
            ):
                continue
            place_type = "station"
        else:
            continue

        candidates.append(
            Candidate(
                osm_id=osm_id,
                place_type=place_type,
                name=names[0],
                names=names,
                normalized_names=tuple(
                    normalized_name(name, place_type) for name in names
                ),
                coordinates=center,
                geometry_type=geometry.get("type", ""),
            )
        )
    return candidates


def normalized_name(name: str, place_type: str) -> str:
    value = unicodedata.normalize("NFKC", name).casefold()
    value = re.sub(r"[\s·•（）()\-—_/]+", "", value)
    suffixes = (
        ("火车站", "铁路车站", "高铁站", "railwaystation", "station", "站")
        if place_type == "station"
        else ("国际机场", "机场", "航空港", "internationalairport", "airport")
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if value.endswith(suffix) and len(value) > len(suffix):
                value = value[: -len(suffix)]
                changed = True
                break
    return value


def name_similarity(expected: str, candidate: Candidate) -> float:
    expected_normalized = normalized_name(expected, candidate.place_type)
    best = 0.0
    for candidate_normalized in candidate.normalized_names:
        if not candidate_normalized:
            continue
        if expected_normalized == candidate_normalized:
            return 1.0
        if (
            expected_normalized in candidate_normalized
            or candidate_normalized in expected_normalized
        ):
            best = max(best, 0.92)
        best = max(
            best,
            SequenceMatcher(None, expected_normalized, candidate_normalized).ratio(),
        )
    return best


def distance_km(first, second) -> float:
    latitude = math.radians((first[1] + second[1]) / 2)
    dx = (second[0] - first[0]) * 111.32 * math.cos(latitude)
    dy = (second[1] - first[1]) * 110.57
    return math.hypot(dx, dy)


def bind_location(
    location: dict,
    candidates: list[Candidate],
    name_index: dict[tuple[str, str], list[Candidate]],
) -> tuple[Candidate, float, float]:
    expected_type = location["type"]
    expected_name = location["name"]
    expected_coordinates = location.get("coordinates")
    expected_normalized = normalized_name(expected_name, expected_type)
    exact_candidates = name_index.get((expected_type, expected_normalized), [])
    if not expected_coordinates:
        if len(exact_candidates) == 1:
            return exact_candidates[0], 1.0, 0.0
        if len(exact_candidates) > 1:
            options = ", ".join(
                f"{candidate.osm_id} {candidate.name}"
                for candidate in exact_candidates[:12]
            )
            raise ValueError(
                f"{location['id']} ({expected_name}): multiple exact OSM matches; "
                f"set osmId explicitly. Candidates: {options}"
            )
        raise ValueError(
            f"{location['id']} ({expected_name}): no unique OSM name match; "
            "set osmId explicitly"
        )

    candidate_pool = exact_candidates
    if not candidate_pool:
        candidate_pool = [
            candidate
            for candidate in candidates
            if candidate.place_type == expected_type
            and any(
                expected_normalized in name or name in expected_normalized
                for name in candidate.normalized_names
            )
        ]

    ranked = []
    distance_limit = 30 if expected_type == "station" else 100
    for candidate in candidate_pool:
        similarity = name_similarity(expected_name, candidate)
        if similarity < 0.5:
            continue
        distance = distance_km(expected_coordinates, candidate.coordinates)
        if distance > distance_limit:
            continue
        geometry_preference = 0.0
        if expected_type == "station" and candidate.geometry_type != "Point":
            geometry_preference = 0.35
        if expected_type == "airport" and candidate.geometry_type == "Point":
            geometry_preference = 0.15
        score = (1 - similarity) * 12 + distance + geometry_preference
        ranked.append((score, -similarity, distance, candidate))

    if not ranked:
        raise ValueError(
            f"{location['id']} ({expected_name}): no matching OSM {expected_type}"
        )
    ranked.sort(key=lambda item: item[:3])
    _, negative_similarity, distance, candidate = ranked[0]
    return candidate, -negative_similarity, distance


def build_places(
    location_document: dict,
    candidates: list[Candidate],
    *,
    allow_binding: bool,
) -> tuple[dict, dict, list[str]]:
    candidates_by_id = {candidate.osm_id: candidate for candidate in candidates}
    name_index: dict[tuple[str, str], list[Candidate]] = {}
    for candidate in candidates:
        for name in candidate.normalized_names:
            name_index.setdefault((candidate.place_type, name), []).append(candidate)
    bound_locations = []
    generated_places = []
    report = []

    for location in location_document["locations"]:
        osm_id = location.get("osmId")
        if osm_id:
            candidate = candidates_by_id.get(osm_id)
            if candidate is None:
                if allow_binding:
                    candidate, similarity, distance = bind_location(
                        location,
                        candidates,
                        name_index,
                    )
                    osm_id = candidate.osm_id
                else:
                    raise ValueError(
                        f"{location['id']}: bound OSM feature {osm_id!r} is missing"
                    )
            else:
                similarity = name_similarity(location["name"], candidate)
                distance = None
        elif allow_binding:
            candidate, similarity, distance = bind_location(
                location,
                candidates,
                name_index,
            )
            osm_id = candidate.osm_id
        else:
            raise ValueError(f"{location['id']}: osmId binding is required")

        if candidate.place_type != location["type"]:
            raise ValueError(
                f"{location['id']}: {osm_id} is {candidate.place_type}, "
                f"expected {location['type']}"
            )

        bound_locations.append(
            {
                "id": location["id"],
                "type": location["type"],
                "name": location["name"],
                "osmId": osm_id,
            }
        )
        generated_places.append(
            {
                "id": location["id"],
                "type": location["type"],
                "name": location["name"],
                "coordinates": [
                    round(candidate.coordinates[0], 6),
                    round(candidate.coordinates[1], 6),
                ],
                "osmId": osm_id,
                "osmName": candidate.name,
            }
        )
        if distance is not None:
            report.append(
                f"{location['id']}: {location['name']} -> {osm_id} "
                f"{candidate.name} ({distance:.2f} km, name {similarity:.2f})"
            )

    return (
        {"schemaVersion": 3, "locations": bound_locations},
        {
            "schemaVersion": 1,
            "source": {
                "provider": "OpenStreetMap contributors",
                "license": "ODbL-1.0",
            },
            "places": generated_places,
        },
        report,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--locations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--write-bindings",
        action="store_true",
        help="Match unbound version 2 locations and rewrite them as version 3.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    candidates = load_candidates(args.catalog)
    location_document = read_json(args.locations)
    if args.output.exists():
        previous_places = read_json(args.output).get("places", [])
        previous_coordinates = {
            place.get("id"): place.get("coordinates")
            for place in previous_places
            if isinstance(place, dict)
        }
        for location in location_document.get("locations", []):
            coordinates = previous_coordinates.get(location.get("id"))
            if coordinates:
                location["coordinates"] = coordinates
    bound, generated, report = build_places(
        location_document,
        candidates,
        allow_binding=args.write_bindings,
    )
    if report:
        print("OSM location bindings:")
        for line in report:
            print(f"  {line}")
    if args.write_bindings:
        write_json(args.locations, bound)
    write_json(args.output, generated)
    print(
        f"Generated {len(generated['places'])} places from "
        f"{len(candidates)} OSM candidates."
    )


if __name__ == "__main__":
    main()
