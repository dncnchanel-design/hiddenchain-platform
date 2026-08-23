from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, date, datetime
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
from ..models import DataUsageRequest, PrivacyComputeJob, User, new_id, utc_now
from ..services.common import add_audit_log
from ..security import canonical_json, sha256_json
from ..trust_models import DataAsset


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


class ParseRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)


class ExecuteRequest(BaseModel):
    authorization_id: str
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


def _match(text: str, vocabulary: dict[str, tuple[str, ...]]) -> str | None:
    for code, terms in vocabulary.items():
        if any(term in text for term in terms):
            return code
    return None


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


@router.post("/parse")
def parse_question(payload: ParseRequest, user: User = Depends(get_current_user)) -> dict[str, Any]:
    if user.role_code == "ADMIN":
        raise HTTPException(403, "平台运维账号不能发起业务查询")
    domain = _match(payload.question, DOMAIN_TERMS)
    resource = _match(payload.question, RESOURCE_TERMS)
    function = _match(payload.question, FUNCTION_TERMS) or "sum"
    return {
        "question": payload.question,
        "energy_domain": domain,
        "resource": resource,
        "function": function,
        "function_name": FUNCTION_LABELS[function],
        "requires_authorization": True,
        "ready": bool(domain and resource),
        "notice": "系统只解析查询意图，正式计算仍由固定函数和企业授权决定。",
    }


@router.post("/execute")
def execute_query(
    payload: ExecuteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if "CREATE_COMPUTE_TASK" not in set(user.permissions_json or []):
        raise HTTPException(403, "当前账号没有创建计算任务的权限")
    if payload.function not in FUNCTION_LABELS:
        raise HTTPException(422, "仅允许使用页面列出的固定函数")
    authorization, asset = _authorization(db, payload.authorization_id, user)
    metadata = asset.metadata_json or {}
    authorized_domain = str(metadata.get("domain") or "")
    authorized_resource = str(metadata.get("resource_id") or "")
    if authorized_domain and authorized_domain != payload.energy_domain:
        raise HTTPException(403, "计算能源范围超出企业批准的授权")
    if authorized_resource and authorized_resource != payload.resource:
        raise HTTPException(403, "计算数据资源超出企业批准的授权")
    endpoints = _configured_map(settings.connector_endpoints_json, "企业连接器地址")
    public_keys = _configured_map(settings.connector_public_keys_json, "企业连接器公钥")
    endpoint = endpoints.get(payload.energy_domain)
    expected_public_key = public_keys.get(payload.energy_domain)
    if not endpoint:
        raise HTTPException(503, "对应能源连接器暂不可用")
    task_id = f"TASK-{datetime.now(UTC).strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
    connector_payload = {
        "task_id": task_id,
        "authorization_id": authorization.request_id,
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
        detail = response.json().get("detail", "企业连接器拒绝了计算任务")
        raise HTTPException(response.status_code, detail)
    result = response.json()
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
    output_hash = sha256_json(signed_result)
    job = PrivacyComputeJob(
        job_id=new_id(),
        task_id=task_id,
        algorithm_code=payload.function,
        adapter_code=f"ENTERPRISE_CONNECTOR_{payload.energy_domain.upper()}",
        input_hashes_json=[authorization.decision_hash or authorization.request_fingerprint],
        output_hash=output_hash,
        result_json=result,
        execution_attestation_json={
            "connector_signature_verified": True,
            "signature_algorithm": "Ed25519",
            "raw_records_returned": False,
            "authorization_id": authorization.request_id,
            "applicant_org_id": user.org_id,
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
            "trust_bootstrap": "DEMO_FIRST_USE" if payload.energy_domain not in public_keys else "PRECONFIGURED_PUBLIC_KEY",
        },
    )
    db.commit()
    return {
        "task_id": task_id,
        "authorization_scope": authorization.request_id,
        "generated_at": result.get("generated_at"),
        "result": result.get("result"),
        "unit": result.get("unit"),
        "resource_name": result.get("resource_name") or "未命名数据资源",
        "function_name": result.get("function_name") or FUNCTION_LABELS[payload.function],
        "digital_signature": "已验证",
        "audit_recorded": True,
        "raw_records_returned": False,
        "capability": result.get("capability", "本地受控计算"),
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
        .where(PrivacyComputeJob.adapter_code.like("ENTERPRISE_CONNECTOR_%"))
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
