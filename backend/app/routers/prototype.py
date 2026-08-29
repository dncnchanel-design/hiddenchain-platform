from __future__ import annotations

import base64
import math
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..models import AccessRule, AuditLog, BlockchainEvidence, DataUsageRequest, DidIdentity, Organization, PrivacyAnalysisJob, SettlementTask, User, new_id, utc_now
from ..security import canonical_json, sha256_json
from ..services.adapters import LocalEvidenceLedgerAdapter
from ..services.common import add_audit_log
from ..services.local_data_boundary import subject_node_config
from ..services.privacy_attestation import (
    ConnectorAuditError,
    PrivacyAttestationError,
    verify_dashboard_audit_pointer,
    verify_signed_connector_non_export,
)
from ..services.trust_space import workbench as trusted_workbench
from ..trust_models import DataAsset, DataAssetVersion
from .trusted_query import DOMAIN_LABELS, FUNCTION_LABELS, _connector_failure, _manual_parse, _platform_private_key, _platform_public_key


router = APIRouter(prefix="/prototype", tags=["target-prototype"])
demo_router = APIRouter(prefix="/prototype", tags=["target-prototype-demo"])

ROLE_LABELS = {
    "GENERATOR": "发电企业",
    "RETAILER": "售电企业",
    "COAL_ENTERPRISE": "煤炭企业",
    "HEAT_ENTERPRISE": "热力企业",
    "GAS_ENTERPRISE": "燃气企业",
    "OIL_ENTERPRISE": "石油企业",
    "EXCHANGE": "交易中心",
    "REGULATOR": "能源局-监管",
}

ENTERPRISE_METRIC_SPECS: dict[str, dict[str, str]] = {
    "GENERATOR": {"resource": "generation", "aggregation": "sum", "label": "日发电量", "unit": "MWh"},
    "RETAILER": {"resource": "load", "aggregation": "average", "label": "平均用电负荷", "unit": "MW"},
    "COAL_ENTERPRISE": {"resource": "inventory", "aggregation": "average", "label": "煤炭库存", "unit": "吨"},
    "HEAT_ENTERPRISE": {"resource": "supply", "aggregation": "sum", "label": "日供热量", "unit": "GJ"},
    "GAS_ENTERPRISE": {"resource": "storage", "aggregation": "average", "label": "天然气储量", "unit": "万立方米"},
    "OIL_ENTERPRISE": {"resource": "inventory", "aggregation": "average", "label": "石油库存", "unit": "吨"},
}

EXCHANGE_METRIC_SPECS: dict[str, dict[str, str]] = {
    "electricity": {"resource": "load", "aggregation": "average", "label": "区域平均负荷", "unit": "MW"},
    "coal": {"resource": "supply", "aggregation": "sum", "label": "日煤炭供应量", "unit": "吨"},
    "heat": {"resource": "supply", "aggregation": "sum", "label": "日供热量", "unit": "GJ"},
    "gas": {"resource": "pipeline_flow", "aggregation": "average", "label": "管道平均流量", "unit": "万立方米/日"},
    "oil": {"resource": "sales", "aggregation": "sum", "label": "日石油销售量", "unit": "吨"},
}

AGGREGATION_LABELS = {"sum": "日度求和", "average": "日度平均", "max": "日度最大值", "min": "日度最小值"}

ENTERPRISE_VIEW_COPY = {
    "GENERATOR": ("发电企业运行总览", "发电侧资产、授权处理与结算结果确认", "本方发电侧态势", "发电出力 · 新能源预测 · 结算协同"),
    "RETAILER": ("售电企业运营总览", "用户负荷、虚拟电厂与结算结果确认", "本方售电侧态势", "用户负荷 · 可调资源 · 结算协同"),
    "COAL_ENTERPRISE": ("煤炭企业运营总览", "煤炭供耗存资产、授权处理与协同任务", "本方煤炭供耗存态势", "煤炭供应 · 消费 · 库存协同"),
    "HEAT_ENTERPRISE": ("热能企业运营总览", "热能供给、授权处理与协同任务", "本方热能供需态势", "供热量 · 热负荷 · 管网协同"),
    "GAS_ENTERPRISE": ("天然气企业运营总览", "天然气供储运资产、授权处理与协同任务", "本方天然气供储运态势", "供应量 · 储量 · 管道协同"),
    "OIL_ENTERPRISE": ("石油企业运营总览", "石油产运销资产、授权处理与协同任务", "本方石油产运销态势", "产量 · 炼化 · 库存协同"),
}

