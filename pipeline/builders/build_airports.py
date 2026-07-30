#!/usr/bin/env python3
"""Build a nationwide scheduled-passenger airport catalog from OSM."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from build_passenger_stations import inside_china, load_china_polygons
from geojson_utils import candidate_names, geometry_center, iter_features


IATA_PATTERN = re.compile(r"^[A-Z]{3}$")
GENERAL_AVIATION_PATTERN = re.compile(
    r"通用|通航|航空运动|飞行俱乐部|飞行学院|飞行学校|飞行训练|"
    r"general[\s_-]*aviation|flying[\s_-]*club|flight[\s_-]*school",
    re.IGNORECASE,
)
NON_PASSENGER_AERODROME_TYPES = {
    "airfield",
    "closed",
    "general_aviation",
    "private",
}
PUBLIC_AERODROME_TYPES = {
    "international",
    "military/public",
    "public",
    "regional",
}
GEOMETRY_SCORES = {
    "MultiPolygon": 4,
    "Polygon": 4,
    "Point": 3,
    "LineString": 1,
}


def clean_names(properties: dict) -> tuple[str, ...]:
    names = list(candidate_names(properties))
    for key in ("name:zh-Hans", "name:zh", "official_name:zh"):
        value = properties.get(key)
        if not isinstance(value, str):
            continue
        for name in value.split(";"):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return tuple(names)


def display_name(properties: dict, names: tuple[str, ...]) -> str:
    for key in ("name:zh-Hans", "name:zh", "official_name:zh"):
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.split(";")[0].strip()
    return names[0]


def normalized_airport_name(name: str) -> str:
    value = name.casefold()
    value = re.sub(r"[\s·•（）()\-—_/]+", "", value)
    suffixes = ("国际机场", "机场", "航空港", "internationalairport", "airport")
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if value.endswith(suffix) and len(value) > len(suffix):
                value = value[: -len(suffix)]
                changed = True
                break
    return value


def general_aviation_evidence(properties: dict, names: tuple[str, ...]) -> str | None:
    aerodrome_type = str(properties.get("aerodrome:type") or "").casefold()
    if aerodrome_type in NON_PASSENGER_AERODROME_TYPES:
        return f"aerodrome:type={aerodrome_type}"
    if str(properties.get("access") or "").casefold() == "private":
        return "access=private"
    if any(
        str(properties.get(key) or "").casefold() in {"yes", "true", "1"}
        for key in ("abandoned", "disused")
    ):
        return "abandoned/disused"
    text = " ".join(
        [
            *names,
            str(properties.get("operator") or ""),
            str(properties.get("description") or ""),
        ]
    )
    if GENERAL_AVIATION_PATTERN.search(text):
        return "general-aviation name or operator"
    return None


def candidate_score(candidate: dict) -> tuple:
    properties = candidate["properties"]
    aerodrome_type = str(properties.get("aerodrome:type") or "").casefold()
    return (
        aerodrome_type in PUBLIC_AERODROME_TYPES,
        bool(properties.get("name:zh-Hans") or properties.get("name:zh")),
        GEOMETRY_SCORES.get(candidate["geometryType"], 0),
        bool(properties.get("icao")),
        str(candidate["osmId"]).startswith("a"),
        str(candidate["osmId"]).startswith("w"),
    )


def build_catalog(
    aerodrome_features: Path,
    china_boundary: Path,
    snapshot: str,
) -> dict:
    china_polygons = load_china_polygons(china_boundary)
    grouped_candidates: dict[str, list[dict]] = defaultdict(list)
    excluded_general_aviation = 0
    excluded_without_passenger_evidence = 0
    excluded_outside_china = 0

    for feature in iter_features(aerodrome_features):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if properties.get("aeroway") != "aerodrome":
            continue

        names = clean_names(properties)
        center = geometry_center(geometry)
        osm_id = feature.get("id")
        if not names or center is None or not osm_id:
            continue
        if not inside_china(center, china_polygons):
            excluded_outside_china += 1
            continue

        iata = str(properties.get("iata") or "").strip().upper()
        scheduled_service = (
            str(properties.get("scheduled_service") or "").strip().casefold()
        )
        if not IATA_PATTERN.fullmatch(iata) and scheduled_service != "yes":
            excluded_without_passenger_evidence += 1
            continue

        if general_aviation_evidence(properties, names) is not None:
            excluded_general_aviation += 1
            continue

        grouped_candidates[iata].append(
            {
                "osmId": str(osm_id),
                "name": display_name(properties, names),
                "names": names,
                "coordinates": center,
                "geometryType": geometry.get("type", ""),
                "properties": properties,
            }
        )

    airports = []
    for iata, candidates in grouped_candidates.items():
        candidate = max(candidates, key=candidate_score)
        properties = candidate["properties"]
        name = candidate["name"]
        aliases = sorted(
            {
                alias
                for item in candidates
                for alias in item["names"]
                if alias and normalized_airport_name(alias) != normalized_airport_name(name)
            }
        )
        airport = {
            "osmId": candidate["osmId"],
            "osmIds": sorted({item["osmId"] for item in candidates}),
            "name": name,
            "osmName": str(properties.get("name") or name),
            "aliases": aliases,
            "coordinates": [
                round(candidate["coordinates"][0], 6),
                round(candidate["coordinates"][1], 6),
            ],
            "iata": iata,
            "evidence": (
                "OSM scheduled_service=yes"
                if str(properties.get("scheduled_service") or "").casefold() == "yes"
                else f"OSM iata={iata}"
            ),
        }
        if properties.get("icao"):
            airport["icao"] = str(properties["icao"]).strip().upper()
        if properties.get("aerodrome:type"):
            airport["aerodromeType"] = str(properties["aerodrome:type"])
        if properties.get("operator"):
            airport["operator"] = str(properties["operator"])
        airports.append(airport)

    airports.sort(key=lambda item: (item["name"], item["iata"]))
    return {
        "schemaVersion": 1,
        "source": {
            "provider": "OpenStreetMap contributors",
            "license": "ODbL-1.0",
            "snapshot": snapshot,
            "selection": (
                "named aeroway=aerodrome features inside China with a valid "
                "three-letter IATA code or scheduled_service=yes; explicit "
                "general-aviation, private, disused and abandoned aerodromes excluded"
            ),
            "excluded": {
                "generalAviation": excluded_general_aviation,
                "withoutPassengerEvidence": excluded_without_passenger_evidence,
                "outsideChina": excluded_outside_china,
            },
        },
        "airports": airports,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aerodromes", type=Path, required=True)
    parser.add_argument("--china-boundary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    document = build_catalog(
        args.aerodromes,
        args.china_boundary,
        args.snapshot,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(document, target, ensure_ascii=False, separators=(",", ":"))
        target.write("\n")
    print(
        f"Passenger airports built: {len(document['airports'])}, "
        f"{args.output.stat().st_size / 1024:.1f} KB."
    )


if __name__ == "__main__":
    main()
