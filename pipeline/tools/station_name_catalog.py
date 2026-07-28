#!/usr/bin/env python3
"""Parse the 12306-style station_names JavaScript data file."""

from __future__ import annotations

import re
from pathlib import Path


FIELD_NAMES = (
    "abbreviation",
    "name",
    "telecode",
    "pinyin",
    "shortPinyin",
    "index",
    "cityCode",
    "city",
    "countryCode",
    "country",
    "englishName",
)
WRAPPER_PATTERN = re.compile(
    r"\A\s*(?:var|let|const)\s+station_names\s*=\s*'(?P<data>.*)'\s*;\s*\Z",
    re.DOTALL,
)


def load_station_names(path: Path, *, domestic_only: bool = True) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    match = WRAPPER_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(
            f"{path}: expected `var station_names = '@...';` JavaScript format"
        )

    records = []
    for record_number, raw_record in enumerate(match.group("data").split("@"), 1):
        if not raw_record:
            continue
        fields = raw_record.split("|")
        if len(fields) != len(FIELD_NAMES):
            raise ValueError(
                f"{path}: record {record_number} has {len(fields)} fields; "
                f"expected {len(FIELD_NAMES)}"
            )
        record = dict(zip(FIELD_NAMES, fields))
        if not record["name"] or not record["telecode"]:
            raise ValueError(
                f"{path}: record {record_number} has no station name or telecode"
            )
        if domestic_only and record["countryCode"]:
            continue
        records.append(record)

    names = [record["name"] for record in records]
    if len(names) != len(set(names)):
        raise ValueError(f"{path}: station names are not unique")
    return records


if __name__ == "__main__":
    raise SystemExit("Import load_station_names() from a project build tool.")