ACTION_LABELS = {
    "allow": "直接提供",
    "deny": "禁止提供",
    "aggregate": "汇总提供",
    "delay": "延迟提供",
    "compute_only": "仅计算不出域",
    "tamper": "模拟篡改",
    "restore": "恢复模拟状态",
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
        if item.action_code == "PROTOTYPE_CHAIN_TAMPER":
            action = "tamper"
        elif item.action_code == "PROTOTYPE_CHAIN_RESTORE":
            action = "restore"
        elif action not in ACTION_LABELS:
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


def _latest_chain_event(db: Session) -> AuditLog | None:
    return db.scalars(
        select(AuditLog)
        .where(AuditLog.action_code.in_(("PROTOTYPE_CHAIN_TAMPER", "PROTOTYPE_CHAIN_RESTORE")))
        .order_by(AuditLog.occurred_at.desc())
        .limit(1)
    ).first()


def _chain_state(db: Session) -> tuple[bool, str]:
    latest = _latest_chain_event(db)
    if latest and latest.action_code == "PROTOTYPE_CHAIN_TAMPER":
        return False, "检测到模拟篡改，哈希链校验失败"
    evidences = db.scalars(select(BlockchainEvidence).order_by(BlockchainEvidence.block_height.asc())).all()
    verified = all(LocalEvidenceLedgerAdapter.verify(item)["matched"] for item in evidences)
    return verified, "哈希链完整" if verified else "哈希链存在异常"


def _tamper_projection(db: Session) -> dict[str, Any] | None:
    tamper = db.scalars(
        select(AuditLog)
        .where(AuditLog.action_code == "PROTOTYPE_CHAIN_TAMPER")
        .order_by(AuditLog.occurred_at.desc())
        .limit(1)
    ).first()
    if tamper is None:
        return None

    details = tamper.details_json if isinstance(tamper.details_json, dict) else {}
    evidence = None
    affected_evidence_id = details.get("affected_evidence_id")
    if affected_evidence_id:
        evidence = db.get(BlockchainEvidence, str(affected_evidence_id))
    if evidence is None:
        evidence = db.scalars(select(BlockchainEvidence).order_by(BlockchainEvidence.block_height.desc())).first()

    latest_chain_event = _latest_chain_event(db)
    block = None
    if evidence is not None:
        block = {
            "id": evidence.evidence_id,
            "height": evidence.block_height,
            "hash": evidence.evidence_hash,
            "tx_hash": evidence.tx_hash,
            "status": evidence.status,
            "created_at": evidence.created_at.isoformat(),
        }
    return {
        "event_id": tamper.log_id,
        "active": bool(latest_chain_event and latest_chain_event.action_code == "PROTOTYPE_CHAIN_TAMPER"),
        "actor_name": tamper.actor_name,
        "actor_user_id": tamper.actor_user_id,
        "actor_org_id": tamper.actor_org_id,
        "occurred_at": tamper.occurred_at.isoformat(),
        "trace_id": tamper.trace_id,
        "target_type": tamper.target_type,
        "target_id": tamper.target_id,
        "block": block,
        "note": "仅写入模拟篡改审计事件，未修改企业原始数据或存证内容",
    }


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
    city_days = {
        "济南": [16.8, 17.0, 17.2, 16.9, 17.5, 17.7, 17.4],
        "青岛": [13.6, 13.8, 14.1, 13.9, 14.4, 14.6, 14.3],
        "烟台": [11.2, 11.5, 11.7, 11.9, 12.2, 12.4, 12.1],
        "潍坊": [14.1, 14.3, 14.6, 14.4, 14.9, 15.1, 14.8],
        "临沂": [9.8, 10.1, 10.3, 10.5, 10.8, 11.0, 10.7],
    }
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
            "city_days": city_days,
        },
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


