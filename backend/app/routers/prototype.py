from __future__ import annotations

import csv
import hashlib
import io
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..models import AccessRule, AuditLog, BlockchainEvidence, DataUsageRequest, DidIdentity, Organization, PrivacyAnalysisJob, SettlementTask, User, new_id, utc_now
from ..security import sha256_json
from ..services.adapters import LocalEvidenceLedgerAdapter
from ..services.common import add_audit_log
from ..trust_models import DataAsset, DataAssetPassport, DataAssetVersion, DataSource
from .trusted_query import DOMAIN_LABELS, FUNCTION_LABELS, _manual_parse


router = APIRouter(prefix="/prototype", tags=["target-prototype"])

ROLE_LABELS = {
    "GENERATOR": "电力企业",
    "RETAILER": "电力企业",
    "COAL_ENTERPRISE": "煤炭企业",
    "HEAT_ENTERPRISE": "热力企业",
    "GAS_ENTERPRISE": "燃气企业",
    "OIL_ENTERPRISE": "石油企业",
    "EXCHANGE": "交易中心",
    "REGULATOR": "能源局-监管",
}

ACTION_LABELS = {
    "allow": "直接提供",
    "deny": "禁止提供",
    "aggregate": "汇总提供",
    "delay": "延迟提供",
    "compute_only": "仅计算不出域",
}

ACTION_TO_MODE = {
    "allow": "AUTO_CALL",
    "deny": "FORBIDDEN",
    "aggregate": "ENTERPRISE_APPROVAL",
    "delay": "ENTERPRISE_APPROVAL",
    "compute_only": "ENTERPRISE_APPROVAL",
}

STATIC_POLICY_MATRIX: list[dict[str, Any]] = [
    {
        "id": "load_curve",
        "name": "电网负荷曲线",
        "level": "L2-内部",
        "connector": "power",
        "default_action": "deny",
        "rules": [
            {"role": "电力企业", "purposes": [], "action": "allow", "fields": ["ts", "region", "load_mw"], "min_granularity": None, "delay_hours": None},
            {"role": "能源局-监管", "purposes": ["运行监测", "日报编制", "趋势分析", "保供监测"], "action": "allow", "fields": ["ts", "region", "load_mw"], "min_granularity": None, "delay_hours": None},
            {"role": "研究机构", "purposes": ["趋势分析", "规划研究"], "action": "aggregate", "fields": ["ts", "region", "load_mw"], "min_granularity": "day", "delay_hours": None},
            {"role": "公众", "purposes": [], "action": "aggregate", "fields": ["ts", "load_mw"], "min_granularity": "month", "delay_hours": None},
        ],
    },
    {
        "id": "generation",
        "name": "发电出力数据",
        "level": "L2-内部",
        "connector": "power",
        "default_action": "deny",
        "rules": [
            {"role": "电力企业", "purposes": [], "action": "allow", "fields": ["ts", "source", "output_mw"], "min_granularity": None, "delay_hours": None},
            {"role": "能源局-监管", "purposes": [], "action": "allow", "fields": ["ts", "source", "output_mw"], "min_granularity": None, "delay_hours": None},
            {"role": "电网调度", "purposes": [], "action": "allow", "fields": ["ts", "source", "output_mw"], "min_granularity": None, "delay_hours": None},
            {"role": "研究机构", "purposes": [], "action": "aggregate", "fields": ["ts", "source", "output_mw"], "min_granularity": "day", "delay_hours": None},
        ],
    },
    {
        "id": "trading",
        "name": "电力交易成交明细",
        "level": "L3-敏感",
        "connector": "power",
        "default_action": "deny",
        "rules": [
            {"role": "电力企业", "purposes": [], "action": "allow", "fields": ["trade_id", "ts", "seller", "buyer", "volume_mwh", "price_yuan"], "min_granularity": None, "delay_hours": None},
            {"role": "能源局-监管", "purposes": ["市场监测"], "action": "delay", "fields": ["ts", "volume_mwh", "price_yuan"], "min_granularity": "hour", "delay_hours": 24},
            {"role": "交易中心", "purposes": [], "action": "allow", "fields": ["trade_id", "ts", "seller", "buyer", "volume_mwh", "price_yuan"], "min_granularity": None, "delay_hours": None},
            {"role": "研究机构", "purposes": [], "action": "aggregate", "fields": ["ts", "volume_mwh", "price_yuan"], "min_granularity": "day", "delay_hours": None},
        ],
    },
    {
        "id": "marketing",
        "name": "营销用户用电数据",
        "level": "L3-敏感",
        "connector": "power",
        "default_action": "deny",
        "rules": [
            {"role": "电力企业", "purposes": [], "action": "allow", "fields": ["user_id", "industry", "region", "day", "kwh"], "min_granularity": None, "delay_hours": None},
            {"role": "能源局-监管", "purposes": ["运行监测", "趋势分析"], "action": "aggregate", "fields": ["industry", "region", "day", "kwh"], "min_granularity": "day", "delay_hours": None},
            {"role": "电网调度", "purposes": ["负荷预测"], "action": "compute_only", "fields": ["industry", "region", "day", "kwh"], "min_granularity": None, "delay_hours": None},
            {"role": "研究机构", "purposes": [], "action": "aggregate", "fields": ["industry", "day", "kwh"], "min_granularity": "month", "delay_hours": None},
        ],
    },
    {
        "id": "coal_daily",
        "name": "电煤供耗存日报",
        "level": "L3-敏感",
        "connector": "coal",
        "default_action": "deny",
        "rules": [
            {"role": "煤炭企业", "purposes": [], "action": "allow", "fields": ["day", "supply_kt", "consumption_kt", "inventory_kt"], "min_granularity": None, "delay_hours": None},
            {"role": "能源局-监管", "purposes": ["保供监测", "运行监测"], "action": "allow", "fields": ["day", "supply_kt", "consumption_kt", "inventory_kt"], "min_granularity": None, "delay_hours": None},
            {"role": "电网调度", "purposes": ["负荷预测", "保供监测"], "action": "compute_only", "fields": ["day", "supply_kt", "consumption_kt", "inventory_kt"], "min_granularity": None, "delay_hours": None},
            {"role": "研究机构", "purposes": [], "action": "aggregate", "fields": ["day", "supply_kt", "consumption_kt", "inventory_kt"], "min_granularity": "month", "delay_hours": None},
        ],
    },
    {
        "id": "privacy_task",
        "name": "隐私计算任务",
        "level": "L2-内部",
        "connector": "platform",
        "default_action": "deny",
        "rules": [
            {"role": "能源局-监管", "purposes": [], "action": "allow", "fields": [], "min_granularity": None, "delay_hours": None},
            {"role": "电网调度", "purposes": [], "action": "compute_only", "fields": [], "min_granularity": None, "delay_hours": None},
            {"role": "研究机构", "purposes": [], "action": "compute_only", "fields": [], "min_granularity": None, "delay_hours": None},
        ],
    },
]


