"""Shared helpers for reading and inspecting Osmium GeoJSON sequences."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def iter_features(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, 1):
            text = raw_line.lstrip("\x1e").strip()
            if not text:
                continue
            try:
                yield json.loads(text)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid GeoJSON sequence"
                ) from error


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