def _dashboard_view(db: Session, user: User, projection: dict[str, Any] | None) -> dict[str, Any]:
    organization = db.get(Organization, user.org_id)
    domain = str(organization.energy_domain or "electricity") if organization else "electricity"
    trusted = trusted_workbench(db, user)
    trusted_kpis = trusted["kpis"]

    if user.role_code == "REGULATOR":
        kind = "regulator"
        domain = "all"
        energy_label = "全域能源"
        title = "全域能源监管总览"
        subtitle = "跨能源域态势监测、审计复核与风险处置"
        visual_title = "全域能源监管态势"
        visual_subtitle = "城市受控天数：截至所选日期，相关数据纳入受控监管的累计时长"
        visual_value_label = "区域监测值"
        visual_value_unit = "综合单位"
        visualization = "regional_map"
        focus_title = "监管重点"
        kpi_items = [
            {"label": "全域数据资源", "value": trusted_kpis["visible_assets"], "meta": "目录元数据"},
            {"label": "审计任务", "value": trusted_kpis["audit_reports"], "meta": "报告与复核"},
            {"label": "授权记录", "value": trusted_kpis["usage_requests"], "meta": "跨主体申请"},
            {"label": "结算任务", "value": trusted_kpis["visible_tasks"], "meta": "全域任务"},
            {"label": "计算任务", "value": trusted_kpis["compute_jobs"], "meta": "受控执行"},
        ]
        primary_action = {"label": "进入审计追溯", "path": "/trusted-space/audit"}
        scope_label = "监管全域视角"
    elif user.role_code == "EXCHANGE":
        kind = "exchange"
        energy_label = DOMAIN_LABELS.get(domain, domain)
        title = f"区域{energy_label}交易中心总览"
        subtitle = f"{energy_label}供需协调、结算发起与审计协同"
        metric_spec = EXCHANGE_METRIC_SPECS.get(domain)
        visual_title = f"区域{energy_label}{metric_spec['label']}趋势" if metric_spec else f"区域{energy_label}业务趋势"
        visual_subtitle = (
            f"按日展示{metric_spec['label']}，统计方式：{AGGREGATION_LABELS[metric_spec['aggregation']]}"
            if metric_spec
            else f"当前{energy_label}交易协同暂无可用受控指标"
        )
        visual_value_label = metric_spec["label"] if metric_spec else f"{energy_label}业务指标"
        visual_value_unit = metric_spec["unit"] if metric_spec else ""
        visualization = "subject_trend"
        focus_title = "交易中心重点"
        kpi_items = [
            {"label": f"{energy_label}数据资产", "value": trusted_kpis["visible_assets"], "meta": "当前能源域目录"},
            {"label": "结算任务", "value": trusted_kpis["visible_tasks"], "meta": "发起、执行与归档"},
            {"label": "授权申请", "value": trusted_kpis["usage_requests"], "meta": "跨主体协同"},
            {"label": "计算任务", "value": trusted_kpis["compute_jobs"], "meta": "受控执行"},
            {"label": "审计报告", "value": trusted_kpis["audit_reports"], "meta": "证据复核"},
        ]
        primary_action = {"label": "发起结算任务", "path": "/trusted-space/mpc/new"}
        scope_label = f"{energy_label}交易协同视角"
    else:
        kind = "enterprise"
        default_copy = (
            f"{ROLE_LABELS.get(user.role_code, '能源主体')}运行总览",
            f"{DOMAIN_LABELS.get(domain, '能源')}资产、授权处理与协同任务",
            f"本方{DOMAIN_LABELS.get(domain, '能源')}数据趋势",
            f"{DOMAIN_LABELS.get(domain, '能源')}主体连接器受控汇总",
        )
        title, subtitle, _legacy_visual_title, _legacy_visual_subtitle = ENTERPRISE_VIEW_COPY.get(user.role_code, default_copy)
        energy_label = DOMAIN_LABELS.get(domain, domain)
        metric_spec = ENTERPRISE_METRIC_SPECS.get(user.role_code)
        if metric_spec is None:
            metric_spec = {
                "resource": "",
                "aggregation": "average",
                "label": f"{energy_label}业务指标",
                "unit": "",
            }
        visual_title = f"本方{metric_spec['label']}趋势"
        visual_subtitle = f"按日展示{metric_spec['label']}，统计方式：{AGGREGATION_LABELS[metric_spec['aggregation']]}"
        visual_value_label = metric_spec["label"]
        visual_value_unit = metric_spec["unit"]
        visualization = "subject_trend"
        focus_title = "本方业务重点"
        kpi_items = [
            {"label": "本方数据资源", "value": trusted_kpis["visible_assets"], "meta": "目录元数据"},
            {"label": "待处理授权", "value": trusted_kpis["inbound_usage_requests"], "meta": "入站申请"},
            {"label": "本方任务", "value": trusted_kpis["visible_tasks"], "meta": "参与结算"},
            {"label": "受控计算任务", "value": trusted_kpis["compute_jobs"], "meta": "不出域执行"},
            {"label": "授权记录", "value": trusted_kpis["usage_requests"], "meta": "本方范围"},
        ]
        primary_action = {"label": "查看本方数据目录", "path": "/trusted-space/catalog"}
        scope_label = f"{ROLE_LABELS.get(user.role_code, '主体')}视角"

    return {
        "kind": kind,
        "role_code": user.role_code,
        "energy_domain": domain,
        "energy_label": energy_label,
        "scope_label": scope_label,
        "title": title,
        "subtitle": subtitle,
        "visualization": visualization,
        "visual_title": visual_title,
        "visual_subtitle": visual_subtitle,
        "visual_value_label": visual_value_label,
        "visual_value_unit": visual_value_unit,
        "focus_title": focus_title,
        "kpis": kpi_items,
        "primary_action": primary_action,
        "data_scope": "role_scoped_controlled_aggregate",
        "projection": "demo_aggregate" if projection is not None else "subject_connector",
    }


