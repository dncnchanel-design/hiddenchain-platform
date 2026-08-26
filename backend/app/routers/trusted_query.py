from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import get_current_user
from ..models import (
    DataRequestBatch,
    DataRequestItem,
    DataUsageRequest,
    ExecutionReceipt,
    PrivacyComputeJob,
    DidIdentity,
    User,
    new_id,
    utc_now,
)
from ..services.common import add_audit_log
from ..services.llm import DeepSeekUnavailable, translate_trusted_space_query
from ..services.query_translation import redact_query_text
from ..security import canonical_json, sha256_json
from ..schemas import TrustedSpaceQueryTranslation
from ..services.local_data_boundary import matching_rule, rule_decision, subject_node_config
from ..trust_models import DataAsset, DataAssetVersion


router = APIRouter(prefix="/trust-space/query", tags=["trusted-query"])

DOMAIN_TERMS = {
    "electricity": ("电力", "发电", "售电", "用电"),
    "coal": ("煤炭", "煤"),
    "heat": ("热能", "供热", "热力"),
    "gas": ("天然气", "燃气"),
    "oil": ("石油", "原油", "成品油"),
}
RESOURCE_TERMS = {
    "generation": ("发电量",),
    "production": ("产量",),
    "supply": ("供应量", "供热量", "供电量"),
    "consumption": ("消费量",),
    "inventory": ("库存",),
    "transport": ("运输量",),
    "price": ("价格",),
    "load": ("负荷",),
    "fuel": ("燃料消耗",),
    "loss": ("损耗",),
    "supply_temperature": ("供水温度",),
    "return_temperature": ("回水温度",),
    "storage": ("储量",),
    "pipeline_flow": ("管道流量",),
    "pressure": ("压力",),
    "refining": ("炼化量",),
    "sales": ("销售量",),
}
FUNCTION_TERMS = {
    "average": ("平均", "均值"),
    "max": ("最大", "最高"),
    "min": ("最小", "最低"),
    "count": ("计数", "多少条"),
    "median": ("中位数",),
    "growth_rate": ("增长率",),
    "yoy": ("同比",),
    "mom": ("环比",),
    "group_by": ("分组", "按地区", "按机构", "按时间"),
    "threshold": ("阈值", "是否超过", "是否低于"),
    "trend": ("趋势",),
    "psi": ("PSI", "psi"),
    "mpc_aggregation": ("MPC", "多方聚合"),
    "sum": ("总量", "合计", "求和"),
}
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

DEEPSEEK_FUNCTION_LABELS = {
    "sum": "求和",
    "average": "平均值",
    "max": "最大值",
    "min": "最小值",
    "count": "计数",
    "trend": "趋势",
}

RESOURCE_CATALOG = {
    "electricity": {"generation", "supply", "load", "price"},
    "coal": {"production", "supply", "consumption", "inventory", "transport", "price"},
    "heat": {"supply", "load", "fuel", "loss", "supply_temperature", "return_temperature", "price"},
    "gas": {"supply", "consumption", "storage", "pipeline_flow", "pressure", "price"},
    "oil": {"production", "refining", "inventory", "transport", "sales", "price"},
}

DOMAIN_LABELS = {
    "electricity": "电力",
    "coal": "煤炭",
    "heat": "热能",
    "gas": "天然气",
    "oil": "石油",
}


class TrustedQueryTranslationRejected(ValueError):
    """Raised when a DeepSeek preview is not a complete, locally safe shape."""


class ParseRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)


class ExecuteRequest(BaseModel):
    authorization_id: str | None = None
    provider_org_id: str | None = None
    energy_domain: str
    resource: str
    function: str
    start_date: date
    end_date: date
    region: str | None = None
    hour: int | None = Field(default=None, ge=0, le=23)
    threshold: float | None = None
    group_by: str | None = None
    decimals: int = Field(default=2, ge=0, le=6)
    confirmation_token: str | None = Field(default=None, min_length=1)


class ConfirmRequest(BaseModel):
    authorization_id: str | None = None
    provider_org_id: str | None = None
    energy_domain: str
    resource: str
    function: str
    start_date: date
    end_date: date
    region: str | None = None
    decimals: int = Field(default=2, ge=0, le=6)


def _match(text: str, vocabulary: dict[str, tuple[str, ...]]) -> str | None:
    for code, terms in vocabulary.items():
        if any(term in text for term in terms):
            return code
    return None


