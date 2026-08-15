from __future__ import annotations

import importlib.util
from typing import Any

from ..security import sha256_json


class ArrowConnectorAdapter:
    """Expose Arrow-compatible schemas at the connector boundary only."""

    code = "APACHE_ARROW_SCHEMA_25"
    version = "25.0.1"

    _TYPE_MAP = {
        "boolean": "bool",
        "integer": "int64",
        "number": "double",
        "string": "string",
    }

    @classmethod
    def status(cls) -> dict[str, Any]:
        installed = importlib.util.find_spec("pyarrow") is not None
        return {
            "code": cls.code,
            "version": cls.version,
            "installed": installed,
            "mode": "METADATA_ONLY_COLUMNAR_SCHEMA",
            "raw_data_exposed": False,
        }

    @classmethod
    def describe_resources(cls, resources: list[dict[str, Any]]) -> dict[str, Any]:
        """Build deterministic Arrow schema summaries without reading connector payloads."""
        summary = cls.status()
        if not summary["installed"]:
            summary["resources"] = []
            return summary

        try:
            import pyarrow as pa
        except (ImportError, ModuleNotFoundError):  # pragma: no cover - status covers minimal installs
            summary["installed"] = False
            summary["resources"] = []
            return summary

        described: list[dict[str, Any]] = []
        for resource in resources:
            fields: list[dict[str, str]] = []
            arrow_fields = []
            for field in resource.get("schema", {}).get("fields", []):
                field_name = str(field["name"])
                field_type = str(field.get("type", "string"))
                if field_type == "array":
                    arrow_type = pa.list_(pa.float64())
                else:
                    arrow_type = {
                        "bool": pa.bool_(),
                        "int64": pa.int64(),
                        "double": pa.float64(),
                        "string": pa.string(),
                    }.get(cls._TYPE_MAP.get(field_type, "string"), pa.string())
                fields.append({"name": field_name, "type": str(arrow_type)})
                arrow_fields.append(pa.field(field_name, arrow_type))
            schema = pa.schema(arrow_fields)
            described.append(
                {
                    "name": resource["name"],
                    "schema_fingerprint": sha256_json(
                        {"fields": fields, "metadata": {"raw_data_exposed": False}}
                    ),
                    "fields": fields,
                    "metadata": {"raw_data_exposed": False},
                    "arrow_schema": str(schema),
                }
            )
        summary["resources"] = described
        return summary