def _subject_metric_spec(view: dict[str, Any]) -> dict[str, str] | None:
    if view["kind"] == "exchange":
        return EXCHANGE_METRIC_SPECS.get(view["energy_domain"])
    if view["kind"] == "enterprise":
        return ENTERPRISE_METRIC_SPECS.get(view["role_code"])
    return None


def _empty_subject_metric(
    spec: dict[str, str],
    *,
    status: str,
    status_label: str,
    message: str,
) -> dict[str, Any]:
    return {
        "title": "主体核心指标",
        "label": spec["label"],
        "value": None,
        "unit": spec["unit"],
        "status": status,
        "status_label": status_label,
        "source": "主体本地连接器",
        "latest_date": None,
        "record_count": 0,
        "aggregation": AGGREGATION_LABELS.get(spec["aggregation"], "日度汇总"),
        "trend": [],
        "message": message,
        "raw_records_returned": False,
    }


def _regulator_metric(view: dict[str, Any]) -> dict[str, Any]:
    value = next(
        (item["value"] for item in view["kpis"] if item["label"] == "全域数据资源"),
        0,
    )
    value = int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
    return {
        "title": "监管可见资源",
        "label": "已纳入监管的数据资源",
        "value": value,
        "unit": "项",
        "status": "available",
        "status_label": "平台汇总",
        "source": "可信空间目录",
        "latest_date": None,
        "record_count": value,
        "aggregation": "当前可见范围",
        "trend": [],
        "message": "仅统计目录元数据，不代表跨主体业务数值",
        "raw_records_returned": False,
    }


def _dashboard_connector_public_key(
    *,
    endpoint: str,
    node: dict[str, Any],
    provider_org_id: str,
    energy_domain: str,
) -> tuple[str, str]:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("主体连接器身份发现端点不安全")
    if settings.app_env not in {"demo", "development", "test"} and parsed.scheme != "https":
        raise ValueError("生产环境主体连接器端点必须使用 HTTPS")
    public_key = str(node.get("public_key") or "")
    key_source = "PRECONFIGURED_PUBLIC_KEY"
    if not public_key:
        if settings.app_env not in {"demo", "development", "test"}:
            raise ValueError("主体连接器公钥未登记")
        try:
            response = httpx.get(
                f"{endpoint.rstrip('/')}/health",
                timeout=min(max(settings.connector_timeout_seconds, 1.0), 8.0),
            )
        except httpx.HTTPError as exc:
            raise ValueError("主体连接器身份发现暂不可用") from exc
        if response.status_code >= 400:
            raise ValueError("主体连接器身份发现失败")
        try:
            health = response.json()
        except ValueError as exc:
            raise ValueError("主体连接器身份信息无效") from exc
        if not isinstance(health, dict) or (
            health.get("connector_id") != node.get("node_code")
            or health.get("organization_id") != provider_org_id
            or health.get("energy_domain") != energy_domain
        ):
            raise ValueError("主体连接器身份与登记节点不一致")
        public_key = str(health.get("public_key") or "")
        key_source = "VERIFIED_HEALTH_DISCOVERY"
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
    except Exception as exc:
        raise ValueError("主体连接器公钥无效") from exc
    return public_key, key_source


