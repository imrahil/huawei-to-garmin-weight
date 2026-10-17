"""Encode readings as FIT "weight" files (file_id.type = 9) with weight_scale messages.

FIT weight_scale fields (Garmin FIT profile) and how they are stored:

    field                 base    scale  units     source (Huawei)
    weight                uint16  100    kg        bodyWeight
    percent_fat           uint16  100    %         bodyFatRate
    percent_hydration     uint16  100    %         moistureRate
    bone_mass             uint16  100    kg        boneSalt
    muscle_mass           uint16  100    kg        skeletalMusclelMass (or muscleMass)
    basal_met             uint16  4      kcal/day  basalMetabolism
    metabolic_age         uint8   1      years     bodyAge
    visceral_fat_rating   uint8   1      -         visceralFatLevel (rounded)
    bmi                   uint16  10     kg/m^2    bmi

FIT timestamps are seconds since the FIT epoch 1989-12-31T00:00:00Z
(Unix 631065600). fit-tool takes Unix milliseconds and applies that offset.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Optional

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.weight_scale_message import WeightScaleMessage
from fit_tool.profile.profile_type import FileType, Manufacturer

from huawei_export import Reading

FIT_EPOCH_UNIX = 631065600

# FIT field resolution (1 / scale) per weight_scale field.
SCALES = {
    "weight": 100,
    "percent_fat": 100,
    "percent_hydration": 100,
    "bone_mass": 100,
    "muscle_mass": 100,
    "basal_met": 4,
    "metabolic_age": 1,
    "visceral_fat_rating": 1,
    "bmi": 10,
}


def _quantize(value: Optional[float], scale: int) -> Optional[float]:
    """Round half-up to the field's resolution so encoding never truncates."""
    if value is None:
        return None
    q = math.floor(value * scale + 0.5) / scale
    return int(q) if scale == 1 else q


def fit_values(r: Reading, muscle: str = "skeletal") -> dict[str, Optional[float]]:
    """The values that will be written for a reading, already at FIT resolution."""
    muscle_mass = r.skeletal_muscle_mass if muscle == "skeletal" else r.muscle_mass
    raw = {
        "weight": r.weight,
        "percent_fat": r.percent_fat,
        "percent_hydration": r.percent_hydration,
        "bone_mass": r.bone_mass,
        "muscle_mass": muscle_mass,
        "basal_met": r.basal_met,
        "metabolic_age": r.metabolic_age,
        "visceral_fat_rating": r.visceral_fat_rating,
        "bmi": r.bmi,
    }
    return {k: _quantize(v, SCALES[k]) for k, v in raw.items()}


def build_fit(readings: list[Reading], muscle: str = "skeletal",
              manufacturer: int = Manufacturer.DEVELOPMENT.value, product: int = 0) -> bytes:
    created_ms = round(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    builder = FitFileBuilder(auto_define=True, min_string_size=50)

    file_id = FileIdMessage()
    file_id.type = FileType.WEIGHT
    file_id.manufacturer = manufacturer
    file_id.product = product
    file_id.serial_number = 0x48574731  # arbitrary, constant across files
    file_id.time_created = created_ms
    builder.add(file_id)

    creator = FileCreatorMessage()
    creator.software_version = 100
    builder.add(creator)

    for r in readings:
        msg = WeightScaleMessage()
        msg.timestamp = (r.timestamp_ms // 1000) * 1000  # FIT has 1 s resolution
        for name, value in fit_values(r, muscle).items():
            if value is not None:
                setattr(msg, name, value)
        builder.add(msg)

    info = DeviceInfoMessage()
    info.timestamp = created_ms
    info.manufacturer = manufacturer
    info.product = product
    info.serial_number = file_id.serial_number
    builder.add(info)

    return builder.build().to_bytes()
