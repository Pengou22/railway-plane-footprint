#!/usr/bin/env python3
"""Build a compact nationwide passenger-station catalog from OSM."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from geojson_utils import candidate_names, geometry_center, iter_features

PROJECT_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(PROJECT_TOOLS) not in sys.path:
    sys.path.insert(0, str(PROJECT_TOOLS))

from station_name_catalog import load_station_names


NON_MAINLINE_STATION_TYPES = {
    "construction",
    "disused",
    "funicular",
    "light_rail",
    "monorail",
    "proposed",
    "subway",
    "tram",
}
PASSENGER_VALUES = {
    "designated",
    "international",
    "national",
    "regional",
    "yes",
}
PUBLIC_TRANSPORT_STATION_VALUES = {
    "halt",
    "station",
    "train_station",
}
NON_PASSENGER_NAME_PATTERN = re.compile(
    r"货场|货运|油库|卸油|装卸|作业区|编组|机务段|车辆段|工务段|"
    r"线路所|专用线|洗煤|选煤|煤矿|矿业|矿区|矿井|电厂|热电|"
    r"(?:矿|矿新)$"
)
GEOMETRY_SCORES = {
    "Point": 3,
    "Polygon": 2,
    "MultiPolygon": 2,
    "LineString": 1,
}
EARTH_RADIUS_KM = 6371.0088


def normalized_station_name(name: str) -> str:
    value = unicodedata.normalize("NFKC", name).casefold()
    value = re.sub(r"[\s·•（）()\-—_/]+", "", value)
    for suffix in ("火车站", "铁路车站", "高铁站", "railwaystation", "station", "站"):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def display_station_name(name: str) -> str:
    value = name.strip()
    for suffix in ("火车站", "铁路车站", "高铁站", "站"):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def distance_km(first, second) -> float:
    latitude = math.radians((first[1] + second[1]) / 2)
    dx = (second[0] - first[0]) * 111.32 * math.cos(latitude)
    dy = (second[1] - first[1]) * 110.57
    return math.hypot(dx, dy)


def unit_sphere(points: list[tuple[float, float]]) -> np.ndarray:
    radians = np.radians(np.asarray(points, dtype=np.float64))
    longitude = radians[:, 0]
    latitude = radians[:, 1]
    cosine = np.cos(latitude)
    return np.column_stack(
        (
            cosine * np.cos(longitude),
            cosine * np.sin(longitude),
            np.sin(latitude),
        )
    )


def load_railway_points(path: Path) -> list[tuple[float, float]]:
    points: set[tuple[float, float]] = set()
    for feature in iter_features(path):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if properties.get("railway") != "rail":
            continue
        if geometry.get("type") != "LineString":
            continue
        for raw_point in geometry.get("coordinates") or []:
            points.add((round(float(raw_point[0]), 6), round(float(raw_point[1]), 6)))
    return sorted(points)


def explicitly_non_heavy_rail(properties: dict) -> bool:
    if properties.get("station") in NON_MAINLINE_STATION_TYPES:
        return True
    if any(
        properties.get(key) == "yes"
        for key in ("subway", "light_rail", "monorail", "tram")
    ):
        return True
    return False


def explicitly_non_mainline(properties: dict) -> bool:
    return explicitly_non_heavy_rail(properties) or (
        properties.get("train") == "no"
        or properties.get("passenger") == "no"
        or properties.get("public_transport") == "no"
        or properties.get("freight") == "yes"
        or properties.get("cargo") == "yes"
        or properties.get("industrial") == "yes"
        or properties.get("usage") in {"freight", "industrial"}
    )


def passenger_evidence(properties: dict) -> tuple[str, str] | None:
    if str(properties.get("passenger", "")).lower() in PASSENGER_VALUES:
        return "confirmed", f"passenger={properties['passenger']}"
    if properties.get("railway") == "halt":
        return "confirmed", "railway=halt"
    if (
        properties.get("train") == "yes"
        and properties.get("public_transport")
        in PUBLIC_TRANSPORT_STATION_VALUES
    ):
        return "confirmed", "train=yes + public_transport=station"
    return None


def load_passenger_name_index(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    index = {}
    for station in load_station_names(path):
        normalized = normalized_station_name(station["name"])
        if normalized in index:
            raise ValueError(
                f"{path}: normalized station name is ambiguous: "
                f"{station['name']}"
            )
        index[normalized] = station
    return index


def load_china_polygons(path: Path):
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    polygons = []
    for feature in document.get("features") or []:
        properties = feature.get("properties") or {}
        if str(properties.get("adcode") or "") == "100000_JD":
            continue
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        raw_polygons = (
            [coordinates]
            if geometry.get("type") == "Polygon"
            else coordinates
            if geometry.get("type") == "MultiPolygon"
            else []
        )
        for polygon in raw_polygons:
            if not polygon or not polygon[0]:
                continue
            longitudes = [point[0] for point in polygon[0]]
            latitudes = [point[1] for point in polygon[0]]
            polygons.append(
                (
                    min(longitudes),
                    max(longitudes),
                    min(latitudes),
                    max(latitudes),
                    polygon,
                )
            )
    if not polygons:
        raise ValueError("No China boundary polygons were found")
    return polygons


def point_in_ring(point, ring) -> bool:
    longitude, latitude = point
    inside = False
    previous_index = len(ring) - 1
    for index, current in enumerate(ring):
        previous = ring[previous_index]
        if (
            (current[1] > latitude) != (previous[1] > latitude)
            and longitude
            < (
                (previous[0] - current[0])
                * (latitude - current[1])
                / (previous[1] - current[1])
                + current[0]
            )
        ):
            inside = not inside
        previous_index = index
    return inside


def inside_china(point, polygons) -> bool:
    longitude, latitude = point
    for minimum_x, maximum_x, minimum_y, maximum_y, polygon in polygons:
        if not (
            minimum_x <= longitude <= maximum_x
            and minimum_y <= latitude <= maximum_y
        ):
            continue
        if point_in_ring(point, polygon[0]) and not any(
            point_in_ring(point, hole) for hole in polygon[1:]
        ):
            return True
    return False


def candidate_score(candidate: dict) -> tuple:
    properties = candidate["properties"]
    return (
        candidate["primaryNameMatch"],
        candidate["confidence"] == "confirmed",
        properties.get("train") == "yes",
        properties.get("usage") == "main",
        bool(properties.get("railway:ref")),
        bool(properties.get("wikidata")),
        GEOMETRY_SCORES.get(candidate["geometryType"], 0),
        str(candidate["osmId"]).startswith("n"),
    )


def cluster_candidates(candidates: list[dict], radius_km: float) -> list[list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        groups[candidate["matchName"]].append(candidate)

    clusters = []
    for group in groups.values():
        local_clusters: list[list[dict]] = []
        for candidate in group:
            matching_cluster = next(
                (
                    cluster
                    for cluster in local_clusters
                    if min(
                        distance_km(candidate["coordinates"], item["coordinates"])
                        for item in cluster
                    )
                    <= radius_km
                ),
                None,
            )
            if matching_cluster is None:
                local_clusters.append([candidate])
            else:
                matching_cluster.append(candidate)
        clusters.extend(local_clusters)
    return clusters


def station_level(properties: dict) -> tuple[str, str]:
    if properties.get("usage") == "main":
        return "major", "usage=main"
    if properties.get("railway") == "halt":
        return "halt", "railway=halt"
    return "station", "railway=station"


def build_catalog(
    station_features: Path,
    railway_features: Path,
    china_boundary: Path,
    passenger_whitelist: Path | None,
    maximum_rail_distance_km: float,
    duplicate_radius_km: float,
    snapshot: str,
) -> dict:
    rail_points = load_railway_points(railway_features)
    if not rail_points:
        raise ValueError("No railway=rail coordinates were found")
    rail_tree = cKDTree(unit_sphere(rail_points))
    china_polygons = load_china_polygons(china_boundary)
    passenger_name_index = load_passenger_name_index(passenger_whitelist)

    raw_candidates = []
    for feature in iter_features(station_features):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if properties.get("railway") not in {"station", "halt"}:
            continue

        names = candidate_names(properties)
        center = geometry_center(geometry)
        osm_id = feature.get("id")
        if not names or center is None or not osm_id:
            continue

        primary_passenger_station = passenger_name_index.get(
            normalized_station_name(names[0])
        )
        passenger_matches = {
            passenger_name_index[normalized_station_name(name)]["name"]:
            passenger_name_index[normalized_station_name(name)]
            for name in names[1:]
            if normalized_station_name(name) in passenger_name_index
        }
        if primary_passenger_station is not None:
            passenger_station = primary_passenger_station
        elif len(passenger_matches) == 1:
            passenger_station = next(iter(passenger_matches.values()))
        elif len(passenger_matches) > 1:
            continue
        else:
            passenger_station = None
        if (
            explicitly_non_heavy_rail(properties)
            if passenger_station is not None
            else explicitly_non_mainline(properties)
        ):
            continue
        if (
            passenger_station is None
            and NON_PASSENGER_NAME_PATTERN.search(display_station_name(names[0]))
        ):
            continue
        if not inside_china(center, china_polygons):
            continue
        if passenger_name_index:
            evidence = (
                ("confirmed", "station_name.js passenger whitelist")
                if passenger_station is not None
                else None
            )
        else:
            evidence = passenger_evidence(properties)
        if evidence is None:
            continue

        chord_distance, _ = rail_tree.query(unit_sphere([center])[0], k=1)
        rail_distance_km = (
            2 * EARTH_RADIUS_KM * math.asin(min(1.0, float(chord_distance) / 2))
        )
        if rail_distance_km > maximum_rail_distance_km:
            continue

        confidence, evidence_source = evidence
        display_name = (
            passenger_station["name"]
            if passenger_station is not None
            else display_station_name(names[0])
        )
        raw_candidates.append(
            {
                "osmId": osm_id,
                "name": display_name,
                "osmName": names[0],
                "aliases": sorted(
                    {
                        display_station_name(name)
                        for name in names
                        if display_station_name(name)
                        and display_station_name(name) != display_name
                    }
                ),
                "matchName": normalized_station_name(display_name),
                "coordinates": center,
                "geometryType": geometry.get("type", ""),
                "confidence": confidence,
                "evidence": evidence_source,
                "mainlineDistanceKm": rail_distance_km,
                "primaryNameMatch": (
                    normalized_station_name(names[0])
                    == normalized_station_name(display_name)
                ),
                "passengerStation": passenger_station,
                "properties": properties,
            }
        )

    stations = []
    if passenger_name_index:
        candidates_by_name: dict[str, list[dict]] = defaultdict(list)
        for candidate in raw_candidates:
            candidates_by_name[candidate["matchName"]].append(candidate)
        candidate_groups = list(candidates_by_name.values())
    else:
        candidate_groups = cluster_candidates(raw_candidates, duplicate_radius_km)

    for cluster in candidate_groups:
        candidate = max(cluster, key=candidate_score)
        properties = candidate.pop("properties")
        passenger_station = candidate.pop("passengerStation")
        candidate.pop("primaryNameMatch")
        candidate.pop("geometryType")
        level, level_source = station_level(properties)
        candidate["coordinates"] = [
            round(candidate["coordinates"][0], 6),
            round(candidate["coordinates"][1], 6),
        ]
        candidate["mainlineDistanceKm"] = round(candidate["mainlineDistanceKm"], 3)
        candidate["level"] = level
        candidate["levelSource"] = level_source
        if properties.get("railway:ref"):
            candidate["railwayRef"] = str(properties["railway:ref"])
        if properties.get("operator"):
            candidate["operator"] = properties["operator"]
        if passenger_station is not None:
            candidate["telecode"] = passenger_station["telecode"]
            candidate["pinyin"] = passenger_station["pinyin"]
            candidate["shortPinyin"] = passenger_station["shortPinyin"]
            candidate["cityCode"] = passenger_station["cityCode"]
            candidate["city"] = passenger_station["city"]
        stations.append(candidate)

    stations.sort(key=lambda item: (item["name"], item["osmId"]))
    matched_whitelist_names = {
        station["name"] for station in stations if "telecode" in station
    }
    unmatched_whitelist_names = sorted(
        station["name"]
        for station in passenger_name_index.values()
        if station["name"] not in matched_whitelist_names
    )
    return {
        "schemaVersion": 1,
        "source": {
            "provider": "OpenStreetMap contributors",
            "license": "ODbL-1.0",
            "snapshot": snapshot,
            "selection": (
                "domestic passenger station names from station_name.js matched "
                "to named non-metro OSM stations inside China; "
                f"within {maximum_rail_distance_km:g} km of railway=rail"
            ),
            "passengerWhitelist": (
                {
                    "file": passenger_whitelist.name,
                    "domesticNames": len(passenger_name_index),
                    "matchedNames": len(matched_whitelist_names),
                    "unmatchedNames": unmatched_whitelist_names,
                }
                if passenger_whitelist is not None
                else None
            ),
        },
        "levels": {
            "major": "OSM usage=main",
            "station": "OSM railway=station",
            "halt": "OSM railway=halt",
        },
        "stations": stations,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", type=Path, required=True)
    parser.add_argument("--railways", type=Path, required=True)
    parser.add_argument("--china-boundary", type=Path, required=True)
    parser.add_argument("--passenger-whitelist", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--maximum-rail-distance-km", type=float, default=3.0)
    parser.add_argument("--duplicate-radius-km", type=float, default=3.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    document = build_catalog(
        args.stations,
        args.railways,
        args.china_boundary,
        args.passenger_whitelist,
        args.maximum_rail_distance_km,
        args.duplicate_radius_km,
        args.snapshot,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(document, target, ensure_ascii=False, separators=(",", ":"))
        target.write("\n")
    counts: dict[str, int] = defaultdict(int)
    for station in document["stations"]:
        counts[station["level"]] += 1
    print(
        f"Passenger stations built: {len(document['stations'])} "
        f"({dict(counts)}), {args.output.stat().st_size / 1024:.1f} KB."
    )


if __name__ == "__main__":
    main()
