from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import BUSINESS_ROLES, get_current_user, require_roles
from ..models import (
    AnomalyEvent,
    AuditReport,
    DataUpload,
    DataSpaceAgreement,
    BlockchainEvidence,
    DidIdentity,
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
from ..services.algorithm_registry import AlgorithmRegistry
from ..services.common import add_audit_log, model_dict
from ..services.datapackage import FrictionlessCatalogAdapter
from ..services.duckdb_connector import DuckDBMetadataAdapter
from ..services.odcs_connector import OpenDataContractAdapter
from ..services.solar import PvlibSolarAdapter
from ..services.workflow import (
    ensure_data_capsule,
    run_privacy_analysis,
    run_settlement_workflow,
    task_summary,
    workflow_bundle,
)
from ..services.trust_domain import (
    TTCState,
    TtcStateMachine,
    TrustDomainError,
    verify_active_identity,
)
from ..services.formal_evidence import (
    EvidenceItemInput,
    process_local_demo_outbox,
    seal_evidence_batch,
)
from ..trust_models import AgentToolCall, ExecutionSnapshot, TtcAttempt


router = APIRouter(tags=["trade"])


def _etag(task: SettlementTask) -> str:
    return f'"{int(task.state_version or 1)}"'


def _required_if_match(if_match: str | None) -> int:
    if not if_match or not if_match.strip():
        raise HTTPException(
            status_code=428,
            detail="必须提供 If-Match 任务状态版本号",
        )
    normalized = if_match.strip()
    if normalized == "*":
        raise HTTPException(
            status_code=412,
            detail="If-Match 不允许使用通配符",
        )
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip()
    normalized = normalized.strip('"')
    try:
        return int(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=412,
            detail="If-Match 必须是任务状态版本号",
        ) from exc


def _assert_if_match(task: SettlementTask, expected: int) -> None:
    if expected != int(task.state_version or 1):
        raise HTTPException(
            status_code=412,
            detail="任务状态版本已变化，请刷新后重试",
            headers={"ETag": _etag(task)},
        )


def _current_attempt_for_task(
    db: Session,
    task: SettlementTask,
) -> TtcAttempt | None:
    attempt_no = int(task.current_attempt or 0)
    if attempt_no < 1:
        return None
    return db.scalar(
        select(TtcAttempt).where(
            TtcAttempt.task_id == task.task_id,
            TtcAttempt.attempt_no == attempt_no,
        )
    )


def _current_settlement_results(
    db: Session,
    task: SettlementTask,
    *,
    lock: bool = False,
) -> tuple[SettlementResult | None, list[SettlementResult]]:
    attempt = _current_attempt_for_task(db, task)
    if attempt is None:
        return None, []
    summary_query = (
        select(SettlementResult)
        .where(
            SettlementResult.task_id == task.task_id,
            SettlementResult.attempt_id == attempt.attempt_id,
            SettlementResult.result_scope == "SUMMARY",
        )
        .order_by(SettlementResult.created_at.desc(), SettlementResult.result_id.desc())
    )
    scoped_query = select(SettlementResult).where(
        SettlementResult.task_id == task.task_id,
        SettlementResult.attempt_id == attempt.attempt_id,
        SettlementResult.result_scope == "ORG",
    )
    if lock:
        summary_query = summary_query.with_for_update()
        scoped_query = scoped_query.with_for_update()
    summary = db.scalar(summary_query)
    if summary is None:
        return None, []
    scoped = [
        item
        for item in db.scalars(scoped_query).all()
        if (item.result_json or {}).get("result_hash_ref") == summary.result_hash
    ]
    return summary, scoped


def _assert_settlement_audit_gate(
    db: Session,
    task: SettlementTask,
) -> tuple[dict, list[Signature]]:
    attempt = _current_attempt_for_task(db, task)
    if attempt is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CURRENT_ATTEMPT_REQUIRED",
                "message": "当前任务缺少可信执行尝试",
            },
        )
    open_anomaly_count = int(
        db.scalar(
            select(func.count(AnomalyEvent.event_id)).where(
                AnomalyEvent.task_id == task.task_id,
                AnomalyEvent.status == "OPEN",
            )
        )
        or 0
    )
    if open_anomaly_count:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "OPEN_ANOMALY_BLOCKS_AUDIT_GATE",
                "message": f"仍有 {open_anomaly_count} 个风险事件待处置",
            },
        )

    report = db.scalar(
        select(AuditReport)
        .where(
            AuditReport.task_id == task.task_id,
            AuditReport.attempt_id == attempt.attempt_id,
        )
        .order_by(AuditReport.created_at.desc(), AuditReport.report_id.desc())
    )
    task_risk_level = str(task.risk_level or "UNKNOWN").upper()
    report_risk_level = str(report.risk_level or "UNKNOWN").upper() if report else None
    risk_level = (
        report_risk_level
        if report_risk_level and report_risk_level != "LOW"
        else task_risk_level
    )
    requires_human_approval = any(
        level != "LOW" for level in (task_risk_level, report_risk_level) if level is not None
    )
    approval_signatures: list[Signature] = []
    if report is not None:
        candidates = db.scalars(
            select(Signature)
            .where(
                Signature.task_id == task.task_id,
                Signature.target_type == "AUDIT_REPORT_APPROVE",
                Signature.target_id == report.report_id,
                Signature.target_hash == report.report_hash,
                Signature.verify_status == "VALID",
            )
            .order_by(Signature.created_at.desc())
        ).all()
        for signature in candidates:
            try:
                verify_active_identity(db, signature.signer_did)
            except TrustDomainError:
                continue
            approval_signatures.append(signature)
    if report is not None and report.status == "REJECTED":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AUDIT_REPORT_REJECTED",
                "message": "最新审计报告已被驳回，必须重新计算并形成新报告",
            },
        )
    if requires_human_approval and (
        report is None or report.status != "APPROVED" or not approval_signatures
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AUDIT_APPROVAL_REQUIRED",
                "message": "中高风险结算必须先由监管方或管理员批准最新审计报告",
            },
        )
    return (
        {
            "decision": "APPROVE" if requires_human_approval else "AUTO_APPROVE_LOW_RISK",
            "risk_level": risk_level,
            "open_anomaly_count": open_anomaly_count,
            "report_id": report.report_id if report else None,
            "report_hash": report.report_hash if report else None,
            "report_status": report.status if report else None,
            "approval_signature_ids": [item.signature_id for item in approval_signatures],
        },
        approval_signatures,
    )


