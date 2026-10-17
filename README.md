# huawei-to-garmin-weight

A one-off migration of body-composition readings from a Huawei Body Fat Scale
(via a Huawei Health data export) into Garmin Connect. The tool writes monthly
FIT `weight` files. You import them by hand. Nothing is uploaded and no
external service is used.

## Usage

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows; bin/python elsewhere

# EXPORT is the unzipped "Request your data" export from Huawei Privacy Centre
.venv/Scripts/python migrate.py inspect  EXPORT
.venv/Scripts/python migrate.py convert  EXPORT            # -> out/fit/YYYY-MM.fit, out/summary.csv, out/months.csv
.venv/Scripts/python migrate.py validate EXPORT            # decode out/fit and compare with the source
```

Options (same for all commands):

| option | meaning |
|---|---|
| `--out DIR` | output directory (default `out`, git-ignored) |
| `--since` / `--until YYYY-MM-DD` | limit by local date, e.g. to stop where the Garmin scale takes over |
| `--muscle skeletal\|total` | which Huawei value becomes FIT `muscle_mass` (default `skeletal`) |
| `--include-sub-users` | also export readings Huawei attributed to a guest or family member |

Then in Garmin Connect web, go to **Import Data** and upload one small file
first (`convert` lists the smallest ones). Check that it looks right before you
import the rest month by month.

## Where the data is in the export

`Health detail data & description/health detail data*.json` contains JSON
arrays of records. Scale readings are records with a single sample point whose
`key` is `WEIGHT_BODYFAT_BROAD`. The `value` of that sample point is itself a
JSON string:

```json
{"bodyWeight":75.4,"bodyFatRate":21.7,"moistureRate":54.6,"muscleMass":56.1,
 "skeletalMusclelMass":31.1,"boneSalt":2.9,"basalMetabolism":1678.0,
 "visceralFatLevel":10.0,"bodyAge":32,"bmi":24.6,"bodyScore":78.0,
 "protein":14.4,"proteinRate":15.0,"age":40,"gender":1,"height":175,
 "extendAttribute":"0"}
```

* `startTime` / `endTime` are Unix epoch **milliseconds**, in UTC. `timeZone`
  (for example `+0100`) is the local offset at the time of the reading. It is
  only used to group readings into months and to show local time in the CSV.
* Every reading appears twice: once as record `type` 8 and once as type 10006,
  with the same `recordId` and identical values. Readings are deduplicated by
  timestamp at 1 s resolution, which is the resolution of a FIT timestamp.
* A reading with `subUser` set, or with a non-`"0"` `extendAttribute`, was
  taken by a guest or family member. These are skipped by default.
* The earliest readings (Dec 2018) contain only `bodyWeight`. Before about
  late 2020 there is no `skeletalMusclelMass`.

## Field mapping

| FIT `weight_scale` | stored as | Huawei |
|---|---|---|
| `timestamp` | uint32, seconds since 1989-12-31 00:00 UTC | `startTime` / 1000 |
| `weight` | uint16 ×100, kg | `bodyWeight` |
| `percent_fat` | uint16 ×100, % | `bodyFatRate` |
| `percent_hydration` | uint16 ×100, % | `moistureRate` |
| `muscle_mass` | uint16 ×100, kg | `skeletalMusclelMass` (default) or `muscleMass` |
| `bone_mass` | uint16 ×100, kg | `boneSalt` |
| `basal_met` | uint16 ×4, kcal/day | `basalMetabolism` |
| `metabolic_age` | uint8, years | `bodyAge` |
| `visceral_fat_rating` | uint8 | `visceralFatLevel`, with .5 rounded up |
| `bmi` | uint16 ×10 | `bmi` |

The default for `muscle_mass` is skeletal muscle. Garmin Index scales report
skeletal muscle, and Huawei's `muscleMass` (about 56 kg) is total muscle, so
using it would make the graph jump when you switch scales. Huawei's
`bodyScore`, `protein`, `proteinRate` and profile `age`/`height`/`gender` have
no FIT field and are dropped.

Values are rounded half-up to the field's resolution before encoding. Encoding
uses [fit-tool](https://pypi.org/project/fit-tool/). Validation decodes with
Garmin's official [garmin-fit-sdk](https://pypi.org/project/garmin-fit-sdk/),
so an epoch or scale bug in the encoder cannot cancel itself out. Each file is
written as `file_id` (type `weight`, manufacturer `development`), then
`file_creator`, then the `weight_scale` messages, then `device_info`.
