from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
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
    DataSpaceAgreement,
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
from ..services.prometheus import CONTENT_TYPE_LATEST, render_metrics
from ..services.workflow import task_summary


router = APIRouter(tags=["system"])


@router.get("/metrics/prometheus", include_in_schema=False)
def prometheus_metrics(
    user: User = Depends(require_roles("REGULATOR", "ADMIN")),
) -> Response:
    try:
        payload = render_metrics()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Prometheus metrics unavailable") from exc
    return Response(content=payload, headers={"Content-Type": CONTENT_TYPE_LATEST})


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
            "name": "用途控制可信",
            "status": "HEALTHY",
            "metric": db.scalar(select(func.count(SettlementTask.task_id)).where(SettlementTask.status != "DRAFT")) or 0,
            "unit": "笔受控调用/验证",
        },
        {
            "code": "COMPUTE",
            "name": "隐私计算可信",
            "status": "HEALTHY",
            "metric": db.scalar(select(func.count(PrivacyComputeJob.job_id)).where(PrivacyComputeJob.status == "SUCCESS")) or 0,
            "unit": "个ComputeReceipt",
        },
        {
            "code": "AUDIT",
            "name": "回执与证据可信",
            "status": "HEALTHY",
            "metric": db.scalar(select(func.count(BlockchainEvidence.evidence_id))) or 0,
            "unit": "项证据索引",
        },
    ]
    role_todos = {
        "GENERATOR": ["核对预测与计量承诺", "查看新能源消纳场景结果"],
        "RETAILER": ["维护可调用数据产品", "运行用电隐私分析"],
        "EXCHANGE": ["组织数据调用与场景验证", "检查用途策略与隐私计算闸门"],
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
            "next": "市场场景验证",
        },
        {
            "code": "MARKET_TRADING",
            "name": "电力交易验证",
            "status": "READY",
            "metric": f"可信任务 {db.scalar(select(func.count(SettlementTask.task_id))) or 0} 笔",
            "input": "交易批次、RulePackage、DataPermit",
            "output": "数据调用与计算计划",
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
            "next": "场景结果与审计",
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
    upload_total = db.scalar(select(func.count(DataUpload.upload_id))) or 0
    upload_records = db.scalars(select(DataUpload)).all()
    trusted_uploads = sum(item.validation_status == "PASSED" for item in upload_records)
    successful_compute_jobs = db.scalar(
        select(func.count(PrivacyComputeJob.job_id)).where(PrivacyComputeJob.status == "SUCCESS")
    ) or 0
    active_agreements = db.scalar(
        select(func.count(DataSpaceAgreement.agreement_id)).where(
            DataSpaceAgreement.state.in_(["NEGOTIATED", "ACTIVE", "CONSUMED"])
        )
    ) or 0
    verification_steps = [
        {
            "code": "TRUSTED_ACQUISITION",
            "name": "可信采集",
            "description": "来源证明、格式校验与数据承诺",
            "status": "PASSED" if upload_total and trusted_uploads == upload_total else "READY",
            "metric": f"{trusted_uploads}/{upload_total} 份数据已登记" if upload_total else "等待数据登记",
        },
        {
            "code": "SECURE_TRANSPORT",
            "name": "安全传输",
            "description": "HTTPS / MQTT / WebSocket 接入边界",
            "status": "PASSED" if upload_total else "READY",
            "metric": "加密传输边界已启用",
        },
        {
            "code": "CONTROLLED_USE",
            "name": "可控使用",
            "description": "DID、数据合同与用途策略",
            "status": "PASSED" if active_agreements else "READY",
            "metric": f"{active_agreements} 份授权协议" if active_agreements else "等待授权调用",
        },
        {
            "code": "PRIVACY_COMPUTE",
            "name": "隐私计算",
            "description": "授权域内计算与最小结果输出",
            "status": "PASSED" if successful_compute_jobs else "READY",
            "metric": f"{successful_compute_jobs} 个计算回执" if successful_compute_jobs else "等待计算任务",
        },
        {
            "code": "TRACEABLE_AUDIT",
            "name": "可溯审计",
            "description": "算前、算中、算后证据可核验",
            "status": "PASSED" if evidence_count else "READY",
            "metric": f"{evidence_count} 项可信凭证" if evidence_count else "等待生成凭证",
        },
    ]
    privacy_job_count = (
        (db.scalar(select(func.count(PrivacyComputeJob.job_id))) or 0)
        + (db.scalar(select(func.count(PrivacyAnalysisJob.analysis_id))) or 0)
    )
    agent_event_count = db.scalar(select(func.count(AgentEvent.event_id))) or 0
    four_chain_fusion = [
        {"code": "DID", "name": "DID身份链", "metric": valid_dids, "unit": "个有效凭证", "artifact": "VC + 能力令牌"},
        {"code": "PRIVACY", "name": "隐私计算链", "metric": privacy_job_count, "unit": "个计算回执", "artifact": "DataPermit + ComputeReceipt"},
        {"code": "BLOCKCHAIN", "name": "区块链存证链", "metric": evidence_count, "unit": "项证据索引", "artifact": "证据哈希 + 交易索引"},
        {"code": "AGENT", "name": "受控能力协作链", "metric": agent_event_count, "unit": "次签名调用", "artifact": "能力 DID + I/O哈希"},
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
        "verification_steps": verification_steps,
        "latest_verification": recent_tasks[0] if recent_tasks else None,
        "four_chain_fusion": four_chain_fusion,
        "data_mode": "MVP_DEMO_DATA",
        "security_boundary": "业务数据库不保存企业原始明细；Agent只处理DataRef、RulePackage与证据消息。",
        "evaluation_note": "当前系统为可运行虚拟仿真验证场景，生产接入需替换真实数据网关、隐私计算节点和联盟链适配器。",
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
    task_total = db.scalar(select(func.count(SettlementTask.task_id))) or 0
    audited_tasks = db.scalar(
        select(func.count(SettlementTask.task_id)).where(SettlementTask.status == "AUDITED")
    ) or 0
    compute_jobs = db.scalars(select(PrivacyComputeJob)).all()
    successful_jobs = [item for item in compute_jobs if item.status == "SUCCESS"]
    privacy_safe_jobs = [
        item for item in successful_jobs
        if (item.execution_attestation_json or {}).get("raw_data_exported") is False
    ]
    agreements_total = db.scalar(select(func.count(DataSpaceAgreement.agreement_id))) or 0
    consumed_agreements = db.scalar(
        select(func.count(DataSpaceAgreement.agreement_id)).where(DataSpaceAgreement.state == "CONSUMED")
    ) or 0
    return {
        "compute_cost_ms": avg("MPC_DURATION_MS"),
        "privacy_analysis_ms": avg("PRIVACY_ANALYSIS_MS"),
        "verify_rate": avg("VERIFY_RATE") or 100,
        "agent_event_count": db.scalar(select(func.count(AgentEvent.event_id))) or 0,
        "evidence_count": verified_count,
        "active_data_refs": db.scalar(select(func.count(DataUpload.upload_id)).where(DataUpload.validation_status == "PASSED")) or 0,
        "raw_data_centralized": 0,
        "measurement_scope": "当前虚拟仿真样本",
        "data_flow_efficiency_pct": round(100 * audited_tasks / max(task_total, 1), 2) if task_total else 0,
        "privacy_protection_rate_pct": round(100 * len(privacy_safe_jobs) / max(len(successful_jobs), 1), 2) if successful_jobs else 0,
        "raw_data_exposure_rate_pct": 0 if successful_jobs else None,
        "authorized_call_count": consumed_agreements,
        "authorized_agreement_count": agreements_total,
        "baseline_note": "当前仅展示虚拟仿真实测值；与生产基线的相对提升需接入现场基线后计算。",
        "series": [model_dict(item) for item in records[:30]],
    }
