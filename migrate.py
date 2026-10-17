"""Huawei Health body composition -> Garmin Connect FIT files.

    python migrate.py inspect  EXPORT_DIR
    python migrate.py convert  EXPORT_DIR [--out out] [--since 2024-01-01] [--until 2026-10-15]
    python migrate.py validate EXPORT_DIR [--out out]

Nothing is uploaded anywhere; import the files from OUT/fit manually via
Garmin Connect web -> Import Data.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict

from fit_writer import build_fit, fit_values
from huawei_export import Reading, iter_raw, load_readings


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _select(args) -> list[Reading]:
    readings, stats = load_readings(args.export_dir, include_sub_users=args.include_sub_users)
    print(f"{stats.files} files, {stats.raw_records} raw weight records "
          f"(record types {dict(stats.by_type)}), {stats.duplicates} duplicates dropped, "
          f"{stats.sub_user_skipped} sub-user/guest records skipped -> {len(readings)} readings")
    if args.since:
        readings = [r for r in readings if r.local.date() >= args.since]
    if args.until:
        readings = [r for r in readings if r.local.date() <= args.until]
    if args.since or args.until:
        print(f"{len(readings)} readings within --since/--until")
    if not readings:
        sys.exit("nothing to do")
    return readings


def cmd_inspect(args) -> None:
    fields = Counter()
    for _, record, sample in iter_raw(args.export_dir):
        fields.update(json.loads(sample["value"]).keys())
    readings = _select(args)
    print(f"range (local): {readings[0].local:%Y-%m-%d %H:%M} -> {readings[-1].local:%Y-%m-%d %H:%M}")
    print("fields in sample values (raw record count):")
    for k, n in fields.most_common():
        print(f"  {k:22} {n}")
    per_year = Counter(r.local.year for r in readings)
    print("readings per year:", dict(sorted(per_year.items())))


def cmd_convert(args) -> None:
    readings = _select(args)
    fit_dir = os.path.join(args.out, "fit")
    os.makedirs(fit_dir, exist_ok=True)
    for old in os.listdir(fit_dir):
        if old.endswith(".fit"):
            os.remove(os.path.join(fit_dir, old))

    by_month: dict[str, list[Reading]] = defaultdict(list)
    for r in readings:
        by_month[f"{r.local:%Y-%m}"].append(r)

    months = []
    for month, rs in sorted(by_month.items()):
        name = f"{month}.fit"
        data = build_fit(rs, muscle=args.muscle)
        with open(os.path.join(fit_dir, name), "wb") as f:
            f.write(data)
        months.append((month, name, len(rs), rs[0], rs[-1], len(data)))

    with open(os.path.join(args.out, "months.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "file", "readings", "first_local", "last_local", "bytes"])
        for month, name, n, first, last, size in months:
            w.writerow([month, name, n, f"{first.local:%Y-%m-%d %H:%M}", f"{last.local:%Y-%m-%d %H:%M}", size])

    fit_cols = list(fit_values(readings[0], args.muscle))
    with open(os.path.join(args.out, "summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "local_time", "utc_time", "record_id",
                    "src_weight", "src_body_fat", "src_hydration", "src_muscle_total", "src_muscle_skeletal",
                    "src_bone", "src_basal_met", "src_visceral_fat", "src_body_age", "src_bmi"]
                   + [f"fit_{c}" for c in fit_cols])
        for r in readings:
            fv = fit_values(r, args.muscle)
            w.writerow([f"{r.local:%Y-%m}.fit", r.local.isoformat(timespec="seconds"),
                        r.utc.isoformat(timespec="seconds"), r.record_id,
                        r.weight, _r(r.percent_fat), _r(r.percent_hydration), _r(r.muscle_mass),
                        _r(r.skeletal_muscle_mass), _r(r.bone_mass), _r(r.basal_met),
                        r.visceral_fat_rating, r.metabolic_age, _r(r.bmi)]
                       + [fv[c] for c in fit_cols])

    print(f"wrote {len(months)} monthly FIT files to {fit_dir}")
    print(f"wrote {os.path.join(args.out, 'summary.csv')} and months.csv")
    smallest = sorted(months, key=lambda m: (m[2], m[0]))[:3]
    print("smallest files (good first test import): " + ", ".join(f"{m[1]} ({m[2]} readings)" for m in smallest))


def cmd_validate(args) -> None:
    from fit_check import validate
    readings = _select(args)
    problems = validate(os.path.join(args.out, "fit"), readings, args.muscle, args.sample)
    sys.exit(1 if problems else 0)


def _r(v, nd: int = 3):
    return None if v is None else round(v, nd)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("inspect", cmd_inspect), ("convert", cmd_convert), ("validate", cmd_validate)):
        s = sub.add_parser(name)
        s.set_defaults(fn=fn)
        s.add_argument("export_dir", help="unzipped Huawei export (contains 'Health detail data & description')")
        s.add_argument("--out", default="out", help="output directory (default: out)")
        s.add_argument("--since", type=_date, help="first local date to include, YYYY-MM-DD")
        s.add_argument("--until", type=_date, help="last local date to include, YYYY-MM-DD")
        s.add_argument("--muscle", choices=("skeletal", "total"), default="skeletal",
                       help="Huawei value to write as FIT muscle_mass (default: skeletal, "
                            "which is what Garmin Index scales report)")
        s.add_argument("--include-sub-users", action="store_true",
                       help="also export readings Huawei attributed to a guest/family member")
        if name == "validate":
            s.add_argument("--sample", type=int, default=10, help="random readings to print")
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
