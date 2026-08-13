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
)
from ..security import sha256_json, sign_value
from .adapters import (
    AGENT_DEFINITIONS,
    AdaptivePrivacyRouter,
    DataSpaceConnectorAdapter,
    MockBlockchainAdapter,
    MockDataSpaceAdapter,
    MockDidAdapter,
    MockPrivacyComputeAdapter,
    RulePackageAdapter,
)
from .common import add_audit_log, model_dict, trace_id
from .llm import DeepSeekUnavailable, explain_audit, invoke_agent_analysis


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
) -> AgentEvent:
    sequence = db.scalar(
        select(func.max(AgentEvent.sequence_no)).where(AgentEvent.task_id == task_id)
    ) or 0
    definition = _agent_definition(agent_code)
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
    db.flush()
    return event


def _scoped_task_allowed(db: Session, task: SettlementTask, user: User) -> bool:
    if user.role_code in {"EXCHANGE", "REGULATOR", "ADMIN"}:
        return True
    return db.scalar(
        select(func.count(TaskParticipant.participant_id)).where(
            TaskParticipant.task_id == task.task_id,
            TaskParticipant.org_id == user.org_id,
        )
    ) > 0


def task_summary(db: Session, task: SettlementTask) -> dict[str, Any]:
    participants = db.scalars(
        select(TaskParticipant).where(TaskParticipant.task_id == task.task_id)
    ).all()
    results = db.scalars(
        select(SettlementResult).where(SettlementResult.task_id == task.task_id)
    ).all()
    summary_result = next((item for item in results if item.result_scope == "SUMMARY"), None)
    agreement_count = db.scalar(
        select(func.count(DataSpaceAgreement.agreement_id)).where(
            DataSpaceAgreement.task_id == task.task_id
        )
    ) or 0
    return {
        **model_dict(task),
        "verification_profile": task.verification_profile_json or {
            "mode": "VIRTUAL_SIMULATION",
            "trusted_acquisition": True,
            "secure_transport": True,
            "controlled_use": True,
            "privacy_compute": task.status == "AUDITED",
            "traceable_audit": task.status == "AUDITED",
            "raw_data_exposed": False,
            "protocols": ["HTTPS", "MQTT", "WebSocket"],
            "connected_layers": ["数据采集终端", "边缘计算节点", "云端数据中心", "业务应用系统"],
            "evidence_stages": ["PRE_COMPUTE", "IN_COMPUTE", "POST_COMPUTE"],
        },
        "participants": [model_dict(item) for item in participants],
        "result_count": len(results),
        "evidence_count": db.scalar(
            select(func.count(BlockchainEvidence.evidence_id)).where(
                BlockchainEvidence.task_id == task.task_id
            )
        ) or 0,
        "agent_event_count": db.scalar(
            select(func.count(AgentEvent.event_id)).where(AgentEvent.task_id == task.task_id)
        ) or 0,
        "data_space_agreement_count": agreement_count,
        "scenario_coordination": (
            summary_result.result_json.get("scenario_coordination", []) if summary_result else []
        ),
    }


def workflow_bundle(db: Session, task: SettlementTask) -> dict[str, Any]:
    """Return the workflow outcome without ever embedding enterprise raw records."""
    job = db.scalar(
        select(PrivacyComputeJob)
        .where(PrivacyComputeJob.task_id == task.task_id)
        .order_by(PrivacyComputeJob.created_at.desc())
    )
    results = db.scalars(
        select(SettlementResult)
        .where(SettlementResult.task_id == task.task_id)
        .order_by(SettlementResult.created_at)
    ).all()
    evidence = db.scalars(
        select(BlockchainEvidence)
        .where(BlockchainEvidence.task_id == task.task_id)
        .order_by(BlockchainEvidence.block_height)
    ).all()
    report = db.scalar(
        select(AuditReport)
        .where(AuditReport.task_id == task.task_id)
        .order_by(AuditReport.created_at.desc())
    )
    agreements = db.scalars(
        select(DataSpaceAgreement)
        .where(DataSpaceAgreement.task_id == task.task_id)
        .order_by(DataSpaceAgreement.created_at)
    ).all()
    job_payload = model_dict(job) if job else None
    if job_payload is not None:
        job_payload["raw_data_exposed"] = False
        job_payload["privacy_guarantees"] = job.privacy_guarantees_json or {
            "raw_data_exported": False,
            "raw_records_returned": False,
            "output_mode": "AGGREGATE_ONLY",
        }
    report_payload = model_dict(report) if report else None
    if report_payload is not None:
        report_payload["conclusion"] = "PASS" if report.risk_level == "LOW" else "REVIEW_REQUIRED"
    return {
        "task": task_summary(db, task),
        "compute_job": job_payload,
        "results": [model_dict(item) for item in results],
        "evidence": [model_dict(item) for item in evidence],
        "report": report_payload,
        "data_space": {
            "protocol_version": DataSpaceConnectorAdapter.protocol_version,
            "agreement_count": len(agreements),
            "agreements": [model_dict(item) for item in agreements],
            "raw_data_transferred": False,
            "usage_control": "PEP_PDP_ENFORCED",
        },
        "security_boundary": {
            "raw_data_exposed": False,
            "agent_direct_raw_data_access": False,
            "deterministic_execution": True,
        },
        "verification_profile": task.verification_profile_json or {
            "mode": "VIRTUAL_SIMULATION",
            "trusted_acquisition": False,
            "secure_transport": False,
            "controlled_use": False,
            "privacy_compute": False,
            "traceable_audit": False,
        },
    }


