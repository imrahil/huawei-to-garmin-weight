"""Decode generated FIT files with Garmin's official SDK and compare to the source.

Encoding uses fit-tool; decoding here uses garmin-fit-sdk, so a scale, epoch or
rounding bug in the encoder cannot cancel itself out on the way back.
"""

from __future__ import annotations

import datetime as dt
import glob
import os
import random

from garmin_fit_sdk import Decoder, Stream

from fit_writer import SCALES, fit_values
from huawei_export import Reading


def decode(path: str) -> tuple[list[dict], dict, list]:
    stream = Stream.from_file(path)
    decoder = Decoder(stream)
    if not decoder.is_fit():
        raise ValueError(f"{path}: not a FIT file")
    if not decoder.check_integrity():
        raise ValueError(f"{path}: CRC / integrity check failed")
    stream.reset()  # the checks above consume the stream
    messages, errors = decoder.read()
    file_id = (messages.get("file_id_mesgs") or [{}])[0]
    return messages.get("weight_scale_mesgs", []), file_id, errors


def _close(a, b, scale: int) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= 0.5 / scale + 1e-9


def validate(fit_dir: str, readings: list[Reading], muscle: str, sample_size: int = 10) -> int:
    """Return the number of problems found; print a report."""
    expected = {r.timestamp_ms // 1000: r for r in readings}
    seen: set[int] = set()
    problems: list[str] = []
    decoded_rows: list[tuple[Reading, dict]] = []

    paths = sorted(glob.glob(os.path.join(fit_dir, "*.fit")))
    for path in paths:
        name = os.path.basename(path)
        try:
            mesgs, file_id, errors = decode(path)
        except ValueError as e:
            problems.append(str(e))
            continue
        if errors:
            problems.append(f"{name}: decoder errors {errors}")
        if file_id.get("type") != "weight":
            problems.append(f"{name}: file_id.type is {file_id.get('type')!r}, expected 'weight'")
        for m in mesgs:
            ts = m.get("timestamp")
            if not isinstance(ts, dt.datetime):
                problems.append(f"{name}: message without timestamp {m}")
                continue
            key = int(ts.timestamp())
            if key in seen:
                problems.append(f"{name}: duplicate timestamp {ts.isoformat()}")
            seen.add(key)
            r = expected.get(key)
            if r is None:
                problems.append(f"{name}: {ts.isoformat()} not in source")
                continue
            if f"{r.local:%Y-%m}" != name[:7]:
                problems.append(f"{name}: {ts.isoformat()} is in the wrong month file")
            want = fit_values(r, muscle)
            for field, value in want.items():
                got = m.get(field)
                if not _close(got, value, SCALES[field]):
                    problems.append(f"{name} {ts.isoformat()} {field}: fit={got!r} expected={value!r}")
            # Also compare against the raw Huawei value, within the FIT resolution.
            if not _close(m.get("weight"), r.weight, SCALES["weight"]):
                problems.append(f"{name} {ts.isoformat()} weight differs from source {r.weight}")
            decoded_rows.append((r, m))

    missing = set(expected) - seen
    for key in sorted(missing)[:20]:
        problems.append(f"missing from FIT output: {expected[key].utc.isoformat()}")

    print(f"Decoded {len(paths)} files, {len(seen)} weight_scale messages; source has {len(expected)} readings.")
    if decoded_rows:
        print(f"\nRandom sample of {min(sample_size, len(decoded_rows))} readings (source -> decoded FIT):")
        rng = random.Random(42)
        for r, m in sorted(rng.sample(decoded_rows, min(sample_size, len(decoded_rows))),
                           key=lambda x: x[0].timestamp_ms):
            print(f"  {r.local:%Y-%m-%d %H:%M} "
                  f"w {r.weight}->{m.get('weight')}  fat {_fmt(r.percent_fat)}->{m.get('percent_fat')}  "
                  f"h2o {_fmt(r.percent_hydration)}->{m.get('percent_hydration')}  "
                  f"muscle {_fmt(r.skeletal_muscle_mass if muscle == 'skeletal' else r.muscle_mass)}->{m.get('muscle_mass')}  "
                  f"bone {_fmt(r.bone_mass)}->{m.get('bone_mass')}  bmr {_fmt(r.basal_met)}->{m.get('basal_met')}  "
                  f"visc {_fmt(r.visceral_fat_rating)}->{m.get('visceral_fat_rating')}  "
                  f"age {r.metabolic_age}->{m.get('metabolic_age')}  bmi {_fmt(r.bmi)}->{m.get('bmi')}")
    print()
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems[:50]:
            print("  " + p)
    else:
        print("OK: every source reading is present exactly once and all fields match within FIT resolution.")
    return len(problems)


def _fmt(v):
    return None if v is None else round(v, 2)
