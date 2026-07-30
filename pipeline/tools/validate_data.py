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
IATA_PATTERN = re.compile(r"^[A-Z]{3}$")
JOURNEY_MODES = {"train", "flight"}


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def normalized_place_name(name: str, place_type: str) -> str:
    value = name.casefold()
    value = re.sub(r"[\s·•（）()\-—_/]+", "", value)
    suffixes = (
        ("火车站", "铁路车站", "高铁站", "railwaystation", "station", "站")
        if place_type == "station"
        else ("国际机场", "机场", "航空港", "internationalairport", "airport")
    )
    for suffix in suffixes:
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def catalog_matches(name: str, items: list[dict], place_type: str) -> list[dict]:
    normalized = normalized_place_name(name, place_type)
    matches = [
        item
        for item in items
        if any(
            normalized_place_name(candidate_name, place_type) == normalized
            for candidate_name in [item["name"], *(item.get("aliases") or [])]
        )
    ]
    primary_matches = [
        item
        for item in matches
        if normalized_place_name(item["name"], place_type) == normalized
    ]
    return primary_matches or matches


def validate_journeys(
    path: Path,
    expected_mode: str,
    stations: list[dict],
    airports: list[dict],
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
        require(
            mode == expected_mode,
            f"{label}.mode must be {expected_mode!r}",
            errors,
        )
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
            expected_type = "station" if expected_mode == "train" else "airport"
            catalog = stations if expected_mode == "train" else airports
            for stop_name in stops:
                matches = (
                    catalog_matches(stop_name, catalog, expected_type)
                    if isinstance(stop_name, str)
                    else []
                )
                require(
                    bool(matches),
                    f"{label}: unknown stop name {stop_name!r}",
                    errors,
                )
                if len(matches) > 1:
                    errors.append(
                        f"{label}: ambiguous stop name {stop_name!r}; "
                        "use an unambiguous formal catalog name"
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
    require(document.get("type") == "FeatureCollection", f"{path}: must be GeoJSON", errors)
    require(document.get("schemaVersion") == 2, f"{path}: schemaVersion must be 2", errors)
    features = document.get("features")
    require(isinstance(features, list), f"{path}: features must be an array", errors)
    if not isinstance(features, list):
        return 0, 0

    line_count = 0
    coordinate_count = 0
    categories = set()
    for index, feature in enumerate(features):
        label = f"{path}: features[{index}]"
        require(isinstance(feature, dict), f"{label} must be an object", errors)
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        category = properties.get("category")
        require(
            category in {"conventional", "highspeed"},
            f"{label}.category is invalid",
            errors,
        )
        categories.add(category)
        require(
            geometry.get("type") == "MultiLineString",
            f"{label}.geometry must be MultiLineString",
            errors,
        )
        lines = geometry.get("coordinates")
        valid_lines = (
            isinstance(lines, list)
            and bool(lines)
            and all(
                isinstance(line, list)
                and len(line) >= 2
                and all(
                    isinstance(point, list)
                    and len(point) == 2
                    and all(isinstance(value, (int, float)) for value in point)
                    for point in line
                )
                for line in lines
            )
        )
        require(valid_lines, f"{label}.geometry is invalid", errors)
        if valid_lines:
            line_count += len(lines)
            coordinate_count += sum(len(line) for line in lines)

    source = document.get("source") or {}
    require(
        source.get("lineCount") == line_count,
        f"{path}: source.lineCount does not match geometry",
        errors,
    )
    require(
        source.get("coordinateCount") == coordinate_count,
        f"{path}: source.coordinateCount does not match geometry",
        errors,
    )
    require(
        categories == {"conventional", "highspeed"},
        f"{path}: both railway categories are required",
        errors,
    )
    return line_count, coordinate_count


def validate_stations(path: Path, errors: list[str]) -> tuple[list[dict], Counter]:
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
        return [], Counter()

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
    return stations, levels


def validate_airports(path: Path, errors: list[str]) -> list[dict]:
    document = read_json(path)
    require(document.get("schemaVersion") == 1, f"{path}: schemaVersion must be 1", errors)
    source = document.get("source")
    require(isinstance(source, dict), f"{path}: source is required", errors)
    if isinstance(source, dict):
        require(
            "general-aviation" in str(source.get("selection") or ""),
            f"{path}: source.selection must document general-aviation exclusion",
            errors,
        )
    airports = document.get("airports")
    require(isinstance(airports, list), f"{path}: airports must be an array", errors)
    if not isinstance(airports, list):
        return []

    iata_codes = set()
    for index, airport in enumerate(airports):
        label = f"{path}: airports[{index}]"
        require(isinstance(airport, dict), f"{label} must be an object", errors)
        if not isinstance(airport, dict):
            continue
        name = airport.get("name")
        require(
            isinstance(name, str) and bool(name.strip()),
            f"{label}.name is required",
            errors,
        )
        iata = airport.get("iata")
        require(
            isinstance(iata, str) and bool(IATA_PATTERN.fullmatch(iata)),
            f"{label}.iata is invalid",
            errors,
        )
        require(iata not in iata_codes, f"{label}: duplicate IATA code {iata!r}", errors)
        iata_codes.add(iata)

        osm_id = airport.get("osmId")
        osm_ids = airport.get("osmIds")
        require(
            isinstance(osm_id, str) and bool(OSM_ID_PATTERN.fullmatch(osm_id)),
            f"{label}.osmId is invalid",
            errors,
        )
        require(
            isinstance(osm_ids, list)
            and osm_id in osm_ids
            and all(
                isinstance(candidate, str)
                and bool(OSM_ID_PATTERN.fullmatch(candidate))
                for candidate in osm_ids
            ),
            f"{label}.osmIds is invalid",
            errors,
        )

        coordinates = airport.get("coordinates")
        valid_coordinates = (
            isinstance(coordinates, list)
            and len(coordinates) == 2
            and all(
                isinstance(value, (int, float)) and math.isfinite(value)
                for value in coordinates
            )
        )
        require(valid_coordinates, f"{label}.coordinates is invalid", errors)
        if valid_coordinates:
            longitude, latitude = coordinates
            require(70 <= longitude <= 140, f"{label}: longitude is outside China", errors)
            require(0 <= latitude <= 60, f"{label}: latitude is outside China", errors)

        searchable_text = " ".join(
            [
                str(name or ""),
                str(airport.get("operator") or ""),
                *(airport.get("aliases") or []),
            ]
        )
        require(
            not re.search(r"通用|通航|general[\s_-]*aviation", searchable_text, re.I),
            f"{label}: general-aviation airport was not excluded",
            errors,
        )

    require(
        len(airports) >= 250,
        f"{path}: passenger airport catalog appears incomplete",
        errors,
    )
    return airports


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
    stations, station_levels = validate_stations(
        args.generated_dir / "stations.json",
        errors,
    )
    airports = validate_airports(
        args.generated_dir / "airports.json",
        errors,
    )
    railway_counts, railway_journeys = validate_journeys(
        args.source_dir / "journeys-railway.json",
        "train",
        stations,
        airports,
        errors,
    )
    flight_counts, flight_journeys = validate_journeys(
        args.source_dir / "journeys-flight.json",
        "flight",
        stations,
        airports,
        errors,
    )
    duplicate_journey_ids = set(railway_journeys) & set(flight_journeys)
    require(
        not duplicate_journey_ids,
        f"journey ids occur in both files: {sorted(duplicate_journey_ids)}",
        errors,
    )
    journey_counts = railway_counts + flight_counts
    journeys = {**railway_journeys, **flight_journeys}
    route_count, route_coordinates = validate_routes(
        args.generated_dir / "routes.json",
        journeys,
        errors,
    )
    railway_lines, railway_coordinates = validate_railways(
        args.generated_dir / "railways.geojson",
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

    station_names = {
        stop
        for journey in railway_journeys.values()
        for stop in journey.get("stops") or []
    }
    airport_names = {
        stop
        for journey in flight_journeys.values()
        for stop in journey.get("stops") or []
    }
    print(
        "Data valid: "
        f"{len(station_names)} journey stations, "
        f"{len(airport_names)} journey airports, "
        f"{journey_counts['train']} train journeys, "
        f"{journey_counts['flight']} flights, "
        f"{route_count} routed journeys / {route_coordinates} route coordinates, "
        f"{railway_lines} railway lines / {railway_coordinates} coordinates, "
        f"{len(stations)} passenger stations {dict(station_levels)}, "
        f"{len(airports)} passenger airports, "
        f"{province_features} province map features / "
        f"{province_coordinates} coordinates."
    )


if __name__ == "__main__":
    main()
