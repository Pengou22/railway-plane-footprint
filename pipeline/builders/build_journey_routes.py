#!/usr/bin/env python3
"""Route train journeys over the extracted OpenStreetMap railway network."""

from __future__ import annotations

import argparse
import heapq
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from build_railway_layer import (
    category,
    iter_features,
    line_length_km,
    normalize_coordinates,
    simplify,
)


Point = tuple[float, float]
Line = list[Point]


@dataclass(slots=True)
class Edge:
    start: int
    end: int
    distance_km: float
    category: str
    usage: str
    service: str
    coordinates: Line


class DisjointSet:
    def __init__(self) -> None:
        self.parents: list[int] = []
        self.sizes: list[int] = []

    def add(self) -> int:
        index = len(self.parents)
        self.parents.append(index)
        self.sizes.append(1)
        return index

    def find(self, value: int) -> int:
        root = value
        while self.parents[root] != root:
            root = self.parents[root]
        while self.parents[value] != value:
            parent = self.parents[value]
            self.parents[value] = root
            value = parent
        return root

    def union(self, first: int, second: int) -> None:
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root == second_root:
            return
        if self.sizes[first_root] < self.sizes[second_root]:
            first_root, second_root = second_root, first_root
        self.parents[second_root] = first_root
        self.sizes[first_root] += self.sizes[second_root]

    def component_size(self, value: int) -> int:
        return self.sizes[self.find(value)]


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def selected_line(feature: dict, precision: int) -> tuple[Line, dict] | None:
    geometry = feature.get("geometry") or {}
    properties = feature.get("properties") or {}
    if geometry.get("type") != "LineString":
        return None
    if properties.get("railway") != "rail":
        return None
    coordinates = normalize_coordinates(geometry.get("coordinates") or [], precision)
    if len(coordinates) < 2:
        return None
    return coordinates, properties


def point_distance_km(first: Point, second: Point) -> float:
    latitude = math.radians((first[1] + second[1]) / 2)
    dx = (second[0] - first[0]) * 111.32 * math.cos(latitude)
    dy = (second[1] - first[1]) * 110.57
    return math.hypot(dx, dy)


def coordinate_occurrences(source_path: Path, precision: int) -> tuple[Counter, int]:
    occurrences: Counter[Point] = Counter()
    selected_features = 0
    for feature in iter_features(source_path):
        selected = selected_line(feature, precision)
        if selected is None:
            continue
        coordinates, _ = selected
        occurrences.update(coordinates)
        selected_features += 1
    return occurrences, selected_features


def station_snap_candidates(
    places: dict,
    occurrences: Counter,
    candidate_count: int,
) -> tuple[dict[str, list[tuple[Point, float]]], set[Point]]:
    unique_points = list(occurrences)
    coordinate_array = np.asarray(unique_points, dtype=np.float64)
    tree = cKDTree(coordinate_array)
    candidates: dict[str, list[tuple[Point, float]]] = {}
    significant_points: set[Point] = set()

    for place in places["places"]:
        if place["type"] != "station":
            continue
        station_point = tuple(place["coordinates"])
        distances, indices = tree.query(station_point, k=candidate_count)
        distances = np.atleast_1d(distances)
        indices = np.atleast_1d(indices)
        station_candidates = []
        for index in indices:
            point = unique_points[int(index)]
            distance = point_distance_km(station_point, point)
            station_candidates.append((point, distance))
            significant_points.add(point)
        candidates[place["id"]] = station_candidates
    return candidates, significant_points