@router.get("/algorithms/registry")
def list_algorithm_registry(
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
) -> list[dict]:
    return AlgorithmRegistry.list()


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


def _record_ttc_run_failure(
    db: Session,
    *,
    task_id: str,
    user: User,
    error: Exception,
) -> None:
    """Persist a failed/rejected Attempt after the business transaction rolls back."""

    task = db.get(SettlementTask, task_id)
    identity = db.scalar(
        select(DidIdentity)
        .where(DidIdentity.owner_id == user.org_id)
        .order_by(DidIdentity.created_at.desc())
    )
    if identity is None or identity.credential_status != "VALID":
        identity = db.get(DidIdentity, "did:hiddenchain:agent:orchestrator")
    if task is None or identity is None or identity.credential_status != "VALID":
        return
    try:
        source = TTCState(task.ttc_state)
    except ValueError:
        return
    if source in {TTCState.FAILED, TTCState.REJECTED}:
        return
    target = (
        TTCState.FAILED
        if TtcStateMachine.can_transition(source, TTCState.FAILED)
        else TTCState.REJECTED
    )
    if not TtcStateMachine.can_transition(source, target):
        return
    TtcStateMachine.transition(
        db,
        task,
        target,
        identity.did_id,
        type(error).__name__.upper(),
        str(error)[:1000] or "Trusted execution failed without an error message",
    )
    task.status = "EXCEPTION" if target == TTCState.FAILED else "REJECTED"
    task.current_stage = "执行失败待重试" if target == TTCState.FAILED else "可信门禁拒绝"
    add_audit_log(
        db,
        action="TRUSTED_SETTLEMENT_ATTEMPT_FAILED",
        target_type="SETTLEMENT_TASK",
        target_id=task.task_id,
        result=target.value,
        user=user,
        details={
            "ttc_state": target.value,
            "error_type": type(error).__name__,
            "retryable": target == TTCState.FAILED,
        },
    )
    db.commit()


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
    return [task_summary(db, item, user) for item in db.scalars(query).all()]


