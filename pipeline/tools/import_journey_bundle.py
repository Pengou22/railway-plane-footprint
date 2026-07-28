#!/usr/bin/env python3
"""Import a journey update bundle downloaded from the static map page."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def validate_bundle(document: dict) -> tuple[dict, dict]:
    if document.get("schemaVersion") != 1:
        raise ValueError("Update bundle schemaVersion must be 1")
    locations = document.get("locations")
    journeys = document.get("journeys")
    if not isinstance(locations, dict) or locations.get("schemaVersion") != 3:
        raise ValueError("Bundle does not contain a valid locations.json document")
    if not isinstance(locations.get("locations"), list):
        raise ValueError("Bundle locations must be an array")
    if not isinstance(journeys, dict) or journeys.get("schemaVersion") != 3:
        raise ValueError("Bundle does not contain a valid journeys.json document")
    if not isinstance(journeys.get("journeys"), list):
        raise ValueError("Bundle journeys must be an array")

    location_names = {
        location.get("name")
        for location in locations["locations"]
        if isinstance(location, dict)
    }
    if None in location_names or len(location_names) != len(locations["locations"]):
        raise ValueError("Location names must be present and globally unique")
    for journey in journeys["journeys"]:
        if not isinstance(journey, dict):
            raise ValueError("Every journey must be an object")
        unknown = set(journey.get("stops", [])) - location_names
        if unknown:
            raise ValueError(
                f"Journey {journey.get('id', '<unknown>')} references unknown "
                f"locations: {sorted(unknown)}"
            )
    return locations, journeys


def atomic_write(path: Path, document: dict) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(document, target, ensure_ascii=False, indent=2)
        target.write("\n")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    locations, journeys = validate_bundle(read_json(args.bundle))
    data_directory = args.project_root.resolve() / "data" / "source"
    if not data_directory.is_dir():
        raise ValueError(f"Project data directory does not exist: {data_directory}")
    atomic_write(data_directory / "locations.json", locations)
    atomic_write(data_directory / "journeys.json", journeys)
    print(
        f"Imported {len(locations['locations'])} locations and "
        f"{len(journeys['journeys'])} journeys."
    )
    print(
        "Next run pipeline/build.ps1 to refresh OSM "
        "coordinates and railway routes."
    )


if __name__ == "__main__":
    main()
