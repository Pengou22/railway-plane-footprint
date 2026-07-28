#!/usr/bin/env python3
"""Build the interactive province-level GeoJSON map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_railway_layer import simplify


PROVINCE_NAME_ALIASES = {
    "北京市": "北京",
    "天津市": "天津",
    "河北省": "河北",
    "山西省": "山西",
    "内蒙古自治区": "内蒙古",
    "辽宁省": "辽宁",
    "吉林省": "吉林",
    "黑龙江省": "黑龙江",
    "上海市": "上海",
    "江苏省": "江苏",
    "浙江省": "浙江",
    "安徽省": "安徽",
    "福建省": "福建",
    "江西省": "江西",
    "山东省": "山东",
    "河南省": "河南",
    "湖北省": "湖北",
    "湖南省": "湖南",
    "广东省": "广东",
    "广西壮族自治区": "广西",
    "海南省": "海南",
    "重庆市": "重庆",
    "四川省": "四川",
    "贵州省": "贵州",
    "云南省": "云南",
    "西藏自治区": "西藏",
    "陕西省": "陕西",
    "甘肃省": "甘肃",
    "青海省": "青海",
    "宁夏回族自治区": "宁夏",
    "新疆维吾尔自治区": "新疆",
    "台湾省": "台湾",
    "香港特别行政区": "香港",
    "澳门特别行政区": "澳门",
}


def compact_ring(raw_ring, tolerance: float, precision: int):
    points = [
        (round(float(point[0]), precision), round(float(point[1]), precision))
        for point in raw_ring
    ]
    if len(points) < 4:
        return None
    if points[0] != points[-1]:
        points.append(points[0])
    simplified = simplify(points, tolerance)
    if simplified[0] != simplified[-1]:
        simplified.append(simplified[0])
    if len(simplified) < 4:
        return None
    return [[longitude, latitude] for longitude, latitude in simplified]


def compact_polygon(raw_polygon, tolerance: float, precision: int):
    rings = []
    for raw_ring in raw_polygon:
        ring = compact_ring(raw_ring, tolerance, precision)
        if ring is not None:
            rings.append(ring)
    return rings or None


def compact_geometry(geometry: dict, tolerance: float, precision: int):
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        polygon = compact_polygon(coordinates, tolerance, precision)
        if polygon is None:
            return None
        return {"type": "Polygon", "coordinates": polygon}
    if geometry_type == "MultiPolygon":
        polygons = []
        for raw_polygon in coordinates:
            polygon = compact_polygon(raw_polygon, tolerance, precision)
            if polygon is not None:
                polygons.append(polygon)
        if not polygons:
            return None
        return {"type": "MultiPolygon", "coordinates": polygons}
    return None


def trim_hainan_offshore_polygons(geometry: dict, minimum_latitude: float = 17.5):
    """Keep Hainan's local islands without letting remote islands distort map fit."""
    if geometry.get("type") != "MultiPolygon":
        return geometry
    polygons = [
        polygon
        for polygon in geometry.get("coordinates") or []
        if polygon
        and polygon[0]
        and max(point[1] for point in polygon[0]) >= minimum_latitude
    ]
    if not polygons:
        return None
    return {"type": "MultiPolygon", "coordinates": polygons}


def feature_point_count(feature: dict) -> int:
    def count_coordinates(value) -> int:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            return 1
        if isinstance(value, list):
            return sum(count_coordinates(item) for item in value)
        return 0

    return count_coordinates((feature.get("geometry") or {}).get("coordinates"))


def map_document(
    *,
    level: str,
    features: list[dict],
    source: dict,
    region_count: int | None = None,
) -> dict:
    return {
        "schemaVersion": 2,
        "source": source,
        "level": level,
        "regionCount": region_count if region_count is not None else len(features),
        "featureCount": len(features),
        "geoJSON": {
            "type": "FeatureCollection",
            "features": features,
        },
    }


def build_province_level(
    source: Path,
    tolerance: float,
    precision: int,
    snapshot: str,
) -> dict:
    raw_document = json.loads(source.read_text(encoding="utf-8-sig"))
    features = []
    administrative_count = 0
    for raw_feature in raw_document.get("features") or []:
        properties = raw_feature.get("properties") or {}
        raw_name = str(properties.get("name") or "").strip()
        adcode = str(properties.get("adcode") or "")
        if adcode == "100000_JD":
            continue
        name = PROVINCE_NAME_ALIASES.get(raw_name)
        if not name:
            continue
        administrative_count += 1
        geometry = compact_geometry(
            raw_feature.get("geometry") or {},
            tolerance,
            precision,
        )
        if adcode == "460000" and geometry is not None:
            geometry = trim_hainan_offshore_polygons(geometry)
        if geometry is None:
            continue
        features.append(
            {
                "type": "Feature",
                "id": f"datav-{adcode}",
                "properties": {
                    "name": name,
                    "fullName": raw_name or name,
                    "adcode": adcode,
                    "supplemental": False,
                },
                "geometry": geometry,
            }
        )

    features.sort(key=lambda feature: feature["properties"]["adcode"])
    return map_document(
        level="province",
        features=features,
        region_count=administrative_count,
        source={
            "provider": "DataV.GeoAtlas",
            "dataset": "areas_v3/bound/100000_full",
            "buildSnapshot": snapshot,
            "simplifyToleranceDegrees": tolerance,
        },
    )


def write_json(path: Path, document: dict) -> None:
    """Write readable metadata and one complete GeoJSON feature per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    geojson = document["geoJSON"]
    with path.open("w", encoding="utf-8", newline="\n") as target:
        target.write("{\n")
        header_items = [
            ("schemaVersion", document["schemaVersion"]),
            ("source", document["source"]),
            ("level", document["level"]),
            ("regionCount", document["regionCount"]),
            ("featureCount", document["featureCount"]),
        ]
        for key, value in header_items:
            encoded = json.dumps(value, ensure_ascii=False, indent=2)
            encoded = encoded.replace("\n", "\n  ")
            target.write(f'  {json.dumps(key)}: {encoded},\n')
        target.write('  "geoJSON": {\n')
        target.write('    "type": "FeatureCollection",\n')
        target.write('    "features": [\n')
        features = geojson["features"]
        for index, feature in enumerate(features):
            comma = "," if index + 1 < len(features) else ""
            encoded = json.dumps(
                feature,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            target.write(f"      {encoded}{comma}\n")
        target.write("    ]\n")
        target.write("  }\n")
        target.write("}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--province-input", type=Path, required=True)
    parser.add_argument("--province-output", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--province-tolerance", type=float, default=0.002)
    parser.add_argument("--precision", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    province_document = build_province_level(
        args.province_input,
        args.province_tolerance,
        args.precision,
        args.snapshot,
    )
    write_json(args.province_output, province_document)
    point_count = sum(
        feature_point_count(feature)
        for feature in province_document["geoJSON"]["features"]
    )
    print(
        f"Province map built: "
        f"{province_document['regionCount']} regions / "
        f"{province_document['featureCount']} features / "
        f"{point_count} coordinates / "
        f"{args.province_output.stat().st_size / 1024:.1f} KB."
    )
    if province_document["regionCount"] != len(PROVINCE_NAME_ALIASES):
        raise SystemExit(
            "Province source did not contain all 34 provincial divisions"
        )


if __name__ == "__main__":
    main()