@router.get("/settlement/tasks/{task_id}")
def get_task(
    task_id: str,
    response: Response,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    scoped_ids = _task_ids_for_user(db, user)
    if scoped_ids is not None and task_id not in scoped_ids:
        raise HTTPException(status_code=403, detail="无权查看该任务")
    response.headers["ETag"] = _etag(task)
    return task_summary(db, task, user)


@router.post("/settlement/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    payload: SettlementTaskCreate,
    response: Response,
    user: User = Depends(require_roles("EXCHANGE")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    request_fingerprint = sha256_json(payload.model_dump(mode="json"))
    normalized_idempotency_key = idempotency_key.strip() if idempotency_key else None
    if normalized_idempotency_key is not None:
        if not 8 <= len(normalized_idempotency_key) <= 128:
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key 长度必须为 8 到 128 个字符",
            )
        keyed_task = db.scalar(
            select(SettlementTask).where(
                SettlementTask.request_idempotency_key == normalized_idempotency_key
            )
        )
        if keyed_task is not None:
            if keyed_task.request_fingerprint != request_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key 已用于不同的请求载荷",
                )
            response.headers["Idempotency-Replayed"] = "true"
            response.headers["ETag"] = _etag(keyed_task)
            return task_summary(db, keyed_task, user)
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
        if normalized_idempotency_key:
            if (
                existing.request_fingerprint
                and existing.request_fingerprint != request_fingerprint
            ):
                raise HTTPException(status_code=409, detail="已有任务与请求载荷不一致")
            if existing.request_idempotency_key not in {
                None,
                normalized_idempotency_key,
            }:
                raise HTTPException(status_code=409, detail="已有任务绑定了其他幂等键")
            existing.request_idempotency_key = normalized_idempotency_key
            existing.request_fingerprint = request_fingerprint
            db.commit()
        response.headers["Idempotency-Replayed"] = "true"
        response.headers["ETag"] = _etag(existing)
        return task_summary(db, existing, user)
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
        request_idempotency_key=normalized_idempotency_key,
        request_fingerprint=request_fingerprint,
        ttc_state="INIT",
        current_attempt=0,
        state_version=1,
    )
    db.add(task)
    db.flush()
    ensure_data_capsule(db, task)
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
    readiness = task_summary(db, task, user)["readiness"]
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
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if not normalized_idempotency_key:
            raise
        concurrent = db.scalar(
            select(SettlementTask).where(
                SettlementTask.request_idempotency_key == normalized_idempotency_key
            )
        )
        if concurrent is None or concurrent.request_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key 并发冲突",
            ) from exc
        response.headers["Idempotency-Replayed"] = "true"
        response.headers["ETag"] = _etag(concurrent)
        return task_summary(db, concurrent, user)
    response.headers["ETag"] = _etag(task)
    return task_summary(db, task, user)


