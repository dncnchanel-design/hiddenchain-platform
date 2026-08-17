from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import BUSINESS_ROLES, get_current_user, require_roles
from ..models import (
    DataUpload,
    DataSpaceAgreement,
    BlockchainEvidence,
    Organization,
    PrivacyAnalysisJob,
    PrivacyComputeJob,
    SettlementResult,
    SettlementRule,
    SettlementTask,
    Signature,
    TaskParticipant,
    User,
)
from ..schemas import (
    UsageControlCheckRequest,
    PrivacyAnalysisCreate,
    ResultConfirmRequest,
    RuleCreate,
    SettlementTaskCreate,
    WorkflowRunRequest,
)
from ..security import sha256_json, sign_value
from ..services.adapters import (
    AdaptivePrivacyRouter,
    DataSpaceConnectorAdapter,
    LocalEvidenceLedgerAdapter,
    OPAPolicyAdapter,
    PandapowerGridAdapter,
)
from ..services.common import add_audit_log, model_dict
from ..services.datapackage import FrictionlessCatalogAdapter
from ..services.duckdb_connector import DuckDBMetadataAdapter
from ..services.odcs_connector import OpenDataContractAdapter
from ..services.solar import PvlibSolarAdapter
from ..services.workflow import run_privacy_analysis, run_settlement_workflow, task_summary


router = APIRouter(tags=["trade"])


def _task_ids_for_user(db: Session, user: User) -> list[str] | None:
    if user.role_code in {"EXCHANGE", "REGULATOR", "ADMIN"}:
        return None
    return list(
        db.scalars(
            select(TaskParticipant.task_id).where(TaskParticipant.org_id == user.org_id)
        ).all()
    )


def _dataset_ids_for_user(db: Session, user: User) -> set[str] | None:
    """Return the data references visible to a role, or None for trusted roles."""
    if user.role_code in {"EXCHANGE", "REGULATOR", "ADMIN"}:
        return None
    return set(
        db.scalars(
            select(DataUpload.upload_id).where(DataUpload.owner_org_id == user.org_id)
        ).all()
    )


def _compute_job_payload(db: Session, job: PrivacyComputeJob, user: User) -> dict:
    task = db.get(SettlementTask, job.task_id)
    participants = db.scalars(
        select(TaskParticipant).where(TaskParticipant.task_id == job.task_id)
    ).all()
    agreements = db.scalars(
        select(DataSpaceAgreement)
        .where(DataSpaceAgreement.task_id == job.task_id)
        .order_by(DataSpaceAgreement.created_at)
    ).all()
    related_org_ids = {
        *[item.org_id for item in participants],
        *[item.provider_org_id for item in agreements],
        *[item.consumer_org_id for item in agreements],
    }
    org_names = {
        item.org_id: item.org_name
        for item in db.scalars(
            select(Organization).where(Organization.org_id.in_(related_org_ids or {"__none__"}))
        ).all()
    }
    rule = db.get(SettlementRule, task.rule_id) if task else None
    evidence_count = db.scalar(
        select(func.count(BlockchainEvidence.evidence_id)).where(
            BlockchainEvidence.task_id == job.task_id
        )
    ) or 0
    payload = model_dict(job)
    payload.update(
        {
            "task_name": task.task_name if task else None,
            "trade_batch_no": task.trade_batch_no if task else None,
            "participants": [
                {
                    "org_id": item.org_id,
                    "org_name": org_names.get(item.org_id),
                    "role_in_task": item.role_in_task,
                }
                for item in participants
            ],
            "authorization_basis": [
                {
                    "agreement_id": item.agreement_id,
                    "provider_org_id": item.provider_org_id,
                    "provider_org_name": org_names.get(item.provider_org_id),
                    "consumer_org_id": item.consumer_org_id,
                    "consumer_org_name": org_names.get(item.consumer_org_id),
                    "purpose": item.requested_purpose,
                    "state": item.state,
                    "policy_hash": item.negotiated_policy_hash,
                }
                for item in agreements
            ],
            "rule": {
                "rule_id": rule.rule_id,
                "rule_name": rule.rule_name,
                "rule_version": rule.rule_version,
                "rule_hash": rule.rule_hash,
            }
            if rule
            else None,
            "disclosure": {
                "output_mode": (job.privacy_guarantees_json or {}).get("output_mode", "NOT_PROVIDED"),
                "api_raw_records_returned": (job.privacy_guarantees_json or {}).get("api_raw_records_returned"),
                "cross_domain_non_export_verified": (job.privacy_guarantees_json or {}).get("cross_domain_non_export_verified", False),
            },
            "evidence_count": evidence_count,
            "privacy_guarantees": job.privacy_guarantees_json or {},
        }
    )
    if user.role_code in {"GENERATOR", "RETAILER"}:
        payload["result_json"] = {
            "output_hash": job.output_hash,
            "raw_data_exposed": False,
            "status": job.status,
        }
    return payload