class PrototypeQueryRequest(BaseModel):
    text: str = Field(min_length=2, max_length=500)


class PrototypeRuleRequest(BaseModel):
    resource_id: str = Field(min_length=1, max_length=96)
    role: str = Field(min_length=1, max_length=96)
    purpose: str = Field(default="", max_length=128)
    action: str = Field(pattern="^(allow|deny|aggregate|delay|compute_only)$")


def _role_label(user: User) -> str:
    return ROLE_LABELS.get(user.role_code, user.role_code)


def _current_did(db: Session, user: User) -> str:
    did = db.scalar(
        select(DidIdentity)
        .where(DidIdentity.owner_id == user.org_id, DidIdentity.org_id == user.org_id)
        .order_by(DidIdentity.created_at.desc())
    )
    return did.did_id if did else f"did:eds:{user.org_id}"


def _org_name(db: Session, org_id: str) -> str:
    org = db.get(Organization, org_id)
    return org.org_name if org else org_id


def _prototype_evidence(db: Session, user: User, *, action: str, target_type: str, target_id: str, payload: dict[str, Any]) -> BlockchainEvidence:
    return LocalEvidenceLedgerAdapter().anchor(
        db,
        task_id=None,
        stage="PROTOTYPE",
        biz_type=target_type,
        biz_id=target_id,
        payload={"action": action, "actor_org_id": user.org_id, **payload},
    )


def _static_policy() -> list[dict[str, Any]]:
    return [{**item, "rules": [dict(rule) for rule in item["rules"]]} for item in STATIC_POLICY_MATRIX]


def _dynamic_policy(db: Session) -> list[dict[str, Any]]:
    assets = db.scalars(
        select(DataAsset)
        .where(DataAsset.status == "ACTIVE")
        .order_by(DataAsset.created_at.desc())
    ).all()
    result: list[dict[str, Any]] = []
    for asset in assets:
        metadata = asset.metadata_json or {}
        if not metadata.get("dynamic"):
            continue
        connector = str(metadata.get("connector") or "power")
        prototype_id = str(metadata.get("resource_id") or asset.asset_code)
        rules = db.scalars(
            select(AccessRule)
            .where(AccessRule.asset_id == asset.asset_id, AccessRule.status == "ACTIVE", AccessRule.revoked_at.is_(None))
            .order_by(AccessRule.version_no.asc())
        ).all()
        rendered_rules = []
        for rule in rules:
            scope = rule.scope_json if isinstance(rule.scope_json, dict) else {}
            role = str(scope.get("prototype_role") or "")
            if not role:
                continue
            rendered_rules.append(
                {
                    "role": role,
                    "purposes": [scope["prototype_purpose"]] if scope.get("prototype_purpose") else [],
                    "action": str(scope.get("prototype_action") or _mode_to_action(rule.mode)),
                    "fields": list(scope.get("fields") or []),
                    "min_granularity": (rule.limits_json or {}).get("granularity"),
                    "delay_hours": (rule.limits_json or {}).get("delay_hours"),
                    "rule_id": rule.rule_id,
                }
            )
        result.append(
            {
                "id": prototype_id,
                "name": asset.asset_name,
                "level": f"{asset.sensitivity_level}-{'敏感' if asset.sensitivity_level == 'L3' else '内部'}",
                "connector": connector,
                "default_action": "deny",
                "dynamic": True,
                "asset_id": asset.asset_id,
                "owner_org_id": asset.owner_org_id,
                "rules": rendered_rules,
            }
        )
    return result