@router.post("/settlement/tasks/{task_id}/run")
def run_task(
    task_id: str,
    payload: WorkflowRunRequest,
    response: Response,
    user: User = Depends(require_roles("EXCHANGE")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
) -> dict:
    expected_version = _required_if_match(if_match)
    requested_task = db.scalar(
        select(SettlementTask)
        .where(SettlementTask.task_id == task_id)
        .with_for_update()
    )
    if requested_task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    normalized_idempotency_key = idempotency_key.strip() if idempotency_key else None
    request_fingerprint = sha256_json(payload.model_dump(mode="json"))
    if normalized_idempotency_key is not None:
        if not 8 <= len(normalized_idempotency_key) <= 128:
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key 长度必须为 8 到 128 个字符",
            )
        existing_attempt = db.scalar(
            select(TtcAttempt).where(
                TtcAttempt.request_idempotency_key == normalized_idempotency_key
            )
        )
        if existing_attempt is not None:
            if existing_attempt.task_id != task_id:
                raise HTTPException(status_code=409, detail="Idempotency-Key 已用于其他 TTC")
            if (
                hasattr(existing_attempt, "request_fingerprint")
                and existing_attempt.request_fingerprint
                and existing_attempt.request_fingerprint != request_fingerprint
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key 已用于不同的执行参数",
                )
            existing_task = db.get(SettlementTask, task_id)
            if existing_task is None:
                raise HTTPException(status_code=404, detail="任务不存在")
            if existing_task.status in {
                "PENDING_CONFIRMATION",
                "PARTIALLY_CONFIRMED",
                "AUDITED",
            }:
                response.headers["Idempotency-Replayed"] = "true"
                response.headers["ETag"] = _etag(existing_task)
                return workflow_bundle(db, existing_task, user)
            raise HTTPException(
                status_code=409,
                detail="相同 Idempotency-Key 的 TTC Attempt 尚未成功完成",
                headers={"Retry-After": "2"},
            )
    _assert_if_match(requested_task, expected_version)
    if settings.app_env == "production" and (
        payload.compute_mode != "LOCAL_CONTROLLED"
        or payload.algorithm_code != "CONTROLLED_SETTLEMENT_V1"
    ):
        raise HTTPException(status_code=400, detail="生产环境只允许已启用的本地受控结算算法")
    try:
        workflow_result = run_settlement_workflow(
            db,
            task_id=task_id,
            actor=user,
            compute_mode=payload.compute_mode,
            algorithm_code=payload.algorithm_code,
            request_idempotency_key=normalized_idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        completed_task = db.get(SettlementTask, task_id)
        if completed_task is not None:
            response.headers["ETag"] = _etag(completed_task)
        return workflow_result
    except TrustDomainError as exc:
        db.rollback()
        try:
            _record_ttc_run_failure(db, task_id=task_id, user=user, error=exc)
        except (TrustDomainError, IntegrityError):
            db.rollback()
        code = 403 if exc.code.startswith(("DID_", "AGENT_", "CONTRACT_", "DATA_")) else 409
        raise HTTPException(
            status_code=code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc
    except PermissionError as exc:
        db.rollback()
        try:
            _record_ttc_run_failure(db, task_id=task_id, user=user, error=exc)
        except (TrustDomainError, IntegrityError):
            db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        try:
            _record_ttc_run_failure(db, task_id=task_id, user=user, error=exc)
        except (TrustDomainError, IntegrityError):
            db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        try:
            _record_ttc_run_failure(db, task_id=task_id, user=user, error=exc)
        except (TrustDomainError, IntegrityError):
            db.rollback()
        raise HTTPException(status_code=409, detail="TTC 幂等键并发冲突") from exc
    except Exception as exc:
        db.rollback()
        try:
            _record_ttc_run_failure(db, task_id=task_id, user=user, error=exc)
        except (TrustDomainError, IntegrityError):
            db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "TRUSTED_EXECUTION_FAILED",
                "message": "可信执行失败，已记录失败 Attempt，可复核后重试",
            },
        ) from exc


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
    query = (
        select(SettlementResult)
        .join(SettlementTask, SettlementTask.task_id == SettlementResult.task_id)
        .join(
            TtcAttempt,
            and_(
                TtcAttempt.task_id == SettlementTask.task_id,
                TtcAttempt.attempt_no == SettlementTask.current_attempt,
                TtcAttempt.attempt_id == SettlementResult.attempt_id,
            ),
        )
        .order_by(SettlementResult.created_at.desc())
    )
    if task_id:
        query = query.where(SettlementResult.task_id == task_id)
    if user.role_code in {"GENERATOR", "RETAILER"}:
        query = query.where(SettlementResult.org_id == user.org_id)
    return [model_dict(item) for item in db.scalars(query).all()]


