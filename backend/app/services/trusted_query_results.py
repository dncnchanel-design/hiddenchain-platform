from __future__ import annotations

import math
from typing import Any, Mapping


FUNCTION_LABELS = {
    "sum": "求和",
    "average": "平均值",
    "max": "最大值",
    "min": "最小值",
    "count": "计数",
    "median": "中位数",
    "growth_rate": "增长率",
    "yoy": "同比",
    "mom": "环比",
    "group_by": "分组汇总",
    "threshold": "阈值判断",
    "trend": "趋势",
    "psi": "PSI",
    "mpc_aggregation": "MPC 聚合",
}


class TrustedQueryProjectionError(ValueError):
    """Raised when a signed connector result cannot be safely projected."""


def validated_trend(value: Any) -> list[dict[str, Any]]:
    """Project signed trend points to the public date/value schema."""

    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 366:
        raise TrustedQueryProjectionError("connector trend result is invalid")
    points: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TrustedQueryProjectionError("connector trend result is invalid")
        point_date = item.get("date")
        point_value = item.get("value")
        if (
            not isinstance(point_date, str)
            or not point_date.strip()
            or isinstance(point_value, bool)
            or not isinstance(point_value, (int, float))
            or not math.isfinite(float(point_value))
        ):
            raise TrustedQueryProjectionError("connector trend result is invalid")
        points.append({"date": point_date, "value": float(point_value)})
    return points


def validated_aggregate_result(value: Any) -> Any:
    """Project only compact aggregate scalars or maps, never row arrays."""

    def scalar(item: Any) -> int | float | str | None:
        if item is None:
            return None
        if isinstance(item, bool):
            raise TrustedQueryProjectionError("connector aggregate result is invalid")
        if isinstance(item, int):
            return item
        if isinstance(item, float):
            if math.isfinite(item):
                return item
            raise TrustedQueryProjectionError("connector aggregate result is invalid")
        if isinstance(item, str) and len(item) <= 160:
            return item
        raise TrustedQueryProjectionError("connector aggregate result is invalid")

    if isinstance(value, Mapping):
        if len(value) > 366:
            raise TrustedQueryProjectionError("connector aggregate result is invalid")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 160:
                raise TrustedQueryProjectionError("connector aggregate result is invalid")
            result[key] = scalar(item)
        return result
    return scalar(value)


def build_trusted_query_public_result(
    *,
    task_id: str,
    job_id: str,
    request_item_id: str,
    authorization_id: str,
    canonical_payload: Mapping[str, Any],
    attempt: int,
    asset_version_id: str,
    signed_result: Mapping[str, Any],
    connector_audit: Mapping[str, Any],
    privacy_verification: Mapping[str, Any],
    receipt_schema: str,
) -> dict[str, Any]:
    """Build the one canonical metadata-only result persisted by the platform."""

    capability = signed_result.get("capability", "本地受控计算")
    if capability not in {"本地受控计算", "本地计算份额"}:
        raise TrustedQueryProjectionError("connector capability is invalid")
    record_count = signed_result.get("record_count")
    if record_count is not None and (
        isinstance(record_count, bool)
        or not isinstance(record_count, int)
        or record_count < 0
    ):
        raise TrustedQueryProjectionError("connector record count is invalid")
    function_code = canonical_payload.get("function")
    if not isinstance(function_code, str) or function_code not in FUNCTION_LABELS:
        raise TrustedQueryProjectionError("trusted-query function is invalid")
    resource_name = signed_result.get("resource_name")
    if (
        not isinstance(resource_name, str)
        or not resource_name
        or resource_name.strip() != resource_name
        or len(resource_name) > 160
    ):
        # Asset display names are mutable after later connector ingestion. V2
        # therefore requires the execution-time label inside the signed result
        # instead of rebuilding historical output from current asset metadata.
        raise TrustedQueryProjectionError("signed resource name is invalid")
    return {
        "task_id": task_id,
        "job_id": job_id,
        "request_item_id": request_item_id,
        "authorization_scope": authorization_id,
        "generated_at": signed_result.get("generated_at"),
        "result": validated_aggregate_result(signed_result.get("result")),
        "unit": signed_result.get("unit"),
        "record_count": record_count,
        "trend": validated_trend(signed_result.get("trend")),
        "resource_name": resource_name,
        "function_name": signed_result.get("function_name")
        or FUNCTION_LABELS[function_code],
        "digital_signature": "已验证",
        "audit_recorded": True,
        "connector_audit": dict(connector_audit),
        "raw_records_returned": False,
        "capability": capability,
        "privacy_verification": dict(privacy_verification),
        "idempotent_replay": attempt > 1,
        "asset_version_id": asset_version_id,
        "dataset_version": signed_result.get("dataset_version"),
        "dataset_local_ref": signed_result.get("dataset_local_ref"),
        "dataset_content_hash": signed_result.get("dataset_content_hash"),
        "verification_status": "CURRENT_SIGNATURE_VERIFIED",
        "receipt_verification_schema": receipt_schema,
    }
