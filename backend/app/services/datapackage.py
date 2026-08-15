from __future__ import annotations

import importlib.util
from typing import Any

from ..security import sha256_json
from .arrow_connector import ArrowConnectorAdapter


class FrictionlessCatalogAdapter:
    """Publish catalog metadata as a Frictionless Data Package descriptor."""

    code = "FRICTIONLESS_DATA_PACKAGE_5_19"
    version = "5.19.0"

    _SCHEMA_FIELDS = {
        "GENERATION_DATA": [{"name": "energy_mwh", "type": "number"}],
        "RETAIL_DATA": [{"name": "energy_mwh", "type": "number"}],
        "RENEWABLE_FORECAST": [
            {"name": "forecast_energy_mwh", "type": "number"},
            {"name": "forecast_accuracy_pct", "type": "number"},
        ],
        "USER_LOAD_CURVE": [{"name": "load_curve", "type": "array"}],
        "VPP_RESOURCE": [
            {"name": "adjustable_capacity_mw", "type": "number"},
            {"name": "storage_energy_mwh", "type": "number"},
            {"name": "response_minutes", "type": "number"},
        ],
        "GRID_CONSTRAINT": [
            {"name": "n_minus_one_passed", "type": "boolean"},
            {"name": "max_residual_imbalance_mwh", "type": "number"},
        ],
    }

    @classmethod
    def status(cls) -> dict[str, Any]:
        installed = importlib.util.find_spec("frictionless") is not None
        return {
            "code": cls.code,
            "version": cls.version,
            "installed": installed,
            "profile": "data-package",
            "raw_data_exposed": False,
        }

    @classmethod
    def build(cls, entries: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            from frictionless import Package
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError("FRICTIONLESS_NOT_INSTALLED") from exc

        resources: list[dict[str, Any]] = []
        for entry in entries:
            product_id = str(entry["data_product_id"])
            asset_type = str(entry["asset_type"])
            resources.append(
                {
                    "name": product_id.lower(),
                    "title": entry["label"],
                    "path": f"connector://hiddenchain/products/{product_id}",
                    "format": "json",
                    "mediatype": "application/json",
                    "schema": {"fields": cls._SCHEMA_FIELDS.get(asset_type, [])},
                    "custom": {
                        "hiddenchain": {
                            "data_product_id": product_id,
                            "asset_type": asset_type,
                            "semantic_ref": entry["semantic_ref"],
                            "unit": entry["unit"],
                            "time_granularity": entry["time_granularity"],
                            "schema_version": entry["schema_version"],
                            "sensitivity_level": entry["sensitivity_level"],
                            "quality": {
                                "validation_status": entry["quality"]["validation_status"],
                                "record_count": entry["quality"]["record_count"],
                                "period": entry["quality"]["period"],
                            },
                            "usage": entry["usage"],
                        }
                    },
                }
            )

        package = Package(
            {
                "name": "hiddenchain-energy-v1",
                "title": "隐链明算能源可信数据目录",
                "profile": "data-package",
                "description": "只描述可发现的数据产品元数据；原始记录留在提供方连接器内。",
                "resources": [],
            }
        )
        descriptor = package.to_descriptor()
        descriptor["resources"] = resources
        descriptor["custom"] = {
            "hiddenchain": {
                "connector_protocol": "HCDS-1.0",
                "raw_data_exposed": False,
                "usage_control": "OPA_REGO_COMPAT",
                "columnar_interop": ArrowConnectorAdapter.describe_resources(resources),
            }
        }
        columnar_interop = descriptor["custom"]["hiddenchain"]["columnar_interop"]
        return {
            "adapter": cls.code,
            "profile": "data-package",
            "resource_count": len(resources),
            "package_hash": sha256_json(descriptor),
            "descriptor": descriptor,
            "columnar_interop": columnar_interop,
            "raw_data_exposed": False,
        }
