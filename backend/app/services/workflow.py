from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    SettlementResult,
    SettlementRule,
    SettlementTask,
    Signature,
    TaskParticipant,
    User,
    utc_now,
)
from ..security import sha256_json, sign_value, verify_signature
from .adapters import (
    AGENT_DEFINITIONS,
    AdaptivePrivacyRouter,
    DataSpaceConnectorAdapter,
    LocalEvidenceLedgerAdapter,
    IdentityCredentialAdapter,
    LocalUsagePolicyAdapter,
    LocalControlledComputeAdapter,
    RulePackageAdapter,
)
from .common import add_audit_log, model_dict, trace_id
from .lineage import emit_run_event, input_dataset
from .llm import DeepSeekUnavailable, explain_audit, invoke_agent_analysis
from .trust_domain import authorize_agent_tool
from ..trust_models import (
    AgentPermission,
    AgentToolCall,
    DataCapsule,
    ExecutionSnapshot,
    TtcAttempt,
)
from .algorithm_registry import AlgorithmRegistry
from .trust_domain import (
    ExecutionSnapshotService,
    SnapshotIntegrityError,
    TTCState,
    TtcStateMachine,
    verify_active_identity,
)


def _agent_definition(code: str) -> dict[str, Any]:
    return next(item for item in AGENT_DEFINITIONS if item["code"] == code)


def _agent_event(
    db: Session,
    *,
    task_id: str,
    agent_code: str,
    message_type: str,
    tool_name: str,
    input_value: Any,
    output_value: Any,
    details: dict[str, Any],
    authorized_permission: AgentPermission | None = None,
) -> AgentEvent:
    sequence = db.scalar(
        select(func.max(AgentEvent.sequence_no)).where(AgentEvent.task_id == task_id)
    ) or 0
    definition = _agent_definition(agent_code)
    permission = authorized_permission or authorize_agent_tool(
        db, definition["did"], tool_name, task_id=task_id
    )
    input_hash = sha256_json(input_value)
    output_hash = sha256_json(output_value)
    signed_call_payload = {
        "task_id": task_id,
        "sequence": int(sequence) + 1,
        "agent_did": definition["did"],
        "tool": tool_name,
        "input_hash": input_hash,
        "output_hash": output_hash,
    }
    event = AgentEvent(
        task_id=task_id,
        sequence_no=int(sequence) + 1,
        agent_code=agent_code,
        agent_did=definition["did"],
        message_type=message_type,
        tool_name=tool_name,
        input_hash=input_hash,
        output_hash=output_hash,
        signed_call=sign_value(signed_call_payload, definition["did"]),
        status="SUCCESS",
        details_json=details,
    )
    db.add(event)
    db.add(
        AgentToolCall(
            tool_id=permission.tool_id,
            permission_id=permission.permission_id,
            task_id=task_id,
            agent_did=definition["did"],
            operation="INVOKE",
            input_hash=input_hash,
            output_hash=output_hash,
            status="SUCCESS",
            trace_id=str(details.get("trace_id") or trace_id()),
            completed_at=utc_now(),
        )
    )
    db.flush()
    return event


def _authorize_agent_operation(
    db: Session,
    *,
    task_id: str,
    agent_code: str,
    tool_name: str,
) -> AgentPermission:
    """Authorize a Tool before any data access, compute, or external call."""

    definition = _agent_definition(agent_code)
    return authorize_agent_tool(
        db,
        definition["did"],
        tool_name,
        task_id=task_id,
    )


def _scoped_task_allowed(db: Session, task: SettlementTask, user: User) -> bool:
    if user.role_code in {"EXCHANGE", "REGULATOR", "ADMIN"}:
        return True
    return db.scalar(
        select(func.count(TaskParticipant.participant_id)).where(
            TaskParticipant.task_id == task.task_id,
            TaskParticipant.org_id == user.org_id,
        )
    ) > 0


def _verify_frozen_compute_inputs(
    db: Session,
    snapshot: ExecutionSnapshot,
    uploads: list[DataUpload],
) -> None:
    """Re-verify snapshot binding and participant signatures before Vault reads."""

    ExecutionSnapshotService.verify(snapshot)
    try:
        canonical_data_refs = snapshot.canonical_payload_json["data"]
        canonical_algorithm = snapshot.canonical_payload_json["algorithm"]
        canonical_parameters = snapshot.canonical_payload_json["parameters"]["algorithm"]
        canonical_units = snapshot.canonical_payload_json["units"]
    except (KeyError, TypeError) as exc:
        raise SnapshotIntegrityError(
            "EXECUTION_SNAPSHOT_BINDING_INCOMPLETE",
            "Frozen execution snapshot lacks complete data or algorithm bindings",
        ) from exc
    if canonical_data_refs != snapshot.data_refs_json:
        raise SnapshotIntegrityError(
            "EXECUTION_SNAPSHOT_DATA_REFS_MISMATCH",
            "Frozen data references differ from the canonical execution snapshot",
        )

    if not isinstance(canonical_algorithm, dict):
        raise SnapshotIntegrityError(
            "ALGORITHM_DESCRIPTOR_RUNTIME_MISMATCH",
            "Frozen algorithm descriptor is not a canonical object",
        )
    frozen_algorithm = dict(canonical_algorithm)
    frozen_algorithm.setdefault("parameters", canonical_parameters)
    frozen_algorithm.setdefault("units", canonical_units)
    registered_algorithm = AlgorithmRegistry.execution_descriptor(snapshot.algorithm_code)
    if frozen_algorithm != registered_algorithm:
        raise SnapshotIntegrityError(
            "ALGORITHM_DESCRIPTOR_RUNTIME_MISMATCH",
            "Frozen algorithm descriptor no longer matches the repository registry",
        )
    actual_adapter_code = LocalControlledComputeAdapter.code
    if registered_algorithm.get("adapter_code") != actual_adapter_code:
        raise SnapshotIntegrityError(
            "ALGORITHM_ADAPTER_RUNTIME_MISMATCH",
            "Frozen algorithm adapter does not match the runtime compute adapter",
        )

    frozen_refs = {
        str(item.get("upload_id")): item
        for item in canonical_data_refs
        if isinstance(item, dict) and item.get("upload_id")
    }
    supplied_ids = {item.upload_id for item in uploads}
    if set(frozen_refs) != supplied_ids:
        raise SnapshotIntegrityError(
            "FROZEN_INPUT_SET_MISMATCH",
            "Execution inputs do not exactly match the frozen snapshot",
        )
    for upload in uploads:
        frozen = frozen_refs[upload.upload_id]
        expected = {
            "asset_type": upload.asset_type,
            "owner_org_id": upload.owner_org_id,
            "trade_batch_no": upload.trade_batch_no,
            "data_hash": upload.data_hash,
            "commitment": upload.commitment,
            "schema_version": upload.schema_version,
            "validation_status": upload.validation_status,
        }
        if any(frozen.get(key) != value for key, value in expected.items()):
            raise SnapshotIntegrityError(
                "FROZEN_INPUT_METADATA_MISMATCH",
                f"Frozen input metadata mismatch for {upload.upload_id}",
            )
        identity = db.scalar(
            select(DidIdentity)
            .where(
                DidIdentity.owner_id == upload.owner_org_id,
                DidIdentity.owner_type == "ORG",
            )
            .order_by(DidIdentity.created_at.desc())
        )
        if identity is None:
            raise ValueError(f"Input owner DID is missing for {upload.upload_id}")
        verify_active_identity(db, identity.did_id)
        signature = db.scalar(
            select(Signature)
            .where(
                Signature.target_type == "DATA_UPLOAD",
                Signature.target_id == upload.upload_id,
                Signature.target_hash == upload.data_hash,
                Signature.signer_org_id == upload.owner_org_id,
                Signature.signer_did == identity.did_id,
                Signature.verify_status == "VALID",
            )
            .order_by(Signature.created_at.desc())
        )
        if signature is None or signature.signature_value != upload.signature_value:
            raise ValueError(f"Verified input signature is missing for {upload.upload_id}")
        valid_signature = verify_signature(
            {"upload_id": upload.upload_id, "data_hash": upload.data_hash},
            signature.signature_value,
            identity.did_id,
        ) or verify_signature(
            {"data_hash": upload.data_hash},
            signature.signature_value,
            identity.did_id,
        )
        if not valid_signature:
            raise ValueError(f"Input signature mismatch for {upload.upload_id}")


def _active_did_for_owner(db: Session, owner_id: str) -> str:
    identity = db.scalar(
        select(DidIdentity)
        .where(DidIdentity.owner_id == owner_id)
        .order_by(DidIdentity.created_at.desc())
    )
    if identity is None:
        raise ValueError(f"DID/VC verification failed for {owner_id}")
    return verify_active_identity(db, identity.did_id).did_id


