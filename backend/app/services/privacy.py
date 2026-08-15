from __future__ import annotations

import importlib.util
import math
from typing import Any

from ..config import settings


class DifferentialPrivacyUnavailable(ValueError):
    """Raised when a DP result was requested but the DP runtime is unavailable."""


class OpenDPAdapter:
    """Bounded-sum + Laplace release backed by the OpenDP Rust/Python library."""

    code = "OPENDP_BOUNDED_SUM_LAPLACE_0_15"

    @classmethod
    def status(cls) -> dict[str, Any]:
        return {
            "code": cls.code,
            "installed": importlib.util.find_spec("opendp") is not None,
            "bound_mw": settings.dp_max_load_mw,
            "mode": "BOUNDED_SUM_WITH_LAPLACE_POSTPROCESSING",
        }

    @classmethod
    def release_curve(
        cls,
        curves: list[list[float]],
        *,
        epsilon: float,
    ) -> tuple[list[float], dict[str, Any]]:
        if not curves:
            raise ValueError("No eligible load curves")
        if any(not curve for curve in curves):
            raise ValueError("Load curves must not be empty")
        curve_lengths = {len(curve) for curve in curves}
        if len(curve_lengths) != 1:
            raise ValueError("Load curves must have the same number of hours")
        if epsilon <= 0:
            raise ValueError("Differential privacy budget must be positive")
        bound = float(settings.dp_max_load_mw)
        if bound <= 0:
            raise ValueError("DP_MAX_LOAD_MW must be positive")

        try:
            import opendp.prelude as dp

            dp.enable_features("contrib")
        except (ImportError, ModuleNotFoundError) as exc:
            raise DifferentialPrivacyUnavailable("OPENDP_NOT_INSTALLED") from exc

        bounded: list[list[float]] = []
        for curve in curves:
            bounded_curve: list[float] = []
            for value in curve:
                numeric_value = float(value)
                if not math.isfinite(numeric_value):
                    raise ValueError("Load curves must contain finite numbers")
                bounded_curve.append(min(max(numeric_value, 0.0), bound))
            bounded.append(bounded_curve)
        noisy_curve: list[float] = []
        scale = bound / float(epsilon)
        for hour_values in zip(*bounded):
            # Each provider/group contributes one bounded value to this hour's
            # sum.  OpenDP checks the (symmetric distance, max divergence)
            # relation before the measurement is invoked.
            input_space = (
                dp.vector_domain(
                    dp.atom_domain(bounds=(0.0, bound), nan=False, T=float),
                    size=len(curves),
                ),
                dp.symmetric_distance(),
            )
            measurement = input_space >> dp.t.then_sum() >> dp.m.then_laplace(scale=scale)
            if not measurement.check(1, float(epsilon)):
                raise DifferentialPrivacyUnavailable("OPENDP_MEASUREMENT_CHECK_FAILED")
            released = float(measurement(list(hour_values)))
            # Non-negative clipping is post-processing and therefore does not
            # weaken the DP guarantee.  It also keeps the chart meaningful.
            released = min(max(released, 0.0), bound * len(curves))
            noisy_curve.append(round(released, 3))

        controls = {
            "engine": "OpenDP",
            "adapter_code": cls.code,
            "mechanism": "bounded_sum_then_laplace",
            "epsilon_per_hour_release": float(epsilon),
            "composition_count": len(noisy_curve),
            "composition_note": (
                "每个小时独立释放；若将整日序列视为单一隐私预算，生产部署应按组合定理分配 epsilon。"
            ),
            "bound_mw": bound,
            "input_clamped": True,
            "raw_records_returned": False,
            "raw_data_exposed": False,
        }
        return noisy_curve, controls