def _mode_to_action(mode: str) -> str:
    return {"AUTO_CALL": "allow", "FORBIDDEN": "deny"}.get(mode, "compute_only")


def _audit_records(db: Session, limit: int) -> list[dict[str, Any]]:
    items = db.scalars(select(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(limit)).all()
    records = []
    for item in items:
        details = item.details_json if isinstance(item.details_json, dict) else {}
        action = str(details.get("prototype_action") or "")
        if action not in ACTION_LABELS:
            action = "deny" if "DEN" in item.action_code or item.result in {"DENIED", "REJECTED"} else "aggregate"
        records.append(
            {
                "id": item.log_id,
                "ts": item.occurred_at.isoformat(),
                "action": action,
                "action_name": ACTION_LABELS[action],
                "subject": item.actor_name,
                "resource": str(details.get("resource_name") or details.get("resource_id") or item.target_id),
                "target_type": item.target_type,
                "target_id": item.target_id,
                "result": item.result,
                "trace_id": item.trace_id,
            }
        )
    return records


def _chain_state(db: Session) -> tuple[bool, str]:
    latest = db.scalars(
        select(AuditLog)
        .where(AuditLog.action_code.in_(("PROTOTYPE_CHAIN_TAMPER", "PROTOTYPE_CHAIN_RESTORE")))
        .order_by(AuditLog.occurred_at.desc())
        .limit(1)
    ).first()
    if latest and latest.action_code == "PROTOTYPE_CHAIN_TAMPER":
        return False, "检测到模拟篡改，哈希链校验失败"
    evidences = db.scalars(select(BlockchainEvidence).order_by(BlockchainEvidence.block_height.asc())).all()
    verified = all(LocalEvidenceLedgerAdapter.verify(item)["matched"] for item in evidences)
    return verified, "哈希链完整" if verified else "哈希链存在异常"


def _demo_dashboard_projection() -> dict[str, Any]:
    """Return aggregate-only demo data for the prototype dashboard in non-production."""
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    days = [(today - timedelta(days=6 - index)).isoformat() for index in range(7)]
    series = {
        "济南": [7420, 7680, 7810, 7540, 8060, 8240, 7980],
        "青岛": [5480, 5610, 5790, 5660, 5840, 5980, 5920],
        "烟台": [3640, 3710, 3820, 3900, 3990, 4050, 3980],
        "潍坊": [4310, 4420, 4510, 4470, 4630, 4700, 4650],
        "临沂": [3290, 3380, 3460, 3520, 3590, 3660, 3610],
    }
    coal_days = [15.4, 15.8, 16.2, 16.0, 16.7, 17.2, 17.8]
    coal_inventory = [468.2, 476.5, 484.1, 480.6, 497.8, 511.4, 522.6]
    coal_consumption = [30.4, 30.1, 29.8, 30.7, 29.6, 29.2, 29.4]
    audit_specs = [
        ("compute_only", "仅计算不出域", "山东电力交易中心", "电煤供耗存日报", "SUCCESS"),
        ("aggregate", "汇总提供", "能源局-监管", "电网负荷曲线", "SUCCESS"),
        ("allow", "直接提供", "华北电力燃料公司", "发电出力数据", "SUCCESS"),
        ("deny", "禁止提供", "研究机构", "电力交易成交明细", "DENIED"),
        ("aggregate", "汇总提供", "能源局-监管", "跨主体供需趋势", "SUCCESS"),
        ("compute_only", "仅计算不出域", "山东电网调度中心", "营销用户用电数据", "SUCCESS"),
    ]
    now = utc_now()
    audit = [
        {
            "id": f"demo-audit-{index + 1:02d}",
            "ts": (now - timedelta(minutes=7 * index + 3)).isoformat(),
            "action": action,
            "action_name": action_name,
            "subject": subject,
            "resource": resource,
            "target_type": "PROTOTYPE_QUERY",
            "target_id": f"demo-query-{index + 1:02d}",
            "result": result,
            "trace_id": f"trace-demo-{index + 1:02d}",
        }
        for index, (action, action_name, subject, resource, result) in enumerate(audit_specs)
    ]
    return {
        "map": {
            "days": days,
            "series": series,
            "coal_days": coal_days,
            "coal_inventory": coal_inventory,
            "coal_consumption": coal_consumption,
        },
        "gauge": {"days": coal_days[-1], "level": "库存充足", "inventory": coal_inventory[-1]},
        "audit": audit,
        "action_counts": {"allow": 8, "deny": 2, "aggregate": 11, "delay": 1, "compute_only": 10},
        "connectors": [
            {"name": "电力连接器", "status": "正常"},
            {"name": "煤炭连接器", "status": "正常"},
            {"name": "策略引擎", "status": "正常"},
            {"name": "哈希链存证", "status": "完整"},
        ],
        "timeline": audit[:5],
    }


def _parse_period(text: str) -> tuple[date, date]:
    match = re.search(r"(?:(20\d{2})年?)?(\d{1,2})月", text)
    today = utc_now().date()
    if match:
        year = int(match.group(1) or today.year)
        month = int(match.group(2))
        if 1 <= month <= 12:
            return date(year, month, 1), date(year, month, monthrange(year, month)[1])
    return today - timedelta(days=30), today


def _result_for_asset(db: Session, asset: DataAsset, resource: str, function: str) -> dict[str, Any]:
    from ..models import DataUpload

    uploads = db.scalars(
        select(DataUpload)
        .where(DataUpload.owner_org_id == asset.owner_org_id)
        .order_by(DataUpload.created_at.desc())
        .limit(20)
    ).all()
    values: list[float] = []
    trend: list[dict[str, Any]] = []
    curves: list[list[float]] = []
    for upload in uploads:
        payload = upload.summary_json if isinstance(upload.summary_json, dict) else {}
        period = str(payload.get("period") or getattr(upload, "label", "") or f"样本 {len(trend) + 1}")
        for key in (resource, "energy_mwh", "record_count", "load_curve"):
            value = payload.get(key)
            if isinstance(value, list):
                values.extend(float(item) for item in value if isinstance(item, (int, float)))
                if key == "load_curve" and resource == "load":
                    curves.append([float(item) for item in value if isinstance(item, (int, float))])
            elif isinstance(value, (int, float)) and key == resource:
                numeric_value = float(value)
                values.append(numeric_value)
                trend.append({"label": period, "value": numeric_value})
    if not values:
        values = [float(max(asset.metadata_json.get("record_count", 0), 0))]
    if curves:
        width = max(len(curve) for curve in curves)
        trend = [
            {"label": f"{index:02d}:00", "value": round(sum(curve[index] for curve in curves if index < len(curve)) / len([curve for curve in curves if index < len(curve)]), 2)}
            for index in range(width)
            if any(index < len(curve) for curve in curves)
        ]
    if not trend:
        trend = [{"label": f"样本 {index + 1}", "value": round(value, 2)} for index, value in enumerate(values[:12])]
    if function == "max": value = max(values)
    elif function == "min": value = min(values)
    elif function == "count": value = len(values)
    elif function == "sum": value = sum(values)
    else: value = sum(values) / len(values)
    return {"value": round(value, 2), "record_count": len(values), "resource": resource, "function": FUNCTION_LABELS.get(function, function), "trend": trend[:24]}


@router.get("/header")
def header(user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {
        "title": "能源可信数据空间 · 原型演示",
        "identity": {"name": _org_name(db, user.org_id), "role": _role_label(user), "did": _current_did(db, user)},
        "stats": [
            {"key": "resources", "label": "数据资源", "value": db.scalar(select(func.count(DataAsset.asset_id)).where(DataAsset.status == "ACTIVE")) or 0},
            {"key": "rules", "label": "策略规则", "value": db.scalar(select(func.count(AccessRule.rule_id)).where(AccessRule.status == "ACTIVE")) or 0},
            {"key": "identities", "label": "注册主体", "value": db.scalar(select(func.count(Organization.org_id)).where(Organization.status == "ACTIVE")) or 0},
            {"key": "blocks", "label": "存证区块", "value": db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0},
        ],
    }


@router.get("/dashboard")
def dashboard(user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    records = _audit_records(db, 200)
    ok, chain_message = _chain_state(db)
    uploads = db.scalars(select(DataUsageRequest).order_by(DataUsageRequest.submitted_at.desc()).limit(1)).all()
    demo_projection = _demo_dashboard_projection() if settings.app_env in {"development", "test", "demo"} else None
    is_demo = demo_projection is not None
    real_activity = bool(
        db.scalar(select(func.count(PrivacyAnalysisJob.analysis_id)))
        or db.scalar(select(func.count(SettlementTask.task_id)))
    )
    use_demo_activity = is_demo and not real_activity
    audit_records = demo_projection["audit"] if use_demo_activity else records[:8]
    action_counts = (
        demo_projection["action_counts"]
        if use_demo_activity
        else {action: sum(1 for item in records if item["action"] == action) for action in ACTION_LABELS}
    )
    timeline = [item for item in records if "隐私" in item["resource"] or "协同" in item["resource"]][:6]
    if use_demo_activity:
        timeline = demo_projection["timeline"]
    map_data = demo_projection["map"] if demo_projection else {"days": [], "series": {}, "coal_days": [], "coal_inventory": [], "coal_consumption": []}
    gauge = demo_projection["gauge"] if demo_projection else {"days": 0, "level": "暂无数据", "inventory": 0}
    connectors = demo_projection["connectors"] if demo_projection else [
        {"name": "电力连接器", "status": "正常"},
        {"name": "煤炭连接器", "status": "正常"},
        {"name": "策略引擎", "status": "正常"},
        {"name": "哈希链存证", "status": "完整" if ok else "异常"},
    ]
    return {
        "kpis": {
            "resources": db.scalar(select(func.count(DataAsset.asset_id)).where(DataAsset.status == "ACTIVE")) or 0,
            "rules": db.scalar(select(func.count(AccessRule.rule_id)).where(AccessRule.status == "ACTIVE")) or 0,
            "identities": db.scalar(select(func.count(Organization.org_id)).where(Organization.status == "ACTIVE")) or 0,
            "blocks": db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0,
            "today_queries": len(records) if records else (sum(action_counts.values()) if use_demo_activity else 0),
            "no_domain_export": "100%",
        },
        "map": map_data,
        "gauge": gauge,
        "audit": audit_records,
        "action_counts": action_counts,
        "connectors": connectors,
        "timeline": timeline,
        "chain": {"ok": ok, "message": chain_message},
        "latest_usage": bool(uploads),
        "data_mode": "demo" if is_demo else "live",
        "data_notice": (
            "演示态势图 · 真实任务已写入审计与计算记录"
            if use_demo_activity is False and is_demo
            else "演示数据 · 仅用于原型展示"
            if is_demo
            else "实时数据 · 当前环境"
        ),
    }


@router.post("/query")
def query(payload: PrototypeQueryRequest, user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    text = payload.text.strip()
    translation = _manual_parse(text)
    domain = translation.energy_domain
    resource = translation.resource
    function = translation.function or "average"
    if not domain:
        if any(term in text for term in ("电网", "电力", "负荷", "交易", "风电", "光伏", "用电")):
            domain = "electricity"
        elif any(term in text for term in ("煤炭", "电煤", "煤")):
            domain = "coal"
    if not resource and "库存" in text:
        resource = "inventory"
    if any(term in text for term in ("各地区", "各行业", "每天")):
        function = "group_by"
    start_date, end_date = _parse_period(text)
    if not domain or not resource:
        return {"question": text, "plan": [], "decision": {"action": "deny", "label": "禁止提供", "reason": "未能识别能源种类或数据资源"}, "result": None, "audit_id": None}
    assets = db.scalars(select(DataAsset).where(DataAsset.status == "ACTIVE")).all()
    asset = next((item for item in assets if (item.metadata_json or {}).get("domain") == domain and (item.metadata_json or {}).get("resource_id") == resource), None)
    action = "deny"
    reason = "当前账号没有该数据资源的有效授权"
    if asset and asset.owner_org_id == user.org_id:
        action, reason = "allow", "当前主体访问自有数据资源"
    elif asset and user.role_code == "REGULATOR":
        action, reason = "aggregate", "监管身份按最小必要范围返回聚合结果"
    elif asset:
        approved = db.scalar(select(DataUsageRequest).where(DataUsageRequest.asset_id == asset.asset_id, DataUsageRequest.applicant_org_id == user.org_id, DataUsageRequest.status == "APPROVED"))
        if approved:
            action, reason = "compute_only", "命中已批准授权，原始明细不出域"
    if asset is None:
        reason = "数据目录中没有匹配的已发布资源"
    target_id = sha256_json({"user": user.user_id, "text": text, "resource": resource, "start": start_date.isoformat(), "end": end_date.isoformat()})
    add_audit_log(db, action="PROTOTYPE_QUERY_" + ("DENIED" if action == "deny" else "COMPLETED"), target_type="PROTOTYPE_QUERY", target_id=target_id, result="DENIED" if action == "deny" else "SUCCESS", user=user, details={"prototype_action": action, "resource_id": resource, "resource_name": asset.asset_name if asset else resource, "domain": domain, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "raw_data_returned": False})
    evidence = _prototype_evidence(db, user, action=action, target_type="PROTOTYPE_QUERY", target_id=target_id, payload={"resource_id": resource, "decision": action, "raw_data_returned": False})
    db.commit()
    return {
        "question": text,
        "plan": [{"stage": "请求解析", "status": "已完成"}, {"stage": "策略裁决", "status": "已完成"}, {"stage": "受控执行", "status": "已完成" if action != "deny" else "已阻断"}, {"stage": "可信留痕", "status": "已完成"}],
        "identity": {"name": _org_name(db, user.org_id), "did": _current_did(db, user)},
        "decision": {"action": action, "label": ACTION_LABELS[action], "reason": reason},
        "result": _result_for_asset(db, asset, resource, function) if asset and action != "deny" else None,
        "resource_name": asset.asset_name if asset else resource,
        "function_name": FUNCTION_LABELS.get(function, function),
        "audit_id": evidence.evidence_id,
        "raw_data_returned": False,
    }


@router.get("/connector")
def connector(user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    assets = db.scalars(select(DataAsset).where(DataAsset.owner_org_id == user.org_id, DataAsset.status == "ACTIVE").order_by(DataAsset.created_at.desc())).all()
    return {"connectors": [{"id": "power", "name": "电力连接器", "available": user.role_code in {"GENERATOR", "RETAILER", "EXCHANGE"}}, {"id": "coal", "name": "煤炭连接器", "available": user.role_code == "COAL_ENTERPRISE"}], "resources": [{"id": str((item.metadata_json or {}).get("resource_id") or item.asset_code), "name": item.asset_name, "level": item.sensitivity_level, "connector": (item.metadata_json or {}).get("connector", "power"), "rows": db.scalar(select(DataAssetVersion.record_count).where(DataAssetVersion.version_id == item.current_version_id)) or 0} for item in assets if (item.metadata_json or {}).get("dynamic")]}


@router.get("/connector/sample.csv")
def connector_sample(user: User = Depends(require_roles(*BUSINESS_ROLES))) -> Response:
    content = "day,supply_kt,consumption_kt,inventory_kt\n2026-06-01,120,110,5515.6\n2026-06-02,121,112,5524.6\n"
    filename = quote("电煤库存示例.csv")
    return Response(content=content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="energy-sample.csv"; filename*=UTF-8\'\'{filename}'})


@router.post("/connector/{connector}/resources/upload")
async def upload_resource(connector: str, connector_name: str = Form(default=""), resource_id: str = Form(default=""), name: str = Form(default=""), level: str = Form(default=""), time_column: str = Form(default=""), numeric_fields: str = Form(default=""), file: UploadFile = File(...), user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
    allowed_roles = {"power": {"GENERATOR", "RETAILER", "EXCHANGE"}, "coal": {"COAL_ENTERPRISE"}}
    if connector not in allowed_roles or user.role_code not in allowed_roles[connector]:
        raise HTTPException(403, "当前账号不能使用该连接器")
    if not resource_id.strip() or not name.strip() or not time_column.strip():
        raise HTTPException(422, "资源编号、资源名称和时间字段不能为空")
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "CSV 文件不能超过 5MB")
    try:
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(422, "CSV 文件必须是 UTF-8 编码且格式有效") from exc
    if not rows:
        raise HTTPException(422, "CSV 文件没有可注册的数据行")
    fields = [item.strip() for item in numeric_fields.split(",") if item.strip()]
    missing = [item for item in [time_column, *fields] if item not in (rows[0] or {})]
    if missing:
        raise HTTPException(422, f"CSV 缺少字段：{'、'.join(missing)}")
    source_code = f"PROTOTYPE-{connector.upper()}-{user.org_id}"
    source = db.scalar(select(DataSource).where(DataSource.source_code == source_code))
    if source is None:
        source = DataSource(source_code=source_code, source_name=f"{name.strip()}连接器", owner_org_id=user.org_id, source_type="ENTERPRISE_CONNECTOR", connector_type="TRUSTED_DATA_SPACE_CONNECTOR", endpoint_ref=f"connector://{user.org_id}/{connector}", security_domain=connector, capability_label="LOCAL_REAL", status="ACTIVE", metadata_json={"dynamic": True, "raw_data_centrally_stored": False})
        db.add(source)
        db.flush()
    asset = db.scalar(select(DataAsset).where(DataAsset.owner_org_id == user.org_id, DataAsset.asset_code == f"PROTOTYPE_{connector.upper()}_{resource_id.strip().upper()}"))
    if asset is None:
        asset = DataAsset(source_id=source.source_id, owner_org_id=user.org_id, asset_code=f"PROTOTYPE_{connector.upper()}_{resource_id.strip().upper()}", asset_name=name.strip(), asset_type="DYNAMIC_CONNECTOR_RESOURCE", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level=level.split("-")[0] if level else "L3", status="ACTIVE", metadata_json={"dynamic": True, "connector": connector, "resource_id": resource_id.strip(), "domain": "electricity" if connector == "power" else "coal", "raw_data_centrally_stored": False, "time_column": time_column, "numeric_fields": fields})
        db.add(asset)
        db.flush()
    else:
        asset.asset_name = name.strip()
        asset.status = "ACTIVE"
    previous = db.scalar(select(func.max(DataAssetVersion.version_no)).where(DataAssetVersion.asset_id == asset.asset_id)) or 0
    data_hash = hashlib.sha256(raw).hexdigest()
    version = DataAssetVersion(asset_id=asset.asset_id, version_no=int(previous) + 1, schema_version="prototype-v1", schema_json={"fields": list(rows[0].keys()), "time_column": time_column, "numeric_fields": fields}, data_ref=f"connector://{user.org_id}/{connector}/{resource_id.strip()}", data_hash=data_hash, commitment=sha256_json({"data_hash": data_hash, "owner_org_id": user.org_id}), record_count=len(rows), immutable_hash=sha256_json({"asset_id": asset.asset_id, "version": int(previous) + 1, "data_hash": data_hash}), status="ACTIVE")
    db.add(version)
    db.flush()
    asset.current_version_id = version.version_id
    did = _current_did(db, user)
    db.add(DataAssetPassport(asset_version_id=version.version_id, owner_did=did, provenance_json={"source": "企业侧连接器", "raw_data_centrally_stored": False}, classification_json={"level": asset.sensitivity_level}, permitted_use_json={"default_action": "deny", "raw_data_export": False}, policy_refs_json=[f"prototype:{resource_id.strip()}"], evidence_refs_json=[], passport_hash=sha256_json({"asset_id": asset.asset_id, "version_id": version.version_id, "data_hash": data_hash}), status="ACTIVE"))
    add_audit_log(db, action="PROTOTYPE_RESOURCE_REGISTERED", target_type="DATA_ASSET", target_id=asset.asset_id, result="SUCCESS", user=user, details={"prototype_action": "allow", "resource_id": resource_id.strip(), "resource_name": name.strip(), "connector": connector, "rows": len(rows), "idempotency_key": idempotency_key, "raw_data_centrally_stored": False})
    evidence = _prototype_evidence(db, user, action="allow", target_type="DATA_ASSET", target_id=asset.asset_id, payload={"resource_id": resource_id.strip(), "version_id": version.version_id, "data_hash": data_hash, "raw_data_centrally_stored": False})
    db.commit()
    return {"resource": {"id": resource_id.strip(), "name": name.strip(), "level": level or asset.sensitivity_level, "connector": connector, "rows": len(rows), "version": version.version_no}, "status": "已注册，默认拒绝", "evidence_id": evidence.evidence_id}


@router.get("/policy")
def policy(user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    matrix = _static_policy() + _dynamic_policy(db)
    applications = db.scalars(select(DataUsageRequest).order_by(DataUsageRequest.submitted_at.desc()).limit(100)).all()
    return {"matrix": matrix, "applications": [{"ts": item.submitted_at.isoformat(), "resource_id": item.asset_id, "resource_name": _org_name(db, item.provider_org_id), "applicant_role": ROLE_LABELS.get(db.get(User, item.applicant_user_id).role_code, "使用方") if db.get(User, item.applicant_user_id) else "使用方", "applicant_did": item.applicant_did, "purpose": item.purpose, "status": {"SUBMITTED": "pending", "APPROVED": "approved", "REJECTED": "rejected"}.get(item.status, "pending")} for item in applications]}


def _dynamic_asset_for_rule(db: Session, resource_id: str) -> DataAsset:
    assets = db.scalars(select(DataAsset).where(DataAsset.status == "ACTIVE")).all()
    asset = next((item for item in assets if (item.metadata_json or {}).get("dynamic") and str((item.metadata_json or {}).get("resource_id")) == resource_id), None)
    if asset is None:
        raise HTTPException(404, "动态接入资源不存在")
    return asset


def _can_manage_dynamic(user: User, asset: DataAsset) -> bool:
    return user.role_code == "REGULATOR" or user.org_id == asset.owner_org_id


@router.post("/policy/rules")
def add_policy_rule(payload: PrototypeRuleRequest, user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    asset = _dynamic_asset_for_rule(db, payload.resource_id)
    if not _can_manage_dynamic(user, asset):
        raise HTTPException(403, "当前账号不能配置该资源策略")
    if user.role_code == "REGULATOR" and payload.action == "allow":
        raise HTTPException(403, "监管方不能配置直接提供")
    action_scope = {"prototype_role": payload.role.strip(), "prototype_action": payload.action, "prototype_purpose": payload.purpose.strip(), "fields": list((asset.metadata_json or {}).get("numeric_fields") or [])}
    rule_code = f"PROTOTYPE:{payload.resource_id}:{payload.role.strip()}"
    existing = db.scalars(select(AccessRule).where(AccessRule.owner_org_id == asset.owner_org_id, AccessRule.rule_code == rule_code).order_by(AccessRule.version_no.desc())).first()
    version_no = (existing.version_no + 1) if existing else 1
    if existing and existing.status == "ACTIVE":
        existing.status = "REVOKED"
        existing.revoked_at = utc_now()
    rule = AccessRule(owner_org_id=asset.owner_org_id, rule_code=rule_code, version_no=version_no, energy_domain=(asset.metadata_json or {}).get("domain"), asset_id=asset.asset_id, resource_id=payload.resource_id, function_code="prototype", mode=ACTION_TO_MODE[payload.action], scope_json=action_scope, limits_json={"granularity": "day" if payload.action in {"aggregate", "delay"} else None, "delay_hours": 24 if payload.action == "delay" else None}, status="ACTIVE", rule_hash=sha256_json({"rule_code": rule_code, "version": version_no, **action_scope}), approved_by_user_id=user.user_id, approved_at=utc_now())
    db.add(rule)
    db.flush()
    add_audit_log(db, action="PROTOTYPE_POLICY_RULE_ADDED", target_type="ACCESS_RULE", target_id=rule.rule_id, result="SUCCESS", user=user, details={"prototype_action": payload.action, "resource_id": payload.resource_id, "resource_name": asset.asset_name, "role": payload.role.strip()})
    evidence = _prototype_evidence(db, user, action=payload.action, target_type="ACCESS_RULE", target_id=rule.rule_id, payload={"resource_id": payload.resource_id, "role": payload.role.strip(), "rule_hash": rule.rule_hash})
    db.commit()
    return {"rule_id": rule.rule_id, "evidence_id": evidence.evidence_id}


@router.delete("/policy/rules")
def delete_policy_rule(resource_id: str = Query(...), role: str = Query(...), user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    asset = _dynamic_asset_for_rule(db, resource_id)
    if not _can_manage_dynamic(user, asset):
        raise HTTPException(403, "当前账号不能删除该资源策略")
    rule = db.scalars(select(AccessRule).where(AccessRule.asset_id == asset.asset_id, AccessRule.status == "ACTIVE")).all()
    target = next((item for item in rule if (item.scope_json or {}).get("prototype_role") == role), None)
    if target is None:
        raise HTTPException(404, "策略规则不存在")
    target.status = "REVOKED"
    target.revoked_at = utc_now()
    add_audit_log(db, action="PROTOTYPE_POLICY_RULE_DELETED", target_type="ACCESS_RULE", target_id=target.rule_id, result="SUCCESS", user=user, details={"prototype_action": "deny", "resource_id": resource_id, "resource_name": asset.asset_name, "role": role})
    evidence = _prototype_evidence(db, user, action="deny", target_type="ACCESS_RULE", target_id=target.rule_id, payload={"resource_id": resource_id, "role": role, "revoked": True})
    db.commit()
    return {"rule_id": target.rule_id, "evidence_id": evidence.evidence_id}


@router.get("/audit")
def audit(limit: int = Query(default=20, ge=1, le=200), user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    records = _audit_records(db, limit)
    blocks = db.scalars(select(BlockchainEvidence).order_by(BlockchainEvidence.block_height.desc()).limit(limit)).all()
    ok, message = _chain_state(db)
    counts = {action: sum(1 for item in records if item["action"] == action) for action in ACTION_LABELS}
    return {"records": records, "blocks": [{"id": item.evidence_id, "height": item.block_height, "hash": item.evidence_hash, "tx_hash": item.tx_hash, "status": item.status, "created_at": item.created_at.isoformat()} for item in blocks], "metrics": {"total": len(records), "denied": counts["deny"], "controlled": counts["aggregate"] + counts["compute_only"], "blocks": db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0}, "chain": {"ok": ok, "message": message}}


@router.post("/audit/verify")
def verify_audit(user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    ok, message = _chain_state(db)
    add_audit_log(db, action="PROTOTYPE_CHAIN_VERIFY", target_type="EVIDENCE_CHAIN", target_id="prototype", result="SUCCESS" if ok else "FAILED", user=user, details={"ok": ok})
    db.commit()
    return {"ok": ok, "message": message, "checked": db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0}


@router.post("/audit/tamper")
def tamper_audit(user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    add_audit_log(db, action="PROTOTYPE_CHAIN_TAMPER", target_type="EVIDENCE_CHAIN", target_id="prototype", result="TAMPERED", user=user, details={"demo": True})
    db.commit()
    return {"ok": True, "message": "已写入模拟篡改状态，验证链将显示异常"}


@router.post("/audit/restore")
def restore_audit(user: User = Depends(require_roles(*BUSINESS_ROLES)), db: Session = Depends(get_db)) -> dict[str, Any]:
    add_audit_log(db, action="PROTOTYPE_CHAIN_RESTORE", target_type="EVIDENCE_CHAIN", target_id="prototype", result="RESTORED", user=user, details={"demo": True})
    db.commit()
    return {"ok": True, "message": "已恢复模拟状态，请重新验证链"}
