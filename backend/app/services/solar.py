from __future__ import annotations

import importlib.util
import math
from datetime import datetime, timezone
from typing import Any

from ..security import sha256_json


class PvlibSolarAdapter:
    """Calculate privacy-safe solar geometry and plane-of-array irradiance."""

    code = "PVLIB_SOLAR_RESOURCE_0_15"
    version = "0.15.2"

    @classmethod
    def status(cls) -> dict[str, Any]:
        installed = importlib.util.find_spec("pvlib") is not None
        return {
            "code": cls.code,
            "version": cls.version,
            "installed": installed,
            "mode": "SOLAR_POSITION_AND_POA_IRRADIANCE",
            "raw_data_exposed": False,
        }

    @staticmethod
    def _bounded(name: str, value: float, minimum: float, maximum: float) -> float:
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < minimum or numeric > maximum:
            raise ValueError(f"{name.upper()}_OUT_OF_RANGE")
        return numeric

    @classmethod
    def evaluate(
        cls,
        *,
        latitude: float,
        longitude: float,
        timestamp_utc: datetime,
        surface_tilt: float,
        surface_azimuth: float,
        ghi_wm2: float,
        dni_wm2: float,
        dhi_wm2: float,
    ) -> dict[str, Any]:
        latitude = cls._bounded("latitude", latitude, -90.0, 90.0)
        longitude = cls._bounded("longitude", longitude, -180.0, 180.0)
        surface_tilt = cls._bounded("surface_tilt", surface_tilt, 0.0, 180.0)
        surface_azimuth = cls._bounded("surface_azimuth", surface_azimuth, -360.0, 360.0)
        ghi_wm2 = cls._bounded("ghi_wm2", ghi_wm2, 0.0, 1500.0)
        dni_wm2 = cls._bounded("dni_wm2", dni_wm2, 0.0, 1500.0)
        dhi_wm2 = cls._bounded("dhi_wm2", dhi_wm2, 0.0, 1500.0)
        if timestamp_utc.tzinfo is None or timestamp_utc.utcoffset() is None:
            raise ValueError("TIMESTAMP_MUST_INCLUDE_TIMEZONE")

        try:
            import pandas as pd
            import pvlib
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError("PVLIB_NOT_INSTALLED") from exc

        timestamp = timestamp_utc.astimezone(timezone.utc)
        times = pd.DatetimeIndex([timestamp])
        location = pvlib.location.Location(latitude, longitude, tz="UTC")
        solar_position = location.get_solarposition(times)
        irradiance = pvlib.irradiance.get_total_irradiance(
            surface_tilt=surface_tilt,
            surface_azimuth=surface_azimuth,
            solar_zenith=float(solar_position["apparent_zenith"].iloc[0]),
            solar_azimuth=float(solar_position["azimuth"].iloc[0]),
            dni=dni_wm2,
            ghi=ghi_wm2,
            dhi=dhi_wm2,
        )

        input_hash = sha256_json(
            {
                "latitude": latitude,
                "longitude": longitude,
                "timestamp_utc": timestamp.isoformat(),
                "surface_tilt": surface_tilt,
                "surface_azimuth": surface_azimuth,
                "ghi_wm2": ghi_wm2,
                "dni_wm2": dni_wm2,
                "dhi_wm2": dhi_wm2,
            }
        )
        return {
            "adapter": cls.code,
            "library_version": cls.version,
            "status": "CALCULATED",
            "input_hash": input_hash,
            "solar_position": {
                "apparent_zenith_deg": round(float(solar_position["apparent_zenith"].iloc[0]), 6),
                "azimuth_deg": round(float(solar_position["azimuth"].iloc[0]), 6),
            },
            "plane_of_array_irradiance_wm2": {
                key: round(float(value), 6)
                for key, value in irradiance.items()
                if value is not None and math.isfinite(float(value))
            },
            "raw_data_exposed": False,
        }