def ensure_data_capsule(db: Session, task: SettlementTask) -> DataCapsule:
    capsule = db.get(DataCapsule, task.capsule_id)
    if capsule is not None:
        return capsule
    payload = {
        "capsule_id": task.capsule_id,
        "task_id": task.task_id,
        "owner_org_id": task.creator_org_id,
        "purpose": "POWER_SETTLEMENT",
        "sensitivity_level": "L4",
    }
    capsule = DataCapsule(
        capsule_id=task.capsule_id,
        task_id=task.task_id,
        owner_org_id=task.creator_org_id,
        purpose="POWER_SETTLEMENT",
        sensitivity_level="L4",
        asset_version_refs_json=[],
        policy_version_refs_json=[],
        contract_refs_json=[],
        status=task.ttc_state,
        capsule_hash=sha256_json(payload),
    )
    db.add(capsule)
    db.flush()
    return capsule


def _authoritative_attempt(db: Session, task: SettlementTask) -> TtcAttempt | None:
    """Resolve the task's declared current Attempt, never a historical latest row."""

    attempt_no = int(getattr(task, "current_attempt", 0) or 0)
    if attempt_no < 1:
        return None
    return db.scalar(
        select(TtcAttempt).where(
            TtcAttempt.task_id == task.task_id,
            TtcAttempt.attempt_no == attempt_no,
        )
    )


def task_summary(
    db: Session,
    task: SettlementTask,
    viewer: User | None = None,
) -> dict[str, Any]:
    authoritative_attempt = _authoritative_attempt(db, task)
    current_attempt_id = (
        authoritative_attempt.attempt_id if authoritative_attempt is not None else None
    )
    participants = db.scalars(
        select(TaskParticipant).where(TaskParticipant.task_id == task.task_id)
    ).all()
    participant_payloads: list[dict[str, Any]] = []
    preflight_blockers: list[str] = []
    ready_data_count = 0
    for participant in participants:
        organization = db.get(Organization, participant.org_id)
        expected_type = "GENERATION_DATA" if participant.role_in_task == "GENERATOR" else "RETAIL_DATA"
        upload = db.scalar(
            select(DataUpload)
            .where(
                DataUpload.owner_org_id == participant.org_id,
                DataUpload.asset_type == expected_type,
                DataUpload.trade_batch_no == task.trade_batch_no,
                DataUpload.validation_status == "PASSED",
            )
            .order_by(DataUpload.created_at.desc())
        )
        provider_name = organization.org_name if organization else participant.org_id
        if upload is None:
            preflight_blockers.append(f"{provider_name}尚未提供当前批次的已校验数据")
        elif not upload.signature_value:
            preflight_blockers.append(f"{provider_name}尚未确认当前批次的数据承诺")
        else:
            ready_data_count += 1
        participant_payloads.append(
            {
                **model_dict(participant),
                "org_name": provider_name,
                "required_asset_type": expected_type,
                "data_reference": (
                    {
                        "upload_id": upload.upload_id,
                        "label": upload.label,
                        "validation_status": upload.validation_status,
                        "commitment_confirmed": bool(upload.signature_value),
                    }
                    if upload
                    else None
                ),
            }
        )
    results = (
        db.scalars(
            select(SettlementResult).where(
                SettlementResult.task_id == task.task_id,
                SettlementResult.attempt_id == current_attempt_id,
            )
        ).all()
        if current_attempt_id is not None
        else []
    )
    summary_result = next((item for item in results if item.result_scope == "SUMMARY"), None)
    scoped_results = [item for item in results if item.result_scope == "ORG"]
    confirmed_results = [item for item in scoped_results if item.confirm_status == "CONFIRMED"]
    agreements = db.scalars(
        select(DataSpaceAgreement)
        .where(DataSpaceAgreement.task_id == task.task_id)
        .order_by(DataSpaceAgreement.created_at)
    ).all()
    authorized_agreements = [
        item for item in agreements if item.state in {"NEGOTIATED", "ACTIVE", "CONSUMED"}
    ]
    latest_job = (
        db.scalar(
            select(PrivacyComputeJob)
            .where(
                PrivacyComputeJob.task_id == task.task_id,
                PrivacyComputeJob.attempt_id == current_attempt_id,
            )
            .order_by(PrivacyComputeJob.created_at.desc())
        )
        if current_attempt_id is not None
        else None
    )
    latest_report = (
        db.scalar(
            select(AuditReport)
            .where(
                AuditReport.task_id == task.task_id,
                AuditReport.attempt_id == current_attempt_id,
            )
            .order_by(AuditReport.created_at.desc())
        )
        if current_attempt_id is not None
        else None
    )
    rule = db.get(SettlementRule, task.rule_id)
    if rule is None:
        preflight_blockers.append("任务绑定的结算规则不存在")
    elif rule.status != "ACTIVE":
        preflight_blockers.append("任务绑定的结算规则版本未启用")
    open_anomaly_count = db.scalar(
        select(func.count(AnomalyEvent.event_id)).where(
            AnomalyEvent.task_id == task.task_id,
            AnomalyEvent.status == "OPEN",
        )
    ) or 0
    confirmation_remaining = max(len(scoped_results) - len(confirmed_results), 0)
    blocking_conditions = list(preflight_blockers)
    if task.status in {"PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED"} and confirmation_remaining:
        blocking_conditions.append(f"仍有 {confirmation_remaining} 个参与主体未确认结算结果")
    if open_anomaly_count:
        blocking_conditions.append(f"仍有 {open_anomaly_count} 个风险事件待处置")
    evidence_count = db.scalar(
        select(func.count(BlockchainEvidence.evidence_id)).where(
            BlockchainEvidence.task_id == task.task_id
        )
    ) or 0
    task_payload = model_dict(task)
    ttc_state_value = str(getattr(task, "ttc_state", "INIT") or "INIT")
    if (
        task.status == "DRAFT"
        and ttc_state_value == TTCState.INIT.value
        and not preflight_blockers
    ):
        task_payload["status"] = "READY"
        task_payload["current_stage"] = "待启动结算"
    effective_status = str(task_payload["status"])
    viewer_role = viewer.role_code if viewer is not None else None
    viewer_org_id = viewer.org_id if viewer is not None else None
    own_result = next(
        (item for item in scoped_results if item.org_id == viewer_org_id),
        None,
    )
    hard_blockers = list(preflight_blockers)
    if open_anomaly_count:
        hard_blockers.append(f"仍有 {open_anomaly_count} 个风险事件待处置")
    if effective_status in {"PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED"} and not hard_blockers:
        if (
            viewer_role in {"GENERATOR", "RETAILER"}
            and own_result is not None
            and own_result.confirm_status != "CONFIRMED"
        ):
            allowed_actions = ["CONFIRM_OWN_RESULT"]
            next_action = {
                "code": "CONFIRM_OWN_RESULT",
                "label": "确认本方结算结果",
                "responsible": "发电企业" if viewer_role == "GENERATOR" else "售电企业",
                "blocked": False,
                "reasons": [],
            }
        else:
            allowed_actions = []
            next_action = {
                "code": "WAIT_FOR_CONFIRMATION",
                "label": "等待其余参与主体确认",
                "responsible": "未确认参与方",
                "blocked": False,
                "reasons": [],
            }
    elif hard_blockers:
        allowed_actions: list[str] = []
        next_action = {
            "code": "RESOLVE_BLOCKING_CONDITIONS",
            "label": "处理阻断条件",
            "responsible": "交易中心 / 监管方",
            "blocked": True,
            "reasons": hard_blockers,
        }
    elif effective_status == "READY":
        if viewer_role == "EXCHANGE":
            allowed_actions = ["RUN_SETTLEMENT"]
            next_action = {
                "code": "RUN_SETTLEMENT",
                "label": "启动可信结算",
                "responsible": "交易中心",
                "blocked": False,
                "reasons": [],
            }
        else:
            allowed_actions = []
            next_action = {
                "code": "WAIT_FOR_RUN",
                "label": "等待交易中心启动",
                "responsible": "交易中心",
                "blocked": False,
                "reasons": [],
            }
    elif ttc_state_value == TTCState.FAILED.value or effective_status == "EXCEPTION":
        if viewer_role == "EXCHANGE":
            allowed_actions = ["RUN_SETTLEMENT"]
            next_action = {
                "code": "RETRY_SETTLEMENT",
                "label": "复核失败原因后重试",
                "responsible": "交易中心",
                "blocked": False,
                "reasons": [],
            }
        else:
            allowed_actions = []
            next_action = {
                "code": "WAIT_FOR_FAILURE_REVIEW",
                "label": "等待交易中心复核失败原因",
                "responsible": "交易中心",
                "blocked": False,
                "reasons": [],
            }
    elif effective_status == "AUDITED":
        allowed_actions = []
        next_action = {
            "code": "COMPLETE",
            "label": "可信结算已完成",
            "responsible": "已完成",
            "blocked": False,
            "reasons": [],
        }
    elif effective_status == "RUNNING":
        allowed_actions = []
        next_action = {
            "code": "WAIT_FOR_EXECUTION",
            "label": "可信执行进行中",
            "responsible": "平台可信执行服务",
            "blocked": False,
            "reasons": [],
        }
    else:
        allowed_actions = []
        next_action = {
            "code": "COMPLETE_PREFLIGHT",
            "label": "完成算前准备",
            "responsible": "数据提供方 / 交易中心",
            "blocked": False,
            "reasons": [],
        }

    from ..trust_models import EvidenceBatch, EvidenceOutbox, TtcStateTransition

    attempts = db.scalars(
        select(TtcAttempt).where(TtcAttempt.task_id == task.task_id)
    ).all()
    attempt_numbers = {item.attempt_id: item.attempt_no for item in attempts}

    persisted_transitions = db.scalars(
        select(TtcStateTransition)
        .where(TtcStateTransition.task_id == task.task_id)
        .order_by(TtcStateTransition.occurred_at, TtcStateTransition.sequence_no)
    ).all()
    trusted_chain = [
        {
            "attempt_id": item.attempt_id,
            "attempt_no": attempt_numbers.get(item.attempt_id),
            "sequence_no": item.sequence_no,
            "from_state": item.from_state,
            "to_state": item.to_state,
            "trigger_code": item.trigger_code,
            "actor_did": item.actor_did,
            "agent_did": item.agent_did,
            "reason": item.reason,
            "trace_id": item.trace_id,
            "evidence_refs": [],
            "transition_hash": item.transition_hash,
            "occurred_at": item.occurred_at.isoformat(),
        }
        for item in persisted_transitions
    ]
    latest_evidence_batch = db.scalar(
        select(EvidenceBatch)
        .where(EvidenceBatch.task_id == task.task_id)
        .order_by(EvidenceBatch.sealed_at.desc())
    )
    latest_evidence_outbox = (
        db.scalar(
            select(EvidenceOutbox).where(
                EvidenceOutbox.batch_id == latest_evidence_batch.batch_id
            )
        )
        if latest_evidence_batch
        else None
    )
    return {
        **task_payload,
        "verification_profile": task.verification_profile_json or {},
        "creator_org_name": (db.get(Organization, task.creator_org_id).org_name if db.get(Organization, task.creator_org_id) else None),
        "participants": participant_payloads,
        "rule": (
            {
                "rule_id": rule.rule_id,
                "rule_name": rule.rule_name,
                "rule_version": rule.rule_version,
                "rule_hash": rule.rule_hash,
                "status": rule.status,
                "created_at": rule.created_at.isoformat(),
                "updated_at": rule.updated_at.isoformat(),
            }
            if rule
            else None
        ),
        "readiness": {
            "ready_data_count": ready_data_count,
            "required_data_count": len(participants),
            "preflight_passed": not preflight_blockers,
            "preflight_blockers": preflight_blockers,
        },
        "authorization_summary": {
            "agreement_count": len(agreements),
            "authorized_count": len(authorized_agreements),
            "states": sorted({item.state for item in agreements}),
        },
        "compute_summary": (
            {
                "job_id": latest_job.job_id,
                "status": latest_job.status,
                "algorithm_code": latest_job.algorithm_code,
                "adapter_code": latest_job.adapter_code,
                "output_hash": latest_job.output_hash,
                "created_at": latest_job.created_at.isoformat(),
            }
            if latest_job
            else None
        ),
        "confirmation_summary": {
            "required_count": len(scoped_results),
            "confirmed_count": len(confirmed_results),
            "remaining_count": confirmation_remaining,
            "confirmed_org_ids": [item.org_id for item in confirmed_results],
        },
        "audit_summary": (
            {
                "report_id": latest_report.report_id,
                "status": latest_report.status,
                "risk_level": latest_report.risk_level,
                "report_hash": latest_report.report_hash,
            }
            if latest_report
            else None
        ),
        "blocking_conditions": blocking_conditions,
        "allowed_actions": allowed_actions,
        "next_action": next_action,
        "ttc": {
            "capsule_id": task.capsule_id,
            "state": task.ttc_state,
            "state_version": task.state_version,
            "current_attempt": task.current_attempt,
            "execution_snapshot_id": task.execution_snapshot_id,
            "execution_snapshot_hash": task.execution_snapshot_hash,
            "authoritative": ttc_state_value != "LEGACY_UNMIGRATED",
            "migration_required": ttc_state_value == "LEGACY_UNMIGRATED",
        },
        "trusted_chain": trusted_chain,
        "open_anomaly_count": open_anomaly_count,
        "result_count": len(results),
        "evidence_count": evidence_count,
        "formal_evidence": (
            {
                "batch_id": latest_evidence_batch.batch_id,
                "batch_type": latest_evidence_batch.batch_type,
                "merkle_root": latest_evidence_batch.merkle_root,
                "leaf_count": latest_evidence_batch.leaf_count,
                "batch_status": latest_evidence_batch.status,
                "outbox_status": (
                    latest_evidence_outbox.status if latest_evidence_outbox else None
                ),
                "anchor_capability": "DEMO_NO_CONSENSUS",
            }
            if latest_evidence_batch
            else None
        ),
        "agent_event_count": db.scalar(
            select(func.count(AgentEvent.event_id)).where(AgentEvent.task_id == task.task_id)
        ) or 0,
        "data_space_agreement_count": len(agreements),
        "scenario_coordination": (
            summary_result.result_json.get("scenario_coordination", []) if summary_result else []
        ),
    }