@router.post("/results/{result_id}/confirm")
def confirm_result(
    result_id: str,
    payload: ResultConfirmRequest,
    response: Response,
    user: User = Depends(require_roles("GENERATOR", "RETAILER")),
    db: Session = Depends(get_db),
    if_match: str = Header(alias="If-Match"),
) -> dict:
    expected_version = _required_if_match(if_match)
    result_reference = db.get(SettlementResult, result_id)
    if result_reference is None:
        raise HTTPException(status_code=404, detail="结算结果不存在")
    if result_reference.org_id is None:
        raise HTTPException(status_code=400, detail="汇总结果无需主体确认")
    if result_reference.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="只能确认本主体结果")
    task = db.scalar(
        select(SettlementTask)
        .where(SettlementTask.task_id == result_reference.task_id)
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = db.scalar(
        select(SettlementResult)
        .where(SettlementResult.result_id == result_id)
        .with_for_update()
    )
    if result is None:
        raise HTTPException(status_code=404, detail="结算结果不存在")
    if result.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="只能确认本主体结果")
    current_attempt = _current_attempt_for_task(db, task)
    if current_attempt is None or result.attempt_id != current_attempt.attempt_id:
        raise HTTPException(status_code=409, detail="该结果不属于当前执行尝试")
    actor_identity = db.scalar(
        select(DidIdentity)
        .where(
            DidIdentity.owner_id == user.org_id,
            DidIdentity.org_id == user.org_id,
            DidIdentity.owner_type == "ORG",
        )
        .order_by(DidIdentity.created_at.desc())
    )
    if actor_identity is None:
        raise HTTPException(status_code=403, detail="当前主体缺少有效 DID")
    try:
        verify_active_identity(db, actor_identity.did_id)
    except TrustDomainError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc
    expected_target_type = (
        "RESULT_CONFIRM" if payload.decision == "APPROVE" else "RESULT_REJECT"
    )
    existing = db.scalar(
        select(Signature)
        .where(
            Signature.task_id == result.task_id,
            Signature.signer_org_id == user.org_id,
            Signature.target_type.in_(("RESULT_CONFIRM", "RESULT_REJECT")),
            Signature.target_id == result.result_id,
            Signature.target_hash == result.result_hash,
            Signature.verify_status == "VALID",
        )
        .order_by(Signature.created_at.desc())
    )
    if existing:
        if existing.target_type != expected_target_type:
            raise HTTPException(status_code=409, detail="当前主体已经提交不可变的相反结论")
        response.headers["ETag"] = _etag(task)
        response.headers["Idempotency-Replayed"] = "true"
        return {
            "result_id": result.result_id,
            "decision": payload.decision,
            "confirm_status": result.confirm_status,
            "signature": existing.signature_value,
            "task": task_summary(db, task, user),
            "formal_evidence": {"status": "NOT_READY"},
            "idempotent_replay": True,
        }
    _assert_if_match(task, expected_version)
    if task.status not in {"PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED"}:
        raise HTTPException(status_code=409, detail="任务不在结果确认阶段")
    try:
        current_state = TTCState(task.ttc_state)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="任务 TTC 状态无效") from exc
    if current_state != TTCState.RESULT_CONFIRM:
        raise HTTPException(status_code=409, detail="任务 TTC 状态不允许结果确认")
    summary_result, scoped_results = _current_settlement_results(
        db,
        task,
        lock=True,
    )
    if summary_result is None or result not in scoped_results:
        raise HTTPException(status_code=409, detail="该结果不属于当前执行尝试")
    if result.confirm_status not in {"UNCONFIRMED", "PENDING"}:
        raise HTTPException(status_code=409, detail="当前结果状态不允许提交结论")

    other_results = [item for item in scoped_results if item.result_id != result.result_id]
    will_finalize = bool(scoped_results) and all(
        item.confirm_status == "CONFIRMED" for item in other_results
    )
    audit_gate: dict | None = None
    audit_approval_signatures: list[Signature] = []
    if payload.decision == "APPROVE" and will_finalize:
        audit_gate, audit_approval_signatures = _assert_settlement_audit_gate(db, task)

    signed_decision = {
        "task_id": task.task_id,
        "result_id": result.result_id,
        "result_hash": result.result_hash,
        "decision": payload.decision,
        "opinion": payload.opinion,
    }
    signature_value = sign_value(signed_decision, actor_identity.did_id)
    signature = Signature(
        task_id=result.task_id,
        signer_org_id=user.org_id,
        signer_did=actor_identity.did_id,
        target_type=expected_target_type,
        target_id=result.result_id,
        target_hash=result.result_hash,
        signature_value=signature_value,
        verify_status="VALID",
    )
    db.add(signature)
    participant = db.scalar(
        select(TaskParticipant).where(
            TaskParticipant.task_id == result.task_id,
            TaskParticipant.org_id == user.org_id,
        )
    )
    task.state_version = int(task.state_version or 1) + 1
    if payload.decision == "REJECT":
        result.confirm_status = "REJECTED"
        if participant is not None:
            participant.confirm_status = "REJECTED"
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="结果结论已由并发请求写入") from exc
        decision_evidence = LocalEvidenceLedgerAdapter().anchor(
            db,
            task_id=task.task_id,
            stage="POST_COMPUTE",
            biz_type="RESULT_DECISION",
            biz_id=result.result_id,
            payload={
                "result_hash": result.result_hash,
                "decision": payload.decision,
                "opinion_hash": sha256_json(payload.opinion),
                "signature_id": signature.signature_id,
                "signer_did": actor_identity.did_id,
                "raw_opinion_included": False,
            },
        )
        try:
            TtcStateMachine.transition(
                db,
                task,
                TTCState.REWORK,
                actor_identity.did_id,
                "PARTICIPANT_RESULT_REJECTED",
                payload.opinion,
            )
        except TrustDomainError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
        task.status = "DRAFT"
        task.current_stage = "结果异议待重算"
        add_audit_log(
            db,
            action="REJECT_SETTLEMENT_RESULT",
            target_type="SETTLEMENT_RESULT",
            target_id=result.result_id,
            result="REJECTED",
            user=user,
            details={
                "decision": payload.decision,
                "opinion": payload.opinion,
                "signature_id": signature.signature_id,
                "evidence_id": decision_evidence.evidence_id,
            },
        )
        db.commit()
        response.headers["ETag"] = _etag(task)
        return {
            "result_id": result.result_id,
            "decision": payload.decision,
            "confirm_status": result.confirm_status,
            "signature": signature_value,
            "task": task_summary(db, task, user),
            "formal_evidence": {"status": "NOT_READY"},
            "evidence_id": decision_evidence.evidence_id,
            "idempotent_replay": False,
        }

    result.confirm_status = "CONFIRMED"
    if participant is not None:
        participant.confirm_status = "CONFIRMED"
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        replay = db.scalar(
            select(Signature).where(
                Signature.task_id == result_reference.task_id,
                Signature.signer_org_id == user.org_id,
                Signature.target_type == "RESULT_CONFIRM",
                Signature.target_id == result_id,
                Signature.target_hash == result_reference.result_hash,
                Signature.verify_status == "VALID",
            )
        )
        if replay is None:
            raise HTTPException(status_code=409, detail="结果确认并发冲突")
        replay_result = db.get(SettlementResult, result_id)
        replay_task = db.get(SettlementTask, result_reference.task_id)
        if replay_result is None or replay_task is None:
            raise HTTPException(status_code=409, detail="结果确认重放状态不完整")
        response.headers["ETag"] = _etag(replay_task)
        return {
            "result_id": replay_result.result_id,
            "decision": "APPROVE",
            "confirm_status": replay_result.confirm_status,
            "signature": replay.signature_value,
            "task": task_summary(db, replay_task, user),
            "formal_evidence": {"status": "NOT_READY"},
            "idempotent_replay": True,
        }
    LocalEvidenceLedgerAdapter().anchor(
        db,
        task_id=task.task_id,
        stage="POST_COMPUTE",
        biz_type="RESULT_DECISION",
        biz_id=result.result_id,
        payload={
            "result_hash": result.result_hash,
            "decision": payload.decision,
            "opinion_hash": sha256_json(payload.opinion),
            "signature_id": signature.signature_id,
            "signer_did": actor_identity.did_id,
            "raw_opinion_included": False,
        },
    )
    confirmed_results = [item for item in scoped_results if item.confirm_status == "CONFIRMED"]
    formal_publication: dict = {"status": "NOT_READY"}
    if task is not None:
        if scoped_results and len(confirmed_results) == len(scoped_results):
            if audit_gate is None:
                raise HTTPException(status_code=409, detail="审计门禁结论缺失")
            task.status = "AUDITED"
            task.current_stage = "结算完成"
            signatures = db.scalars(
                select(Signature).where(
                    Signature.task_id == task.task_id,
                    Signature.target_type == "RESULT_CONFIRM",
                    Signature.target_id.in_(
                        [item.result_id for item in confirmed_results]
                    ),
                    Signature.verify_status == "VALID",
                )
            ).all()
            existing_confirmation_evidence = db.scalar(
                select(BlockchainEvidence).where(
                    BlockchainEvidence.task_id == task.task_id,
                    BlockchainEvidence.biz_type == "RESULT_CONFIRMATION",
                    BlockchainEvidence.biz_id == summary_result.result_id,
                )
            )
            if existing_confirmation_evidence is None:
                LocalEvidenceLedgerAdapter().anchor(
                    db,
                    task_id=task.task_id,
                    stage="POST_COMPUTE",
                    biz_type="RESULT_CONFIRMATION",
                    biz_id=summary_result.result_id,
                    payload={
                        "task_id": task.task_id,
                        "confirmed_result_ids": [item.result_id for item in confirmed_results],
                        "signature_ids": [item.signature_id for item in signatures],
                        "decisions": ["APPROVE" for _ in signatures],
                        "audit_gate": audit_gate,
                        "confirmation_complete": True,
                    },
                )
            if TTCState(task.ttc_state) == TTCState.RESULT_CONFIRM:
                TtcStateMachine.transition(
                    db,
                    task,
                    TTCState.AUDIT_GATE,
                    actor_identity.did_id,
                    "MULTIPARTY_CONFIRMATION_COMPLETE",
                    "All scoped settlement results carry active participant DID signatures",
                    agent_did="did:hiddenchain:agent:audit-risk",
                    attempt_id=current_attempt.attempt_id,
                )
                snapshot = (
                    db.get(ExecutionSnapshot, task.execution_snapshot_id)
                    if task.execution_snapshot_id
                    else None
                )
                agreements = db.scalars(
                    select(DataSpaceAgreement).where(
                        DataSpaceAgreement.task_id == task.task_id
                    )
                ).all()
                participant_ids = list(
                    db.scalars(
                        select(TaskParticipant.org_id).where(
                            TaskParticipant.task_id == task.task_id
                        )
                    ).all()
                )
                identity_records = db.scalars(
                    select(DidIdentity).where(DidIdentity.owner_id.in_(participant_ids))
                ).all()
                tool_calls = db.scalars(
                    select(AgentToolCall).where(AgentToolCall.task_id == task.task_id)
                ).all()
                formal_items = [
                    EvidenceItemInput(
                        evidence_type="IDENTITY_VERIFICATION",
                        biz_type="TTC_IDENTITY_GATE",
                        biz_id=task.task_id,
                        body={
                            "identities": [
                                {
                                    "did": item.did_id,
                                    "credential_status": item.credential_status,
                                    "fingerprint": item.public_key_fingerprint,
                                }
                                for item in identity_records
                            ],
                            "raw_credentials_included": False,
                        },
                    ),
                    EvidenceItemInput(
                        evidence_type="RULE_FREEZE",
                        biz_type="EXECUTION_SNAPSHOT",
                        biz_id=snapshot.snapshot_id if snapshot else task.task_id,
                        body={
                            "snapshot_id": snapshot.snapshot_id if snapshot else None,
                            "snapshot_hash": snapshot.snapshot_hash if snapshot else None,
                            "rule_hash": snapshot.rule_hash if snapshot else None,
                            "algorithm_hash": snapshot.algorithm_hash if snapshot else None,
                        },
                    ),
                    EvidenceItemInput(
                        evidence_type="CONTRACT_AGREEMENT_SUMMARY",
                        biz_type="DATA_SPACE_AGREEMENTS",
                        biz_id=task.task_id,
                        body={
                            "agreements": [
                                {
                                    "agreement_id": item.agreement_id,
                                    "state": item.state,
                                    "policy_hash": item.negotiated_policy_hash,
                                }
                                for item in agreements
                            ]
                        },
                    ),
                    EvidenceItemInput(
                        evidence_type="FINAL_RESULT_HASH",
                        biz_type="SETTLEMENT_RESULT",
                        biz_id=summary_result.result_id if summary_result else task.task_id,
                        body={
                            "result_hash": summary_result.result_hash if summary_result else None,
                            "confirmed_result_hashes": [item.result_hash for item in confirmed_results],
                        },
                    ),
                    EvidenceItemInput(
                        evidence_type="CRITICAL_HUMAN_APPROVAL",
                        biz_type="RESULT_CONFIRMATIONS",
                        biz_id=task.task_id,
                        body={
                            "signature_ids": [item.signature_id for item in signatures],
                            "target_hashes": [item.target_hash for item in signatures],
                            "signer_dids": [item.signer_did for item in signatures],
                            "decisions": ["APPROVE" for _ in signatures],
                            "audit_gate": audit_gate,
                            "audit_approval_signature_ids": [
                                item.signature_id for item in audit_approval_signatures
                            ],
                            "signature_values_included": False,
                        },
                    ),
                    EvidenceItemInput(
                        evidence_type="TOOL_LOG",
                        biz_type="AGENT_TOOL_CALLS",
                        biz_id=task.task_id,
                        body={
                            "call_count": len(tool_calls),
                            "call_ids": [item.call_id for item in tool_calls],
                            "input_hashes": [item.input_hash for item in tool_calls],
                            "output_hashes": [item.output_hash for item in tool_calls],
                        },
                    ),
                ]
                batch, outbox = seal_evidence_batch(
                    db,
                    task_id=task.task_id,
                    attempt_id=current_attempt.attempt_id,
                    batch_type="FINAL_SETTLEMENT",
                    sealed_by_did=actor_identity.did_id,
                    items=formal_items,
                )
                TtcStateMachine.transition(
                    db,
                    task,
                    TTCState.EVIDENCE_STAGE,
                    actor_identity.did_id,
                    "AUDIT_GATE_PASSED",
                    "Audit-approved result evidence was sealed into the transactional outbox",
                    agent_did="did:hiddenchain:agent:audit-risk",
                    attempt_id=current_attempt.attempt_id,
                )
                formal_publication = {
                    "status": outbox.status,
                    "batch_id": batch.batch_id,
                    "merkle_root": batch.merkle_root,
                    "outbox_id": outbox.outbox_id,
                    "transactional": True,
                }
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
        details={"decision": payload.decision, "opinion": payload.opinion},
    )
    db.commit()
    if formal_publication.get("outbox_id") and task is not None:
        try:
            processed = process_local_demo_outbox(db, limit=25)
            db.commit()
            own_result = next(
                (
                    item
                    for item in processed
                    if item["outbox_id"] == formal_publication["outbox_id"]
                ),
                None,
            )
            task = db.get(SettlementTask, task.task_id)
            if own_result is None:
                formal_publication["status"] = "PENDING"
            elif own_result["status"] == "PUBLISHED":
                formal_publication.update(
                    {
                        "status": "PUBLISHED_DEMO",
                        "anchor": own_result,
                        "consensus_verified": False,
                    }
                )
            else:
                formal_publication["status"] = own_result["status"]
        except Exception:
            # The confirmation transaction is already durable.  Keep the
            # outbox pending/retryable and never convert an anchor outage into
            # a false business rollback.
            db.rollback()
            formal_publication["status"] = "POST_COMMIT_WORKER_UNAVAILABLE"
    task = db.get(SettlementTask, task.task_id)
    response.headers["ETag"] = _etag(task)
    return {
        "result_id": result.result_id,
        "decision": payload.decision,
        "confirm_status": result.confirm_status,
        "signature": signature_value,
        "task": task_summary(db, task, user),
        "formal_evidence": formal_publication,
        "idempotent_replay": False,
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