def _load_subject_metric(db: Session, user: User, view: dict[str, Any]) -> dict[str, Any]:
    if view["kind"] == "regulator":
        return _regulator_metric(view)

    spec = _subject_metric_spec(view)
    energy_label = view["energy_label"]
    if spec is None:
        fallback = {
            "resource": "",
            "aggregation": "average",
            "label": f"{energy_label}业务指标",
            "unit": "",
        }
        return _empty_subject_metric(
            fallback,
            status="not_configured",
            status_label="未配置",
            message=f"当前主体没有配置可展示的{energy_label}业务指标。",
        )

    node = subject_node_config(db, user.org_id)
    endpoint = node.get("endpoint") if node else None
    if not endpoint or not str(endpoint).lower().startswith(("http://", "https://")):
        return _empty_subject_metric(
            spec,
            status="not_configured",
            status_label="未接入",
            message=f"暂未接入{energy_label}主体连接器，无法展示{spec['label']}。",
        )

    try:
        today = utc_now().date()
        expected_public_key, key_source = _dashboard_connector_public_key(
            endpoint=str(endpoint),
            node=node or {},
            provider_org_id=user.org_id,
            energy_domain=view["energy_domain"],
        )
        connector_payload = {
            "request_id": f"dashboard-{new_id()}",
            "provider_org_id": user.org_id,
            "resource": spec["resource"],
            "aggregation": spec["aggregation"],
            "start_date": (today - timedelta(days=30)).isoformat(),
            "end_date": today.isoformat(),
            "decimals": 2,
        }
        timestamp = str(int(datetime.now(ZoneInfo("UTC")).timestamp()))
        nonce = new_id()
        signed_request = {"timestamp": timestamp, "nonce": nonce, "payload": connector_payload}
        platform_private_key = _platform_private_key()
        signature = platform_private_key.sign(canonical_json(signed_request).encode())
        response = httpx.post(
            f"{str(endpoint).rstrip('/')}/dashboard",
            json=connector_payload,
            headers={
                "X-Request-Timestamp": timestamp,
                "X-Request-Nonce": nonce,
                "X-Request-Signature": base64.b64encode(signature).decode(),
                "X-Platform-Public-Key": _platform_public_key(platform_private_key),
            },
            timeout=min(max(settings.connector_timeout_seconds, 1.0), 8.0),
        )
        if response.status_code >= 400:
            status_code, detail = _connector_failure(response)
            return _empty_subject_metric(
                spec,
                status="unavailable",
                status_label="不可用",
                message=f"主体连接器返回 {status_code}：{detail}",
            )

        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("主体连接器返回格式无效")
        if result.get("public_key") != expected_public_key:
            raise ValueError("主体连接器签名公钥与登记信息不一致")
        signed_result = {
            key: value
            for key, value in result.items()
            if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}
        }
        Ed25519PublicKey.from_public_bytes(base64.b64decode(expected_public_key)).verify(
            base64.b64decode(str(result["signature"])),
            canonical_json(signed_result).encode(),
        )
        if result.get("provider_org_id") != user.org_id:
            raise ValueError("主体连接器返回了不匹配的组织身份")
        if result.get("energy_domain") != view["energy_domain"]:
            raise ValueError("主体连接器返回了不匹配的能源域")
        if result.get("resource") != spec["resource"]:
            raise ValueError("主体连接器返回了不匹配的数据资源")
        try:
            privacy_verification = verify_signed_connector_non_export(
                signed_result,
                connector_payload,
            )
        except PrivacyAttestationError as exc:
            raise ValueError("主体连接器未提供可验证的不出域证明") from exc
        try:
            connector_audit = verify_dashboard_audit_pointer(
                signed_result,
                connector_payload,
                expected_connector_id=str((node or {}).get("node_code") or ""),
                expected_provider_org_id=user.org_id,
                expected_energy_domain=view["energy_domain"],
            )
        except ConnectorAuditError as exc:
            raise ValueError("主体连接器审计事件指针校验失败") from exc
        connector_audit["key_source"] = key_source

        trend: list[dict[str, Any]] = []
        raw_trend = result.get("trend")
        if isinstance(raw_trend, list):
            for point in raw_trend:
                if not isinstance(point, dict):
                    continue
                point_date = str(point.get("date") or "")
                raw_value = point.get("value")
                if not point_date or isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                    continue
                value = float(raw_value)
                if math.isfinite(value):
                    trend.append({"date": point_date, "value": value})
        if not trend:
            raise ValueError("主体连接器没有返回可用日度汇总")
        raw_count = result.get("record_count", 0)
        record_count = int(raw_count) if isinstance(raw_count, (int, float)) and not isinstance(raw_count, bool) else 0
        latest = trend[-1]
        return {
            "title": "主体核心指标",
            "label": spec["label"],
            "value": latest["value"],
            "unit": str(result.get("unit") or spec["unit"]),
            "status": "available",
            "status_label": "已接入",
            "source": f"{energy_label}主体本地连接器 · 签名汇总",
            "latest_date": latest["date"],
            "record_count": max(0, record_count),
            "aggregation": AGGREGATION_LABELS.get(spec["aggregation"], "日度汇总"),
            "trend": trend,
            "message": f"已接收 {latest['date']} 日度受控汇总",
            "raw_records_returned": False,
            "privacy_verification": privacy_verification,
            "connector_audit": connector_audit,
        }
    except Exception:
        return _empty_subject_metric(
            spec,
            status="unavailable",
            status_label="不可用",
            message="主体连接器暂不可用，未生成业务指标。",
        )