def build_graph(
    source_path: Path,
    occurrences: Counter,
    forced_vertices: set[Point],
    precision: int,
) -> tuple[
    list[Point],
    list[list[tuple[int, int, bool]]],
    list[Edge],
    dict[Point, int],
    DisjointSet,
]:
    node_ids: dict[Point, int] = {}
    node_points: list[Point] = []
    adjacency: list[list[tuple[int, int, bool]]] = []
    edges: list[Edge] = []
    components = DisjointSet()

    def node_id(point: Point) -> int:
        existing = node_ids.get(point)
        if existing is not None:
            return existing
        index = len(node_points)
        node_ids[point] = index
        node_points.append(point)
        adjacency.append([])
        components.add()
        return index

    for feature in iter_features(source_path):
        selected = selected_line(feature, precision)
        if selected is None:
            continue
        coordinates, properties = selected
        vertex_indices = [0]
        vertex_indices.extend(
            index
            for index in range(1, len(coordinates) - 1)
            if occurrences[coordinates[index]] > 1
            or coordinates[index] in forced_vertices
        )
        vertex_indices.append(len(coordinates) - 1)

        for first_index, last_index in zip(vertex_indices, vertex_indices[1:]):
            geometry = coordinates[first_index : last_index + 1]
            if len(geometry) < 2:
                continue
            start = node_id(geometry[0])
            end = node_id(geometry[-1])
            if start == end:
                continue
            edge_index = len(edges)
            edge = Edge(
                start=start,
                end=end,
                distance_km=line_length_km(geometry),
                category=category(properties),
                usage=properties.get("usage", "main"),
                service=properties.get("service", ""),
                coordinates=geometry,
            )
            edges.append(edge)
            adjacency[start].append((end, edge_index, True))
            adjacency[end].append((start, edge_index, False))
            components.union(start, end)

    return node_points, adjacency, edges, node_ids, components


def choose_station_nodes(
    candidates: dict[str, list[tuple[Point, float]]],
    node_ids: dict[Point, int],
    components: DisjointSet,
    maximum_snap_km: float,
) -> tuple[dict[str, list[tuple[int, float]]], dict[str, float]]:
    station_nodes = {}
    snap_distances = {}

    for station_id, station_candidates in candidates.items():
        available = [
            (point, distance, node_ids[point])
            for point, distance in station_candidates
            if point in node_ids and distance <= maximum_snap_km
        ]
        if not available:
            nearest_distance = min(distance for _, distance in station_candidates)
            raise ValueError(
                f"{station_id}: no railway graph node within {maximum_snap_km} km "
                f"(nearest {nearest_distance:.2f} km)"
            )

        nationwide = [
            item for item in available if components.component_size(item[2]) >= 1000
        ]
        regional = [
            item for item in available if components.component_size(item[2]) >= 100
        ]
        pool = nationwide or regional or available
        unique_nodes = {}
        for _, distance, node in sorted(pool, key=lambda item: item[1]):
            unique_nodes[node] = min(distance, unique_nodes.get(node, math.inf))
        station_nodes[station_id] = list(unique_nodes.items())
        snap_distances[station_id] = min(unique_nodes.values())
    return station_nodes, snap_distances


def route_profile(code: str) -> str:
    prefix = code[:1].upper()
    if prefix in {"G", "C"}:
        return "highspeed"
    if prefix == "D":
        return "emu"
    if prefix in {"K", "Z", "T", "Y"}:
        return "conventional"
    return "balanced"


PROFILE_FACTORS = {
    "highspeed": {"highspeed": 0.65, "conventional": 1.05},
    "emu": {"highspeed": 0.78, "conventional": 1.00},
    "conventional": {"highspeed": 1.15, "conventional": 0.90},
    "balanced": {"highspeed": 0.95, "conventional": 1.00},
}


def edge_cost(edge: Edge, profile: str) -> float:
    factor = PROFILE_FACTORS[profile][edge.category]
    usage_factors = {
        "branch": 1.08,
        "industrial": 3.0,
        "military": 4.0,
        "test": 4.0,
        "tourism": 1.7,
        "yard": 4.0,
        "siding": 3.0,
        "spur": 3.5,
    }
    service_factors = {
        "crossover": 1.25,
        "siding": 2.5,
        "yard": 4.0,
        "spur": 3.0,
        "industrial": 4.0,
    }
    return (
        edge.distance_km
        * factor
        * usage_factors.get(edge.usage, 1.0)
        * service_factors.get(edge.service, 1.0)
    )


def heuristic(first: Point, second: Point, profile: str) -> float:
    minimum_factor = min(PROFILE_FACTORS[profile].values())
    return point_distance_km(first, second) * minimum_factor