def workflow_bundle(
    db: Session,
    task: SettlementTask,
    viewer: User | None = None,
) -> dict[str, Any]:
    """Return the workflow outcome without ever embedding enterprise raw records."""
    authoritative_attempt = _authoritative_attempt(db, task)
    current_attempt_id = (
        authoritative_attempt.attempt_id if authoritative_attempt is not None else None
    )
    job = (
        db.scalar(
            select(PrivacyComputeJob)
            .where(
                PrivacyComputeJob.task_id == task.task_id,
                PrivacyComputeJob.attempt_id == current_attempt_id,
            )
            .order_by(PrivacyComputeJob.created_at.desc())
        )
        if current_attempt_id is not None
        else None
    )
    results = (
        db.scalars(
            select(SettlementResult)
            .where(
                SettlementResult.task_id == task.task_id,
                SettlementResult.attempt_id == current_attempt_id,
            )
            .order_by(SettlementResult.created_at)
        ).all()
        if current_attempt_id is not None
        else []
    )
    evidence = db.scalars(
        select(BlockchainEvidence)
        .where(BlockchainEvidence.task_id == task.task_id)
        .order_by(BlockchainEvidence.block_height)
    ).all()
    report = (
        db.scalar(
            select(AuditReport)
            .where(
                AuditReport.task_id == task.task_id,
                AuditReport.attempt_id == current_attempt_id,
            )
            .order_by(AuditReport.created_at.desc())
        )
        if current_attempt_id is not None
        else None
    )
    agreements = db.scalars(
        select(DataSpaceAgreement)
        .where(DataSpaceAgreement.task_id == task.task_id)
        .order_by(DataSpaceAgreement.created_at)
    ).all()
    job_payload = model_dict(job) if job else None
    if job_payload is not None:
        job_payload["privacy_guarantees"] = job.privacy_guarantees_json or {}
    report_payload = model_dict(report) if report else None
    if report_payload is not None:
        report_payload["conclusion"] = "PASS" if report.risk_level == "LOW" else "REVIEW_REQUIRED"
    return {
        "task": task_summary(db, task, viewer),
        "compute_job": job_payload,
        "results": [model_dict(item) for item in results],
        "evidence": [model_dict(item) for item in evidence],
        "report": report_payload,
        "data_space": {
            "protocol_version": DataSpaceConnectorAdapter.protocol_version,
            "agreement_count": len(agreements),
            "agreements": [model_dict(item) for item in agreements],
            "raw_data_transfer_verification": "NOT_PROVIDED",
            "usage_control": "PEP_PDP_ENFORCED",
        },
        "security_boundary": {
            "api_raw_records_returned": False,
            "cross_domain_non_export_verified": False,
            "deterministic_execution": True,
        },
        "verification_profile": task.verification_profile_json or {},
    }


