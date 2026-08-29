from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..dependencies import get_current_user
from ..models import (
    AnomalyEvent,
    DataRequestBatch,
    DataRequestItem,
    DataUsageRequest,
    ExecutionReceipt,
    PrivacyComputeJob,
    TrustedQueryTask,
    DidIdentity,
    User,
    new_id,
    utc_now,
)
from ..services.common import add_audit_log
from ..services.llm import DeepSeekUnavailable, translate_trusted_space_query
from ..services.query_translation import redact_query_text
from ..services.privacy_attestation import (
    ConnectorAuditError,
    PrivacyAttestationError,
    canonical_connector_request_payload,
    verify_connector_audit_pointer,
    verify_signed_connector_non_export,
)
from ..services.trusted_query_results import (
    FUNCTION_LABELS,
    TrustedQueryProjectionError,
    build_trusted_query_public_result,
    validated_aggregate_result,
    validated_trend,
)
from ..security import canonical_json, sha256_json
from ..schemas import TrustedSpaceQueryTranslation
from ..services.local_data_boundary import matching_rule, rule_decision, subject_node_config
from ..trust_models import DataAsset, DataAssetVersion


router = APIRouter(prefix="/trust-space/query", tags=["trusted-query"])

QUERY_OPERATION_NAMESPACE = "TRUSTED_QUERY_EXECUTE_V1"
QUERY_TASK_RUNNABLE_STATUSES = frozenset({"QUEUED", "PENDING_RETRY"})
QUERY_TASK_MAX_ATTEMPTS = 3
TRUSTED_QUERY_RECEIPT_SCHEMA = "TRUSTED_QUERY_RECEIPT_V2"


class TrustedQueryExecutionError(RuntimeError):
    def __init__(self, code: str, summary: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.summary = summary
        self.retryable = retryable


class TrustedQueryLeaseLost(RuntimeError):
    pass

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
    # A connector's 401 is a node-to-node protocol failure, not the user's
    # platform session. Keep it away from the frontend authentication path.
    if response.status_code == 401:
        status_code = 502
    elif response.status_code >= 500:
        status_code = 503
    else:
        status_code = response.status_code
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
    try:
        return validated_trend(value)
    except TrustedQueryProjectionError as exc:
        raise HTTPException(502, "企业连接器趋势结果格式无效") from exc


def _validated_aggregate_result(value: Any) -> Any:
    """Accept only compact aggregate values, never row-shaped result arrays."""
    try:
        return validated_aggregate_result(value)
    except TrustedQueryProjectionError as exc:
        raise HTTPException(502, "企业连接器聚合结果格式无效") from exc


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
    execution_key: str,
) -> DataRequestItem:
    """Bind a query to one provider-scoped item and make retries idempotent."""

    batch_key = f"trusted-query:{sha256_json({'scope': execution_key})[:64]}"
    batch = db.scalar(
        select(DataRequestBatch).where(
            DataRequestBatch.applicant_org_id == user.org_id,
            DataRequestBatch.idempotency_key == batch_key,
        )
    )
    if batch is not None:
        if batch.applicant_user_id != user.user_id:
            raise HTTPException(409, "查询幂等范围与当前账号不一致")
        existing = db.scalar(
            select(DataRequestItem).where(
                DataRequestItem.batch_id == batch.batch_id,
                DataRequestItem.provider_org_id == authorization.provider_org_id,
            )
        )
        if existing is None:
            raise HTTPException(409, "查询幂等记录不完整，无法安全重放")
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
        "hour": payload.hour,
        "threshold": payload.threshold,
        "group_by": payload.group_by,
        "decimals": payload.decimals,
        "duration_days": max(1, (payload.end_date - payload.start_date).days + 1),
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
        idempotency_key=batch_key,
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
        idempotency_key=batch_key,
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


def _canonical_execute_payload(payload: ExecuteRequest) -> dict[str, Any]:
    return {
        "authorization_id": payload.authorization_id,
        "provider_org_id": payload.provider_org_id,
        "energy_domain": payload.energy_domain,
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


def _query_task_matches_fingerprint(
    task: TrustedQueryTask,
    request_fingerprint: str,
) -> bool:
    if task.request_fingerprint == request_fingerprint:
        return True
    legacy_payload = dict(task.canonical_payload_json or {})
    if "confirmation_token_hash" not in legacy_payload:
        return False
    legacy_payload.pop("confirmation_token_hash", None)
    return sha256_json(legacy_payload) == request_fingerprint


def _query_task_url(task_id: str) -> str:
    return f"{settings.api_prefix}{router.prefix}/tasks/{task_id}"


def _query_task_status_payload(
    task: TrustedQueryTask,
    *,
    idempotent_replay: bool = False,
) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "status": task.status,
        "status_url": _query_task_url(task.task_id),
        "result_url": (
            f"{_query_task_url(task.task_id)}/result"
            if task.status == "SUCCEEDED"
            else None
        ),
        "attempt": task.attempt,
        "max_attempts": task.max_attempts,
        "failure_code": task.failure_code,
        "failure_summary": task.failure_summary,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "idempotent_replay": idempotent_replay,
    }


def _scoped_query_task(
    db: Session,
    *,
    task_id: str,
    user: User,
) -> TrustedQueryTask:
    if "VIEW_COMPUTE_RESULT" not in set(user.permissions_json or []):
        raise HTTPException(403, "当前账号没有查看计算结果的权限")
    task = db.scalar(
        select(TrustedQueryTask).where(
            TrustedQueryTask.task_id == task_id,
            TrustedQueryTask.applicant_org_id == user.org_id,
            TrustedQueryTask.applicant_user_id == user.user_id,
        )
    )
    if task is None:
        raise HTTPException(404, "未找到可信查询任务")
    return task