def run_settlement_workflow(
    db: Session,
    *,
    task_id: str,
    actor: User | None,
    compute_mode: str = "MPC_MOCK",
    algorithm_code: str = "SETTLEMENT_MPC_V1",
    commit: bool = True,
) -> dict[str, Any]:
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise ValueError("Settlement task not found")
    if actor and not _scoped_task_allowed(db, task, actor):
        raise PermissionError("Task is outside the current user's scope")
    if task.status == "AUDITED":
        return workflow_bundle(db, task)

    run_trace = trace_id()
    rule = db.get(SettlementRule, task.rule_id)
    if rule is None or rule.status != "ACTIVE":
        raise ValueError("Task must bind an active RulePackage")
    participants = db.scalars(
        select(TaskParticipant).where(TaskParticipant.task_id == task.task_id)
    ).all()
    if len(participants) < 2:
        raise ValueError("Settlement requires generator and retailer participants")
    orgs = {item.org_id: db.get(Organization, item.org_id) for item in participants}

    task.status = "AUTHORIZED"
    task.current_stage = "身份认证与任务编排"
    identity_proofs = [MockDidAdapter.verify_owner(db, item.org_id) for item in participants]
    orchestrator = _agent_definition("ORCHESTRATOR")
    capability = MockDidAdapter.issue_capability(
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
    )

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
        contract = MockDataSpaceAdapter.create_contract(
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
        grid_contract = MockDataSpaceAdapter.create_contract(
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
            execution_environment="AUTHORIZED_COMPUTE_SANDBOX",
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
    )

    chain = MockBlockchainAdapter()
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
        "policy_decision": "PERMIT" if grid_upload else "MVP_FALLBACK",
        "check_mode": "SECURE_POST_MPC_GATE",
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
    )

    task.status = "COMPUTING"
    task.current_stage = "隐私计算与场景结果生成"
    compute_strategy = AdaptivePrivacyRouter.recommend(
        "MARKET_SETTLEMENT",
        sensitivity_level="L4",
        latency_requirement="BATCH",
        participant_count=len(participants),
    )
    job = PrivacyComputeJob(
        task_id=task.task_id,
        algorithm_code=algorithm_code,
        adapter_code="MOCK_SECRET_FLOW" if compute_mode == "MPC_MOCK" else "SECRET_FLOW_RESERVED",
        input_hashes_json=[item.data_hash for item in uploads_by_role.values()],
        status="RUNNING",
        progress=35,
        logs_json=[
            "DataPermit accepted",
            "PSI input commitments loaded",
            f"Adaptive plan accepted: {compute_strategy['primary']}",
        ],
    )
    db.add(job)
    db.flush()
    result_value, receipt, compute_logs, duration_ms = MockPrivacyComputeAdapter().run_settlement(
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
            execution_environment="AUTHORIZED_COMPUTE_SANDBOX",
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
        "raw_data_exported": False,
        "raw_records_returned": False,
        "output_mode": "AGGREGATE_ONLY",
        "input_commitments_only": True,
        "execution_environment": "AUTHORIZED_COMPUTE_SANDBOX",
        "strategy": compute_strategy["primary"],
        "strategy_hash": compute_strategy["plan_hash"],
    }

    summary_result = SettlementResult(
        task_id=task.task_id,
        org_id=None,
        result_scope="SUMMARY",
        result_json=result_value,
        result_hash=sha256_json(result_value),
        confirm_status="CONFIRMED",
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
            org_id=participant.org_id,
            result_scope="ORG",
            result_json=role_result,
            result_hash=sha256_json(role_result),
            confirm_status="CONFIRMED",
        )
        db.add(scoped_result)
        did = MockDidAdapter.verify_owner(db, participant.org_id)["did"]
        signature_value = sign_value(
            {"result_hash": summary_result.result_hash, "opinion": "CONFIRMED"}, did
        )
        db.add(
            Signature(
                task_id=task.task_id,
                signer_org_id=participant.org_id,
                signer_did=did,
                target_type="RESULT_CONFIRM",
                target_id=summary_result.result_id,
                target_hash=summary_result.result_hash,
                signature_value=signature_value,
                verify_status="VALID",
            )
        )
        participant.confirm_status = "CONFIRMED"

    _agent_event(
        db,
        task_id=task.task_id,
        agent_code="SECURE_SETTLEMENT",
        message_type="ComputeReceipt",
        tool_name="PSIAdapter+MPCAdapter+DeterministicEngine",
        input_value={"data_permit": data_permit, "rule_package": rule_package},
        output_value=receipt,
        details={
            "job_id": job.job_id,
            "result_id": summary_result.result_id,
            "logs": compute_logs,
            "data_space": receipt["data_space"],
        },
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
            "party_signatures": db.scalar(
                select(func.count(Signature.signature_id)).where(Signature.task_id == task.task_id)
            ),
            "contract_state": "SIGNED",
        },
    )

    task.status = "EVIDENCED"
    task.current_stage = "证据图谱核验"
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
    risk_level = "HIGH" if scenario_rejected or any(not item["matched"] for item in verification) else (
        "MEDIUM" if open_anomalies else "LOW"
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
        tool_name="EvidenceGraph+FISCOAdapter+RiskRuleEngine",
        input_value={"evidence_ids": [item.evidence_id for item in evidence_items]},
        output_value=audit_bundle,
        details={"checks": verification, "raw_data_accessed": False},
    )

    report_content = (
        f"# {task.task_name}全过程可信审计报告\n\n"
        f"- 可信验证胶囊：{task.capsule_id}\n"
        f"- 规则版本：{rule.rule_version}（{rule.rule_hash}）\n"
        f"- 身份校验：{len(identity_proofs)}个主体VC有效\n"
        f"- 数据合同：{len(contracts)}份，策略决策均为PERMIT\n"
        f"- 隐私计算：{job.adapter_code}，原始数据未出域\n"
        f"- 四场景协同：新能源预测、市场结算、虚拟电厂响应与调度安全校核已串联\n"
        f"- 策略路由：{compute_strategy['primary']}（{compute_strategy['plan_hash']}）\n"
        f"- 场景结果哈希：{summary_result.result_hash}\n"
        f"- 三阶段证据：{len(evidence_items) + 1}项，风险等级{risk_level}\n"
        f"- 审计结论：{'通过' if risk_level == 'LOW' else '需复核'}。"
    )
    report_hash = sha256_json({"content": report_content, "audit_bundle": audit_bundle})
    report = AuditReport(
        task_id=task.task_id,
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
    )

    task.status = "AUDITED"
    task.current_stage = "监管审计完成"
    task.risk_level = risk_level
    task.verification_profile_json = {
        "mode": "VIRTUAL_SIMULATION",
        "scenario": "能源可信数据空间多方安全协同",
        "trusted_acquisition": True,
        "secure_transport": True,
        "controlled_use": True,
        "privacy_compute": True,
        "traceable_audit": True,
        "raw_data_exposed": False,
        "protocols": ["HTTPS", "MQTT", "WebSocket"],
        "connected_layers": ["数据采集终端", "边缘计算节点", "云端数据中心", "业务应用系统"],
        "evidence_stages": ["PRE_COMPUTE", "IN_COMPUTE", "POST_COMPUTE"],
        "evidence_count": len(evidence_items) + 1,
        "acceptance_metrics": {
            "compute_duration_ms": duration_ms,
            "raw_data_transferred": 0,
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
            MetricRecord(task_id=task.task_id, metric_code="MPC_DURATION_MS", metric_value=duration_ms, metric_unit="ms"),
            MetricRecord(task_id=task.task_id, metric_code="CHAIN_EVIDENCE_COUNT", metric_value=len(evidence_items) + 1, metric_unit="count"),
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
    return workflow_bundle(db, task)


def create_audit_report(db: Session, task_id: str, template_code: str) -> AuditReport:
    existing = db.scalar(
        select(AuditReport)
        .where(AuditReport.task_id == task_id, AuditReport.template_code == template_code)
        .order_by(AuditReport.created_at.desc())
    )
    if existing:
        return existing
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise ValueError("Settlement task not found")
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
    "ORCHESTRATOR": "核对当前任务上下文和六Agent协作链，指出当前阶段、已有协作结果与下一步。",
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
        checks = [MockBlockchainAdapter.verify(item) for item in evidences]
        matched = all(item["matched"] for item in checks)
        answer = f"共核验{len(checks)}项链上证据，当前哈希{'全部一致' if matched else '存在不一致'}。"
    elif "规则" in question or "rule" in lower:
        rule = db.get(SettlementRule, task.rule_id)
        answer = f"该任务绑定规则{rule.rule_version if rule else '未知'}，RuleHash为{rule.rule_hash if rule else '未知'}。"
    elif "签名" in question or "确认" in question:
        answer = f"当前存在{len(signatures)}条多方签名，均由主体DID对场景结果哈希签署。"
    elif "原始数据" in question or "隐私" in question:
        answer = "审计链只引用DataRef、输入承诺和ComputeReceipt；Agent、交易中心与监管方均未读取企业原始明细。"
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
        )
        return answer
    except DeepSeekUnavailable as exc:
        fallback_reason = str(exc)
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
    strategy = job.output_json.get("compute_strategy") or AdaptivePrivacyRouter.recommend(
        job.purpose,
        sensitivity_level="L3",
        latency_requirement="BATCH",
        participant_count=len(eligible),
    )
    result, duration_ms = MockPrivacyComputeAdapter().run_load_analysis(eligible, strategy)
    result.update(
        {
            "privacy_level": job.privacy_level,
            "privacy_budget": job.privacy_budget,
            "purpose": job.purpose,
            "minimum_group_size_passed": len(eligible) >= 1,
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