def _query_prompt_catalog() -> list[dict[str, Any]]:
    return [
        {
            "energy_domain": domain,
            "energy_domain_name": DOMAIN_LABELS[domain],
            "resources": sorted(resources),
        }
        for domain, resources in RESOURCE_CATALOG.items()
    ]


def _validate_selection(
    *,
    energy_domain: str,
    resource: str,
    function: str,
    start_date: date,
    end_date: date,
) -> None:
    if energy_domain not in RESOURCE_CATALOG:
        raise HTTPException(422, "能源种类不在固定查询范围内")
    if resource not in RESOURCE_CATALOG[energy_domain]:
        raise HTTPException(422, "数据资源不属于所选能源范围")
    if function not in FUNCTION_LABELS:
        raise HTTPException(422, "仅允许使用页面列出的固定函数")
    if start_date > end_date:
        raise HTTPException(422, "查询开始日期不能晚于结束日期")


def _translation_from_model(raw_payload: dict[str, Any]) -> TrustedSpaceQueryTranslation:
    try:
        translation = TrustedSpaceQueryTranslation.model_validate(raw_payload)
    except Exception as exc:
        raise TrustedQueryTranslationRejected("DeepSeek 翻译结果缺少必要字段或包含非法字段") from exc
    if translation.resource and not any(
        translation.resource in resources for resources in RESOURCE_CATALOG.values()
    ):
        raise TrustedQueryTranslationRejected("DeepSeek 翻译结果包含未登记的数据资源")
    if translation.energy_domain and translation.resource:
        if translation.resource not in RESOURCE_CATALOG[translation.energy_domain]:
            raise TrustedQueryTranslationRejected("DeepSeek 翻译出的能源种类与数据资源不匹配")
    if translation.function and translation.function not in DEEPSEEK_FUNCTION_LABELS:
        raise TrustedQueryTranslationRejected("DeepSeek 翻译出了未开放的固定函数")
    if translation.start_date and translation.end_date and translation.start_date > translation.end_date:
        raise TrustedQueryTranslationRejected("DeepSeek 翻译出的时间范围无效")
    return translation


def _intent_response(
    *,
    question: str,
    translation: TrustedSpaceQueryTranslation,
    provider: str,
    notice: str,
    model: str | None = None,
    request_id: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    function = translation.function or ""
    ready = all(
        (
            translation.energy_domain,
            translation.resource,
            translation.function,
            translation.start_date,
            translation.end_date,
        )
    )
    return {
        "question": question,
        "energy_domain": translation.energy_domain,
        "energy_domain_name": DOMAIN_LABELS.get(translation.energy_domain or "", "未识别"),
        "resource": translation.resource,
        "function": function,
        "function_name": FUNCTION_LABELS.get(function, "未识别固定函数"),
        "start_date": translation.start_date.isoformat() if translation.start_date else None,
        "end_date": translation.end_date.isoformat() if translation.end_date else None,
        "region": translation.region,
        "requires_authorization": True,
        "requires_confirmation": True,
        "ready": ready,
        "provider": provider,
        "model": model,
        "request_id": request_id,
        "duration_ms": duration_ms,
        "notice": notice,
    }


def _manual_parse(question: str) -> TrustedSpaceQueryTranslation:
    domain = _match(question, DOMAIN_TERMS)
    resource = _match(question, RESOURCE_TERMS)
    function = _match(question, FUNCTION_TERMS) or "sum"
    if domain and resource and resource not in RESOURCE_CATALOG[domain]:
        resource = None
    start_date, end_date = _manual_period(question)
    return TrustedSpaceQueryTranslation(
        energy_domain=domain,
        resource=resource,
        function=function if function in FUNCTION_LABELS else None,
        start_date=start_date,
        end_date=end_date,
    )


def _manual_period(question: str) -> tuple[date | None, date | None]:
    """Parse only explicit, deterministic periods for the offline fallback."""

    today = utc_now().date()
    full_date = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日?", question)
    if full_date:
        year, month, day = (int(value) for value in full_date.groups())
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None, None
        return parsed, parsed

    month = re.search(r"(?:(20\d{2})年?)?(\d{1,2})月", question)
    if month:
        year = int(month.group(1) or today.year)
        month_number = int(month.group(2))
        if 1 <= month_number <= 12:
            return date(year, month_number, 1), date(year, month_number, monthrange(year, month_number)[1])

    if "上月" in question or "上个月" in question:
        previous_month = today.replace(day=1) - timedelta(days=1)
        return previous_month.replace(day=1), previous_month
    relative_days = re.search(r"(?:近|最近)(\d{1,3})天", question)
    if relative_days:
        days = int(relative_days.group(1))
        if days > 0:
            return today - timedelta(days=days - 1), today
    return None, None


def _confirmation_claims(payload: ConfirmRequest, user: User) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "authorization_id": payload.authorization_id,
        "provider_org_id": payload.provider_org_id,
        "energy_domain": payload.energy_domain,
        "resource": payload.resource,
        "function": payload.function,
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "region": payload.region or None,
        "decimals": payload.decimals,
    }