@router.get("/data-space/protocol")
def data_space_protocol(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    agreements = db.scalars(select(DataSpaceAgreement)).all()
    if user.role_code in {"GENERATOR", "RETAILER"}:
        agreements = [
            item
            for item in agreements
            if item.provider_org_id == user.org_id or item.consumer_org_id == user.org_id
        ]
    active = [item for item in agreements if item.state in {"NEGOTIATED", "ACTIVE"}]
    consumed = [item for item in agreements if item.state == "CONSUMED"]
    return {
        "protocol_version": DataSpaceConnectorAdapter.protocol_version,
        "connector_code": DataSpaceConnectorAdapter.code,
        "transport_protocols": DataSpaceConnectorAdapter.transport_protocols,
        "connected_layers": DataSpaceConnectorAdapter.connected_layers,
        "capabilities": [
            "CATALOG_DISCOVERY",
            "IDENTITY_VERIFICATION",
            "CONTRACT_NEGOTIATION",
            "USAGE_CONTROL",
            "AGGREGATE_ONLY_OUTPUT",
            "RECEIPT_RECORDING",
        ],
        "three_unified": [
            "UNIFIED_CATALOG_ID",
            "UNIFIED_IDENTITY_REGISTRATION",
            "UNIFIED_INTERFACE_REQUIREMENTS",
        ],
        "agreement_total": len(agreements),
        "active_agreements": len(active),
        "consumed_agreements": len(consumed),
        "negotiated_agreements": sum(item.state == "NEGOTIATED" for item in agreements),
        "cross_domain_non_export_verification": "NOT_PROVIDED",
        "api_raw_records_returned": False,
        "acquisition_rule": "校验通过后登记数据引用",
        "transport_evidence_scope": "按数据登记记录逐项核对，不从协议清单推断",
        "maturity_note": "当前内置本地授权与证据记录；跨域连接、隐私协议和外部存证需由部署适配器及单笔证明确认。",
        "service_adapters": {
            "policy": OPAPolicyAdapter.status(),
            "grid": PandapowerGridAdapter.status(),
            "solar_resource": PvlibSolarAdapter.status(),
            "data_package": FrictionlessCatalogAdapter.status(),
            "metadata_analytics": DuckDBMetadataAdapter.status(),
            "data_contract": OpenDataContractAdapter.status(),
        },
    }


@router.post("/data-space/usage-control/check")
def check_usage_control(
    payload: UsageControlCheckRequest,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    agreement = db.get(DataSpaceAgreement, payload.agreement_id)
    if agreement is None:
        raise HTTPException(status_code=404, detail="数据空间协议不存在")
    decision = DataSpaceConnectorAdapter.enforce(
        db,
        agreement,
        purpose=payload.purpose,
        algorithm_code=payload.algorithm_code,
        execution_environment=payload.execution_environment,
        output_mode=payload.output_mode,
        raw_data_export=payload.raw_data_export,
        consume=False,
    )
    add_audit_log(
        db,
        action="CHECK_DATA_SPACE_USAGE_CONTROL",
        target_type="DATA_SPACE_AGREEMENT",
        target_id=agreement.agreement_id,
        result=decision["decision"],
        user=user,
        details=decision,
    )
    db.commit()
    return decision


@router.get("/rules")
def list_rules(
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [model_dict(item) for item in db.scalars(select(SettlementRule).order_by(SettlementRule.created_at.desc())).all()]


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: RuleCreate,
    user: User = Depends(require_roles("EXCHANGE")),
    db: Session = Depends(get_db),
) -> dict:
    version_no = (db.scalar(select(func.count(SettlementRule.rule_id))) or 0) + 1
    parameters = {
        "contract_price": payload.contract_price,
        "deviation_threshold_mwh": payload.deviation_threshold_mwh,
        "deviation_penalty_rate": payload.deviation_penalty_rate,
        "service_fee_rate": payload.service_fee_rate,
        "rounding": payload.rounding,
    }
    formula = "PAYABLE = MIN(GENERATION, RETAIL) * PRICE - MAX(ABS(GENERATION-RETAIL)-THRESHOLD,0) * PENALTY_RATE - SETTLEMENT_ENERGY * SERVICE_FEE_RATE"
    rule_payload = {"formula": formula, "parameters": parameters, "source_refs": payload.source_refs}
    existing = db.scalar(
        select(SettlementRule)
        .where(SettlementRule.rule_hash == sha256_json(rule_payload))
        .order_by(SettlementRule.created_at.desc())
    )
    if existing:
        return model_dict(existing)
    rule = SettlementRule(
        rule_name=payload.rule_name,
        rule_version=f"SETTLE-2026-{version_no:03d}",
        description=payload.description,
        source_refs_json=payload.source_refs,
        formula_dsl=formula,
        parameters_json=parameters,
        policy_refs_json=["policy:settlement-purpose", "policy:no-raw-data-export"],
        approver_signatures_json=[],
        rule_hash=sha256_json(rule_payload),
        status="DRAFT",
    )
    db.add(rule)
    db.flush()
    add_audit_log(
        db,
        action="CREATE_RULE_PACKAGE",
        target_type="SETTLEMENT_RULE",
        target_id=rule.rule_id,
        result="SUCCESS",
        user=user,
        details={"rule_hash": rule.rule_hash},
    )
    db.commit()
    db.refresh(rule)
    return model_dict(rule)


@router.post("/rules/{rule_id}/activate")
def activate_rule(
    rule_id: str,
    user: User = Depends(require_roles("EXCHANGE")),
    db: Session = Depends(get_db),
) -> dict:
    rule = db.get(SettlementRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    if rule.status == "ACTIVE":
        return model_dict(rule)
    signature = sign_value({"rule_hash": rule.rule_hash, "decision": "ACTIVATE"}, user.user_id)
    rule.approver_signatures_json = rule.approver_signatures_json + [
        {"user_id": user.user_id, "signature": signature}
    ]
    rule.status = "ACTIVE"
    add_audit_log(
        db,
        action="ACTIVATE_RULE_PACKAGE",
        target_type="SETTLEMENT_RULE",
        target_id=rule.rule_id,
        result="SUCCESS",
        user=user,
        details={"rule_hash": rule.rule_hash, "human_gate": "APPROVED"},
    )
    db.commit()
    return model_dict(rule)


@router.get("/settlement/tasks")
def list_tasks(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(SettlementTask).order_by(
        SettlementTask.period_end.desc(), SettlementTask.created_at.desc()
    )
    scoped_ids = _task_ids_for_user(db, user)
    if scoped_ids is not None:
        query = query.where(SettlementTask.task_id.in_(scoped_ids or ["__none__"]))
    return [task_summary(db, item) for item in db.scalars(query).all()]


@router.get("/settlement/tasks/{task_id}")
def get_task(
    task_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    scoped_ids = _task_ids_for_user(db, user)
    if scoped_ids is not None and task_id not in scoped_ids:
        raise HTTPException(status_code=403, detail="无权查看该任务")
    return task_summary(db, task)


@router.post("/settlement/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    payload: SettlementTaskCreate,
    user: User = Depends(require_roles("EXCHANGE")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=400, detail="结算结束日期不能早于开始日期")
    rule = db.get(SettlementRule, payload.rule_id)
    if rule is None or rule.status != "ACTIVE":
        raise HTTPException(status_code=400, detail="只能绑定已启用的规则版本")
    if len(payload.participants) != 2:
        raise HTTPException(status_code=400, detail="当前结算流程必须包含且只能包含两个参与主体")
    participant_keys = {(item.org_id, item.role_in_task) for item in payload.participants}
    if len(participant_keys) != len(payload.participants):
        raise HTTPException(status_code=400, detail="参与主体不能重复")
    roles = {item.role_in_task for item in payload.participants}
    if roles != {"GENERATOR", "RETAILER"}:
        raise HTTPException(status_code=400, detail="结算任务必须包含一个发电企业和一个售电企业")
    organizations = {
        item.org_id: db.get(Organization, item.org_id)
        for item in payload.participants
    }
    if any(item is None for item in organizations.values()):
        raise HTTPException(status_code=400, detail="参与组织不存在")
    for participant in payload.participants:
        organization = organizations[participant.org_id]
        if organization.org_type != participant.role_in_task:
            raise HTTPException(status_code=400, detail="参与组织类型与任务角色不匹配")
    existing = db.scalar(
        select(SettlementTask)
        .where(
            SettlementTask.trade_batch_no == payload.trade_batch_no,
            SettlementTask.task_name == payload.task_name,
            SettlementTask.period_start == payload.period_start,
            SettlementTask.period_end == payload.period_end,
            SettlementTask.creator_org_id == user.org_id,
        )
        .order_by(SettlementTask.created_at.desc())
    )
    if existing:
        return task_summary(db, existing)
    task = SettlementTask(
        capsule_id=(
            f"HC-CAPSULE-{payload.period_start.strftime('%Y%m')}-"
            f"{sha256_json({'task_name': payload.task_name, 'trade_batch_no': payload.trade_batch_no})[:8].upper()}"
        ),
        task_name=payload.task_name,
        trade_batch_no=payload.trade_batch_no,
        period_start=payload.period_start,
        period_end=payload.period_end,
        rule_id=payload.rule_id,
        creator_org_id=user.org_id,
        status="DRAFT",
        current_stage="任务创建",
        verification_profile_json={
            "scenario_code": payload.scenario_code,
            "business_description": payload.business_description,
            "compute_mode": payload.compute_mode,
            "algorithm_code": payload.algorithm_code,
            "output_mode": payload.output_mode,
        },
    )
    db.add(task)
    db.flush()
    for participant in payload.participants:
        db.add(
            TaskParticipant(
                task_id=task.task_id,
                org_id=participant.org_id,
                role_in_task=participant.role_in_task,
                data_status="READY",
                confirm_status="PENDING",
            )
        )
    db.flush()
    readiness = task_summary(db, task)["readiness"]
    if readiness["preflight_passed"]:
        task.status = "READY"
        task.current_stage = "待启动结算"
    add_audit_log(
        db,
        action="CREATE_SETTLEMENT_TASK",
        target_type="SETTLEMENT_TASK",
        target_id=task.task_id,
        result="SUCCESS",
        user=user,
        details={"capsule_id": task.capsule_id, "rule_id": task.rule_id},
    )
    db.commit()
    return task_summary(db, task)


@router.post("/settlement/tasks/{task_id}/run")
def run_task(
    task_id: str,
    payload: WorkflowRunRequest,
    user: User = Depends(require_roles("EXCHANGE")),
    db: Session = Depends(get_db),
) -> dict:
    if settings.app_env == "production" and (
        payload.compute_mode != "LOCAL_CONTROLLED"
        or payload.algorithm_code != "CONTROLLED_SETTLEMENT_V1"
    ):
        raise HTTPException(status_code=400, detail="生产环境只允许已启用的本地受控结算算法")
    try:
        return run_settlement_workflow(
            db,
            task_id=task_id,
            actor=user,
            compute_mode=payload.compute_mode,
            algorithm_code=payload.algorithm_code,
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/privacy/jobs")
def list_compute_jobs(
    task_id: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(PrivacyComputeJob).order_by(PrivacyComputeJob.created_at.desc())
    if task_id:
        query = query.where(PrivacyComputeJob.task_id == task_id)
    scoped_ids = _task_ids_for_user(db, user)
    if scoped_ids is not None:
        query = query.where(PrivacyComputeJob.task_id.in_(scoped_ids or ["__none__"]))
    return [_compute_job_payload(db, item, user) for item in db.scalars(query).all()]


@router.get("/privacy/jobs/{job_id}")
def get_compute_job(
    job_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(PrivacyComputeJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="计算任务不存在")
    scoped_ids = _task_ids_for_user(db, user)
    if scoped_ids is not None and job.task_id not in scoped_ids:
        raise HTTPException(status_code=403, detail="无权查看该计算任务")
    return _compute_job_payload(db, job, user)


@router.get("/settlement/results")
def list_results(
    task_id: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(SettlementResult).order_by(SettlementResult.created_at.desc())
    if task_id:
        query = query.where(SettlementResult.task_id == task_id)
    if user.role_code in {"GENERATOR", "RETAILER"}:
        query = query.where(SettlementResult.org_id == user.org_id)
    return [model_dict(item) for item in db.scalars(query).all()]


@router.post("/results/{result_id}/confirm")
def confirm_result(
    result_id: str,
    payload: ResultConfirmRequest,
    user: User = Depends(require_roles("GENERATOR", "RETAILER")),
    db: Session = Depends(get_db),
) -> dict:
    result = db.get(SettlementResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="结算结果不存在")
    if result.org_id is None:
        raise HTTPException(status_code=400, detail="汇总结果无需主体确认")
    if result.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="只能确认本主体结果")
    existing = db.scalar(
        select(Signature)
        .where(
            Signature.task_id == result.task_id,
            Signature.signer_org_id == user.org_id,
            Signature.target_type == "RESULT_CONFIRM",
            Signature.target_id == result.result_id,
            Signature.target_hash == result.result_hash,
            Signature.verify_status == "VALID",
        )
        .order_by(Signature.created_at.desc())
    )
    if existing:
        task = db.get(SettlementTask, result.task_id)
        return {
            "result_id": result.result_id,
            "confirm_status": result.confirm_status,
            "signature": existing.signature_value,
            "task": task_summary(db, task) if task is not None else None,
        }
    signature_value = sign_value(
        {"result_hash": result.result_hash, "opinion": payload.opinion}, user.user_id
    )
    db.add(
        Signature(
            task_id=result.task_id,
            signer_org_id=user.org_id,
            signer_did=f"did:hiddenchain:org:{user.org_id}",
            target_type="RESULT_CONFIRM",
            target_id=result.result_id,
            target_hash=result.result_hash,
            signature_value=signature_value,
            verify_status="VALID",
        )
    )
    result.confirm_status = "CONFIRMED"
    participant = db.scalar(
        select(TaskParticipant).where(
            TaskParticipant.task_id == result.task_id,
            TaskParticipant.org_id == user.org_id,
        )
    )
    if participant is not None:
        participant.confirm_status = "CONFIRMED"
    db.flush()

    scoped_results = db.scalars(
        select(SettlementResult).where(
            SettlementResult.task_id == result.task_id,
            SettlementResult.result_scope == "ORG",
        )
    ).all()
    confirmed_results = [item for item in scoped_results if item.confirm_status == "CONFIRMED"]
    task = db.get(SettlementTask, result.task_id)
    if task is not None:
        if scoped_results and len(confirmed_results) == len(scoped_results):
            task.status = "AUDITED"
            task.current_stage = "结算完成"
            existing_confirmation_evidence = db.scalar(
                select(BlockchainEvidence).where(
                    BlockchainEvidence.task_id == task.task_id,
                    BlockchainEvidence.biz_type == "RESULT_CONFIRMATION",
                )
            )
            if existing_confirmation_evidence is None:
                signatures = db.scalars(
                    select(Signature).where(
                        Signature.task_id == task.task_id,
                        Signature.target_type == "RESULT_CONFIRM",
                        Signature.verify_status == "VALID",
                    )
                ).all()
                LocalEvidenceLedgerAdapter().anchor(
                    db,
                    task_id=task.task_id,
                    stage="POST_COMPUTE",
                    biz_type="RESULT_CONFIRMATION",
                    biz_id=task.task_id,
                    payload={
                        "task_id": task.task_id,
                        "confirmed_result_ids": [item.result_id for item in confirmed_results],
                        "signature_ids": [item.signature_id for item in signatures],
                        "confirmation_complete": True,
                    },
                )
        else:
            task.status = "PARTIALLY_CONFIRMED"
            task.current_stage = "待主体确认"
    add_audit_log(
        db,
        action="CONFIRM_SETTLEMENT_RESULT",
        target_type="SETTLEMENT_RESULT",
        target_id=result.result_id,
        result="SUCCESS",
        user=user,
        details={"opinion": payload.opinion},
    )
    db.commit()
    return {
        "result_id": result.result_id,
        "confirm_status": result.confirm_status,
        "signature": signature_value,
        "task": task_summary(db, task) if task is not None else None,
    }


@router.get("/privacy/analysis/jobs")
def list_analysis_jobs(
    user: User = Depends(require_roles("RETAILER", "EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    records = db.scalars(select(PrivacyAnalysisJob).order_by(PrivacyAnalysisJob.created_at.desc())).all()
    visible_dataset_ids = _dataset_ids_for_user(db, user)
    if visible_dataset_ids is not None:
        records = [
            item
            for item in records
            if set(item.dataset_ids_json).issubset(visible_dataset_ids)
        ]
    return [
        {
            **model_dict(item),
            "result_json": item.output_json,
            "raw_records_returned": False,
        }
        for item in records
    ]


@router.get("/privacy/strategy/catalog")
def privacy_strategy_catalog(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
) -> list[dict]:
    return AdaptivePrivacyRouter.catalog()


@router.post("/privacy/analysis/jobs", status_code=status.HTTP_201_CREATED)
def create_analysis_job(
    payload: PrivacyAnalysisCreate,
    user: User = Depends(require_roles("RETAILER", "EXCHANGE", "REGULATOR")),
    db: Session = Depends(get_db),
) -> dict:
    datasets = [db.get(DataUpload, item) for item in payload.dataset_ids]
    if any(item is None or item.asset_type != "USER_LOAD_CURVE" for item in datasets):
        raise HTTPException(status_code=400, detail="只能选择用户负荷曲线数据引用")
    if len(set(payload.dataset_ids)) != len(payload.dataset_ids):
        raise HTTPException(status_code=400, detail="数据引用不能重复")
    if user.role_code == "RETAILER" and any(item.owner_org_id != user.org_id for item in datasets if item):
        raise HTTPException(status_code=403, detail="只能分析本主体授权的用户负荷数据")
    strategy = AdaptivePrivacyRouter.recommend(
        payload.scenario_code,
        sensitivity_level=payload.sensitivity_level,
        latency_requirement=payload.latency_requirement,
        participant_count=len(payload.dataset_ids),
    )
    job = PrivacyAnalysisJob(
        analysis_name=payload.analysis_name,
        analysis_type=payload.analysis_type,
        dataset_ids_json=payload.dataset_ids,
        privacy_level=payload.privacy_level,
        privacy_budget=payload.privacy_budget,
        purpose=payload.scenario_code,
        output_json={"recommended_strategy": strategy},
        status="RUNNING",
    )
    db.add(job)
    db.flush()
    try:
        run_privacy_analysis(db, job)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    add_audit_log(
        db,
        action="RUN_PRIVACY_LOAD_ANALYSIS",
        target_type="PRIVACY_ANALYSIS_JOB",
        target_id=job.analysis_id,
        result="SUCCESS",
        user=user,
        details={
            "dataset_count": len(payload.dataset_ids),
            "raw_records_returned": False,
            "scenario_code": payload.scenario_code,
            "compute_plan_hash": strategy["plan_hash"],
        },
    )
    db.commit()
    return {
        **model_dict(job),
        "result_json": job.output_json,
        "raw_records_returned": False,
    }