def _query_task_is_due(task: TrustedQueryTask, *, now: datetime | None = None) -> bool:
    current = now or utc_now()
    if task.status in QUERY_TASK_RUNNABLE_STATUSES:
        return task.next_attempt_at is None or task.next_attempt_at <= current
    return bool(
        task.status == "RUNNING"
        and task.lease_expires_at is not None
        and task.lease_expires_at <= current
    )


@router.post("/execute", status_code=202)
def execute_query(
    payload: ExecuteRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=160,
    ),
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
    scoped_key = idempotency_key.strip()
    if not scoped_key:
        raise HTTPException(422, "Idempotency-Key 不能为空")
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
    submitted_payload = _canonical_execute_payload(payload)
    request_fingerprint = sha256_json(submitted_payload)
    existing = db.scalar(
        select(TrustedQueryTask).where(
            TrustedQueryTask.applicant_org_id == user.org_id,
            TrustedQueryTask.applicant_user_id == user.user_id,
            TrustedQueryTask.operation_namespace == QUERY_OPERATION_NAMESPACE,
            TrustedQueryTask.idempotency_key == scoped_key,
        )
    )
    if existing is not None:
        if not _query_task_matches_fingerprint(existing, request_fingerprint):
            raise HTTPException(409, "该幂等键已绑定另一组查询条件")
        response = _query_task_status_payload(existing, idempotent_replay=True)
        if _query_task_is_due(existing):
            background_tasks.add_task(run_trusted_query_task, existing.task_id)
        return response
    if authorization.provider_org_id != payload.provider_org_id:
        raise HTTPException(403, "执行主体与授权主体不一致")
    if asset.status != "ACTIVE":
        raise HTTPException(409, "授权对应的数据资源当前不可用")
    version = db.get(DataAssetVersion, authorization.asset_version_id)
    if version is None or version.asset_id != asset.asset_id or version.status != "ACTIVE":
        raise HTTPException(409, "授权对应的数据版本当前不可用")
    if asset.current_version_id != version.version_id:
        raise HTTPException(409, "授权数据版本已变化，请重新确认")

    execution_scope_key = sha256_json(
        {
            "organization_id": user.org_id,
            "user_id": user.user_id,
            "operation": QUERY_OPERATION_NAMESPACE,
            "idempotency_key": scoped_key,
        }
    )
    request_item = _request_item(
        db,
        authorization=authorization,
        asset=asset,
        payload=payload,
        user=user,
        execution_key=execution_scope_key,
    )
    task = TrustedQueryTask(
        task_id=new_id(),
        applicant_user_id=user.user_id,
        applicant_org_id=user.org_id,
        operation_namespace=QUERY_OPERATION_NAMESPACE,
        idempotency_key=scoped_key,
        request_fingerprint=request_fingerprint,
        canonical_payload_json=submitted_payload,
        authorization_id=authorization.request_id,
        provider_org_id=authorization.provider_org_id,
        asset_id=asset.asset_id,
        asset_version_id=version.version_id,
        request_item_id=request_item.request_item_id,
        status="QUEUED",
        attempt=0,
        max_attempts=QUERY_TASK_MAX_ATTEMPTS,
        next_attempt_at=utc_now(),
    )
    db.add(task)
    add_audit_log(
        db,
        action="TRUSTED_QUERY_QUEUED",
        target_type="TRUSTED_QUERY_TASK",
        target_id=task.task_id,
        result="QUEUED",
        user=user,
        details={
            "authorization_id": authorization.request_id,
            "request_item_id": request_item.request_item_id,
            "provider_org_id": authorization.provider_org_id,
            "energy_domain": payload.energy_domain,
            "resource": payload.resource,
            "function": payload.function,
            "request_fingerprint": request_fingerprint,
            "raw_data_accessed": False,
        },
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(TrustedQueryTask).where(
                TrustedQueryTask.applicant_org_id == user.org_id,
                TrustedQueryTask.applicant_user_id == user.user_id,
                TrustedQueryTask.operation_namespace == QUERY_OPERATION_NAMESPACE,
                TrustedQueryTask.idempotency_key == scoped_key,
            )
        )
        if existing is None:
            raise HTTPException(409, "查询任务并发创建冲突，请使用同一幂等键重试")
        if not _query_task_matches_fingerprint(existing, request_fingerprint):
            raise HTTPException(409, "该幂等键已绑定另一组查询条件")
        response = _query_task_status_payload(existing, idempotent_replay=True)
        if _query_task_is_due(existing):
            background_tasks.add_task(run_trusted_query_task, existing.task_id)
        return response

    response = _query_task_status_payload(task)
    background_tasks.add_task(run_trusted_query_task, task.task_id)
    return response


