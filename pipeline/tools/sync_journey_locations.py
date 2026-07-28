#!/usr/bin/env python3
"""Add train stops missing from locations.json using local OSM catalogs."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

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
NAME_KEYS = (
    "name",
    "name:zh",
    "name:zh-Hans",
    "official_name",
    "short_name",
    "alt_name",
)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as source:
        return json.load(source)


def write_json(path: Path, document: dict) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(document, target, ensure_ascii=False, indent=2)
        target.write("\n")
    temporary.replace(path)


def normalized_station_name(name: str) -> str:
    value = unicodedata.normalize("NFKC", name).casefold()
    value = re.sub(r"[\s·•（）()\-—_/]+", "", value)
    suffixes = ("火车站", "铁路车站", "高铁站", "railwaystation", "station", "站")
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if value.endswith(suffix) and len(value) > len(suffix):
                value = value[: -len(suffix)]
                changed = True
                break
    return value


def split_names(properties: dict) -> list[str]:
    names = []
    for key in NAME_KEYS:
        value = properties.get(key)
        if not isinstance(value, str):
            continue
        for raw_name in value.split(";"):
            name = raw_name.strip()
            if name and name not in names:
                names.append(name)
    return names


def catalog_candidates(path: Path) -> list[dict]:
    if not path.exists():
        return []
    document = read_json(path)
    candidates = []
    for station in document.get("stations") or []:
        names = [station.get("name"), *(station.get("aliases") or [])]
        candidates.append(
            {
                "osmId": station.get("osmId"),
                "osmName": station.get("name"),
                "names": [name for name in names if isinstance(name, str)],
                "source": "passenger station catalog",
            }
        )
    return candidates


def osm_candidates(path: Path) -> list[dict]:
    candidates = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, 1):
            text = raw_line.lstrip("\x1e").strip()
            if not text:
                continue
            try:
                feature = json.loads(text)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid GeoJSON sequence"
                ) from error

            properties = feature.get("properties") or {}
            if properties.get("railway") not in {"station", "halt"}:
                continue
            if properties.get("station") in NON_MAINLINE_STATION_TYPES:
                continue
            if any(
                properties.get(key) == "yes"
                for key in ("subway", "light_rail", "monorail", "tram")
            ):
                continue
            names = split_names(properties)
            if not names:
                continue
            candidates.append(
                {
                    "osmId": feature.get("id"),
                    "osmName": names[0],
                    "names": names,
                    "source": "OSM station extract",
                }
            )
    return candidates


def build_name_index(candidates: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, dict[str, dict]] = defaultdict(dict)
    for candidate in candidates:
        osm_id = candidate.get("osmId")
        if not isinstance(osm_id, str):
            continue
        for name in candidate["names"]:
            normalized = normalized_station_name(name)
            if normalized:
                index[normalized][osm_id] = candidate
    return {name: list(by_id.values()) for name, by_id in index.items()}


def missing_train_stops(journeys: dict, locations: dict) -> list[str]:
    known_names = {
        location.get("name")
        for location in locations.get("locations") or []
        if isinstance(location, dict)
    }
    missing = []
    for journey in journeys.get("journeys") or []:
        if journey.get("mode") != "train":
            continue
        for name in journey.get("stops") or []:
            if name not in known_names and name not in missing:
                missing.append(name)
    return missing


def unique_location_id(osm_id: str, used_ids: set[str]) -> str:
    base = f"osm-{osm_id}"
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def sync_locations(
    journeys: dict,
    locations: dict,
    passenger_candidates: list[dict],
    fallback_candidates: list[dict],
    allowed_station_names: set[str] | None = None,
) -> list[dict]:
    missing = missing_train_stops(journeys, locations)
    if not missing:
        return []
    if allowed_station_names is not None:
        rejected = [name for name in missing if name not in allowed_station_names]
        if rejected:
            raise ValueError(
                "train stops absent from the passenger whitelist: "
                + ", ".join(rejected)
            )

    primary_index = build_name_index(passenger_candidates)
    fallback_index = build_name_index(fallback_candidates)
    used_ids = {
        location.get("id")
        for location in locations.get("locations") or []
        if isinstance(location, dict)
    }
    additions = []
    unresolved = []
    ambiguous = []

    for name in missing:
        normalized = normalized_station_name(name)
        matches = primary_index.get(normalized) or fallback_index.get(normalized) or []
        if not matches:
            unresolved.append(name)
            continue
        if len(matches) > 1:
            ambiguous.append((name, matches))
            continue
        match = matches[0]
        additions.append(
            {
                "id": unique_location_id(match["osmId"], used_ids),
                "type": "station",
                "name": name,
                "osmId": match["osmId"],
            }
        )

    if unresolved or ambiguous:
        messages = []
        if unresolved:
            messages.append(f"unresolved stops: {', '.join(unresolved)}")
        for name, matches in ambiguous:
            options = ", ".join(
                f"{candidate['osmId']} {candidate['osmName']}" for candidate in matches
            )
            messages.append(f"ambiguous stop {name}: {options}")
        raise ValueError("; ".join(messages))

    items = locations["locations"]
    first_airport = next(
        (index for index, item in enumerate(items) if item.get("type") == "airport"),
        len(items),
    )
    items[first_airport:first_airport] = additions
    return additions


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--journeys",
        type=Path,
        default=project_root / "data" / "source" / "journeys.json",
    )
    parser.add_argument(
        "--locations",
        type=Path,
        default=project_root / "data" / "source" / "locations.json",
    )
    parser.add_argument(
        "--passenger-stations",
        type=Path,
        default=project_root / "data" / "generated" / "passenger-stations.json",
    )
    parser.add_argument(
        "--osm-catalog",
        type=Path,
        required=True,
        help="GeoJSON sequence exported from OSM railway station features.",
    )
    parser.add_argument(
        "--station-names",
        type=Path,
        help="Optional station_name.js passenger whitelist.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    journeys = read_json(args.journeys)
    locations = read_json(args.locations)
    allowed_station_names = (
        {
            station["name"]
            for station in load_station_names(args.station_names)
        }
        if args.station_names is not None
        else None
    )
    additions = sync_locations(
        journeys,
        locations,
        catalog_candidates(args.passenger_stations),
        osm_candidates(args.osm_catalog),
        allowed_station_names,
    )
    if additions:
        write_json(args.locations, locations)
        print(f"Added {len(additions)} train stops to {args.locations}:")
        for addition in additions:
            print(
                f"  {addition['name']} -> {addition['osmId']} "
                f"({addition['id']})"
            )
    else:
        print("All train stops already exist in locations.json.")


if __name__ == "__main__":
    main()