def astar(
    starts: list[tuple[int, float]],
    goals: list[tuple[int, float]],
    profile: str,
    node_points: list[Point],
    adjacency: list[list[tuple[int, int, bool]]],
    edges: list[Edge],
) -> list[tuple[int, bool]]:
    goal_snap_cost = {node: distance * 2.0 for node, distance in goals}
    goal_points = [node_points[node] for node, _ in goals]

    def goal_heuristic(node: int) -> float:
        return min(
            heuristic(node_points[node], goal_point, profile)
            for goal_point in goal_points
        )

    queue = []
    best_cost = {}
    previous: dict[int, tuple[int, int, bool]] = {}
    start_nodes = set()
    for start, snap_distance in starts:
        start_cost = snap_distance * 2.0
        if start_cost >= best_cost.get(start, math.inf):
            continue
        best_cost[start] = start_cost
        start_nodes.add(start)
        heapq.heappush(
            queue,
            (start_cost + goal_heuristic(start), start_cost, start),
        )

    best_goal = None
    best_goal_cost = math.inf

    while queue:
        priority, current_cost, current = heapq.heappop(queue)
        if priority >= best_goal_cost:
            break
        if current_cost != best_cost.get(current):
            continue
        if current in goal_snap_cost:
            total_cost = current_cost + goal_snap_cost[current]
            if total_cost < best_goal_cost:
                best_goal = current
                best_goal_cost = total_cost
            continue

        for neighbor, edge_index, forward in adjacency[current]:
            candidate_cost = current_cost + edge_cost(edges[edge_index], profile)
            if candidate_cost >= best_cost.get(neighbor, math.inf):
                continue
            best_cost[neighbor] = candidate_cost
            previous[neighbor] = (current, edge_index, forward)
            priority = candidate_cost + goal_heuristic(neighbor)
            heapq.heappush(queue, (priority, candidate_cost, neighbor))

    if best_goal is None:
        raise ValueError("stations are in disconnected railway components")

    path = []
    node = best_goal
    while node not in start_nodes or node in previous:
        if node not in previous:
            break
        parent, edge_index, forward = previous[node]
        path.append((edge_index, forward))
        node = parent
    path.reverse()
    return path


def path_geometry(
    path: list[tuple[int, bool]],
    edges: list[Edge],
) -> tuple[Line, float]:
    coordinates: Line = []
    distance = 0.0
    for edge_index, forward in path:
        edge = edges[edge_index]
        geometry = edge.coordinates if forward else list(reversed(edge.coordinates))
        if coordinates:
            coordinates.extend(geometry[1:])
        else:
            coordinates.extend(geometry)
        distance += edge.distance_km
    return coordinates, distance


