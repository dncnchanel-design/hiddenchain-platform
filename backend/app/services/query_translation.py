from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from ..schemas import (
    TrustedExecutionTranslationRequest,
    TrustedQueryTranslation,
)
from .llm import DeepSeekUnavailable, translate_query_intent
from .trust_execution import TARGET_CATALOG


FUNCTION_LABELS = {
    "SUM": "求和",
    "BALANCE": "平衡计算",
    "TREND": "趋势分析",
}

ALLOWED_GROUPS = {"region", "organization", "period"}


class QueryTranslationRejected(RuntimeError):
    """Raised when the model output is not a safe, executable instruction."""


def redact_query_text(value: str) -> str:
    """Remove common identifiers before the question leaves the local service."""

    redacted = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱]", value)
    redacted = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号]", redacted)
    redacted = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b", "[标识符]", redacted)
    redacted = re.sub(r"(?<!\d)\d{6,}(?!\d)", "[编号]", redacted)
    redacted = re.sub(
        r"(?<![\d.])-?(?:\d{1,3}\.){3}\d{1,3}(?![\d.])",
        "[地址]",
        redacted,
    )
    redacted = re.sub(
        r"(?<!\d)(?:-?\d{1,3}(?:\.\d+)?\s*,\s*)-?\d{1,3}(?:\.\d+)?(?!\d)",
        "[坐标]",
        redacted,
    )
    return redacted


def _catalog_for_prompt() -> list[dict[str, Any]]:
    return [
        {
            "id": target_id,
            "unit": str(descriptor.get("unit", "")),
            "provider": str(descriptor.get("provider", "")),
            "granularity": str(descriptor.get("granularity", "")),
            "description": ",".join(str(item) for item in descriptor.get("tags", [])),
        }
        for target_id, descriptor in TARGET_CATALOG.items()
        if target_id != "USER_DETAIL"
    ]


def _previous_month(reference: date) -> tuple[date, date]:
    first = reference.replace(day=1)
    last = first.fromordinal(first.toordinal() - 1)
    return last.replace(day=1), last


def validate_translation(payload: dict[str, Any]) -> TrustedQueryTranslation:
    """Validate every model field locally before it can reach the executor."""

    try:
        translation = TrustedQueryTranslation.model_validate(payload)
    except ValidationError as exc:
        raise QueryTranslationRejected("翻译结果缺少必要字段或包含非法字段") from exc

    targets = translation.target_data_types
    if len(set(targets)) != len(targets):
        raise QueryTranslationRejected("翻译结果包含重复数据目标")
    unknown = [target for target in targets if target not in TARGET_CATALOG or target == "USER_DETAIL"]
    if unknown:
        raise QueryTranslationRejected(f"翻译结果包含未登记的数据目标：{', '.join(unknown)}")
    if translation.period_start > translation.period_end:
        raise QueryTranslationRejected("翻译结果的时间范围无效")
    if not translation.group_by or any(item not in ALLOWED_GROUPS for item in translation.group_by):
        raise QueryTranslationRejected("翻译结果包含未登记的分组方式")
    if "period" not in translation.group_by:
        raise QueryTranslationRejected("固定查询必须按时间分组")

    units = {str(TARGET_CATALOG[target]["unit"]) for target in targets}
    if translation.function == "SUM":
        if len(targets) < 2:
            raise QueryTranslationRejected("求和至少需要两个数据目标")
        if len(units) != 1:
            raise QueryTranslationRejected("求和数据的单位必须完全一致")
    elif translation.function == "BALANCE":
        if set(targets) != {"POWER_THERMAL_OUTPUT", "GRID_LOAD"} or len(targets) != 2:
            raise QueryTranslationRejected("当前只支持火电出力减电网负荷的固定平衡公式")
    elif translation.function == "TREND" and not targets:
        raise QueryTranslationRejected("趋势分析至少需要一个数据目标")
    return translation