def _issue_confirmation_token(claims: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(canonical_json(claims).encode()).decode().rstrip("=")
    signature = hmac.new(settings.signing_secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _verify_confirmation_token(token: str, payload: ExecuteRequest, user: User) -> None:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(settings.signing_secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        padding = "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(f"{encoded}{padding}").decode())
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, base64.binascii.Error) as exc:
        raise HTTPException(409, "确认令牌无效，请重新核对查询条件") from exc
    expected_claims = {
        "user_id": user.user_id,
        "authorization_id": payload.authorization_id,
        "provider_org_id": payload.provider_org_id,
        "energy_domain": payload.energy_domain,
        "resource": payload.resource,
        "function": payload.function,
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "region": payload.region or None,
        "decimals": payload.decimals,
    }
    if claims != expected_claims:
        raise HTTPException(409, "查询条件已变化，请重新确认后再执行")


def _configured_map(raw: str, label: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(503, f"{label}配置无效") from exc
    if not isinstance(value, dict):
        raise HTTPException(503, f"{label}配置无效")
    return {str(key): str(item) for key, item in value.items()}


def _platform_private_key() -> Ed25519PrivateKey:
    if not settings.platform_signing_private_key:
        raise HTTPException(503, "平台请求签名密钥未配置")
    try:
        decoded = base64.b64decode(settings.platform_signing_private_key, validate=True)
    except Exception:
        decoded = b""
    seed = decoded if len(decoded) == 32 else hashlib.sha256(settings.platform_signing_private_key.encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def _platform_public_key(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def _connector_failure(response: httpx.Response) -> tuple[int, Any]:
    status_code = 503 if response.status_code >= 500 else response.status_code
    try:
        payload = response.json()
    except ValueError:
        return status_code, "企业连接器正在启动或暂不可用，请稍后重试"
    if not isinstance(payload, dict):
        return status_code, "企业连接器拒绝了计算任务"
    detail = payload.get("detail")
    if detail in (None, ""):
        return status_code, "企业连接器拒绝了计算任务"
    return status_code, detail


def _validated_trend(value: Any) -> list[dict[str, Any]]:
    """Keep only signed, finite date/value points from a connector response."""

    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 366:
        raise HTTPException(502, "企业连接器趋势结果格式无效")
    points: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise HTTPException(502, "企业连接器趋势结果格式无效")
        point_date = item.get("date")
        point_value = item.get("value")
        if (
            not isinstance(point_date, str)
            or not point_date.strip()
            or isinstance(point_value, bool)
            or not isinstance(point_value, (int, float))
            or not math.isfinite(float(point_value))
        ):
            raise HTTPException(502, "企业连接器趋势结果格式无效")
        points.append({"date": point_date, "value": float(point_value)})
    return points


def _authorization(db: Session, request_id: str, user: User) -> tuple[DataUsageRequest, DataAsset]:
    authorization = db.get(DataUsageRequest, request_id)
    if authorization is None:
        raise HTTPException(404, "未找到授权记录")
    if authorization.applicant_org_id != user.org_id:
        raise HTTPException(403, "该授权不属于当前企业")
    if authorization.status != "APPROVED" or authorization.expires_at <= utc_now():
        raise HTTPException(403, "授权尚未批准、已撤销或已过期")
    asset = db.get(DataAsset, authorization.asset_id)
    if asset is None:
        raise HTTPException(409, "授权对应的数据资源不存在")
    return authorization, asset


def _resolve_authorization(
    db: Session,
    *,
    authorization_id: str | None,
    provider_org_id: str | None,
    energy_domain: str,
    resource: str,
    function: str,
    start_date: date,
    end_date: date,
    region: str | None,
    user: User,
) -> tuple[DataUsageRequest, DataAsset]:
    if authorization_id:
        return _authorization(db, authorization_id, user)
    if user.role_code != "REGULATOR" or "CREATE_CROSS_ENERGY_QUERY" not in set(user.permissions_json or []):
        raise HTTPException(403, "无授权编号时只有具备监管申请权限的 REGULATOR 可以命中主体规则")
    if not provider_org_id:
        raise HTTPException(422, "规则自动调用必须明确指定数据主体")

    assets = db.scalars(
        select(DataAsset).where(DataAsset.owner_org_id == provider_org_id, DataAsset.status == "ACTIVE")
    ).all()
    asset = next(
        (
            item
            for item in assets
            if (item.metadata_json or {}).get("domain") == energy_domain
            and (item.metadata_json or {}).get("resource_id") == resource
        ),
        None,
    )
    if asset is None:
        raise HTTPException(404, "该主体没有可用的目录资源")
    rule = matching_rule(
        db,
        owner_org_id=provider_org_id,
        resource_id=resource,
        function_code=function,
        requested_scope={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "region": region,
            "output_mode": "AGGREGATE_ONLY",
            "raw_data_export": False,
        },
    )
    if rule is None or rule_decision(rule) != "AUTO_CALL":
        raise HTTPException(403, "该请求未命中主体批准的自动调用规则，请先向企业申请")
    version = db.scalar(
        select(DataAssetVersion).where(DataAssetVersion.asset_id == asset.asset_id, DataAssetVersion.status == "ACTIVE").order_by(DataAssetVersion.version_no.desc())
    )
    applicant_did = db.scalar(
        select(DidIdentity).where(DidIdentity.owner_id == user.org_id, DidIdentity.org_id == user.org_id).order_by(DidIdentity.created_at.desc())
    )
    provider_did = db.scalar(
        select(DidIdentity).where(DidIdentity.owner_id == provider_org_id, DidIdentity.org_id == provider_org_id).order_by(DidIdentity.created_at.desc())
    )
    if version is None or applicant_did is None or provider_did is None:
        raise HTTPException(409, "主体目录或身份凭证不完整，无法执行规则调用")
    fingerprint = sha256_json(
        {
            "applicant_org_id": user.org_id,
            "provider_org_id": provider_org_id,
            "asset_id": asset.asset_id,
            "resource": resource,
            "function": function,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "region": region,
            "rule_id": rule.rule_id,
        }
    )
    existing = db.scalar(
        select(DataUsageRequest).where(DataUsageRequest.request_fingerprint == fingerprint)
    )
    if existing is not None:
        return _authorization(db, existing.request_id, user)
    now = utc_now()
    request = DataUsageRequest(
        request_id=new_id(),
        asset_id=asset.asset_id,
        asset_version_id=version.version_id,
        applicant_user_id=user.user_id,
        applicant_org_id=user.org_id,
        provider_org_id=provider_org_id,
        applicant_did=applicant_did.did_id,
        provider_did=provider_did.did_id,
        purpose="REGULATORY_CROSS_ENERGY_REVIEW",
        usage_mode="MPC_AGGREGATE",
        requested_scope_json={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "region": region,
            "output_mode": "AGGREGATE_ONLY",
            "raw_data_export": False,
        },
        requested_fields_json=[resource, function],
        terms_json={
            "output_mode": "AGGREGATE_ONLY",
            "raw_data_export": False,
            "authorization_source": "SUBJECT_APPROVED_RULE",
            "rule_id": rule.rule_id,
            "rule_version": f"v{rule.version_no}",
        },
        duration_days=max(1, (end_date - start_date).days + 1),
        expires_at=now + timedelta(days=1),
        status="APPROVED",
        decision_reason="命中主体预先批准的自动调用规则",
        decision_hash=rule.rule_hash,
        decision_capability_label="RULE_AUTO",
        state_version=1,
        request_fingerprint=fingerprint,
        submitted_at=now,
        decided_at=now,
        trace_id=f"trace-{new_id()[:24]}",
    )
    db.add(request)
    add_audit_log(
        db,
        action="REGULATOR_RULE_AUTO_AUTHORIZED",
        target_type="DATA_USAGE_REQUEST",
        target_id=request.request_id,
        result="SUCCESS",
        user=user,
        details={
            "provider_org_id": provider_org_id,
            "rule_id": rule.rule_id,
            "rule_version": rule.version_no,
            "raw_data_accessed": False,
        },
    )
    db.flush()
    return request, asset


def _request_item(
    db: Session,
    *,
    authorization: DataUsageRequest,
    asset: DataAsset,
    payload: ExecuteRequest,
    user: User,
) -> DataRequestItem:
    """Bind a query to one provider-scoped item and make retries idempotent."""

    existing = db.scalar(
        select(DataRequestItem).where(
            DataRequestItem.authorization_id == authorization.request_id,
            DataRequestItem.provider_org_id == authorization.provider_org_id,
        )
    )
    if existing is not None:
        if existing.status in {"REVOKED", "REJECTED", "FAILED"}:
            raise HTTPException(403, "该主体请求项已拒绝或撤销，不能继续调用")
        return existing

    metadata = asset.metadata_json or {}
    resource_id = str(metadata.get("resource_id") or payload.resource)
    requested_scope = {
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "region": payload.region,
        "function": payload.function,
        "output_mode": "AGGREGATE_ONLY",
        "raw_data_export": False,
    }
    rule = matching_rule(
        db,
        owner_org_id=authorization.provider_org_id,
        resource_id=resource_id,
        function_code=payload.function,
        requested_scope=requested_scope,
    )
    if rule_decision(rule) == "FORBIDDEN":
        raise HTTPException(403, "该主体规则禁止外部调用")
    confirmation_hash = sha256_json(
        {
            "authorization_id": authorization.request_id,
            "provider_org_id": authorization.provider_org_id,
            "resource": payload.resource,
            "function": payload.function,
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat(),
        }
    )
    batch = DataRequestBatch(
        batch_id=new_id(),
        applicant_user_id=user.user_id,
        applicant_org_id=user.org_id,
        purpose=authorization.purpose,
        requested_scope_json=requested_scope,
        allow_partial=False,
        status="EXECUTING",
        confirmation_hash=confirmation_hash,
        idempotency_key=f"authorization:{authorization.request_id}",
    )
    item = DataRequestItem(
        request_item_id=new_id(),
        batch_id=batch.batch_id,
        provider_org_id=authorization.provider_org_id,
        asset_id=authorization.asset_id,
        authorization_id=authorization.request_id,
        matched_rule_id=rule.rule_id if rule else None,
        matched_rule_version=f"v{rule.version_no}" if rule else None,
        scope_json=requested_scope,
        status="READY",
        idempotency_key=f"authorization:{authorization.request_id}",
    )
    db.add(batch)
    db.add(item)
    db.flush()
    return item


@router.post("/parse")
def parse_question(
    payload: ParseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if user.role_code == "ADMIN":
        raise HTTPException(403, "平台运维账号不能发起业务查询")
    question = payload.question.strip()
    provider = "deepseek"
    generated: dict[str, Any] = {}
    try:
        generated = translate_trusted_space_query(
            question=redact_query_text(question),
            context={
                "today": utc_now().date().isoformat(),
                "allowed_functions": [
                    {"id": code, "label": label}
                    for code, label in DEEPSEEK_FUNCTION_LABELS.items()
                ],
                "catalog": _query_prompt_catalog(),
                "constraints": {
                    "single_metric": True,
                    "single_function": True,
                    "single_period": True,
                    "raw_data_access": False,
                },
            },
        )
        translation = _translation_from_model(generated["payload"])
        response = _intent_response(
            question=question,
            translation=translation,
            provider=generated["provider"],
            notice="DeepSeek 只完成固定字段翻译；请核对下方条件，确认后才会创建计算任务。",
            model=generated["model"],
            request_id=generated["request_id"],
            duration_ms=generated["duration_ms"],
        )
    except DeepSeekUnavailable as exc:
        if str(exc).startswith("DeepSeek returned"):
            raise HTTPException(422, "DeepSeek 翻译结果无法确认，请重新描述查询需求") from exc
        provider = "manual_rules"
        translation = _manual_parse(question)
        response = _intent_response(
            question=question,
            translation=translation,
            provider=provider,
            notice="DeepSeek 当前不可用，已切换为手动规则预览；系统不会因此执行查询。",
        )
    except TrustedQueryTranslationRejected as exc:
        raise HTTPException(422, str(exc)) from exc

    add_audit_log(
        db,
        action="TRANSLATE_TRUSTED_SPACE_QUERY",
        target_type="TRUSTED_SPACE_QUERY_TRANSLATION",
        target_id=sha256_json(
            {
                "question": redact_query_text(question),
                "energy_domain": response["energy_domain"],
                "resource": response["resource"],
                "function": response["function"],
                "start_date": response["start_date"],
                "end_date": response["end_date"],
                "region": response["region"],
            }
        ),
        result="READY" if response["ready"] else "NEEDS_INPUT",
        user=user,
        details={
            "question": redact_query_text(question),
            "translation": {
                key: response[key]
                for key in (
                    "energy_domain",
                    "resource",
                    "function",
                    "start_date",
                    "end_date",
                    "region",
                )
            },
            "provider": response["provider"],
            "model": response["model"],
            "request_id": response["request_id"],
            "duration_ms": response["duration_ms"],
            "raw_data_accessed": False,
        },
    )
    db.commit()
    return response


@router.post("/confirm")
def confirm_query(
    payload: ConfirmRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if user.role_code == "ADMIN":
        raise HTTPException(403, "平台运维账号不能发起业务查询")
    if "CREATE_COMPUTE_TASK" not in set(user.permissions_json or []):
        raise HTTPException(403, "当前账号没有创建计算任务的权限")
    _validate_selection(
        energy_domain=payload.energy_domain,
        resource=payload.resource,
        function=payload.function,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    authorization, _asset = _resolve_authorization(
        db,
        authorization_id=payload.authorization_id,
        provider_org_id=payload.provider_org_id,
        energy_domain=payload.energy_domain,
        resource=payload.resource,
        function=payload.function,
        start_date=payload.start_date,
        end_date=payload.end_date,
        region=payload.region,
        user=user,
    )
    if payload.provider_org_id and payload.provider_org_id != authorization.provider_org_id:
        raise HTTPException(403, "确认的主体与授权主体不一致")
    payload.authorization_id = authorization.request_id
    payload.provider_org_id = authorization.provider_org_id
    claims = _confirmation_claims(payload, user)
    token = _issue_confirmation_token(claims)
    add_audit_log(
        db,
        action="CONFIRM_TRUSTED_SPACE_QUERY",
        target_type="TRUSTED_SPACE_QUERY_CONFIRMATION",
        target_id=sha256_json(claims),
        result="SUCCESS",
        user=user,
        details={
            **claims,
            "raw_data_accessed": False,
            "confirmation_token_issued": True,
        },
    )
    db.commit()
    return {
        "confirmed": True,
        "confirmation_token": token,
        "notice": "查询条件已确认，只有完全一致的条件才能执行。",
    }


@router.post("/execute")
def execute_query(
    payload: ExecuteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if "CREATE_COMPUTE_TASK" not in set(user.permissions_json or []):
        raise HTTPException(403, "当前账号没有创建计算任务的权限")
    if not payload.confirmation_token:
        raise HTTPException(409, "请先核对并确认查询条件")
    _validate_selection(
        energy_domain=payload.energy_domain,
        resource=payload.resource,
        function=payload.function,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    authorization, asset = _resolve_authorization(
        db,
        authorization_id=payload.authorization_id,
        provider_org_id=payload.provider_org_id,
        energy_domain=payload.energy_domain,
        resource=payload.resource,
        function=payload.function,
        start_date=payload.start_date,
        end_date=payload.end_date,
        region=payload.region,
        user=user,
    )
    payload.authorization_id = authorization.request_id
    payload.provider_org_id = authorization.provider_org_id
    _verify_confirmation_token(payload.confirmation_token, payload, user)
    if payload.provider_org_id and payload.provider_org_id != authorization.provider_org_id:
        raise HTTPException(403, "执行主体与授权主体不一致")
    payload.provider_org_id = authorization.provider_org_id
    request_item = _request_item(
        db,
        authorization=authorization,
        asset=asset,
        payload=payload,
        user=user,
    )
    if request_item.status == "SUCCEEDED" and request_item.result_json:
        replayed_result = request_item.result_json
        return {
            "task_id": replayed_result.get("_hiddenchain_task_id") or replayed_result.get("task_id"),
            "job_id": replayed_result.get("_hiddenchain_job_id"),
            "request_item_id": request_item.request_item_id,
            "authorization_scope": authorization.request_id,
            "generated_at": replayed_result.get("generated_at"),
            "result": replayed_result.get("result"),
            "unit": replayed_result.get("unit"),
            "record_count": replayed_result.get("record_count"),
            "trend": _validated_trend(replayed_result.get("trend")),
            "resource_name": replayed_result.get("resource_name") or "未命名数据资源",
            "function_name": replayed_result.get("function_name") or FUNCTION_LABELS[payload.function],
            "digital_signature": "已验证",
            "audit_recorded": True,
            "raw_records_returned": False,
            "capability": replayed_result.get("capability", "本地受控计算"),
            "idempotent_replay": True,
        }
    metadata = asset.metadata_json or {}
    authorized_domain = str(metadata.get("domain") or "")
    authorized_resource = str(metadata.get("resource_id") or "")
    if authorized_domain and authorized_domain != payload.energy_domain:
        raise HTTPException(403, "计算能源范围超出企业批准的授权")
    if authorized_resource and authorized_resource != payload.resource:
        raise HTTPException(403, "计算数据资源超出企业批准的授权")
    node = subject_node_config(db, authorization.provider_org_id)
    endpoint = node.get("endpoint") if node else None
    expected_public_key = node.get("public_key") if node else None
    if not endpoint:
        request_item.status = "PENDING_RETRY"
        request_item.failure_code = "SUBJECT_NODE_OFFLINE"
        request_item.failure_detail = "主体本地节点未配置或暂不可用，平台未读取中央缓存"
        db.commit()
        raise HTTPException(503, "主体本地节点暂不可用，任务已进入待重试状态")
    task_id = f"TASK-{datetime.now(UTC).strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
    connector_payload = {
        "task_id": task_id,
        "authorization_id": authorization.request_id,
        "request_item_id": request_item.request_item_id,
        "provider_org_id": authorization.provider_org_id,
        "rule_version": request_item.matched_rule_version,
        "resource": payload.resource,
        "function": payload.function,
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "region": payload.region,
        "hour": payload.hour,
        "threshold": payload.threshold,
        "group_by": payload.group_by,
        "decimals": payload.decimals,
    }
    timestamp = str(int(datetime.now(UTC).timestamp()))
    nonce = secrets.token_urlsafe(24)
    signed_request = {"timestamp": timestamp, "nonce": nonce, "payload": connector_payload}
    platform_private_key = _platform_private_key()
    signature = platform_private_key.sign(canonical_json(signed_request).encode())
    try:
        response = httpx.post(
            f"{endpoint.rstrip('/')}/compute",
            json=connector_payload,
            headers={
                "X-Request-Timestamp": timestamp,
                "X-Request-Nonce": nonce,
                "X-Request-Signature": base64.b64encode(signature).decode(),
                "X-Platform-Public-Key": _platform_public_key(platform_private_key),
            },
            timeout=settings.connector_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "企业连接器暂时离线，任务未读取任何缓存数据") from exc
    if response.status_code >= 400:
        status_code, detail = _connector_failure(response)
        raise HTTPException(status_code, detail)
    result = response.json()
    if not isinstance(result, dict):
        raise HTTPException(502, "企业连接器返回格式无效")
    if expected_public_key and result.get("public_key") != expected_public_key:
        raise HTTPException(502, "企业连接器签名公钥与登记信息不一致")
    if not expected_public_key and settings.app_env == "demo":
        expected_public_key = str(result.get("public_key") or "")
    if not expected_public_key:
        raise HTTPException(503, "企业连接器公钥未登记")
    signed_result = {key: value for key, value in result.items() if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}}
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(expected_public_key)).verify(
            base64.b64decode(str(result["signature"])),
            canonical_json(signed_result).encode(),
        )
    except Exception as exc:
        raise HTTPException(502, "企业计算结果数字签名验证失败") from exc
    privacy = result.get("privacy")
    if result.get("raw_records_returned") is True or (
        isinstance(privacy, dict) and privacy.get("raw_records_returned") is True
    ):
        raise HTTPException(502, "企业连接器返回了不允许交付的原始记录")
    trend = _validated_trend(result.get("trend"))
    output_hash = sha256_json(signed_result)
    job_id = new_id()
    job = PrivacyComputeJob(
        job_id=job_id,
        task_id=task_id,
        algorithm_code=payload.function,
        adapter_code=f"LOCAL_SUBJECT_NODE_{authorization.provider_org_id}",
        input_hashes_json=[authorization.decision_hash or authorization.request_fingerprint],
        output_hash=output_hash,
        result_json=result,
        execution_attestation_json={
            "connector_signature_verified": True,
            "signature_algorithm": "Ed25519",
            "raw_records_returned": False,
            "authorization_id": authorization.request_id,
            "applicant_org_id": user.org_id,
            "provider_org_id": authorization.provider_org_id,
            "request_item_id": request_item.request_item_id,
            "node_code": node.get("node_code") if node else None,
        },
        status="SUCCEEDED",
        progress=100,
        privacy_guarantees_json=result.get("privacy", {}),
    )
    db.add(job)
    add_audit_log(
        db,
        action="CONTROLLED_QUERY_COMPLETED",
        target_type="COMPUTE_TASK",
        target_id=task_id,
        result="SUCCESS",
        user=user,
        details={
            "authorization_id": authorization.request_id,
            "energy_domain": payload.energy_domain,
            "function": payload.function,
            "result_hash": output_hash,
            "raw_records_returned": False,
            "signature_verified": True,
            "trust_bootstrap": "DEMO_FIRST_USE" if not expected_public_key else "PRECONFIGURED_PUBLIC_KEY",
        },
    )
    request_item.status = "SUCCEEDED"
    request_item.result_json = {
        **result,
        "_hiddenchain_task_id": task_id,
        "_hiddenchain_job_id": job.job_id,
    }
    request_item.result_hash = output_hash
    request_item.completed_at = utc_now()
    db.add(
        ExecutionReceipt(
            receipt_id=new_id(),
            request_item_id=request_item.request_item_id,
            provider_org_id=authorization.provider_org_id,
            task_id=task_id,
            request_hash=sha256_json(connector_payload),
            result_hash=output_hash,
            node_code=node.get("node_code") if node else "UNKNOWN",
            node_signature=str(result.get("signature") or ""),
            result_summary_json={
                "result": result.get("result"),
                "unit": result.get("unit"),
                "record_count": result.get("record_count"),
                "trend": trend,
                "raw_records_returned": False,
            },
            visible_to_orgs_json=[user.org_id, authorization.provider_org_id],
        )
    )
    db.commit()
    return {
        "task_id": task_id,
        "job_id": job.job_id,
        "request_item_id": request_item.request_item_id,
        "authorization_scope": authorization.request_id,
        "generated_at": result.get("generated_at"),
        "result": result.get("result"),
        "unit": result.get("unit"),
        "record_count": result.get("record_count"),
        "trend": trend,
        "resource_name": result.get("resource_name") or "未命名数据资源",
        "function_name": result.get("function_name") or FUNCTION_LABELS[payload.function],
        "digital_signature": "已验证",
        "audit_recorded": True,
        "raw_records_returned": False,
        "capability": result.get("capability", "本地受控计算"),
        "idempotent_replay": False,
    }


@router.get("/tasks")
def list_query_tasks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if "VIEW_COMPUTE_RESULT" not in set(user.permissions_json or []):
        raise HTTPException(403, "当前账号没有查看计算结果的权限")
    candidate_jobs = db.scalars(
        select(PrivacyComputeJob)
        .where(
            PrivacyComputeJob.adapter_code.like("LOCAL_SUBJECT_NODE_%")
            | PrivacyComputeJob.adapter_code.like("ENTERPRISE_CONNECTOR_%")
        )
        .order_by(PrivacyComputeJob.created_at.desc())
        .limit(200)
    ).all()
    jobs = [
        item
        for item in candidate_jobs
        if (item.execution_attestation_json or {}).get("applicant_org_id") == user.org_id
    ][:50]
    return {
        "items": [
            {
                "task_id": item.task_id,
                "status": "已完成" if item.status == "SUCCEEDED" else "处理中",
                "resource_name": (item.result_json or {}).get("resource_name") or "未命名数据资源",
                "function_name": (item.result_json or {}).get("function_name") or "固定函数",
                "generated_at": (item.result_json or {}).get("generated_at"),
                "signature": "已验证" if (item.execution_attestation_json or {}).get("connector_signature_verified") else "待验证",
            }
            for item in jobs
        ]
    }