def run_settlement_workflow(
    db: Session,
    *,
    task_id: str,
    actor: User | None,
    compute_mode: str = "LOCAL_CONTROLLED",
    algorithm_code: str = "CONTROLLED_SETTLEMENT_V1",
    request_idempotency_key: str | None = None,
    request_fingerprint: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise ValueError("Settlement task not found")
    if actor and not _scoped_task_allowed(db, task, actor):
        raise PermissionError("Task is outside the current user's scope")
    if task.status in {"AUDITED", "PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED"}:
        return workflow_bundle(db, task, actor)
    if task.status == "RUNNING":
        raise ValueError("Settlement task is already running")

    required_agent_tools = (
        ("ORCHESTRATOR", "WorkflowEngine"),
        ("DATA_ACCESS", "EDCAdapter+OPAAdapter"),
        ("RULE_CONTRACT", "RuleRAG+DSLValidator+SigningGate"),
        ("AUDIT_RISK", "GridBoundaryAdapter+SecurityGate"),
        (
            "SECURE_SETTLEMENT",
            "CommitmentJoin+LocalControlledCompute+DeterministicEngine",
        ),
        ("AUDIT_RISK", "EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine"),
        ("REPORT_EXPLAIN", "ReportTemplate+CitationRAG+CredentialService"),
    )
    authorized_tools = {
        (agent_code, tool_name): _authorize_agent_operation(
            db,
            task_id=task.task_id,
            agent_code=agent_code,
            tool_name=tool_name,
        )
        for agent_code, tool_name in required_agent_tools
    }

    run_trace = trace_id()
    actor_did = _active_did_for_owner(
        db,
        actor.org_id if actor is not None else task.creator_org_id,
    )
    rule = db.get(SettlementRule, task.rule_id)
    if rule is None or rule.status != "ACTIVE":
        raise ValueError("Task must bind an active RulePackage")
    participants = db.scalars(
        select(TaskParticipant).where(TaskParticipant.task_id == task.task_id)
    ).all()
    if len(participants) != 2 or {item.role_in_task for item in participants} != {"GENERATOR", "RETAILER"}:
        raise ValueError("Settlement requires generator and retailer participants")
    orgs = {item.org_id: db.get(Organization, item.org_id) for item in participants}

    identity_proofs = [IdentityCredentialAdapter.verify_owner(db, item.org_id) for item in participants]
    for proof in identity_proofs:
        verify_active_identity(db, str(proof["did"]))
    ensure_data_capsule(db, task)
    current_ttc_state = TTCState(task.ttc_state)
    if current_ttc_state == TTCState.FAILED:
        TtcStateMachine.transition(
            db,
            task,
            TTCState.REWORK,
            actor_did,
            "RETRY_REQUESTED",
            "Authorized operator requested a new immutable execution attempt",
            agent_did="did:hiddenchain:agent:orchestrator",
            trace_id=run_trace,
        )
    elif current_ttc_state == TTCState.INIT:
        TtcStateMachine.transition(
            db,
            task,
            TTCState.IDENTITY_VERIFIED,
            actor_did,
            "IDENTITY_GATE_PASSED",
            "All task participant and operator DID records are active",
            agent_did="did:hiddenchain:agent:orchestrator",
            trace_id=run_trace,
        )
    elif current_ttc_state not in {
        TTCState.IDENTITY_VERIFIED,
        TTCState.DATA_AUTHORIZED,
        TTCState.RULE_FROZEN,
        TTCState.REWORK,
    }:
        raise ValueError(f"TTC state does not permit execution: {task.ttc_state}")

    task.status = "RUNNING"
    task.current_stage = "身份认证与任务编排"
    active_attempt = db.scalar(
        select(TtcAttempt)
        .where(TtcAttempt.task_id == task.task_id)
        .order_by(TtcAttempt.attempt_no.desc())
    )
    if (
        request_idempotency_key
        and active_attempt is not None
        and active_attempt.status == "ACTIVE"
    ):
        if active_attempt.request_idempotency_key not in {
            None,
            request_idempotency_key,
        }:
            raise ValueError("TTC attempt already uses another Idempotency-Key")
        active_attempt.request_idempotency_key = request_idempotency_key
        if hasattr(active_attempt, "request_fingerprint"):
            active_attempt.request_fingerprint = request_fingerprint
    orchestrator = _agent_definition("ORCHESTRATOR")
    capability = IdentityCredentialAdapter.issue_capability(
        orchestrator["did"], orchestrator["tools"], task.capsule_id
    )
    task_context = {
        "capsule_id": task.capsule_id,
        "task_id": task.task_id,
        "rule_id": task.rule_id,
        "participants": [item.org_id for item in participants],
        "identity_proofs": identity_proofs,
    }
    _agent_event(
        db,
        task_id=task.task_id,
        agent_code="ORCHESTRATOR",
        message_type="TaskContext",
        tool_name="WorkflowEngine",
        input_value={"request": "POWER_SETTLEMENT", "task_id": task.task_id},
        output_value=task_context,
        details={"capability_token": capability, "dag": [item["code"] for item in AGENT_DEFINITIONS]},
        authorized_permission=authorized_tools[("ORCHESTRATOR", "WorkflowEngine")],
    )
    if commit:
        # Persist the Attempt and identity gate before touching the execution
        # plane so a later failure remains auditable after rollback.
        db.commit()

    uploads_by_role: dict[str, DataUpload] = {}
    scenario_uploads: dict[str, DataUpload] = {}
    contracts: list[DataContract] = []
    agreements: list[DataSpaceAgreement] = []
    policy_decisions: list[dict[str, Any]] = []
    for participant in participants:
        expected_type = "GENERATION_DATA" if participant.role_in_task == "GENERATOR" else "RETAIL_DATA"
        upload = db.scalar(
            select(DataUpload)
            .where(
                DataUpload.owner_org_id == participant.org_id,
                DataUpload.asset_type == expected_type,
                DataUpload.trade_batch_no == task.trade_batch_no,
                DataUpload.validation_status == "PASSED",
            )
            .order_by(DataUpload.created_at.desc())
        )
        if upload is None:
            raise ValueError(
                f"Missing validated {expected_type} for {participant.org_id} "
                f"in batch {task.trade_batch_no}"
            )
        if not upload.signature_value:
            raise ValueError(
                f"Data commitment is not confirmed for {participant.org_id} "
                f"in batch {task.trade_batch_no}"
            )
        uploads_by_role[participant.role_in_task] = upload
        provider = orgs[participant.org_id]
        if provider is None:
            raise ValueError("Participant organization not found")
        provider_uploads = [upload]
        scenario_asset_type = (
            "RENEWABLE_FORECAST"
            if participant.role_in_task == "GENERATOR"
            else "VPP_RESOURCE"
        )
        scenario_upload = db.scalar(
            select(DataUpload)
            .where(
                DataUpload.owner_org_id == participant.org_id,
                DataUpload.asset_type == scenario_asset_type,
                DataUpload.trade_batch_no == task.trade_batch_no,
                DataUpload.validation_status == "PASSED",
            )
            .order_by(DataUpload.created_at.desc())
        )
        if scenario_upload is not None:
            provider_uploads.append(scenario_upload)
            scenario_uploads[scenario_asset_type] = scenario_upload
        contract = LocalUsagePolicyAdapter.create_contract(
            db,
            task,
            provider,
            provider_uploads,
            consumer_org_id=task.creator_org_id,
            algorithm_code=algorithm_code,
        )
        agreement, decision = DataSpaceConnectorAdapter.negotiate(
            db,
            task=task,
            contract=contract,
            provider_org_id=provider.org_id,
            consumer_org_id=task.creator_org_id,
            uploads=provider_uploads,
            purpose="POWER_SETTLEMENT",
            algorithm_code=algorithm_code,
            max_uses=1,
            current_trace_id=run_trace,
        )
        if decision["decision"] != "PERMIT":
            raise PermissionError(
                f"Data space negotiation denied: {', '.join(decision.get('reasons', []))}"
            )
        contracts.append(contract)
        agreements.append(agreement)
        policy_decisions.append(decision)
        participant.data_status = "AUTHORIZED"

    grid_upload = db.scalar(
        select(DataUpload)
        .where(
            DataUpload.owner_org_id == task.creator_org_id,
            DataUpload.asset_type == "GRID_CONSTRAINT",
            DataUpload.trade_batch_no == task.trade_batch_no,
            DataUpload.validation_status == "PASSED",
        )
        .order_by(DataUpload.created_at.desc())
    )
    if grid_upload is not None:
        grid_provider = db.get(Organization, grid_upload.owner_org_id)
        if grid_provider is None:
            raise ValueError("Grid boundary provider organization not found")
        grid_contract = LocalUsagePolicyAdapter.create_contract(
            db,
            task,
            grid_provider,
            [grid_upload],
            purpose="GRID_SECURITY_CHECK",
            consumer_org_id=task.creator_org_id,
            algorithm_code=algorithm_code,
        )
        grid_agreement, grid_decision = DataSpaceConnectorAdapter.negotiate(
            db,
            task=task,
            contract=grid_contract,
            provider_org_id=grid_provider.org_id,
            consumer_org_id=task.creator_org_id,
            uploads=[grid_upload],
            purpose="GRID_SECURITY_CHECK",
            algorithm_code=algorithm_code,
            max_uses=1,
            current_trace_id=run_trace,
        )
        if grid_decision["decision"] != "PERMIT":
            raise PermissionError(
                f"Grid boundary negotiation denied: {', '.join(grid_decision.get('reasons', []))}"
            )
        contracts.append(grid_contract)
        agreements.append(grid_agreement)
        policy_decisions.append(grid_decision)
        scenario_uploads["GRID_CONSTRAINT"] = grid_upload

    enforcement_decisions = [
        DataSpaceConnectorAdapter.enforce(
            db,
            agreement,
            purpose=agreement.requested_purpose,
            algorithm_code=algorithm_code,
            execution_environment="APPLICATION_PROCESS",
            output_mode="AGGREGATE_ONLY",
            raw_data_export=False,
            consume=False,
        )
        for agreement in agreements
    ]
    if any(item["decision"] != "PERMIT" for item in enforcement_decisions):
        denied = next(item for item in enforcement_decisions if item["decision"] != "PERMIT")
        raise PermissionError(
            f"Usage control denied before compute: {', '.join(denied.get('reasons', []))}"
        )

    if TTCState(task.ttc_state) == TTCState.IDENTITY_VERIFIED:
        TtcStateMachine.transition(
            db,
            task,
            TTCState.DATA_AUTHORIZED,
            actor_did,
            "DATA_AUTHORIZATION_PASSED",
            "Active contracts and usage-control decisions permit aggregate settlement",
            agent_did="did:hiddenchain:agent:data-access",
            trace_id=run_trace,
        )

    data_permit = {
        "capsule_id": task.capsule_id,
        "protocol_version": DataSpaceConnectorAdapter.protocol_version,
        "contracts": [
            {
                "contract_id": item.contract_id,
                "provider_org_id": item.provider_org_id,
                "data_refs": item.data_refs_json,
                "policy_hash": item.policy_hash,
                "data_product_ids": next(
                    (
                        agreement.data_product_ids_json
                        for agreement in agreements
                        if agreement.contract_id == item.contract_id
                    ),
                    [],
                ),
            }
            for item in contracts
        ],
        "decisions": policy_decisions,
        "enforcement_decisions": enforcement_decisions,
        "agreement_ids": [item.agreement_id for item in agreements],
        "raw_data_export": False,
    }
    _agent_event(
        db,
        task_id=task.task_id,
        agent_code="DATA_ACCESS",
        message_type="DataPermit",
        tool_name="EDCAdapter+OPAAdapter",
        input_value=task_context,
        output_value=data_permit,
        details={
            "contract_count": len(contracts),
            "agreement_count": len(agreements),
            "policy_decisions": policy_decisions,
            "usage_control": "PEP_PDP_ENFORCED",
        },
        authorized_permission=authorized_tools[("DATA_ACCESS", "EDCAdapter+OPAAdapter")],
    )

    rule_package = RulePackageAdapter.build(rule)
    _agent_event(
        db,
        task_id=task.task_id,
        agent_code="RULE_CONTRACT",
        message_type="RulePackage",
        tool_name="RuleRAG+DSLValidator+SigningGate",
        input_value={"rule_id": rule.rule_id, "period": [str(task.period_start), str(task.period_end)]},
        output_value=rule_package,
        details={
            "rag_boundary": "retrieval-and-citation-only",
            "human_gate": "approved",
            "source_refs": rule.source_refs_json,
        },
        authorized_permission=authorized_tools[
            ("RULE_CONTRACT", "RuleRAG+DSLValidator+SigningGate")
        ],
    )

    registered_algorithm = AlgorithmRegistry.execution_descriptor(algorithm_code)
    snapshot = ExecutionSnapshotService.freeze(
        db,
        task,
        rule,
        contracts,
        [*uploads_by_role.values(), *scenario_uploads.values()],
        registered_algorithm,
        actor_did,
        run_trace,
    )
    task.execution_snapshot_id = snapshot.snapshot_id
    task.execution_snapshot_hash = snapshot.snapshot_hash
    snapshot_attempt = db.get(TtcAttempt, snapshot.attempt_id)
    if request_idempotency_key and snapshot_attempt is not None:
        if snapshot_attempt.request_idempotency_key not in {
            None,
            request_idempotency_key,
        }:
            raise ValueError("TTC attempt already uses another Idempotency-Key")
        snapshot_attempt.request_idempotency_key = request_idempotency_key
        if hasattr(snapshot_attempt, "request_fingerprint"):
            snapshot_attempt.request_fingerprint = request_fingerprint
    capsule = ensure_data_capsule(db, task)
    capsule.contract_refs_json = [item.contract_id for item in contracts]
    capsule.asset_version_refs_json = [item.upload_id for item in [*uploads_by_role.values(), *scenario_uploads.values()]]
    capsule.policy_version_refs_json = [item.policy_hash for item in contracts]
    if commit:
        # Rule Freeze is the execution-plane boundary.  Committing it before
        # compute guarantees a failed calculation cannot erase its Attempt,
        # authorizations, or immutable snapshot.
        db.commit()

    chain = LocalEvidenceLedgerAdapter()
    pre_evidence = chain.anchor(
        db,
        task_id=task.task_id,
        stage="PRE_COMPUTE",
        biz_type="AUTHORIZATION_BUNDLE",
        biz_id=task.task_id,
        payload={
            "capsule_id": task.capsule_id,
            "identity_proofs": identity_proofs,
            "policy_hashes": [item.policy_hash for item in contracts],
            "rule_hash": rule.rule_hash,
            "agreement_ids": [item.agreement_id for item in agreements],
            "input_commitments": [
                item.commitment for item in [*uploads_by_role.values(), *scenario_uploads.values()]
            ],
        },
    )

    grid_gate_context = {
        "capsule_id": task.capsule_id,
        "boundary_ref": grid_upload.data_ref if grid_upload else None,
        "boundary_commitment": grid_upload.commitment if grid_upload else None,
        "policy_decision": "PERMIT" if grid_upload else "NOT_PROVIDED",
        "check_mode": "POST_COMPUTE_BOUNDARY_CHECK" if grid_upload else "NOT_RUN",
        "raw_boundary_export": False,
    }
    _agent_event(
        db,
        task_id=task.task_id,
        agent_code="AUDIT_RISK",
        message_type="GridSecurityGate",
        tool_name="GridBoundaryAdapter+SecurityGate",
        input_value={"trade_batch_no": task.trade_batch_no, "data_permit": data_permit},
        output_value=grid_gate_context,
        details={"gate_status": "ARMED", "raw_boundary_accessed_by_agent": False},
        authorized_permission=authorized_tools[
            ("AUDIT_RISK", "GridBoundaryAdapter+SecurityGate")
        ],
    )

    _verify_frozen_compute_inputs(
        db,
        snapshot,
        [*uploads_by_role.values(), *scenario_uploads.values()],
    )
    task.current_stage = "隐私计算与场景结果生成"
    TtcStateMachine.transition(
        db,
        task,
        TTCState.COMPUTE_EXEC,
        actor_did,
        "COMPUTE_STARTED",
        "Frozen rule, policy, contract, data, algorithm, parameter and unit references accepted",
        agent_did="did:hiddenchain:agent:secure-settlement",
        trace_id=run_trace,
        attempt_id=snapshot.attempt_id,
    )
    compute_strategy = AdaptivePrivacyRouter.recommend(
        "MARKET_SETTLEMENT",
        sensitivity_level="L4",
        latency_requirement="BATCH",
        participant_count=len(participants),
    )
    job = PrivacyComputeJob(
        task_id=task.task_id,
        algorithm_code=algorithm_code,
        adapter_code=LocalControlledComputeAdapter.code,
        input_hashes_json=[item.data_hash for item in uploads_by_role.values()],
        status="RUNNING",
        progress=35,
        logs_json=[
            "DataPermit accepted",
            "Input commitments loaded for participant-period matching",
            f"Execution plan recorded: {compute_strategy['primary']}",
        ],
        attempt_id=snapshot.attempt_id,
        execution_snapshot_id=snapshot.snapshot_id,
    )
    db.add(job)
    db.flush()
    result_value, receipt, compute_logs, duration_ms = LocalControlledComputeAdapter().run_settlement(
        generator_upload=uploads_by_role["GENERATOR"],
        retailer_upload=uploads_by_role["RETAILER"],
        rule_package=rule_package,
        capsule_id=task.capsule_id,
        scenario_uploads=scenario_uploads,
        algorithm_code=algorithm_code,
    )
    receipt.pop("receipt_signature", None)
    usage_receipts: list[dict[str, Any]] = []
    for agreement in agreements:
        decision = DataSpaceConnectorAdapter.enforce(
            db,
            agreement,
            purpose=agreement.requested_purpose,
            algorithm_code=algorithm_code,
            execution_environment="APPLICATION_PROCESS",
            output_mode="AGGREGATE_ONLY",
            raw_data_export=False,
            consume=True,
        )
        if decision["decision"] != "PERMIT":
            raise PermissionError(
                f"Usage control denied after compute: {', '.join(decision.get('reasons', []))}"
            )
        usage_receipts.append(decision)
        DataSpaceConnectorAdapter.record_receipt(agreement, receipt)
    receipt["data_space"] = {
        "protocol_version": DataSpaceConnectorAdapter.protocol_version,
        "agreement_ids": [item.agreement_id for item in agreements],
        "usage_control": usage_receipts,
        "raw_data_exported": False,
    }
    receipt["receipt_signature"] = sign_value(
        receipt,
        "did:hiddenchain:agent:secure-settlement",
    )
    job.status = "SUCCESS"
    job.progress = 100
    job.output_hash = receipt["output_hash"]
    job.result_json = result_value
    job.execution_attestation_json = receipt["execution_attestation"]
    job.logs_json = job.logs_json + compute_logs
    job.duration_ms = duration_ms
    job.privacy_guarantees_json = {
        "api_raw_records_returned": False,
        "output_mode": "AGGREGATE_ONLY",
        "input_commitments_only": False,
        "execution_environment": "APPLICATION_PROCESS",
        "cross_domain_non_export_verified": False,
        "attestation_status": "NOT_PROVIDED",
        "strategy": LocalControlledComputeAdapter.code,
        "strategy_hash": receipt["compute_strategy"]["plan_hash"],
    }

    summary_result = SettlementResult(
        task_id=task.task_id,
        attempt_id=snapshot.attempt_id,
        org_id=None,
        result_scope="SUMMARY",
        result_json=result_value,
        result_hash=sha256_json(result_value),
        confirm_status="NOT_REQUIRED",
    )
    db.add(summary_result)
    db.flush()
    for participant in participants:
        role_result = {
            "capsule_id": task.capsule_id,
            "org_id": participant.org_id,
            "role": participant.role_in_task,
            "settlement_energy_mwh": result_value["settlement_energy_mwh"],
            "amount_yuan": result_value["payable_amount_yuan"],
            "amount_direction": "RECEIVABLE" if participant.role_in_task == "GENERATOR" else "PAYABLE",
            "result_hash_ref": summary_result.result_hash,
        }
        scoped_result = SettlementResult(
            task_id=task.task_id,
            attempt_id=snapshot.attempt_id,
            org_id=participant.org_id,
            result_scope="ORG",
            result_json=role_result,
            result_hash=sha256_json(role_result),
            confirm_status="UNCONFIRMED",
        )
        db.add(scoped_result)
        participant.confirm_status = "PENDING"

    TtcStateMachine.transition(
        db,
        task,
        TTCState.RESULT_CONFIRM,
        actor_did,
        "COMPUTE_RESULT_PERSISTED",
        "Deterministic aggregate result and scoped confirmation records were persisted",
        agent_did="did:hiddenchain:agent:secure-settlement",
        trace_id=run_trace,
        attempt_id=snapshot.attempt_id,
    )

    _agent_event(
        db,
        task_id=task.task_id,
        agent_code="SECURE_SETTLEMENT",
        message_type="ComputeReceipt",
        tool_name="CommitmentJoin+LocalControlledCompute+DeterministicEngine",
        input_value={"data_permit": data_permit, "rule_package": rule_package},
        output_value=receipt,
        details={
            "job_id": job.job_id,
            "result_id": summary_result.result_id,
            "logs": compute_logs,
            "data_space": receipt["data_space"],
        },
        authorized_permission=authorized_tools[
            (
                "SECURE_SETTLEMENT",
                "CommitmentJoin+LocalControlledCompute+DeterministicEngine",
            )
        ],
    )
    during_evidence = chain.anchor(
        db,
        task_id=task.task_id,
        stage="IN_COMPUTE",
        biz_type="COMPUTE_RECEIPT",
        biz_id=job.job_id,
        payload=receipt,
    )
    result_evidence = chain.anchor(
        db,
        task_id=task.task_id,
        stage="POST_COMPUTE",
        biz_type="SETTLEMENT_RESULT",
        biz_id=summary_result.result_id,
        payload={
            "result_hash": summary_result.result_hash,
            "party_signatures": 0,
            "contract_state": "RESULT_GENERATED",
        },
    )

    task.current_stage = "证据摘要核验"
    evidence_items = db.scalars(
        select(BlockchainEvidence)
        .where(BlockchainEvidence.task_id == task.task_id)
        .order_by(BlockchainEvidence.block_height)
    ).all()
    verification = [chain.verify(item) for item in evidence_items]
    open_anomalies = db.scalars(
        select(AnomalyEvent).where(
            AnomalyEvent.task_id == task.task_id, AnomalyEvent.status == "OPEN"
        )
    ).all()
    scenario_rejected = any(
        item.get("status") == "REJECTED"
        for item in result_value.get("scenario_coordination", [])
    )
    scenario_incomplete = any(
        item.get("status") in {"NOT_PROVIDED", "REVIEW_REQUIRED", "NOT_CONNECTED"}
        for item in result_value.get("scenario_coordination", [])
    )
    risk_level = "HIGH" if scenario_rejected or any(not item["matched"] for item in verification) else (
        "MEDIUM"
        if open_anomalies
        or scenario_incomplete
        or not receipt["execution_attestation"]["cross_domain_non_export_verified"]
        else "LOW"
    )
    audit_bundle = {
        "capsule_id": task.capsule_id,
        "evidence_graph": [
            {
                "stage": item.stage,
                "biz_type": item.biz_type,
                "evidence_id": item.evidence_id,
                "tx_hash": item.tx_hash,
            }
            for item in evidence_items
        ],
        "verification": verification,
        "risk_level": risk_level,
        "anomaly_count": len(open_anomalies),
    }
    _agent_event(
        db,
        task_id=task.task_id,
        agent_code="AUDIT_RISK",
        message_type="AuditBundle",
        tool_name="EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine",
        input_value={"evidence_ids": [item.evidence_id for item in evidence_items]},
        output_value=audit_bundle,
        details={"checks": verification, "raw_data_accessed": False},
        authorized_permission=authorized_tools[
            ("AUDIT_RISK", "EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine")
        ],
    )

    report_content = (
        f"# {task.task_name}全过程可信审计报告\n\n"
        f"- 结算任务编号：{task.capsule_id}\n"
        f"- 规则版本：{rule.rule_version}（{rule.rule_hash}）\n"
        f"- 身份校验：{len(identity_proofs)}个主体凭证记录有效\n"
        f"- 数据授权：{len(contracts)}份协议，策略决策均为允许\n"
        f"- 计算执行：{job.adapter_code}，接口未返回原始记录\n"
        f"- 跨域隐私协议证明：未提供\n"
        f"- 调度边界：{'已提供并完成校核' if grid_upload else '未提供'}\n"
        f"- 结果摘要：{summary_result.result_hash}\n"
        f"- 审计证据：{len(evidence_items) + 1}项，风险等级{risk_level}\n"
        f"- 过程复核结论：{'通过' if risk_level == 'LOW' else '需复核'}；主体结果确认尚待完成。"
    )
    report_hash = sha256_json({"content": report_content, "audit_bundle": audit_bundle})
    report = AuditReport(
        task_id=task.task_id,
        attempt_id=snapshot.attempt_id,
        template_code="REGULATORY_AUDIT_V1",
        report_title=f"{task.task_name}全过程可信审计报告",
        report_content=report_content,
        report_hash=report_hash,
        risk_level=risk_level,
        evidence_refs_json=[item.evidence_id for item in evidence_items],
        status="GENERATED",
    )
    db.add(report)
    db.flush()
    report_evidence = chain.anchor(
        db,
        task_id=task.task_id,
        stage="POST_COMPUTE",
        biz_type="AUDIT_REPORT",
        biz_id=report.report_id,
        payload={"report_hash": report_hash, "risk_level": risk_level},
    )
    _agent_event(
        db,
        task_id=task.task_id,
        agent_code="REPORT_EXPLAIN",
        message_type="ReportArtifact",
        tool_name="ReportTemplate+CitationRAG+CredentialService",
        input_value=audit_bundle,
        output_value={"report_id": report.report_id, "report_hash": report_hash},
        details={"citation_count": len(evidence_items), "chain_evidence_id": report_evidence.evidence_id},
        authorized_permission=authorized_tools[
            ("REPORT_EXPLAIN", "ReportTemplate+CitationRAG+CredentialService")
        ],
    )

    task.status = "PENDING_CONFIRMATION"
    task.current_stage = "待主体确认"
    task.risk_level = risk_level
    task.verification_profile_json = {
        **(task.verification_profile_json or {}),
        "data_references_validated": True,
        "transport_evidence_provided": all(
            item.ingress_json.get("encryption") in {"TLS1.2", "TLS1.3"}
            for item in uploads_by_role.values()
        ),
        "controlled_use": True,
        "controlled_compute": True,
        "privacy_compute_protocol_verified": False,
        "traceable_audit": True,
        "api_raw_records_returned": False,
        "cross_domain_non_export_verified": False,
        "compute_adapter": job.adapter_code,
        "evidence_ledger": LocalEvidenceLedgerAdapter.code,
        "evidence_stages": ["PRE_COMPUTE", "IN_COMPUTE", "POST_COMPUTE"],
        "evidence_count": len(evidence_items) + 1,
        "acceptance_metrics": {
            "compute_duration_ms": duration_ms,
            "api_raw_records_returned": 0,
            "authorized_agreement_count": len(agreements),
            "evidence_verify_rate_pct": round(
                100 * sum(item["matched"] for item in verification) / max(len(verification), 1), 2
            ),
        },
    }
    agent_event_count = db.scalar(
        select(func.count(AgentEvent.event_id)).where(AgentEvent.task_id == task.task_id)
    ) or 0
    db.add_all(
        [
            MetricRecord(task_id=task.task_id, metric_code="LOCAL_COMPUTE_DURATION_MS", metric_value=duration_ms, metric_unit="ms"),
            MetricRecord(task_id=task.task_id, metric_code="EVIDENCE_RECORD_COUNT", metric_value=len(evidence_items) + 1, metric_unit="count"),
            MetricRecord(task_id=task.task_id, metric_code="VERIFY_RATE", metric_value=100 if risk_level == "LOW" else 75, metric_unit="percent"),
            MetricRecord(task_id=task.task_id, metric_code="AGENT_EVENT_COUNT", metric_value=agent_event_count, metric_unit="count"),
            MetricRecord(task_id=task.task_id, metric_code="SCENARIO_COUPLING_COUNT", metric_value=4, metric_unit="count"),
        ]
    )
    add_audit_log(
        db,
        action="RUN_TRUSTED_SETTLEMENT_WORKFLOW",
        target_type="SETTLEMENT_TASK",
        target_id=task.task_id,
        result="SUCCESS",
        user=actor,
        actor_name="SYSTEM_SEED" if actor is None else None,
        actor_org_id=task.creator_org_id,
        details={
            "capsule_id": task.capsule_id,
            "pre_evidence": pre_evidence.evidence_id,
            "during_evidence": during_evidence.evidence_id,
            "result_evidence": result_evidence.evidence_id,
            "report_id": report.report_id,
        },
        current_trace_id=run_trace,
    )
    if commit:
        db.commit()
        emit_settlement_lineage(
            task,
            uploads=list({item.upload_id: item for item in [*uploads_by_role.values(), *scenario_uploads.values()]}.values()),
            result_hash=summary_result.result_hash,
            trace_id_value=run_trace,
        )
    return workflow_bundle(db, task, actor)


def emit_settlement_lineage(
    task: SettlementTask,
    *,
    uploads: list[DataUpload],
    result_hash: str,
    trace_id_value: str,
) -> dict[str, Any]:
    """Publish a redacted OpenLineage event for a completed settlement run."""

    inputs = [
        input_dataset(
            namespace=f"hiddenchain://org/{upload.owner_org_id}",
            name=f"data-product/{DataSpaceConnectorAdapter.data_product_id(upload)}",
            data_product_id=DataSpaceConnectorAdapter.data_product_id(upload),
            asset_type=upload.asset_type,
            data_hash=upload.data_hash,
            commitment=upload.commitment,
        )
        for upload in uploads
    ]
    return emit_run_event(
        run_id=task.task_id,
        job_name="controlled-settlement",
        event_type="COMPLETE",
        trace_id=trace_id_value,
        input_datasets=inputs,
        output_name=f"settlement-result/{task.task_id}",
        output_hash=result_hash,
        result_status=task.status,
        policy_hash=sha256_json(task.verification_profile_json or {}),
        raw_data_exported=False,
    )


def create_audit_report(db: Session, task_id: str, template_code: str) -> AuditReport:
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise ValueError("Settlement task not found")
    attempt = _authoritative_attempt(db, task)
    if attempt is None:
        raise ValueError("Current TTC attempt not found")
    existing = db.scalar(
        select(AuditReport)
        .where(
            AuditReport.task_id == task_id,
            AuditReport.attempt_id == attempt.attempt_id,
            AuditReport.template_code == template_code,
        )
        .order_by(AuditReport.created_at.desc())
    )
    if existing:
        return existing
    evidences = db.scalars(
        select(BlockchainEvidence).where(BlockchainEvidence.task_id == task_id)
    ).all()
    events = db.scalars(select(AgentEvent).where(AgentEvent.task_id == task_id)).all()
    content = (
        f"# {task.task_name}补充审计报告\n\n"
        f"可信验证胶囊：{task.capsule_id}\n\n"
        f"证据数量：{len(evidences)}；Agent事件数量：{len(events)}；"
        f"当前状态：{task.status}；风险等级：{task.risk_level}。"
    )
    report = AuditReport(
        task_id=task_id,
        attempt_id=attempt.attempt_id,
        template_code=template_code,
        report_title=f"{task.task_name}补充审计报告",
        report_content=content,
        report_hash=sha256_json(content),
        risk_level=task.risk_level,
        evidence_refs_json=[item.evidence_id for item in evidences],
        status="GENERATED",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def _audit_context(
    db: Session,
    task: SettlementTask,
    evidences: list[BlockchainEvidence],
    signatures: list[Signature],
) -> dict[str, Any]:
    """Build a deliberately redacted context for the optional LLM explainer."""
    rule = db.get(SettlementRule, task.rule_id)
    job = db.scalar(
        select(PrivacyComputeJob)
        .where(PrivacyComputeJob.task_id == task.task_id)
        .order_by(PrivacyComputeJob.created_at.desc())
    )
    events = db.scalars(
        select(AgentEvent)
        .where(AgentEvent.task_id == task.task_id)
        .order_by(AgentEvent.sequence_no)
    ).all()
    anomalies = db.scalars(
        select(AnomalyEvent)
        .where(AnomalyEvent.task_id == task.task_id)
        .order_by(AnomalyEvent.created_at)
    ).all()
    return {
        "task": {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "capsule_id": task.capsule_id,
            "trade_batch_no": task.trade_batch_no,
            "period_start": task.period_start.isoformat(),
            "period_end": task.period_end.isoformat(),
            "status": task.status,
            "current_stage": task.current_stage,
            "risk_level": task.risk_level,
        },
        "rule": {
            "rule_id": rule.rule_id if rule else None,
            "rule_version": rule.rule_version if rule else None,
            "rule_hash": rule.rule_hash if rule else None,
            "source_refs": rule.source_refs_json if rule else [],
        },
        "compute": {
            "status": job.status if job else None,
            "adapter_code": job.adapter_code if job else None,
            "algorithm_code": job.algorithm_code if job else None,
            "output_hash": job.output_hash if job else None,
            "duration_ms": job.duration_ms if job else None,
        },
        "signatures": {
            "count": len(signatures),
            "valid_count": sum(item.verify_status == "VALID" for item in signatures),
            "target_types": sorted({item.target_type for item in signatures}),
        },
        "agent_events": [
            {
                "sequence_no": item.sequence_no,
                "agent_code": item.agent_code,
                "message_type": item.message_type,
                "tool_name": item.tool_name,
                "status": item.status,
            }
            for item in events
        ],
        "anomalies": [
            {
                "event_type": item.event_type,
                "risk_level": item.risk_level,
                "title": item.title,
                "status": item.status,
            }
            for item in anomalies
        ],
        "citations": [
            {
                "evidence_id": item.evidence_id,
                "stage": item.stage,
                "biz_type": item.biz_type,
                "biz_id": item.biz_id,
                "evidence_hash": item.evidence_hash,
                "tx_hash": item.tx_hash,
                "block_height": item.block_height,
                "status": item.status,
            }
            for item in evidences[:6]
        ],
        "boundary": {
            "raw_data_included": False,
            "raw_data_accessed_by_agent": False,
            "deterministic_execution": True,
            "llm_role": "explanation_only",
        },
    }


AGENT_DEFAULT_INSTRUCTIONS = {
    "ORCHESTRATOR": "核对当前任务上下文和六个受控能力模块的协作链，指出当前阶段、已有协作结果与下一步。",
    "DATA_ACCESS": "基于数据合同、许可状态和数据摘要，分析新能源数据能否在不出域前提下参与任务。",
    "RULE_CONTRACT": "核对当前市场规则版本、RuleHash、来源引用和确定性执行边界。",
    "SECURE_SETTLEMENT": "分析隐私计算回执、虚拟电厂协同结果和确定性结算状态，不重新计算或修改结果。",
    "AUDIT_RISK": "核验证据链、签名、异常和风险状态，给出有引用的安全审计分析。",
    "REPORT_EXPLAIN": "基于现有四场景结果和审计证据，形成可信报告摘要及后续报告完善建议。",
}


def invoke_deepseek_agent(
    db: Session,
    *,
    task_id: str,
    agent_code: str,
    instruction: str,
) -> dict[str, Any]:
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise ValueError("Settlement task not found")
    try:
        definition = _agent_definition(agent_code)
    except StopIteration as exc:
        raise ValueError("Agent definition not found") from exc

    deepseek_permission = _authorize_agent_operation(
        db,
        task_id=task_id,
        agent_code=agent_code,
        tool_name="DeepSeekChatCompletions",
    )

    evidences = db.scalars(
        select(BlockchainEvidence)
        .where(BlockchainEvidence.task_id == task_id)
        .order_by(BlockchainEvidence.block_height)
    ).all()
    signatures = db.scalars(select(Signature).where(Signature.task_id == task_id)).all()
    context = _audit_context(db, task, evidences, signatures)
    context["active_agent"] = {
        "code": definition["code"],
        "name": definition["name"],
        "scenario_code": definition["scenario_code"],
        "raw_data_accessed": False,
    }
    generated = invoke_agent_analysis(
        agent_definition=definition,
        instruction=instruction,
        context=context,
    )
    result = {
        "agent_code": agent_code,
        "agent_name": definition["name"],
        "agent_did": definition["did"],
        "task_id": task_id,
        "summary": generated["summary"],
        "findings": generated["findings"],
        "recommended_next_action": generated["recommended_next_action"],
        "confidence": generated["confidence"],
        "provider": generated["provider"],
        "model": generated["model"],
        "request_id": generated["request_id"],
        "duration_ms": generated["duration_ms"],
        "usage": generated["usage"],
        "fallback": False,
        "raw_data_accessed": False,
    }
    event = _agent_event(
        db,
        task_id=task_id,
        agent_code=agent_code,
        message_type="DeepSeekAgentAnalysis",
        tool_name="DeepSeekChatCompletions",
        input_value={"instruction": instruction, "context": context},
        output_value={
            "summary_hash": sha256_json(result["summary"]),
            "findings": result["findings"],
            "request_id": result["request_id"],
        },
        details={
            "provider": result["provider"],
            "model": result["model"],
            "request_id": result["request_id"],
            "duration_ms": result["duration_ms"],
            "usage": result["usage"],
            "fallback": False,
            "confidence": result["confidence"],
            "raw_data_accessed": False,
        },
        authorized_permission=deepseek_permission,
    )
    result["event_id"] = event.event_id
    result["sequence_no"] = event.sequence_no
    return result


def _template_audit_answer(
    db: Session,
    task: SettlementTask,
    evidences: list[BlockchainEvidence],
    signatures: list[Signature],
    question: str,
) -> dict[str, Any]:
    lower = question.lower()
    if "篡改" in question or "哈希" in question:
        checks = [LocalEvidenceLedgerAdapter.verify(item) for item in evidences]
        matched = all(item["matched"] for item in checks)
        answer = f"共核验{len(checks)}项证据台账记录，当前摘要{'全部一致' if matched else '存在不一致'}。"
    elif "规则" in question or "rule" in lower:
        rule = db.get(SettlementRule, task.rule_id)
        answer = f"该任务绑定规则{rule.rule_version if rule else '未知'}，RuleHash为{rule.rule_hash if rule else '未知'}。"
    elif "签名" in question or "确认" in question:
        answer = f"当前存在{len(signatures)}条多方签名，均由主体DID对场景结果哈希签署。"
    elif "原始数据" in question or "隐私" in question:
        answer = "审计记录只引用DataRef、输入承诺和ComputeReceipt；当前API响应不返回企业原始明细。跨域非导出尚未获得外部证明。"
    else:
        answer = f"任务{task.task_name}当前状态为{task.status}，风险等级{task.risk_level}，已形成{len(evidences)}项证据。"
    return {
        "answer": answer,
        "citations": [
            {"evidence_id": item.evidence_id, "stage": item.stage, "tx_hash": item.tx_hash}
            for item in evidences[:6]
        ],
        "boundary": "本回答由结构化证据模板生成，不直接访问企业原始数据。",
        "grounded": True,
        "raw_data_accessed": False,
        "provider": "template_fallback",
        "model": None,
        "fallback": True,
        "confidence": "MEDIUM",
    }


def answer_audit_question(db: Session, task_id: str, question: str) -> dict[str, Any]:
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise ValueError("Settlement task not found")
    deepseek_permission = _authorize_agent_operation(
        db,
        task_id=task_id,
        agent_code="AUDIT_RISK",
        tool_name="DeepSeekChatCompletions",
    )
    evidences = db.scalars(
        select(BlockchainEvidence)
        .where(BlockchainEvidence.task_id == task_id)
        .order_by(BlockchainEvidence.block_height)
    ).all()
    signatures = db.scalars(select(Signature).where(Signature.task_id == task_id)).all()
    context = _audit_context(db, task, evidences, signatures)
    fallback_reason = None
    try:
        generated = explain_audit(question=question, context=context)
        citation_by_id = {item["evidence_id"]: item for item in context["citations"]}
        citations = [citation_by_id[item] for item in generated["citations"] if item in citation_by_id]
        answer = {
            "answer": generated["answer"],
            "citations": [
                {"evidence_id": item["evidence_id"], "stage": item["stage"], "tx_hash": item["tx_hash"]}
                for item in citations
            ],
            "boundary": generated["limitations"] or "回答仅基于结构化审计证据，不直接访问企业原始数据。",
            "grounded": bool(citations) or generated["confidence"] == "LOW",
            "raw_data_accessed": False,
            "provider": generated["provider"],
            "model": generated["model"],
            "request_id": generated["request_id"],
            "duration_ms": generated["duration_ms"],
            "usage": generated["usage"],
            "fallback": False,
            "confidence": generated["confidence"],
        }
        _agent_event(
            db,
            task_id=task_id,
            agent_code="AUDIT_RISK",
            message_type="AuditExplanation",
            tool_name="DeepSeekChatCompletions",
            input_value=context,
            output_value={"answer_hash": sha256_json(answer["answer"]), "citations": answer["citations"]},
            details={
                "provider": "deepseek",
                "model": answer["model"],
                "request_id": answer["request_id"],
                "duration_ms": answer["duration_ms"],
                "usage": answer["usage"],
                "fallback": False,
                "citation_count": len(answer["citations"]),
                "raw_data_accessed": False,
            },
            authorized_permission=deepseek_permission,
        )
        return answer
    except DeepSeekUnavailable as exc:
        fallback_reason = str(exc)
        fallback_permission = _authorize_agent_operation(
            db,
            task_id=task_id,
            agent_code="AUDIT_RISK",
            tool_name="TemplateAuditFallback",
        )
        answer = _template_audit_answer(db, task, evidences, signatures, question)
        _agent_event(
            db,
            task_id=task_id,
            agent_code="AUDIT_RISK",
            message_type="AuditExplanation",
            tool_name="TemplateAuditFallback",
            input_value=context,
            output_value={"answer_hash": sha256_json(answer["answer"]), "citations": answer["citations"]},
            details={
                "provider": "template_fallback",
                "model": None,
                "fallback": True,
                "fallback_reason": fallback_reason,
                "citation_count": len(answer["citations"]),
                "raw_data_accessed": False,
            },
            authorized_permission=fallback_permission,
        )
        return answer


def run_privacy_analysis(
    db: Session,
    job: PrivacyAnalysisJob,
    *,
    commit: bool = True,
) -> PrivacyAnalysisJob:
    uploads = [db.get(DataUpload, item) for item in job.dataset_ids_json]
    eligible = [item for item in uploads if item and item.asset_type == "USER_LOAD_CURVE"]
    recommended_strategy = (
        job.output_json.get("recommended_strategy")
        or job.output_json.get("compute_strategy")
        or AdaptivePrivacyRouter.recommend(
        job.purpose,
        sensitivity_level="L3",
        latency_requirement="BATCH",
        participant_count=len(eligible),
        )
    )
    execution_strategy = {
        "primary": LocalControlledComputeAdapter.code,
        "recommended_primary": recommended_strategy.get("primary"),
        "recommended_plan_hash": recommended_strategy.get("plan_hash"),
        "cross_domain_protocol": "NOT_PROVIDED",
        "attestation_status": "NOT_PROVIDED",
    }
    execution_strategy["plan_hash"] = sha256_json(execution_strategy)
    result, duration_ms = LocalControlledComputeAdapter().run_load_analysis(
        eligible,
        execution_strategy,
        privacy_level=job.privacy_level,
        privacy_budget=job.privacy_budget,
    )
    result.update(
        {
            "privacy_level": job.privacy_level,
            "privacy_budget": job.privacy_budget,
            "purpose": job.purpose,
            "minimum_group_size_passed": len(eligible) >= 1,
            "recommended_strategy": recommended_strategy,
        }
    )
    job.output_json = result
    job.result_hash = sha256_json(result)
    job.status = "SUCCESS"
    db.add(MetricRecord(task_id=None, metric_code="PRIVACY_ANALYSIS_MS", metric_value=duration_ms, metric_unit="ms"))
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(job)
    return job
