#!/usr/bin/env python3
"""Validate all published data used by the footprint map."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path


ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
OSM_ID_PATTERN = re.compile(r"^[nwra]\d+$")
LOCATION_TYPES = {"station", "airport"}
JOURNEY_MODES = {"train", "flight"}


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_locations(path: Path, errors: list[str]) -> dict[str, dict]:
    document = read_json(path)
    require(document.get("schemaVersion") == 3, f"{path}: schemaVersion must be 3", errors)
    items = document.get("locations")
    require(isinstance(items, list), f"{path}: locations must be an array", errors)
    if not isinstance(items, list):
        return {}

    by_id: dict[str, dict] = {}
    names: Counter[str] = Counter()
    for index, item in enumerate(items):
        label = f"{path}: locations[{index}]"
        require(isinstance(item, dict), f"{label} must be an object", errors)
        if not isinstance(item, dict):
            continue

        location_id = item.get("id")
        require(
            isinstance(location_id, str) and bool(ID_PATTERN.fullmatch(location_id)),
            f"{label}.id must be a lowercase stable identifier",
            errors,
        )
        if isinstance(location_id, str):
            require(location_id not in by_id, f"{label}: duplicate id {location_id}", errors)
            by_id[location_id] = item

        location_type = item.get("type")
        require(location_type in LOCATION_TYPES, f"{label}.type is invalid", errors)

        name = item.get("name")
        require(isinstance(name, str) and bool(name.strip()), f"{label}.name is required", errors)
        if isinstance(name, str):
            names[name] += 1

        osm_id = item.get("osmId")
        require(
            isinstance(osm_id, str) and bool(OSM_ID_PATTERN.fullmatch(osm_id)),
            f"{label}.osmId must be an exported OSM feature id",
            errors,
        )

    for name, count in names.items():
        require(
            count == 1,
            f"{path}: duplicate location name {name!r}",
            errors,
        )
    return by_id


def validate_places(
    path: Path,
    locations: dict[str, dict],
    errors: list[str],
) -> dict[str, dict]:
    document = read_json(path)
    require(document.get("schemaVersion") == 1, f"{path}: schemaVersion must be 1", errors)
    items = document.get("places")
    require(isinstance(items, list), f"{path}: places must be an array", errors)
    if not isinstance(items, list):
        return {}

    by_id = {}
    for index, item in enumerate(items):
        label = f"{path}: places[{index}]"
        require(isinstance(item, dict), f"{label} must be an object", errors)
        if not isinstance(item, dict):
            continue
        place_id = item.get("id")
        require(place_id in locations, f"{label}: unknown source id {place_id!r}", errors)
        require(place_id not in by_id, f"{label}: duplicate id {place_id!r}", errors)
        by_id[place_id] = item

        if place_id in locations:
            source = locations[place_id]
            for field in ("type", "name", "osmId"):
                require(
                    item.get(field) == source.get(field),
                    f"{label}.{field} differs from locations.json",
                    errors,
                )

        coordinates = item.get("coordinates")
        valid_coordinates = (
            isinstance(coordinates, list)
            and len(coordinates) == 2
            and all(
                isinstance(value, (int, float)) and math.isfinite(value)
                for value in coordinates
            )
        )
        require(
            valid_coordinates,
            f"{label}.coordinates must be [longitude, latitude]",
            errors,
        )
        if valid_coordinates:
            longitude, latitude = coordinates
            require(70 <= longitude <= 140, f"{label}: longitude is outside China", errors)
            require(0 <= latitude <= 60, f"{label}: latitude is outside China", errors)

    require(
        set(by_id) == set(locations),
        f"{path}: generated places do not exactly match locations.json",
        errors,
    )
    return by_id


def validate_journeys(
    path: Path,
    locations: dict[str, dict],
    errors: list[str],
) -> tuple[Counter[str], dict[str, dict]]:
    document = read_json(path)
    require(document.get("schemaVersion") == 3, f"{path}: schemaVersion must be 3", errors)
    items = document.get("journeys")
    require(isinstance(items, list), f"{path}: journeys must be an array", errors)
    if not isinstance(items, list):
        return Counter(), {}

    ids: set[str] = set()
    by_id: dict[str, dict] = {}
    exact_journeys: set[tuple] = set()
    counts: Counter[str] = Counter()
    for index, item in enumerate(items):
        label = f"{path}: journeys[{index}]"
        require(isinstance(item, dict), f"{label} must be an object", errors)
        if not isinstance(item, dict):
            continue

        journey_id = item.get("id")
        require(
            isinstance(journey_id, str) and bool(ID_PATTERN.fullmatch(journey_id)),
            f"{label}.id must be a lowercase stable identifier",
            errors,
        )
        if isinstance(journey_id, str):
            require(journey_id not in ids, f"{label}: duplicate id {journey_id}", errors)
            ids.add(journey_id)
            by_id[journey_id] = item

        mode = item.get("mode")
        require(mode in JOURNEY_MODES, f"{label}.mode is invalid", errors)
        if mode in JOURNEY_MODES:
            counts[mode] += 1

        code = item.get("code")
        require(isinstance(code, str) and bool(code.strip()), f"{label}.code is required", errors)

        date_text = item.get("date")
        try:
            date.fromisoformat(date_text)
        except (TypeError, ValueError):
            errors.append(f"{label}.date must be a real ISO date")

        stops = item.get("stops")
        require(
            isinstance(stops, list) and len(stops) >= 2,
            f"{label}.stops must contain at least two location names",
            errors,
        )
        if isinstance(stops, list):
            expected_type = "station" if mode == "train" else "airport"
            for stop_name in stops:
                require(
                    stop_name in locations,
                    f"{label}: unknown stop name {stop_name!r}",
                    errors,
                )
                if stop_name in locations:
                    require(
                        locations[stop_name].get("type") == expected_type,
                        f"{label}: {stop_name!r} is not a {expected_type}",
                        errors,
                    )

            signature = (mode, code, date_text, tuple(stops))
            require(signature not in exact_journeys, f"{label}: duplicate journey", errors)
            exact_journeys.add(signature)

        if "note" in item:
            require(isinstance(item["note"], str), f"{label}.note must be text", errors)
    return counts, by_id


def validate_routes(
    path: Path,
    journeys: dict[str, dict],
    errors: list[str],
) -> tuple[int, int]:
    document = read_json(path)
    require(document.get("schemaVersion") == 1, f"{path}: schemaVersion must be 1", errors)
    items = document.get("routes")
    require(isinstance(items, list), f"{path}: routes must be an array", errors)
    if not isinstance(items, list):
        return 0, 0

    route_ids = set()
    coordinate_count = 0
    for index, item in enumerate(items):
        label = f"{path}: routes[{index}]"
        require(isinstance(item, dict), f"{label} must be an object", errors)
        if not isinstance(item, dict):
            continue

        journey_id = item.get("journeyId")
        require(journey_id in journeys, f"{label}: unknown journey {journey_id!r}", errors)
        require(journey_id not in route_ids, f"{label}: duplicate journey route", errors)
        route_ids.add(journey_id)
        if journey_id in journeys:
            require(
                journeys[journey_id].get("mode") == "train",
                f"{label}: flight journeys must not have railway routes",
                errors,
            )
            snap_distances = item.get("snapDistanceKm")
            expected_stop_names = set(journeys[journey_id].get("stops", []))
            require(
                isinstance(snap_distances, dict)
                and set(snap_distances) == expected_stop_names,
                f"{label}.snapDistanceKm must use the journey stop names",
                errors,
            )
            if isinstance(snap_distances, dict):
                require(
                    all(
                        isinstance(distance, (int, float)) and distance >= 0
                        for distance in snap_distances.values()
                    ),
                    f"{label}.snapDistanceKm values must be non-negative",
                    errors,
                )

        require(
            item.get("profile") in {"highspeed", "emu", "conventional", "balanced"},
            f"{label}.profile is invalid",
            errors,
        )
        require(
            isinstance(item.get("distanceKm"), (int, float))
            and item["distanceKm"] > 0,
            f"{label}.distanceKm must be positive",
            errors,
        )
        coordinates = item.get("coords")
        valid_line = (
            isinstance(coordinates, list)
            and len(coordinates) >= 2
            and all(
                isinstance(point, list)
                and len(point) == 2
                and all(isinstance(value, (int, float)) for value in point)
                for point in coordinates
            )
        )
        require(valid_line, f"{label}.coords is not a valid line", errors)
        if valid_line:
            coordinate_count += len(coordinates)

    expected_ids = {
        journey_id
        for journey_id, journey in journeys.items()
        if journey.get("mode") == "train"
    }
    require(
        route_ids == expected_ids,
        f"{path}: routes must exist for every train journey and no flights",
        errors,
    )
    return len(items), coordinate_count


def validate_railways(path: Path, errors: list[str]) -> tuple[int, int]:
    if not path.exists():
        errors.append(f"{path}: generated railway layer is missing")
        return 0, 0

    document = read_json(path)
    require(document.get("schemaVersion") == 1, f"{path}: schemaVersion must be 1", errors)
    lines = document.get("lines")
    require(isinstance(lines, list), f"{path}: lines must be an array", errors)
    if not isinstance(lines, list):
        return 0, 0

    coordinate_count = 0
    for index, item in enumerate(lines):
        label = f"{path}: lines[{index}]"
        require(isinstance(item, dict), f"{label} must be an object", errors)
        if not isinstance(item, dict):
            continue
        require(
            item.get("category") in {"conventional", "highspeed"},
            f"{label}.category is invalid",
            errors,
        )
        coordinates = item.get("coords")
        valid_line = (
            isinstance(coordinates, list)
            and len(coordinates) >= 2
            and all(
                isinstance(point, list)
                and len(point) == 2
                and all(isinstance(value, (int, float)) for value in point)
                for point in coordinates
            )
        )
        require(valid_line, f"{label}.coords is not a valid line", errors)
        if valid_line:
            coordinate_count += len(coordinates)
    return len(lines), coordinate_count


def validate_passenger_stations(path: Path, errors: list[str]) -> tuple[int, Counter]:
    document = read_json(path)
    require(document.get("schemaVersion") == 1, f"{path}: schemaVersion must be 1", errors)
    source = document.get("source")
    whitelist = source.get("passengerWhitelist") if isinstance(source, dict) else None
    require(
        isinstance(whitelist, dict),
        f"{path}: source.passengerWhitelist is required",
        errors,
    )
    stations = document.get("stations")
    require(isinstance(stations, list), f"{path}: stations must be an array", errors)
    if not isinstance(stations, list):
        return 0, Counter()

    osm_ids = set()
    names = set()
    telecodes = set()
    levels = Counter()
    for index, station in enumerate(stations):
        label = f"{path}: stations[{index}]"
        require(isinstance(station, dict), f"{label} must be an object", errors)
        if not isinstance(station, dict):
            continue
        osm_id = station.get("osmId")
        require(
            isinstance(osm_id, str) and bool(OSM_ID_PATTERN.fullmatch(osm_id)),
            f"{label}.osmId is invalid",
            errors,
        )
        require(osm_id not in osm_ids, f"{label}: duplicate osmId {osm_id!r}", errors)
        osm_ids.add(osm_id)
        name = station.get("name")
        require(
            isinstance(name, str) and bool(name.strip()),
            f"{label}.name is required",
            errors,
        )
        require(name not in names, f"{label}: duplicate name {name!r}", errors)
        names.add(name)
        telecode = station.get("telecode")
        require(
            isinstance(telecode, str) and bool(telecode),
            f"{label}.telecode is required",
            errors,
        )
        require(
            telecode not in telecodes,
            f"{label}: duplicate telecode {telecode!r}",
            errors,
        )
        telecodes.add(telecode)
        for field in ("pinyin", "shortPinyin", "cityCode", "city"):
            require(
                isinstance(station.get(field), str) and bool(station[field]),
                f"{label}.{field} is required",
                errors,
            )
        level = station.get("level")
        require(level in {"major", "station", "halt"}, f"{label}.level is invalid", errors)
        if level:
            levels[level] += 1
        coordinates = station.get("coordinates")
        valid_coordinates = (
            isinstance(coordinates, list)
            and len(coordinates) == 2
            and all(isinstance(value, (int, float)) for value in coordinates)
        )
        require(valid_coordinates, f"{label}.coordinates is invalid", errors)
        if valid_coordinates:
            longitude, latitude = coordinates
            require(70 <= longitude <= 140, f"{label}: longitude is outside China", errors)
            require(0 <= latitude <= 60, f"{label}: latitude is outside China", errors)
    require(
        len(stations) >= 3000,
        f"{path}: passenger station catalog appears incomplete",
        errors,
    )
    if isinstance(whitelist, dict):
        domestic_names = whitelist.get("domesticNames")
        matched_names = whitelist.get("matchedNames")
        unmatched_names = whitelist.get("unmatchedNames")
        require(
            matched_names == len(stations),
            f"{path}: whitelist matchedNames does not match stations",
            errors,
        )
        require(
            isinstance(unmatched_names, list)
            and all(isinstance(name, str) and name for name in unmatched_names),
            f"{path}: whitelist unmatchedNames is invalid",
            errors,
        )
        if isinstance(unmatched_names, list):
            require(
                len(unmatched_names) == len(set(unmatched_names)),
                f"{path}: whitelist unmatchedNames contains duplicates",
                errors,
            )
            require(
                isinstance(domestic_names, int)
                and domestic_names == len(stations) + len(unmatched_names),
                f"{path}: whitelist domesticNames is inconsistent",
                errors,
            )
    return len(stations), levels


def validate_boundaries(
    path: Path,
    expected_level: str,
    minimum_regions: int,
    errors: list[str],
) -> tuple[int, int]:
    document = read_json(path)
    require(document.get("schemaVersion") == 2, f"{path}: schemaVersion must be 2", errors)
    require(document.get("level") == expected_level, f"{path}: level is invalid", errors)
    region_count = document.get("regionCount")
    require(
        isinstance(region_count, int) and region_count >= minimum_regions,
        f"{path}: region count appears incomplete",
        errors,
    )
    geojson = document.get("geoJSON")
    require(
        isinstance(geojson, dict) and geojson.get("type") == "FeatureCollection",
        f"{path}: geoJSON must be a FeatureCollection",
        errors,
    )
    features = geojson.get("features") if isinstance(geojson, dict) else None
    require(isinstance(features, list), f"{path}: features must be an array", errors)
    if not isinstance(features, list):
        return 0, 0
    require(
        document.get("featureCount") == len(features),
        f"{path}: featureCount does not match features",
        errors,
    )
    require(
        isinstance(region_count, int) and region_count <= len(features),
        f"{path}: regionCount cannot exceed featureCount",
        errors,
    )

    coordinate_count = 0
    for feature_index, feature in enumerate(features):
        label = f"{path}: features[{feature_index}]"
        properties = feature.get("properties") if isinstance(feature, dict) else None
        require(
            isinstance(properties, dict)
            and isinstance(properties.get("name"), str)
            and bool(properties["name"].strip()),
            f"{label}.properties.name is invalid",
            errors,
        )
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        geometry_type = geometry.get("type") if isinstance(geometry, dict) else None
        coordinates = (
            geometry.get("coordinates") if isinstance(geometry, dict) else None
        )
        require(
            geometry_type in {"Polygon", "MultiPolygon"}
            and isinstance(coordinates, list)
            and bool(coordinates),
            f"{label}.geometry is not a polygon",
            errors,
        )
        if geometry_type == "Polygon":
            polygons = [coordinates]
        elif geometry_type == "MultiPolygon":
            polygons = coordinates
        else:
            continue
        for polygon_index, polygon in enumerate(polygons):
            valid_polygon = isinstance(polygon, list) and bool(polygon)
            require(
                valid_polygon,
                f"{label}.geometry polygon {polygon_index} is empty",
                errors,
            )
            if not valid_polygon:
                continue
            for ring_index, ring in enumerate(polygon):
                valid_ring = (
                    isinstance(ring, list)
                    and len(ring) >= 4
                    and ring[0] == ring[-1]
                    and all(
                        isinstance(point, list)
                        and len(point) == 2
                        and all(
                            isinstance(value, (int, float))
                            for value in point
                        )
                        for point in ring
                    )
                )
                require(
                    valid_ring,
                    f"{label}.geometry ring {ring_index} is not closed",
                    errors,
                )
                if valid_ring:
                    coordinate_count += len(ring)
    return len(features), coordinate_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    project_root = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=project_root / "data" / "source",
    )
    parser.add_argument(
        "--generated-dir",
        type=Path,
        default=project_root / "data" / "generated",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    locations = validate_locations(args.source_dir / "locations.json", errors)
    places = validate_places(args.generated_dir / "places.json", locations, errors)
    locations_by_name = {
        location["name"]: location
        for location in locations.values()
        if isinstance(location.get("name"), str)
    }
    journey_counts, journeys = validate_journeys(
        args.source_dir / "journeys.json",
        locations_by_name,
        errors,
    )
    route_count, route_coordinates = validate_routes(
        args.generated_dir / "journey-routes.json",
        journeys,
        errors,
    )
    railway_lines, railway_coordinates = validate_railways(
        args.generated_dir / "railways.json",
        errors,
    )
    passenger_station_count, passenger_station_levels = validate_passenger_stations(
        args.generated_dir / "passenger-stations.json",
        errors,
    )
    province_features, province_coordinates = validate_boundaries(
        args.generated_dir / "admin-boundaries-province.json",
        "province",
        34,
        errors,
    )
    if errors:
        print("Data validation failed:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    location_counts = Counter(item["type"] for item in locations.values())
    print(
        "Data valid: "
        f"{location_counts['station']} stations, "
        f"{location_counts['airport']} airports, "
        f"{journey_counts['train']} train journeys, "
        f"{journey_counts['flight']} flights, "
        f"{len(places)} OSM-derived places, "
        f"{route_count} routed journeys / {route_coordinates} route coordinates, "
        f"{railway_lines} railway lines / {railway_coordinates} coordinates, "
        f"{passenger_station_count} passenger stations "
        f"{dict(passenger_station_levels)}, "
        f"{province_features} province map features / "
        f"{province_coordinates} coordinates."
    )


if __name__ == "__main__":
    main()
