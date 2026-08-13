from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..models import (
    AgentEvent,
    AnomalyEvent,
    AuditReport,
    BlockchainEvidence,
    DataContract,
    DataUpload,
    DidIdentity,
    MetricRecord,
    Organization,
    PrivacyAnalysisJob,
    PrivacyComputeJob,
    SettlementTask,
    User,
)
from ..services.common import model_dict
from ..services.workflow import task_summary


router = APIRouter(tags=["system"])


@router.get("/dashboard/summary")
def dashboard_summary(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    tasks_query = select(SettlementTask).order_by(
        SettlementTask.period_end.desc(), SettlementTask.created_at.desc()
    ).limit(6)
    if user.role_code in {"GENERATOR", "RETAILER"}:
        from ..models import TaskParticipant

        task_ids = list(db.scalars(select(TaskParticipant.task_id).where(TaskParticipant.org_id == user.org_id)).all())
        tasks_query = tasks_query.where(SettlementTask.task_id.in_(task_ids or ["__none__"]))
    recent_tasks = [task_summary(db, item) for item in db.scalars(tasks_query).all()]
    latest_coordination = next(
        (
            item["scenario_coordination"]
            for item in recent_tasks
            if item.get("scenario_coordination")
        ),
        [],
    )
    capabilities = [
        {
            "code": "IDENTITY",
            "name": "主体身份可信",
            "status": "HEALTHY",
            "metric": db.scalar(select(func.count(DidIdentity.did_id)).where(DidIdentity.credential_status == "VALID")) or 0,
            "unit": "个有效DID/VC",
        },
        {
            "code": "DATA",
            "name": "数据流通可信",
            "status": "HEALTHY",
            "metric": db.scalar(select(func.count(DataContract.contract_id)).where(DataContract.status == "ACTIVE")) or 0,
            "unit": "份有效数据合同",
        },
        {
            "code": "RULE",
            "name": "规则授权可信",
            "status": "HEALTHY",
            "metric": db.scalar(select(func.count(SettlementTask.task_id)).where(SettlementTask.status != "DRAFT")) or 0,
            "unit": "笔绑定RuleHash",
        },
        {
            "code": "COMPUTE",
            "name": "协同计算可信",
            "status": "HEALTHY",
            "metric": db.scalar(select(func.count(PrivacyComputeJob.job_id)).where(PrivacyComputeJob.status == "SUCCESS")) or 0,
            "unit": "次成功计算",
        },
        {
            "code": "AUDIT",
            "name": "结果审计可信",
            "status": "HEALTHY",
            "metric": db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0,
            "unit": "项证据索引",
        },
    ]
    role_todos = {
        "GENERATOR": ["核对预测与计量承诺", "查看新能源消纳结算结果"],
        "RETAILER": ["维护虚拟电厂资源池", "运行用电隐私分析"],
        "EXCHANGE": ["组织四场景可信结算", "检查规则与调度安全闸门"],
        "REGULATOR": ["核验四链证据关系", "处置高风险异常"],
        "ADMIN": ["维护DID状态", "检查服务与节点健康"],
    }
    fallback_scenarios = [
        {
            "code": "RENEWABLE_CONSUMPTION",
            "name": "新能源消纳",
            "status": "READY",
            "metric": f"预测资产 {db.scalar(select(func.count(DataUpload.upload_id)).where(DataUpload.asset_type == 'RENEWABLE_FORECAST')) or 0} 份",
            "input": "气象特征、出力预测、计量承诺",
            "output": "消纳风险摘要",
            "next": "市场报价与结算",
        },
        {
            "code": "MARKET_TRADING",
            "name": "电力市场交易",
            "status": "READY",
            "metric": f"可信任务 {db.scalar(select(func.count(SettlementTask.task_id))) or 0} 笔",
            "input": "交易批次、RulePackage、DataPermit",
            "output": "出清/结算计算计划",
            "next": "虚拟电厂偏差响应",
        },
        {
            "code": "VPP_OPERATION",
            "name": "虚拟电厂运营",
            "status": "READY",
            "metric": f"资源池 {db.scalar(select(func.count(DataUpload.upload_id)).where(DataUpload.asset_type == 'VPP_RESOURCE')) or 0} 份",
            "input": "储能与可调负荷承诺",
            "output": "聚合响应能力",
            "next": "电网安全校核",
        },
        {
            "code": "GRID_DISPATCH",
            "name": "电网调度",
            "status": "READY",
            "metric": f"安全边界 {db.scalar(select(func.count(DataUpload.upload_id)).where(DataUpload.asset_type == 'GRID_CONSTRAINT')) or 0} 份",
            "input": "调度边界、剩余交易偏差",
            "output": "安全闸门结论",
            "next": "自动结算与审计",
        },
    ]
    scenario_map = {
        item["code"]: item for item in latest_coordination if item.get("artifact")
    }
    scenario_coordination = [
        {**item, **scenario_map.get(item["code"], {})} for item in fallback_scenarios
    ]
    valid_dids = db.scalar(
        select(func.count(DidIdentity.did_id)).where(DidIdentity.credential_status == "VALID")
    ) or 0
    evidence_count = db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0
    privacy_job_count = (
        (db.scalar(select(func.count(PrivacyComputeJob.job_id))) or 0)
        + (db.scalar(select(func.count(PrivacyAnalysisJob.analysis_id))) or 0)
    )
    agent_event_count = db.scalar(select(func.count(AgentEvent.event_id))) or 0
    four_chain_fusion = [
        {"code": "DID", "name": "DID身份链", "metric": valid_dids, "unit": "个有效凭证", "artifact": "VC + 能力令牌"},
        {"code": "PRIVACY", "name": "隐私计算链", "metric": privacy_job_count, "unit": "个计算回执", "artifact": "DataPermit + ComputeReceipt"},
        {"code": "BLOCKCHAIN", "name": "区块链存证链", "metric": evidence_count, "unit": "项证据索引", "artifact": "证据哈希 + 交易索引"},
        {"code": "AGENT", "name": "智能体协作链", "metric": agent_event_count, "unit": "次签名调用", "artifact": "Agent DID + I/O哈希"},
    ]
    return {
        "kpis": {
            "task_total": db.scalar(select(func.count(SettlementTask.task_id))) or 0,
            "audited_tasks": db.scalar(select(func.count(SettlementTask.task_id)).where(SettlementTask.status == "AUDITED")) or 0,
            "open_anomalies": db.scalar(select(func.count(AnomalyEvent.event_id)).where(AnomalyEvent.status == "OPEN")) or 0,
            "agent_events": db.scalar(select(func.count(AgentEvent.event_id))) or 0,
            "audit_reports": db.scalar(select(func.count(AuditReport.report_id))) or 0,
        },
        "trusted_capabilities": capabilities,
        "recent_tasks": recent_tasks,
        "role_todos": role_todos.get(user.role_code, []),
        "scenario_coordination": scenario_coordination,
        "four_chain_fusion": four_chain_fusion,
        "data_mode": "MVP_DEMO_DATA",
        "security_boundary": "业务数据库不保存企业原始明细；Agent只处理DataRef、RulePackage与证据消息。",
    }


@router.get("/system/organizations")
def organizations(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [model_dict(item) for item in db.scalars(select(Organization).order_by(Organization.org_type)).all()]


@router.get("/system/users")
def users(
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    records = []
    for item in db.scalars(select(User).order_by(User.role_code)).all():
        value = model_dict(item)
        value.pop("password_hash", None)
        records.append(value)
    return records


@router.get("/system/dids")
def dids(
    user: User = Depends(require_roles("REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [model_dict(item) for item in db.scalars(select(DidIdentity).order_by(DidIdentity.owner_type, DidIdentity.owner_id)).all()]


@router.get("/metrics/summary")
def metrics(
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    records = db.scalars(select(MetricRecord).order_by(MetricRecord.recorded_at.desc()).limit(200)).all()
    by_code: dict[str, list[float]] = {}
    for record in records:
        by_code.setdefault(record.metric_code, []).append(record.metric_value)
    def avg(code: str) -> float:
        values = by_code.get(code, [])
        return round(sum(values) / len(values), 2) if values else 0

    verified_count = db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0
    return {
        "compute_cost_ms": avg("MPC_DURATION_MS"),
        "privacy_analysis_ms": avg("PRIVACY_ANALYSIS_MS"),
        "verify_rate": avg("VERIFY_RATE") or 100,
        "agent_event_count": db.scalar(select(func.count(AgentEvent.event_id))) or 0,
        "evidence_count": verified_count,
        "active_data_refs": db.scalar(select(func.count(DataUpload.upload_id)).where(DataUpload.validation_status == "PASSED")) or 0,
        "raw_data_centralized": 0,
        "series": [model_dict(item) for item in records[:30]],
    }