def _dashboard_connectors(
    view: dict[str, Any],
    metric: dict[str, Any],
    chain_ok: bool,
    projection: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if projection is not None:
        return projection["connectors"]
    subject_name = "监管目录汇总" if view["kind"] == "regulator" else f"{view['energy_label']}主体连接器"
    subject_status = metric["status_label"]
    return [
        {"name": subject_name, "status": subject_status},
        {"name": "策略引擎", "status": "正常"},
        {"name": "审计哈希链", "status": "完整" if chain_ok else "异常"},
    ]


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
    demo_projection = _demo_dashboard_projection() if settings.app_env in {"development", "test", "demo"} and user.role_code == "REGULATOR" else None
    view = _dashboard_view(db, user, demo_projection)
    metric = _load_subject_metric(db, user, view)
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
    map_data = demo_projection["map"] if demo_projection else {"days": [], "series": {}}
    connectors = _dashboard_connectors(view, metric, ok, demo_projection)
    return {
        "kpis": {
            "resources": db.scalar(select(func.count(DataAsset.asset_id)).where(DataAsset.status == "ACTIVE")) or 0,
            "rules": db.scalar(select(func.count(AccessRule.rule_id)).where(AccessRule.status == "ACTIVE")) or 0,
            "identities": db.scalar(select(func.count(Organization.org_id)).where(Organization.status == "ACTIVE")) or 0,
            "blocks": db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0,
            "today_queries": len(records) if records else (sum(action_counts.values()) if use_demo_activity else 0),
        },
        "map": map_data,
        "metric": metric,
        "audit": audit_records,
        "action_counts": action_counts,
        "connectors": connectors,
        "timeline": timeline,
        "chain": {"ok": ok, "message": chain_message},
        "latest_usage": bool(uploads),
        "data_mode": "demo" if is_demo else "subject_connector",
        "view": view,
        "data_notice": (
            "演示数据 · 当前页面仅展示监管演示汇总，业务指标不代表生产数据"
            if is_demo
            else "演示环境 · 当前主体连接器已返回签名汇总，节点数据为本地样例"
            if settings.app_env in {"development", "test", "demo"} and metric["status"] == "available"
            else "主体受控汇总 · 当前主体连接器已返回签名汇总"
            if metric["status"] == "available"
            else "主体受控汇总 · 主体连接器未接入，未生成业务指标"
            if metric["status"] == "not_configured"
            else "主体受控汇总 · 主体连接器暂不可用，未生成业务指标"
        ),
    }


@demo_router.post("/query")
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


@demo_router.get("/connector/sample.csv")
def connector_sample(user: User = Depends(require_roles(*BUSINESS_ROLES))) -> Response:
    content = "day,supply_kt,consumption_kt,inventory_kt\n2026-06-01,120,110,5515.6\n2026-06-02,121,112,5524.6\n"
    filename = quote("电煤库存示例.csv")
    return Response(content=content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="energy-sample.csv"; filename*=UTF-8\'\'{filename}'})


