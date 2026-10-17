"""Read body-composition readings from a Huawei Health data export.

The export ("Privacy Centre -> Request your data") contains
``Health detail data & description/health detail data*.json``. Each file is a
JSON array of records; scale readings are records whose single sample point
has ``key == "WEIGHT_BODYFAT_BROAD"``. The sample's ``value`` is itself a JSON
string with the measurements, e.g.::

    {"bodyWeight": 72.4, "bodyFatRate": 20.7, "moistureRate": 55.3, ...}

Every reading appears twice (record ``type`` 8 and 10006, same ``recordId``
and identical values), so readings are deduplicated by timestamp.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import glob
import json
import os
import re
from collections import Counter
from typing import Iterable, Optional

WEIGHT_KEY = "WEIGHT_BODYFAT_BROAD"
DETAIL_DIR = "Health detail data & description"


@dataclasses.dataclass
class Reading:
    timestamp_ms: int  # Unix epoch, UTC
    utc_offset_min: int  # local offset at the time of the reading
    record_id: str
    device_code: int
    weight: float  # kg
    percent_fat: Optional[float] = None  # %
    percent_hydration: Optional[float] = None  # %
    muscle_mass: Optional[float] = None  # kg, total muscle (Huawei "muscleMass")
    skeletal_muscle_mass: Optional[float] = None  # kg
    bone_mass: Optional[float] = None  # kg
    basal_met: Optional[float] = None  # kcal/day
    visceral_fat_rating: Optional[float] = None  # Huawei level, can be x.5
    metabolic_age: Optional[int] = None  # years (Huawei "bodyAge")
    bmi: Optional[float] = None
    sub_user: Optional[str] = None  # set for guest/family-member readings

    @property
    def utc(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.timestamp_ms / 1000, dt.timezone.utc)

    @property
    def local(self) -> dt.datetime:
        return self.utc.astimezone(dt.timezone(dt.timedelta(minutes=self.utc_offset_min)))


@dataclasses.dataclass
class LoadStats:
    files: int = 0
    raw_records: int = 0
    duplicates: int = 0
    sub_user_skipped: int = 0
    by_type: Counter = dataclasses.field(default_factory=Counter)


def _parse_offset(tz: Optional[str]) -> int:
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", tz or "")
    if not m:
        return 0
    sign = -1 if m.group(1) == "-" else 1
    return sign * (int(m.group(2)) * 60 + int(m.group(3)))


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _to_reading(record: dict, sample: dict) -> Reading:
    v = json.loads(sample["value"])
    sub_user = record.get("subUser") or (
        v.get("extendAttribute") if v.get("extendAttribute") not in (None, "", "0") else None
    )
    age = _num(v.get("bodyAge"))
    return Reading(
        timestamp_ms=int(sample.get("startTime") or record["startTime"]),
        utc_offset_min=_parse_offset(record.get("timeZone")),
        record_id=record.get("recordId", ""),
        device_code=record.get("deviceCode", 0),
        weight=float(v["bodyWeight"]),
        percent_fat=_num(v.get("bodyFatRate")),
        percent_hydration=_num(v.get("moistureRate")),
        muscle_mass=_num(v.get("muscleMass")),
        skeletal_muscle_mass=_num(v.get("skeletalMusclelMass")),  # sic, Huawei typo
        bone_mass=_num(v.get("boneSalt")),
        basal_met=_num(v.get("basalMetabolism")),
        visceral_fat_rating=_num(v.get("visceralFatLevel")),
        metabolic_age=int(age) if age is not None else None,
        bmi=_num(v.get("bmi")),
        sub_user=sub_user,
    )


def iter_raw(export_dir: str) -> Iterable[tuple[str, dict, dict]]:
    """Yield (file, record, sample) for every weight sample point in the export."""
    pattern = os.path.join(export_dir, DETAIL_DIR, "*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no files match {pattern!r}")
    for path in files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for record in data:
            for sample in record.get("samplePoints") or []:
                if sample.get("key") == WEIGHT_KEY:
                    yield path, record, sample


def load_readings(export_dir: str, include_sub_users: bool = False) -> tuple[list[Reading], LoadStats]:
    """Load, filter and deduplicate readings, sorted by time.

    Deduplication key is the timestamp truncated to whole seconds, because
    that is the resolution of a FIT timestamp.
    """
    stats = LoadStats()
    files = set()
    by_second: dict[int, Reading] = {}
    for path, record, sample in iter_raw(export_dir):
        files.add(path)
        stats.raw_records += 1
        stats.by_type[record.get("type")] += 1
        r = _to_reading(record, sample)
        if r.sub_user and not include_sub_users:
            stats.sub_user_skipped += 1
            continue
        key = r.timestamp_ms // 1000
        if key in by_second:
            stats.duplicates += 1
            continue
        by_second[key] = r
    stats.files = len(files)
    return sorted(by_second.values(), key=lambda r: r.timestamp_ms), stats