def build_routes(
    journeys: dict,
    places: dict,
    station_nodes: dict[str, list[tuple[int, float]]],
    snap_distances: dict[str, float],
    node_points: list[Point],
    adjacency: list[list[tuple[int, int, bool]]],
    edges: list[Edge],
    route_tolerance: float,
) -> tuple[dict, list[str]]:
    places_by_name = {place["name"]: place for place in places["places"]}
    if len(places_by_name) != len(places["places"]):
        raise ValueError("Place names must be globally unique for journey routing")
    routes = []
    errors = []
    cache: dict[tuple[str, str, str], list[tuple[int, bool]]] = {}

    for journey in journeys["journeys"]:
        if journey["mode"] != "train":
            continue
        profile = route_profile(journey["code"])
        combined_geometry: Line = []
        total_distance = 0.0

        try:
            for start_name, end_name in zip(
                journey["stops"],
                journey["stops"][1:],
            ):
                start_place = places_by_name[start_name]
                end_place = places_by_name[end_name]
                start_id = start_place["id"]
                end_id = end_place["id"]
                starts = station_nodes[start_id]
                goals = station_nodes[end_id]
                cache_key = (profile, start_id, end_id)
                reverse_key = (profile, end_id, start_id)
                if cache_key in cache:
                    path = cache[cache_key]
                elif reverse_key in cache:
                    path = [
                        (edge_index, not forward)
                        for edge_index, forward in reversed(cache[reverse_key])
                    ]
                else:
                    path = astar(
                        starts,
                        goals,
                        profile,
                        node_points,
                        adjacency,
                        edges,
                    )
                    cache[cache_key] = path

                geometry, distance = path_geometry(path, edges)
                straight_distance = point_distance_km(
                    tuple(start_place["coordinates"]),
                    tuple(end_place["coordinates"]),
                )
                maximum_reasonable_distance = max(
                    straight_distance * 4.0,
                    straight_distance + 120.0,
                )
                if distance > maximum_reasonable_distance:
                    raise ValueError(
                        f"{start_id} -> {end_id} produced an unreasonable "
                        f"{distance:.1f} km route for {straight_distance:.1f} km "
                        "straight-line distance"
                    )
                if combined_geometry and geometry:
                    combined_geometry.extend(geometry[1:])
                else:
                    combined_geometry.extend(geometry)
                total_distance += distance

            combined_geometry = simplify(combined_geometry, route_tolerance)
            routes.append(
                {
                    "journeyId": journey["id"],
                    "profile": profile,
                    "distanceKm": round(total_distance, 1),
                    "coords": [
                        [round(longitude, 5), round(latitude, 5)]
                        for longitude, latitude in combined_geometry
                    ],
                    "snapDistanceKm": {
                        stop_name: round(
                            snap_distances[places_by_name[stop_name]["id"]],
                            3,
                        )
                        for stop_name in dict.fromkeys(journey["stops"])
                    },
                }
            )
        except (KeyError, ValueError) as error:
            errors.append(
                f"{journey['id']} ({' → '.join(journey['stops'])}): {error}"
            )

    return (
        {
            "schemaVersion": 1,
            "routing": {
                "algorithm": "A*",
                "profiles": PROFILE_FACTORS,
                "railFilter": (
                    "all railway=rail; service and non-passenger tracks "
                    "are retained with routing penalties"
                ),
                "routeSimplifyToleranceDegrees": route_tolerance,
            },
            "routes": routes,
        },
        errors,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--railways", type=Path, required=True)
    parser.add_argument("--places", type=Path, required=True)
    parser.add_argument("--journeys", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--precision", type=int, default=7)
    parser.add_argument("--snap-candidates", type=int, default=16)
    parser.add_argument("--maximum-snap-km", type=float, default=8.0)
    parser.add_argument("--route-tolerance", type=float, default=0.0008)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    places = read_json(args.places)
    journeys = read_json(args.journeys)

    print("Pass 1/2: indexing railway coordinates")
    occurrences, feature_count = coordinate_occurrences(
        args.railways,
        args.precision,
    )
    print(
        f"  {feature_count} selected railway features, "
        f"{len(occurrences)} unique coordinates"
    )

    candidates, forced_vertices = station_snap_candidates(
        places,
        occurrences,
        args.snap_candidates,
    )
    print("Pass 2/2: building compressed railway graph")
    node_points, adjacency, edges, node_ids, components = build_graph(
        args.railways,
        occurrences,
        forced_vertices,
        args.precision,
    )
    print(f"  {len(node_points)} nodes, {len(edges)} edges")

    station_nodes, snap_distances = choose_station_nodes(
        candidates,
        node_ids,
        components,
        args.maximum_snap_km,
    )
    print(
        "  station snapping: "
        f"max {max(snap_distances.values()):.3f} km, "
        f"mean {sum(snap_distances.values()) / len(snap_distances):.3f} km"
    )

    document, errors = build_routes(
        journeys,
        places,
        station_nodes,
        snap_distances,
        node_points,
        adjacency,
        edges,
        args.route_tolerance,
    )
    if errors:
        print("Routing failures:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(document, target, ensure_ascii=False, separators=(",", ":"))
        target.write("\n")
    coordinate_count = sum(len(route["coords"]) for route in document["routes"])
    print(
        f"Generated {len(document['routes'])} train routes / "
        f"{coordinate_count} coordinates / "
        f"{args.output.stat().st_size / 1024:.1f} KB."
    )


if __name__ == "__main__":
    main()