def _claim_query_task(
    db: Session,
    *,
    task_id: str,
    lease_owner: str,
) -> TrustedQueryTask | None:
    now = utc_now()
    due = or_(
        and_(
            TrustedQueryTask.status.in_(tuple(QUERY_TASK_RUNNABLE_STATUSES)),
            or_(
                TrustedQueryTask.next_attempt_at.is_(None),
                TrustedQueryTask.next_attempt_at <= now,
            ),
        ),
        and_(
            TrustedQueryTask.status == "RUNNING",
            TrustedQueryTask.lease_expires_at.is_not(None),
            TrustedQueryTask.lease_expires_at <= now,
        ),
    )
    exhausted = db.scalar(
        select(TrustedQueryTask).where(
            TrustedQueryTask.task_id == task_id,
            due,
            TrustedQueryTask.attempt >= TrustedQueryTask.max_attempts,
        )
    )
    if exhausted is not None:
        _persist_fenced_query_task_failure(
            db,
            task=exhausted,
            expected_status=exhausted.status,
            expected_lease_owner=exhausted.lease_owner,
            error=TrustedQueryExecutionError(
                "RETRY_LIMIT_EXHAUSTED",
                "可信查询重试次数已用尽",
                retryable=False,
            ),
            expired_before=now if exhausted.status == "RUNNING" else None,
        )
        return None
    lease_seconds = max(60.0, float(settings.connector_timeout_seconds) + 30.0)
    claimed = db.execute(
        update(TrustedQueryTask)
        .where(
            TrustedQueryTask.task_id == task_id,
            due,
            TrustedQueryTask.attempt < TrustedQueryTask.max_attempts,
        )
        .values(
            status="RUNNING",
            attempt=TrustedQueryTask.attempt + 1,
            lease_owner=lease_owner,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            heartbeat_at=now,
            next_attempt_at=None,
            started_at=func.coalesce(TrustedQueryTask.started_at, now),
            failure_code=None,
            failure_summary=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if claimed.rowcount != 1:
        return None
    return db.get(TrustedQueryTask, task_id)


def _heartbeat_query_task(
    db: Session,
    *,
    task_id: str,
    lease_owner: str,
) -> TrustedQueryTask:
    now = utc_now()
    lease_seconds = max(60.0, float(settings.connector_timeout_seconds) + 30.0)
    refreshed = db.execute(
        update(TrustedQueryTask)
        .where(
            TrustedQueryTask.task_id == task_id,
            TrustedQueryTask.status == "RUNNING",
            TrustedQueryTask.lease_owner == lease_owner,
        )
        .values(
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if refreshed.rowcount != 1:
        raise TrustedQueryLeaseLost(task_id)
    task = db.get(TrustedQueryTask, task_id)
    if task is None:
        raise TrustedQueryLeaseLost(task_id)
    return task


def _revalidate_query_dispatch(
    db: Session,
    *,
    task: TrustedQueryTask,
) -> tuple[User, DataUsageRequest, DataAsset, DataAssetVersion, DataRequestItem]:
    user = db.get(User, task.applicant_user_id)
    if (
        user is None
        or user.status != "ACTIVE"
        or user.org_id != task.applicant_org_id
        or "CREATE_COMPUTE_TASK" not in set(user.permissions_json or [])
    ):
        raise TrustedQueryExecutionError(
            "USER_ACCESS_REVOKED",
            "发起账号已停用或执行权限已撤销",
            retryable=False,
        )
    authorization = db.get(DataUsageRequest, task.authorization_id)
    if authorization is None:
        raise TrustedQueryExecutionError(
            "AUTHORIZATION_NOT_FOUND",
            "可信查询授权记录不存在",
            retryable=False,
        )
    if (
        authorization.applicant_org_id != task.applicant_org_id
        or authorization.provider_org_id != task.provider_org_id
        or authorization.asset_id != task.asset_id
        or authorization.asset_version_id != task.asset_version_id
    ):
        raise TrustedQueryExecutionError(
            "AUTHORIZATION_SCOPE_CHANGED",
            "可信查询授权范围已变化",
            retryable=False,
        )
    if authorization.status != "APPROVED":
        raise TrustedQueryExecutionError(
            "AUTHORIZATION_REVOKED",
            "可信查询授权已撤销或不再有效",
            retryable=False,
        )
    if authorization.expires_at <= utc_now():
        raise TrustedQueryExecutionError(
            "AUTHORIZATION_EXPIRED",
            "可信查询授权已过期",
            retryable=False,
        )
    asset = db.get(DataAsset, task.asset_id)
    if asset is None or asset.status != "ACTIVE" or asset.owner_org_id != task.provider_org_id:
        raise TrustedQueryExecutionError(
            "DATA_ASSET_UNAVAILABLE",
            "授权数据资源当前不可用",
            retryable=False,
        )
    payload = task.canonical_payload_json or {}
    metadata = asset.metadata_json or {}
    if (
        str(metadata.get("domain") or "") != str(payload.get("energy_domain") or "")
        or str(metadata.get("resource_id") or "") != str(payload.get("resource") or "")
    ):
        raise TrustedQueryExecutionError(
            "DATA_ASSET_SCOPE_CHANGED",
            "授权数据资源范围已变化",
            retryable=False,
        )
    version = db.get(DataAssetVersion, task.asset_version_id)
    if (
        version is None
        or version.asset_id != asset.asset_id
        or version.status != "ACTIVE"
    ):
        raise TrustedQueryExecutionError(
            "DATA_VERSION_CHANGED",
            "任务绑定的数据版本已失效或不再属于授权资源",
            retryable=False,
        )
    now = utc_now()
    if (
        version.effective_from is not None
        and version.effective_from > now
        or version.effective_until is not None
        and version.effective_until <= now
    ):
        raise TrustedQueryExecutionError(
            "DATA_VERSION_UNAVAILABLE",
            "授权数据版本不在有效期内",
            retryable=False,
        )
    request_item = db.get(DataRequestItem, task.request_item_id)
    if (
        request_item is None
        or request_item.authorization_id != authorization.request_id
        or request_item.provider_org_id != authorization.provider_org_id
        or request_item.asset_id != asset.asset_id
    ):
        raise TrustedQueryExecutionError(
            "REQUEST_ITEM_SCOPE_CHANGED",
            "主体请求项范围已变化",
            retryable=False,
        )
    if request_item.status in {"REVOKED", "REJECTED"}:
        raise TrustedQueryExecutionError(
            "REQUEST_ITEM_REVOKED",
            "主体请求项已撤销或拒绝",
            retryable=False,
        )
    requested_scope = {
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "region": payload.get("region"),
        "function": payload.get("function"),
        "hour": payload.get("hour"),
        "threshold": payload.get("threshold"),
        "group_by": payload.get("group_by"),
        "decimals": payload.get("decimals"),
        "duration_days": max(
            1,
            (
                date.fromisoformat(str(payload["end_date"]))
                - date.fromisoformat(str(payload["start_date"]))
            ).days
            + 1,
        ),
        "output_mode": "AGGREGATE_ONLY",
        "raw_data_export": False,
    }
    current_rule = matching_rule(
        db,
        owner_org_id=authorization.provider_org_id,
        resource_id=str(payload.get("resource") or ""),
        function_code=str(payload.get("function") or ""),
        requested_scope=requested_scope,
    )
    if request_item.matched_rule_id is not None:
        if (
            current_rule is None
            or current_rule.rule_id != request_item.matched_rule_id
            or f"v{current_rule.version_no}" != request_item.matched_rule_version
        ):
            raise TrustedQueryExecutionError(
                "ACCESS_RULE_CHANGED",
                "主体访问规则已变化",
                retryable=False,
            )
    if rule_decision(current_rule) == "FORBIDDEN":
        raise TrustedQueryExecutionError(
            "ACCESS_RULE_REVOKED",
            "主体访问规则不再允许该查询",
            retryable=False,
        )
    if (
        (authorization.terms_json or {}).get("authorization_source")
        == "SUBJECT_APPROVED_RULE"
        and rule_decision(current_rule) != "AUTO_CALL"
    ):
        raise TrustedQueryExecutionError(
            "ACCESS_RULE_CHANGED",
            "主体自动调用规则已变化",
            retryable=False,
        )
    return user, authorization, asset, version, request_item


def _connector_query_payload(
    task: TrustedQueryTask,
    authorization: DataUsageRequest,
    version: DataAssetVersion,
    request_item: DataRequestItem,
) -> dict[str, Any]:
    data_ref = str(version.data_ref or "")
    data_hash = str(version.data_hash or "")
    if (
        isinstance(version.version_no, bool)
        or not isinstance(version.version_no, int)
        or version.version_no < 1
        or not data_ref.startswith("connector://")
        or len(data_hash) != 64
        or any(character not in "0123456789abcdef" for character in data_hash)
    ):
        raise TrustedQueryExecutionError(
            "DATA_VERSION_BINDING_INVALID",
            "中央授权数据版本缺少可验证的连接器绑定",
            retryable=False,
        )
    payload = task.canonical_payload_json or {}
    return canonical_connector_request_payload(
        {
            "task_id": task.task_id,
            "authorization_id": authorization.request_id,
            "request_item_id": request_item.request_item_id,
            "provider_org_id": authorization.provider_org_id,
            "rule_version": request_item.matched_rule_version,
            "dataset_version": version.version_no,
            "dataset_local_ref": data_ref,
            "dataset_content_hash": data_hash,
            "resource": payload.get("resource"),
            "function": payload.get("function"),
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "region": payload.get("region"),
            "hour": payload.get("hour"),
            "threshold": payload.get("threshold"),
            "group_by": payload.get("group_by"),
            "decimals": payload.get("decimals"),
        }
    )


def _discover_connector_public_key(
    *,
    endpoint: str,
    node: dict[str, Any],
    provider_org_id: str,
    energy_domain: str,
) -> str:
    if settings.app_env not in {"demo", "development", "test"}:
        raise TrustedQueryExecutionError(
            "CONNECTOR_KEY_NOT_REGISTERED",
            "企业连接器公钥未登记",
            retryable=False,
        )
    parsed = urlparse(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise TrustedQueryExecutionError(
            "CONNECTOR_DISCOVERY_ENDPOINT_INVALID",
            "企业连接器公钥发现端点无效",
            retryable=False,
        )

    def load_json(path: str) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{endpoint.rstrip('/')}{path}",
                timeout=settings.connector_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise TrustedQueryExecutionError(
                "CONNECTOR_DISCOVERY_UNAVAILABLE",
                "企业连接器身份发现暂不可用，任务将在稍后重试",
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            retryable = response.status_code in {408, 425, 429} or response.status_code >= 500
            raise TrustedQueryExecutionError(
                "CONNECTOR_DISCOVERY_UNAVAILABLE"
                if retryable
                else "CONNECTOR_DISCOVERY_REJECTED",
                (
                    "企业连接器身份发现暂不可用，任务将在稍后重试"
                    if retryable
                    else "企业连接器拒绝了身份发现请求"
                ),
                retryable=retryable,
            )
        try:
            value = response.json()
        except ValueError as exc:
            raise TrustedQueryExecutionError(
                "CONNECTOR_IDENTITY_INVALID",
                "企业连接器身份信息无效",
                retryable=False,
            ) from exc
        if not isinstance(value, dict):
            raise TrustedQueryExecutionError(
                "CONNECTOR_IDENTITY_INVALID",
                "企业连接器身份信息无效",
                retryable=False,
            )
        return value

    health = load_json("/health")
    if (
        health.get("organization_id") != provider_org_id
        or health.get("energy_domain") != energy_domain
    ):
        raise TrustedQueryExecutionError(
            "CONNECTOR_IDENTITY_MISMATCH",
            "企业连接器身份与授权主体不一致",
            retryable=False,
        )
    connector_id = str(health.get("connector_id") or "")
    if not connector_id:
        catalog = load_json("/catalog")
        if (
            catalog.get("organization_id") != provider_org_id
            or catalog.get("energy_domain") != energy_domain
        ):
            raise TrustedQueryExecutionError(
                "CONNECTOR_IDENTITY_MISMATCH",
                "企业连接器目录身份与授权主体不一致",
                retryable=False,
            )
        connector_id = str(catalog.get("connector_id") or "")
    if not connector_id or connector_id != str(node.get("node_code") or ""):
        raise TrustedQueryExecutionError(
            "CONNECTOR_IDENTITY_MISMATCH",
            "企业连接器标识与登记节点不一致",
            retryable=False,
        )
    public_key = str(health.get("public_key") or "")
    try:
        key_bytes = base64.b64decode(public_key, validate=True)
        Ed25519PublicKey.from_public_bytes(key_bytes)
    except Exception as exc:
        raise TrustedQueryExecutionError(
            "CONNECTOR_IDENTITY_INVALID",
            "企业连接器身份公钥无效",
            retryable=False,
        ) from exc
    return public_key


def _execute_claimed_query_task(
    db: Session,
    *,
    task_id: str,
    lease_owner: str,
) -> None:
    task = db.get(TrustedQueryTask, task_id)
    if task is None or task.status != "RUNNING" or task.lease_owner != lease_owner:
        raise TrustedQueryLeaseLost(task_id)
    user, authorization, asset, version, request_item = _revalidate_query_dispatch(
        db,
        task=task,
    )
    node = subject_node_config(db, authorization.provider_org_id)
    endpoint = node.get("endpoint") if node else None
    expected_public_key = node.get("public_key") if node else None
    if not endpoint:
        raise TrustedQueryExecutionError(
            "SUBJECT_NODE_OFFLINE",
            "主体本地节点暂不可用，任务将在稍后重试",
            retryable=True,
        )
    trust_bootstrap = "PRECONFIGURED_PUBLIC_KEY"
    if not expected_public_key:
        expected_public_key = _discover_connector_public_key(
            endpoint=str(endpoint),
            node=node or {},
            provider_org_id=authorization.provider_org_id,
            energy_domain=str((task.canonical_payload_json or {}).get("energy_domain") or ""),
        )
        trust_bootstrap = "VERIFIED_HEALTH_DISCOVERY"
    task = _heartbeat_query_task(db, task_id=task_id, lease_owner=lease_owner)
    connector_payload = _connector_query_payload(task, authorization, version, request_item)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    nonce = secrets.token_urlsafe(24)
    signed_request = {"timestamp": timestamp, "nonce": nonce, "payload": connector_payload}
    try:
        platform_private_key = _platform_private_key()
    except HTTPException as exc:
        raise TrustedQueryExecutionError(
            "PLATFORM_SIGNING_UNAVAILABLE",
            "平台请求签名能力暂不可用",
            retryable=True,
        ) from exc
    signature = platform_private_key.sign(canonical_json(signed_request).encode())
    try:
        response = httpx.post(
            f"{str(endpoint).rstrip('/')}/compute",
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
        raise TrustedQueryExecutionError(
            "CONNECTOR_TEMPORARILY_UNAVAILABLE",
            "企业连接器暂时不可用，任务将在稍后重试",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        retryable = response.status_code in {408, 425, 429} or response.status_code >= 500
        raise TrustedQueryExecutionError(
            "CONNECTOR_TEMPORARY_FAILURE" if retryable else "CONNECTOR_REQUEST_REJECTED",
            (
                "企业连接器暂时不可用，任务将在稍后重试"
                if retryable
                else "企业连接器拒绝了受控计算请求"
            ),
            retryable=retryable,
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise TrustedQueryExecutionError(
            "CONNECTOR_RESPONSE_INVALID",
            "企业连接器返回格式无效",
            retryable=False,
        ) from exc
    if not isinstance(result, dict):
        raise TrustedQueryExecutionError(
            "CONNECTOR_RESPONSE_INVALID",
            "企业连接器返回格式无效",
            retryable=False,
        )
    if expected_public_key and result.get("public_key") != expected_public_key:
        raise TrustedQueryExecutionError(
            "CONNECTOR_IDENTITY_MISMATCH",
            "企业连接器身份校验失败",
            retryable=False,
        )
    if not expected_public_key:
        raise TrustedQueryExecutionError(
            "CONNECTOR_KEY_NOT_REGISTERED",
            "企业连接器公钥未登记",
            retryable=False,
        )
    signed_result = {
        key: value
        for key, value in result.items()
        if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}
    }
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(expected_public_key)).verify(
            base64.b64decode(str(result["signature"])),
            canonical_json(signed_result).encode(),
        )
    except Exception as exc:
        raise TrustedQueryExecutionError(
            "CONNECTOR_SIGNATURE_INVALID",
            "企业计算结果数字签名验证失败",
            retryable=False,
        ) from exc
    returned_version = result.get("dataset_version")
    if (
        isinstance(returned_version, bool)
        or not isinstance(returned_version, int)
        or returned_version != version.version_no
        or result.get("dataset_local_ref") != version.data_ref
        or result.get("dataset_content_hash") != version.data_hash
    ):
        raise TrustedQueryExecutionError(
            "DATA_VERSION_BINDING_MISMATCH",
            "企业连接器返回的数据版本与中央授权不一致",
            retryable=False,
        )
    privacy = result.get("privacy")
    if result.get("raw_records_returned") is True or (
        isinstance(privacy, dict) and privacy.get("raw_records_returned") is True
    ):
        raise TrustedQueryExecutionError(
            "RAW_DATA_EXPORT_REJECTED",
            "企业连接器返回了不允许交付的原始记录",
            retryable=False,
        )
    try:
        privacy_verification = verify_signed_connector_non_export(
            signed_result,
            connector_payload,
        )
    except PrivacyAttestationError as exc:
        raise TrustedQueryExecutionError(
            "CONNECTOR_ATTESTATION_INVALID",
            "企业连接器不出域证明校验失败",
            retryable=False,
        ) from exc
    try:
        connector_audit = {
            **verify_connector_audit_pointer(
                signed_result,
                connector_payload,
                expected_connector_id=str(node.get("node_code") or ""),
                expected_provider_org_id=authorization.provider_org_id,
                expected_energy_domain=str(
                    (task.canonical_payload_json or {}).get("energy_domain") or ""
                ),
                expected_task_id=task.task_id,
                expected_request_item_id=request_item.request_item_id,
            ),
            "pointer_verified": True,
            "event_hash_verified": True,
            "verification_scope": "SINGLE_SIGNED_EVENT_POINTER",
        }
    except ConnectorAuditError as exc:
        raise TrustedQueryExecutionError(
            "CONNECTOR_AUDIT_INVALID",
            "企业连接器审计事件指针校验失败",
            retryable=False,
        ) from exc
    try:
        trend = _validated_trend(result.get("trend"))
        result_value = _validated_aggregate_result(result.get("result"))
    except HTTPException as exc:
        raise TrustedQueryExecutionError(
            "CONNECTOR_RESPONSE_INVALID",
            "企业连接器返回格式无效",
            retryable=False,
        ) from exc
    capability = result.get("capability", "本地受控计算")
    if capability not in {"本地受控计算", "本地计算份额"}:
        raise TrustedQueryExecutionError(
            "CONNECTOR_CAPABILITY_INVALID",
            "企业连接器返回的能力标签不在受控计算允许范围内",
            retryable=False,
        )
    record_count = result.get("record_count")
    if (
        record_count is not None
        and (
            isinstance(record_count, bool)
            or not isinstance(record_count, int)
            or record_count < 0
        )
    ):
        raise TrustedQueryExecutionError(
            "CONNECTOR_RESPONSE_INVALID",
            "企业连接器返回格式无效",
            retryable=False,
        )
    task = _heartbeat_query_task(db, task_id=task_id, lease_owner=lease_owner)
    output_hash = sha256_json(signed_result)
    signing_key_fingerprint = hashlib.sha256(
        base64.b64decode(expected_public_key, validate=True)
    ).hexdigest()
    privacy_verification = {
        **privacy_verification,
        "result_hash": output_hash,
        "connector_audit": connector_audit,
    }
    job = db.scalar(
        select(PrivacyComputeJob).where(
            PrivacyComputeJob.task_id == task.task_id,
            PrivacyComputeJob.adapter_code
            == f"LOCAL_SUBJECT_NODE_{authorization.provider_org_id}",
        )
    )
    if job is None:
        job = PrivacyComputeJob(
            job_id=new_id(),
            task_id=task.task_id,
            algorithm_code=str((task.canonical_payload_json or {}).get("function") or ""),
            adapter_code=f"LOCAL_SUBJECT_NODE_{authorization.provider_org_id}",
            input_hashes_json=[
                authorization.decision_hash or authorization.request_fingerprint
            ],
            output_hash=output_hash,
            result_json={},
            execution_attestation_json={
                "connector_signature_verified": True,
                "signature_algorithm": "Ed25519",
                "raw_records_returned": False,
                "raw_data_exported": False,
                "execution_environment": "SUBJECT_CONNECTOR",
                "attestation_status": "CONNECTOR_SIGNED",
                "cross_domain_non_export_verified": True,
                "connector_audit_event_verified": True,
                "receipt_verification_schema": TRUSTED_QUERY_RECEIPT_SCHEMA,
                "signing_key_fingerprint": signing_key_fingerprint,
                "connector_audit": connector_audit,
                "privacy_verification": privacy_verification,
                "authorization_id": authorization.request_id,
                "applicant_org_id": user.org_id,
                "applicant_user_id": user.user_id,
                "provider_org_id": authorization.provider_org_id,
                "request_item_id": request_item.request_item_id,
                "node_code": node.get("node_code") if node else None,
            },
            status="SUCCEEDED",
            progress=100,
            privacy_guarantees_json={
                "execution_environment": "SUBJECT_CONNECTOR",
                "attestation_status": "CONNECTOR_SIGNED",
                "connector_signature_verified": True,
                "cross_domain_non_export_verified": True,
                "connector_audit_event_verified": True,
                "receipt_verification_schema": TRUSTED_QUERY_RECEIPT_SCHEMA,
                "signing_key_fingerprint": signing_key_fingerprint,
                "connector_audit": connector_audit,
                "raw_records_returned": False,
                "raw_data_exported": False,
                "privacy_verification": privacy_verification,
            },
        )
        db.add(job)
    try:
        public_result = build_trusted_query_public_result(
            task_id=task.task_id,
            job_id=job.job_id,
            request_item_id=request_item.request_item_id,
            authorization_id=authorization.request_id,
            canonical_payload=task.canonical_payload_json or {},
            attempt=task.attempt,
            asset_version_id=task.asset_version_id,
            signed_result=signed_result,
            connector_audit=connector_audit,
            privacy_verification=privacy_verification,
            receipt_schema=TRUSTED_QUERY_RECEIPT_SCHEMA,
        )
    except TrustedQueryProjectionError as exc:
        raise TrustedQueryExecutionError(
            "CONNECTOR_RESPONSE_INVALID",
            "企业连接器返回格式无效",
            retryable=False,
        ) from exc
    job.result_json = public_result
    request_item.status = "SUCCEEDED"
    request_item.result_json = public_result
    request_item.result_hash = output_hash
    request_item.failure_code = None
    request_item.failure_detail = None
    request_item.completed_at = utc_now()
    request_hash = sha256_json(connector_payload)
    receipt = db.scalar(
        select(ExecutionReceipt).where(
            ExecutionReceipt.request_item_id == request_item.request_item_id,
            ExecutionReceipt.request_hash == request_hash,
        )
    )
    if receipt is None:
        db.add(
            ExecutionReceipt(
                receipt_id=new_id(),
                request_item_id=request_item.request_item_id,
                provider_org_id=authorization.provider_org_id,
                task_id=task.task_id,
                request_hash=request_hash,
                result_hash=output_hash,
                node_code=node.get("node_code") if node else "UNKNOWN",
                node_signature=str(result.get("signature") or ""),
                result_summary_json={
                    "result": result_value,
                    "unit": result.get("unit"),
                    "record_count": record_count,
                    "trend": trend,
                    "raw_records_returned": False,
                    "raw_data_exported": False,
                    "connector_audit": connector_audit,
                    "privacy_verification": privacy_verification,
                    "verification_envelope": {
                        "schema": TRUSTED_QUERY_RECEIPT_SCHEMA,
                        "signed_result": signed_result,
                        "signing_key_fingerprint": signing_key_fingerprint,
                        "verifier": "ED25519_CANONICAL_JSON_V1",
                    },
                },
                visible_to_orgs_json=[user.org_id, authorization.provider_org_id],
                audit_sequence=int(connector_audit["sequence"]),
                previous_audit_hash=str(connector_audit["previous_hash"]),
                connector_audit_hash=str(connector_audit["audit_hash"]),
                audit_event_verified=True,
            )
        )
    elif receipt.result_hash != output_hash or any(
        (
            receipt.audit_sequence != connector_audit["sequence"],
            receipt.previous_audit_hash != connector_audit["previous_hash"],
            receipt.connector_audit_hash != connector_audit["audit_hash"],
            receipt.audit_event_verified is not True,
        )
    ):
        raise TrustedQueryExecutionError(
            "CONNECTOR_REPLAY_MISMATCH",
            "企业连接器重放回执与既有结果不一致",
            retryable=False,
        )
    add_audit_log(
        db,
        action="CONTROLLED_QUERY_COMPLETED",
        target_type="TRUSTED_QUERY_TASK",
        target_id=task.task_id,
        result="SUCCESS",
        user=user,
        details={
            "authorization_id": authorization.request_id,
            "request_item_id": request_item.request_item_id,
            "energy_domain": (task.canonical_payload_json or {}).get("energy_domain"),
            "function": (task.canonical_payload_json or {}).get("function"),
            "result_hash": output_hash,
            "raw_records_returned": False,
            "raw_data_exported": False,
            "signature_verified": True,
            "cross_domain_non_export_verified": True,
            "connector_audit_event_verified": True,
            "connector_audit": connector_audit,
            "privacy_verification": privacy_verification,
            "trust_bootstrap": trust_bootstrap,
        },
    )
    now = utc_now()
    completed = db.execute(
        update(TrustedQueryTask)
        .where(
            TrustedQueryTask.task_id == task.task_id,
            TrustedQueryTask.status == "RUNNING",
            TrustedQueryTask.lease_owner == lease_owner,
        )
        .values(
            status="SUCCEEDED",
            result_json=public_result,
            result_hash=output_hash,
            failure_code=None,
            failure_summary=None,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=now,
            next_attempt_at=None,
            completed_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if completed.rowcount != 1:
        db.rollback()
        raise TrustedQueryLeaseLost(task_id)
    db.commit()


def _persist_fenced_query_task_failure(
    db: Session,
    *,
    task: TrustedQueryTask,
    expected_status: str,
    expected_lease_owner: str | None,
    error: TrustedQueryExecutionError,
    expired_before: datetime | None = None,
) -> bool:
    now = utc_now()
    terminal = not error.retryable or task.attempt >= task.max_attempts
    next_attempt_at = (
        None if terminal else now + timedelta(seconds=min(30, 2 ** task.attempt))
    )
    fence_conditions = [
        TrustedQueryTask.task_id == task.task_id,
        TrustedQueryTask.status == expected_status,
        TrustedQueryTask.lease_owner == expected_lease_owner,
    ]
    if expired_before is not None:
        fence_conditions.extend(
            [
                TrustedQueryTask.lease_expires_at.is_not(None),
                TrustedQueryTask.lease_expires_at <= expired_before,
            ]
        )
    fenced = db.execute(
        update(TrustedQueryTask)
        .where(*fence_conditions)
        .values(
            status="FAILED" if terminal else "PENDING_RETRY",
            failure_code=error.code,
            failure_summary=error.summary,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=now,
            next_attempt_at=next_attempt_at,
            completed_at=now if terminal else None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if fenced.rowcount != 1:
        db.rollback()
        return False
    request_item = db.get(DataRequestItem, task.request_item_id)
    if request_item is not None:
        request_item.status = "FAILED" if terminal else "PENDING_RETRY"
        request_item.failure_code = error.code
        request_item.failure_detail = error.summary
        request_item.completed_at = now if terminal else None
    user = db.get(User, task.applicant_user_id)
    add_audit_log(
        db,
        action="TRUSTED_QUERY_FAILED" if terminal else "TRUSTED_QUERY_RETRY_SCHEDULED",
        target_type="TRUSTED_QUERY_TASK",
        target_id=task.task_id,
        result="FAILED" if terminal else "PENDING_RETRY",
        user=user,
        actor_name=None if user else "TRUSTED_QUERY_WORKER",
        actor_org_id=task.applicant_org_id,
        details={
            "failure_code": error.code,
            "retryable": error.retryable and not terminal,
            "attempt": task.attempt,
            "max_attempts": task.max_attempts,
            "raw_data_accessed": False,
        },
    )
    if terminal:
        anomaly_dedupe = f"trusted-query-terminal-failure:{task.task_id}"
        if not db.scalar(select(AnomalyEvent.event_id).where(AnomalyEvent.dedupe_key == anomaly_dedupe)):
            db.add(AnomalyEvent(
                task_id=task.task_id,
                event_type="TRUSTED_QUERY_TERMINAL_FAILURE",
                risk_level="HIGH",
                title="受控查询终态失败",
                description=error.summary,
                evidence_json={
                    "failure_code": error.code,
                    "attempt": task.attempt,
                    "max_attempts": task.max_attempts,
                },
                dedupe_key=anomaly_dedupe,
            ))
    db.commit()
    return True


def _record_query_task_failure(
    db: Session,
    *,
    task_id: str,
    lease_owner: str,
    error: TrustedQueryExecutionError,
) -> None:
    db.rollback()
    task = db.get(TrustedQueryTask, task_id)
    if task is None or task.status != "RUNNING" or task.lease_owner != lease_owner:
        return
    _persist_fenced_query_task_failure(
        db,
        task=task,
        expected_status="RUNNING",
        expected_lease_owner=lease_owner,
        error=error,
    )


def run_trusted_query_task(task_id: str) -> None:
    lease_owner = f"trusted-query-worker-{secrets.token_hex(8)}"
    with SessionLocal() as db:
        task = _claim_query_task(db, task_id=task_id, lease_owner=lease_owner)
        if task is None:
            return
        try:
            _execute_claimed_query_task(
                db,
                task_id=task_id,
                lease_owner=lease_owner,
            )
        except TrustedQueryLeaseLost:
            db.rollback()
        except TrustedQueryExecutionError as exc:
            try:
                _record_query_task_failure(
                    db,
                    task_id=task_id,
                    lease_owner=lease_owner,
                    error=exc,
                )
            except Exception:
                db.rollback()
        except Exception:
            try:
                _record_query_task_failure(
                    db,
                    task_id=task_id,
                    lease_owner=lease_owner,
                    error=TrustedQueryExecutionError(
                        "INTERNAL_EXECUTION_ERROR",
                        "可信查询执行暂时失败，任务将在稍后重试",
                        retryable=True,
                    ),
                )
            except Exception:
                db.rollback()


@router.get("/tasks/{task_id}")
def get_query_task_status(
    task_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _scoped_query_task(db, task_id=task_id, user=user)
    response = _query_task_status_payload(task)
    if _query_task_is_due(task):
        background_tasks.add_task(run_trusted_query_task, task.task_id)
    return response


@router.get("/tasks/{task_id}/result")
def get_query_task_result(
    task_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _scoped_query_task(db, task_id=task_id, user=user)
    if task.status != "SUCCEEDED":
        if _query_task_is_due(task):
            background_tasks.add_task(run_trusted_query_task, task.task_id)
        raise HTTPException(
            409,
            {
                "code": "TRUSTED_QUERY_NOT_SUCCEEDED",
                "message": "可信查询任务尚未成功完成",
                "status": task.status,
            },
        )
    return dict(task.result_json or {})


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
    current_task_ids = set(
        db.scalars(
            select(TrustedQueryTask.task_id).where(
                TrustedQueryTask.task_id.in_([item.task_id for item in jobs])
            )
        ).all()
    ) if jobs else set()
    return {
        "items": [
            {
                "task_id": item.task_id,
                "status": (
                    "历史隔离（未按当前协议复验）"
                    if item.adapter_code.startswith("ENTERPRISE_CONNECTOR_")
                    else "历史只读"
                    if item.task_id not in current_task_ids
                    else "已完成" if item.status == "SUCCEEDED" else "处理中"
                ),
                "resource_name": (
                    "升级前历史记录"
                    if item.adapter_code.startswith("ENTERPRISE_CONNECTOR_")
                    else (item.result_json or {}).get("resource_name") or "未命名数据资源"
                ),
                "function_name": (
                    "已隔离"
                    if item.adapter_code.startswith("ENTERPRISE_CONNECTOR_")
                    else (item.result_json or {}).get("function_name") or "固定函数"
                ),
                "generated_at": (item.result_json or {}).get("generated_at"),
                "signature": (
                    "未复验"
                    if item.adapter_code.startswith("ENTERPRISE_CONNECTOR_")
                    else "已验证"
                    if (
                        item.task_id in current_task_ids
                        and (item.execution_attestation_json or {}).get(
                            "receipt_verification_schema"
                        ) == TRUSTED_QUERY_RECEIPT_SCHEMA
                    )
                    else "已验证（升级前协议，只读）"
                    if (item.execution_attestation_json or {}).get(
                        "connector_signature_verified"
                    )
                    else "待验证"
                ),
            }
            for item in jobs
        ]
    }