def translate_query(request: TrustedExecutionTranslationRequest) -> dict[str, Any]:
    question = request.question.strip()
    redacted_question = redact_query_text(question)
    today = datetime.now(UTC).date()
    default_start, default_end = _previous_month(today)
    context = {
        "today": today.isoformat(),
        "catalog": _catalog_for_prompt(),
        "allowed_functions": [
            {"id": code, "label": label}
            for code, label in FUNCTION_LABELS.items()
        ],
        "constraints": {
            "period_start_hint": request.period_start.isoformat() if request.period_start else None,
            "period_end_hint": request.period_end.isoformat() if request.period_end else None,
            "requested_granularity_hint": request.requested_granularity,
            "spatial_scope_hint": request.spatial_scope,
            "group_by_hint": request.group_by,
            "output_mode_hint": request.output_mode,
            "default_period_if_question_says_previous_month": {
                "start": default_start.isoformat(),
                "end": default_end.isoformat(),
            },
        },
    }
    if request.offline_test:
        if request.offline_test and request.spatial_scope == "METER_POINT":
            raise QueryTranslationRejected("离线测试模式不支持计量点范围")
        generated = _offline_translation(question, default_start, default_end)
    else:
        generated = translate_query_intent(question=redacted_question, context=context)
    raw_payload = generated.get("payload")
    if not isinstance(raw_payload, dict):
        raise QueryTranslationRejected("翻译结果不是结构化对象")

    # Explicit form selections are local constraints, not model decisions.
    if request.period_start:
        raw_payload["period_start"] = request.period_start.isoformat()
    if request.period_end:
        raw_payload["period_end"] = request.period_end.isoformat()
    if request.requested_granularity:
        raw_payload["requested_granularity"] = request.requested_granularity
    raw_payload["spatial_scope"] = request.spatial_scope
    raw_payload["group_by"] = request.group_by
    raw_payload["output_mode"] = request.output_mode

    try:
        validated = validate_translation(raw_payload)
    except QueryTranslationRejected:
        raise
    except Exception as exc:
        raise QueryTranslationRejected("翻译结果校验失败") from exc
    return {
        "translation": validated.model_dump(mode="json"),
        "translation_hash": translation_hash(validated.model_dump(mode="json")),
        "question": question,
        "redacted_question": redacted_question,
        "ready": True,
        "function_label": FUNCTION_LABELS[validated.function],
        "provider": generated["provider"],
        "model": generated["model"],
        "request_id": generated["request_id"],
        "duration_ms": generated["duration_ms"],
        "usage": generated["usage"],
        "offline_test": request.offline_test,
    }


def _offline_translation(question: str, default_start: date, default_end: date) -> dict[str, Any]:
    """Small, explicit fixture for local UI checks; never used as production fallback."""

    normalized = question.strip()
    if normalized == "查询调度实时出力变化趋势":
        payload = {
            "function": "TREND",
            "target_data_types": ["POWER_DISPATCH"],
            "period_start": default_start.isoformat(),
            "period_end": default_end.isoformat(),
            "requested_granularity": "15_MINUTE",
            "spatial_scope": "REGION",
            "group_by": ["region", "period"],
            "output_mode": "CHART",
        }
    elif normalized == "查询某企业15分钟级原始负荷明细":
        payload = {
            "function": "TREND",
            "target_data_types": ["GRID_LOAD"],
            "period_start": default_start.isoformat(),
            "period_end": default_end.isoformat(),
            "requested_granularity": "15_MINUTE",
            "spatial_scope": "ORGANIZATION",
            "group_by": ["organization", "period"],
            "output_mode": "COMPUTE_ONLY",
        }
    elif normalized == "分析上月由于电煤库存变化引起的火电出力与电网负荷平衡趋势":
        payload = {
            "function": "TREND",
            "target_data_types": ["COAL_INVENTORY", "POWER_THERMAL_OUTPUT", "GRID_LOAD"],
            "period_start": default_start.isoformat(),
            "period_end": default_end.isoformat(),
            "requested_granularity": "MONTH",
            "spatial_scope": "REGION",
            "group_by": ["region", "period"],
            "output_mode": "SUMMARY",
        }
    else:
        raise QueryTranslationRejected("离线测试模式只支持页面预置示例")
    return {
        "payload": payload,
        "provider": "local_offline_fixture",
        "model": None,
        "request_id": None,
        "duration_ms": 0,
        "usage": {},
    }


def translation_hash(payload: dict[str, Any]) -> str:
    import hashlib
    import json

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_client_translation(payload: Any) -> TrustedQueryTranslation:
    if not isinstance(payload, dict):
        raise QueryTranslationRejected("缺少已确认的翻译指令")
    return validate_translation(payload)


__all__ = [
    "DeepSeekUnavailable",
    "FUNCTION_LABELS",
    "QueryTranslationRejected",
    "redact_query_text",
    "translate_query",
    "translation_hash",
    "validate_client_translation",
]