@demo_router.post("/connector/{connector}/resources/upload")
def upload_resource(
    connector: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
) -> None:
    raise HTTPException(
        status_code=410,
        detail="中央平台原始文件上传已下线，请在企业连接器本地导入",
    )


@demo_router.get("/policy")
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


@demo_router.post("/policy/rules")
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


@demo_router.delete("/policy/rules")
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
def audit(limit: int = Query(default=20, ge=1, le=200), user: User = Depends(require_roles("REGULATOR")), db: Session = Depends(get_db)) -> dict[str, Any]:
    records = _audit_records(db, limit)
    blocks = db.scalars(select(BlockchainEvidence).order_by(BlockchainEvidence.block_height.desc()).limit(limit)).all()
    ok, message = _chain_state(db)
    counts = {action: sum(1 for item in records if item["action"] == action) for action in ACTION_LABELS}
    return {"records": records, "blocks": [{"id": item.evidence_id, "height": item.block_height, "hash": item.evidence_hash, "tx_hash": item.tx_hash, "status": item.status, "created_at": item.created_at.isoformat()} for item in blocks], "metrics": {"total": len(records), "denied": counts["deny"], "controlled": counts["aggregate"] + counts["compute_only"], "blocks": db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0}, "chain": {"ok": ok, "message": message}, "tamper": _tamper_projection(db)}


@router.post("/audit/verify")
def verify_audit(user: User = Depends(require_roles("REGULATOR")), db: Session = Depends(get_db)) -> dict[str, Any]:
    ok, message = _chain_state(db)
    add_audit_log(db, action="PROTOTYPE_CHAIN_VERIFY", target_type="EVIDENCE_CHAIN", target_id="prototype", result="SUCCESS" if ok else "FAILED", user=user, details={"ok": ok})
    db.commit()
    return {"ok": ok, "message": message, "checked": db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0}


@demo_router.post("/audit/tamper")
def tamper_audit(user: User = Depends(require_roles("REGULATOR")), db: Session = Depends(get_db)) -> dict[str, Any]:
    evidence = db.scalars(select(BlockchainEvidence).order_by(BlockchainEvidence.block_height.desc())).first()
    event = add_audit_log(
        db,
        action="PROTOTYPE_CHAIN_TAMPER",
        target_type="EVIDENCE_CHAIN",
        target_id="prototype",
        result="TAMPERED",
        user=user,
        details={
            "demo": True,
            "prototype_action": "tamper",
            "affected_evidence_id": evidence.evidence_id if evidence else None,
            "affected_block_height": evidence.block_height if evidence else None,
        },
    )
    db.flush()
    db.commit()
    return {
        "ok": True,
        "event_id": event.log_id,
        "affected_block": evidence.block_height if evidence else None,
        "message": "已写入模拟篡改状态，验证链将显示异常",
    }


@demo_router.post("/audit/restore")
def restore_audit(user: User = Depends(require_roles("REGULATOR")), db: Session = Depends(get_db)) -> dict[str, Any]:
    event = add_audit_log(
        db,
        action="PROTOTYPE_CHAIN_RESTORE",
        target_type="EVIDENCE_CHAIN",
        target_id="prototype",
        result="RESTORED",
        user=user,
        details={"demo": True, "prototype_action": "restore"},
    )
    db.flush()
    db.commit()
    return {"ok": True, "event_id": event.log_id, "message": "已恢复模拟状态，请重新验证链"}
