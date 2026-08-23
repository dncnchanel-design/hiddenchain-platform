from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import public_branding, settings
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
    SettlementRule,
    SettlementTask,
    User,
)
from ..services.common import model_dict
from ..services.prometheus import CONTENT_TYPE_LATEST, render_metrics
from ..services.workflow import task_summary


router = APIRouter(tags=["system"])


@router.get("/public/config")
def public_config() -> dict[str, object]:
    return public_branding(settings)


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
    recent_tasks = [task_summary(db, item, user) for item in db.scalars(tasks_query).all()]
    latest_coordination = next(
        (item["scenario_coordination"] for item in recent_tasks if item.get("scenario_coordination")),
        [],
    )
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
    active_rules = db.scalar(
        select(func.count(SettlementRule.rule_id)).where(SettlementRule.status == "ACTIVE")
    ) or 0
    capabilities = [
        {"code": "IDENTITY", "name": "主体身份记录", "status": "RECORDED" if valid_dids else "NOT_CONFIGURED", "metric": valid_dids, "unit": "个有效凭证"},
        {"code": "DATA", "name": "数据授权协议", "status": "RECORDED" if active_agreements else "NOT_CONFIGURED", "metric": active_agreements, "unit": "份有效协议"},
        {"code": "RULE", "name": "结算规则版本", "status": "RECORDED" if active_rules else "NOT_CONFIGURED", "metric": active_rules, "unit": "个启用版本"},
        {"code": "COMPUTE", "name": "受控计算回执", "status": "RECORDED" if successful_compute_jobs else "NOT_CONFIGURED", "metric": successful_compute_jobs, "unit": "个执行回执"},
        {"code": "AUDIT", "name": "审计证据记录", "status": "RECORDED" if evidence_count else "NOT_CONFIGURED", "metric": evidence_count, "unit": "项证据索引"},
    ]
    encrypted_uploads = sum(
        bool(item.ingress_json.get("encryption")) and "SIMULATION" not in str(item.ingress_json.get("source_type", "")).upper()
        for item in upload_records
    )
    verification_steps = [
        {
            "code": "TRUSTED_ACQUISITION",
            "name": "数据登记",
            "description": "来源信息、格式校验与数据承诺",
            "status": "RECORDED" if upload_total and trusted_uploads == upload_total else "NOT_CONFIGURED",
            "metric": f"{trusted_uploads}/{upload_total} 份数据已登记" if upload_total else "等待数据登记",
        },
        {
            "code": "SECURE_TRANSPORT",
            "name": "传输证明",
            "description": "按每份数据记录的接入与加密信息核对",
            "status": "RECORDED" if encrypted_uploads else "UNVERIFIED",
            "metric": f"{encrypted_uploads}/{upload_total} 份提供加密信息" if upload_total else "未提供传输记录",
        },
        {
            "code": "CONTROLLED_USE",
            "name": "可控使用",
            "description": "去中心化身份标识、数据合同与用途策略",
            "status": "RECORDED" if active_agreements else "NOT_CONFIGURED",
            "metric": f"{active_agreements} 份授权协议" if active_agreements else "等待授权调用",
        },
        {
            "code": "PRIVACY_COMPUTE",
            "name": "受控计算",
            "description": "计算方式与结果披露范围以单笔回执为准",
            "status": "RECORDED" if successful_compute_jobs else "NOT_CONFIGURED",
            "metric": f"{successful_compute_jobs} 个计算回执" if successful_compute_jobs else "等待计算任务",
        },
        {
            "code": "TRACEABLE_AUDIT",
            "name": "可溯审计",
            "description": "算前、算中、算后证据可核验",
            "status": "RECORDED" if evidence_count else "NOT_CONFIGURED",
            "metric": f"{evidence_count} 项可信凭证" if evidence_count else "等待生成凭证",
        },
    ]
    compute_job_count = (
        (db.scalar(select(func.count(PrivacyComputeJob.job_id))) or 0)
        + (db.scalar(select(func.count(PrivacyAnalysisJob.analysis_id))) or 0)
    )
    agent_event_count = db.scalar(select(func.count(AgentEvent.event_id))) or 0
    four_chain_fusion = [
        {"code": "IDENTITY", "name": "身份记录", "metric": valid_dids, "unit": "个有效凭证", "artifact": "主体凭证与签名"},
        {"code": "COMPUTE", "name": "计算记录", "metric": compute_job_count, "unit": "个计算回执", "artifact": "授权结果与计算回执"},
        {"code": "EVIDENCE", "name": "证据台账", "metric": evidence_count, "unit": "项证据索引", "artifact": "证据摘要与顺序索引"},
        {"code": "PROCESS", "name": "过程记录", "metric": agent_event_count, "unit": "次受控调用", "artifact": "输入输出摘要与追踪编号"},
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
        "role_todos": [],
        "scenario_coordination": latest_coordination,
        "verification_steps": verification_steps,
        "latest_verification": recent_tasks[0] if recent_tasks else None,
        "four_chain_fusion": four_chain_fusion,
        "data_mode": settings.app_env.upper(),
        "security_boundary": "业务列表只返回数据引用、摘要与受控结果；原始数据处理边界必须按单笔执行回执核对。",
        "evaluation_note": "跨主体原始数据不出域、隐私协议和外部存证能力不得由汇总数量推断，必须以部署配置和单笔执行证明为准。",
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
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [model_dict(item) for item in db.scalars(select(DidIdentity).order_by(DidIdentity.owner_type, DidIdentity.owner_id)).all()]


@router.get("/metrics/summary")
def metrics(
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "compute_cost_ms": None,
        "privacy_analysis_ms": None,
        "verify_rate": None,
        "agent_event_count": 0,
        "evidence_count": 0,
        "active_data_refs": 0,
        "raw_data_centralized": False,
        "measurement_scope": settings.environment_name or settings.app_env,
        "data_flow_efficiency_pct": 0,
        "api_output_boundary_rate_pct": None,
        "cross_domain_non_export_rate_pct": None,
        "authorized_call_count": 0,
        "authorized_agreement_count": 0,
        "baseline_note": "平台运维仅查看技术运行状态，不展示企业目录、授权、任务、结果或业务审计内容。",
        "series": [],
    }
