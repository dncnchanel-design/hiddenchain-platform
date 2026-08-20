from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    DataContract,
    DataSpaceAgreement,
    DataUpload,
    DidIdentity,
    PrivacyComputeJob,
    SettlementResult,
    SettlementRule,
    SettlementTask,
    TaskParticipant,
    utc_now,
)
from app.security import sha256_json
from app.services.algorithm_registry import AlgorithmRegistry
from app.services.trust_domain import (
    AuthorizationDenied,
    ExecutionSnapshotService,
    IdentityVerificationError,
    InvalidTtcTransition,
    ResourceExpired,
    SnapshotIntegrityError,
    TTCState,
    TtcStateMachine,
    authorize_agent_tool,
    verify_active_contract,
    verify_active_identity,
    verify_active_policy_version,
)
from app.trust_models import (
    AgentPermission,
    AgentTool,
    ExecutionSnapshot,
    ImmutableSnapshotError,
    TtcAttempt,
    TtcStateTransition,
    UsagePolicy,
    UsagePolicyVersion,
)


ACTOR_DID = "did:hiddenchain:org:org-exchange-t01"
AGENT_DID = "did:hiddenchain:agent:orchestrator"
TASK_ID = "task-ready-t01"


def _task(db) -> SettlementTask:
    task = db.get(SettlementTask, TASK_ID)
    assert task is not None
    task.ttc_state = TTCState.INIT.value
    task.current_attempt = 0
    return task


def _authorize_task(
    db, task: SettlementTask
) -> tuple[list[DataContract], list[DataUpload]]:
    TtcStateMachine.transition(
        db,
        task,
        TTCState.IDENTITY_VERIFIED,
        ACTOR_DID,
        "IDENTITY_GATE",
        "Organization credential verified",
    )
    bindings = [
        (
            "contract-generator-trust-domain-t01",
            "agreement-generator-trust-domain-t01",
            "org-generator-t01",
            "upload-generation-july-t01",
        ),
        (
            "contract-retailer-trust-domain-t01",
            "agreement-retailer-trust-domain-t01",
            "org-retailer-t01",
            "upload-retail-july-t01",
        ),
    ]
    contracts: list[DataContract] = []
    uploads: list[DataUpload] = []
    for contract_id, agreement_id, provider_org_id, upload_id in bindings:
        contract = _contract(
            db,
            contract_id=contract_id,
            provider_org_id=provider_org_id,
            upload_id=upload_id,
        )
        upload = db.get(DataUpload, upload_id)
        assert upload is not None
        _agreement(db, contract=contract, agreement_id=agreement_id)
        contracts.append(contract)
        uploads.append(upload)
    TtcStateMachine.transition(
        db,
        task,
        TTCState.DATA_AUTHORIZED,
        ACTOR_DID,
        "POLICY_GATE",
        "Data use was authorized",
    )
    return contracts, uploads


def _contract(
    db,
    *,
    contract_id: str = "contract-trust-domain-t01",
    provider_org_id: str = "org-generator-t01",
    upload_id: str = "upload-generation-july-t01",
) -> DataContract:
    contract = DataContract(
        contract_id=contract_id,
        task_id=TASK_ID,
        provider_org_id=provider_org_id,
        consumer_type="CONTROLLED_EXECUTION",
        purpose="POWER_SETTLEMENT",
        data_refs_json=[upload_id],
        policy_json={"output": "AGGREGATE_ONLY"},
        policy_hash=sha256_json({"output": "AGGREGATE_ONLY"}),
        status="ACTIVE",
    )
    db.add(contract)
    db.flush()
    return contract


def _agreement(
    db,
    *,
    contract: DataContract,
    agreement_id: str,
) -> DataSpaceAgreement:
    current = utc_now()
    agreement = DataSpaceAgreement(
        agreement_id=agreement_id,
        contract_id=contract.contract_id,
        task_id=TASK_ID,
        provider_org_id=contract.provider_org_id,
        consumer_org_id="org-exchange-t01",
        provider_did=f"did:hiddenchain:org:{contract.provider_org_id}",
        consumer_did=ACTOR_DID,
        protocol_version="HCDS-1.0",
        state="NEGOTIATED",
        requested_purpose="POWER_SETTLEMENT",
        algorithm_code="CONTROLLED_SETTLEMENT_V1",
        data_product_ids_json=list(contract.data_refs_json),
        offered_policy_hash=contract.policy_hash,
        negotiated_policy_hash=contract.policy_hash,
        valid_from=current - timedelta(minutes=1),
        expires_at=current + timedelta(days=1),
        max_uses=1,
        use_count=0,
        decision_json={"decision": "PERMIT"},
        last_receipt_json={},
        trace_id=f"trace-{agreement_id}",
    )
    db.add(agreement)
    db.flush()
    return agreement


def _persist_successful_compute_artifacts(
    db,
    *,
    task: SettlementTask,
    snapshot: ExecutionSnapshot,
) -> None:
    result_value = {"settlement_energy_mwh": 1.0, "payable_amount_yuan": 420.0}
    result_hash = sha256_json(result_value)
    db.add(
        PrivacyComputeJob(
            task_id=task.task_id,
            algorithm_code="CONTROLLED_SETTLEMENT_V1",
            adapter_code="LOCAL_CONTROLLED_SETTLEMENT_V1",
            input_hashes_json=[],
            output_hash=result_hash,
            result_json=result_value,
            status="SUCCESS",
            progress=100,
            attempt_id=snapshot.attempt_id,
            execution_snapshot_id=snapshot.snapshot_id,
        )
    )
    summary = SettlementResult(
        task_id=task.task_id,
        attempt_id=snapshot.attempt_id,
        org_id=None,
        result_scope="SUMMARY",
        result_json=result_value,
        result_hash=result_hash,
        confirm_status="NOT_REQUIRED",
    )
    db.add(summary)
    db.flush()
    participants = db.scalars(
        select(TaskParticipant).where(TaskParticipant.task_id == task.task_id)
    ).all()
    for participant in participants:
        scoped_value = {
            "org_id": participant.org_id,
            "role": participant.role_in_task,
            "result_hash_ref": result_hash,
        }
        db.add(
            SettlementResult(
                task_id=task.task_id,
                attempt_id=snapshot.attempt_id,
                org_id=participant.org_id,
                result_scope="ORG",
                result_json=scoped_value,
                result_hash=sha256_json(scoped_value),
                confirm_status="UNCONFIRMED",
            )
        )


def _algorithm_descriptor() -> dict:
    return AlgorithmRegistry.execution_descriptor("CONTROLLED_SETTLEMENT_V1")


def test_ttc_accepts_next_state_and_rejects_stage_bypass() -> None:
    with SessionLocal() as db:
        task = _task(db)
        initial_state_version = task.state_version
        transition = TtcStateMachine.transition(
            db,
            task,
            TTCState.IDENTITY_VERIFIED,
            ACTOR_DID,
            "IDENTITY_GATE",
            "DID and organization are active",
        )

        assert transition.from_state == TTCState.INIT.value
        assert transition.to_state == TTCState.IDENTITY_VERIFIED.value
        assert task.ttc_state == TTCState.IDENTITY_VERIFIED.value
        assert task.state_version == initial_state_version + 1
        assert task.last_transition_at is not None
        assert db.scalar(
            select(func.count(TtcStateTransition.transition_id)).where(
                TtcStateTransition.task_id == task.task_id
            )
        ) == 1

        with pytest.raises(InvalidTtcTransition, match="is not allowed"):
            TtcStateMachine.transition(
                db,
                task,
                TTCState.COMPUTE_EXEC,
                ACTOR_DID,
                "BYPASS_ATTEMPT",
                "Attempted to skip authorization and Rule Freeze",
            )


def test_rule_frozen_transition_requires_persisted_snapshot() -> None:
    with SessionLocal() as db:
        task = _task(db)
        _authorize_task(db, task)

        with pytest.raises(InvalidTtcTransition, match="immutable execution snapshot"):
            TtcStateMachine.transition(
                db,
                task,
                TTCState.RULE_FROZEN,
                ACTOR_DID,
                "BYPASS_FREEZE",
                "Attempted to mark rules frozen without a snapshot",
            )


def test_data_authorized_transition_requires_negotiated_participant_contracts() -> None:
    with SessionLocal() as db:
        task = _task(db)
        TtcStateMachine.transition(
            db,
            task,
            TTCState.IDENTITY_VERIFIED,
            ACTOR_DID,
            "IDENTITY_GATE",
            "Participant identities are active",
        )

        with pytest.raises(
            InvalidTtcTransition,
            match="Every task participant must have an active data contract",
        ):
            TtcStateMachine.transition(
                db,
                task,
                TTCState.DATA_AUTHORIZED,
                ACTOR_DID,
                "AUTHORIZATION_BYPASS",
                "Attempted authorization without negotiated contracts",
            )


def test_execution_snapshot_hash_is_deterministic_idempotent_and_immutable() -> None:
    with SessionLocal() as db:
        task = _task(db)
        contracts, uploads = _authorize_task(db, task)
        rule = db.get(SettlementRule, task.rule_id)
        assert rule is not None
        descriptor = _algorithm_descriptor()

        snapshot = ExecutionSnapshotService.freeze(
            db,
            task,
            rule,
            contracts,
            uploads,
            descriptor,
            ACTOR_DID,
            "trace-rule-freeze-t01",
        )

        assert task.ttc_state == TTCState.RULE_FROZEN.value
        assert snapshot.snapshot_hash == sha256_json(snapshot.canonical_payload_json)
        assert snapshot.snapshot_version == 1
        reordered = dict(reversed(list(snapshot.canonical_payload_json.items())))
        ExecutionSnapshotService.assert_unchanged(snapshot, reordered)

        same = ExecutionSnapshotService.freeze(
            db,
            task,
            rule,
            contracts,
            uploads,
            descriptor,
            ACTOR_DID,
            "trace-rule-freeze-t01",
        )
        assert same.snapshot_id == snapshot.snapshot_id

        modified = {**snapshot.canonical_payload_json, "units": {"energy": "kWh"}}
        with pytest.raises(SnapshotIntegrityError, match="cannot be modified"):
            ExecutionSnapshotService.assert_unchanged(snapshot, modified)

        snapshot.canonical_payload_json = modified
        with pytest.raises(ImmutableSnapshotError, match="IMMUTABLE"):
            db.flush()


def test_result_confirm_transition_requires_current_compute_artifacts() -> None:
    with SessionLocal() as db:
        task = _task(db)
        contracts, uploads = _authorize_task(db, task)
        rule = db.get(SettlementRule, task.rule_id)
        assert rule is not None
        snapshot = ExecutionSnapshotService.freeze(
            db,
            task,
            rule,
            contracts,
            uploads,
            _algorithm_descriptor(),
            ACTOR_DID,
            "trace-result-gate",
        )
        TtcStateMachine.transition(
            db,
            task,
            TTCState.COMPUTE_EXEC,
            ACTOR_DID,
            "COMPUTE_START",
            "Compute started",
        )

        with pytest.raises(InvalidTtcTransition, match="successful current-attempt compute"):
            TtcStateMachine.transition(
                db,
                task,
                TTCState.RESULT_CONFIRM,
                ACTOR_DID,
                "RESULT_BYPASS",
                "Attempted result confirmation without a compute result",
                attempt_id=snapshot.attempt_id,
            )


def test_rework_creates_a_new_attempt_and_snapshot_version() -> None:
    with SessionLocal() as db:
        task = _task(db)
        contracts, uploads = _authorize_task(db, task)
        rule = db.get(SettlementRule, task.rule_id)
        assert rule is not None
        descriptor = _algorithm_descriptor()
        first = ExecutionSnapshotService.freeze(
            db,
            task,
            rule,
            contracts,
            uploads,
            descriptor,
            ACTOR_DID,
            "trace-rework-first",
        )
        TtcStateMachine.transition(
            db, task, TTCState.COMPUTE_EXEC, ACTOR_DID, "COMPUTE_START", "Compute started"
        )
        _persist_successful_compute_artifacts(db, task=task, snapshot=first)
        TtcStateMachine.transition(
            db, task, TTCState.RESULT_CONFIRM, ACTOR_DID, "RESULT_READY", "Result generated"
        )
        TtcStateMachine.transition(
            db, task, TTCState.REWORK, ACTOR_DID, "RESULT_REJECTED", "Participant requested rework"
        )

        second = ExecutionSnapshotService.freeze(
            db,
            task,
            rule,
            contracts,
            uploads,
            descriptor,
            ACTOR_DID,
            "trace-rework-second",
        )

        assert second.snapshot_version == 2
        assert second.attempt_id != first.attempt_id
        assert task.current_attempt == 2
        assert task.ttc_state == TTCState.RULE_FROZEN.value
        assert db.scalar(
            select(func.count(TtcAttempt.attempt_id)).where(TtcAttempt.task_id == task.task_id)
        ) == 2


def test_revoked_did_is_rejected_before_state_change() -> None:
    with SessionLocal() as db:
        identity = db.get(DidIdentity, ACTOR_DID)
        assert identity is not None
        identity.credential_status = "REVOKED"
        db.flush()
        task = _task(db)

        with pytest.raises(IdentityVerificationError, match="not valid"):
            verify_active_identity(db, ACTOR_DID)
        with pytest.raises(IdentityVerificationError):
            TtcStateMachine.transition(
                db,
                task,
                TTCState.IDENTITY_VERIFIED,
                ACTOR_DID,
                "IDENTITY_GATE",
                "Credential must be valid",
            )
        assert task.ttc_state == TTCState.INIT.value


def test_expired_policy_version_and_contract_agreement_are_rejected() -> None:
    with SessionLocal() as db:
        current = utc_now()
        policy_document = {"purpose": "POWER_SETTLEMENT", "output": "AGGREGATE_ONLY"}
        policy = UsagePolicy(
            policy_id="policy-expired-t01",
            policy_code="policy-expired-t01",
            policy_name="Expired test policy",
            owner_org_id="org-exchange-t01",
            policy_type="USAGE_CONTROL",
            current_version_no=1,
            status="ACTIVE",
        )
        version = UsagePolicyVersion(
            policy_version_id="policy-version-expired-t01",
            policy_id=policy.policy_id,
            version_no=1,
            policy_json=policy_document,
            policy_hash=sha256_json(policy_document),
            immutable_hash=sha256_json({"version": 1, "policy": policy_document}),
            valid_from=current - timedelta(days=2),
            expires_at=current - timedelta(days=1),
            status="ACTIVE",
        )
        db.add_all([policy, version])
        contract = _contract(db, contract_id="contract-expired-t01")
        agreement = DataSpaceAgreement(
            agreement_id="agreement-expired-t01",
            contract_id=contract.contract_id,
            task_id=TASK_ID,
            provider_org_id="org-generator-t01",
            consumer_org_id="org-exchange-t01",
            provider_did="did:hiddenchain:org:org-generator-t01",
            consumer_did=ACTOR_DID,
            protocol_version="HCDS-1.0",
            state="ACTIVE",
            requested_purpose="POWER_SETTLEMENT",
            algorithm_code="CONTROLLED_SETTLEMENT_V1",
            data_product_ids_json=["upload-grid-constraint-july-t01"],
            offered_policy_hash=contract.policy_hash,
            negotiated_policy_hash=contract.policy_hash,
            valid_from=current - timedelta(days=2),
            expires_at=current - timedelta(seconds=1),
            max_uses=1,
            use_count=0,
            decision_json={"decision": "PERMIT"},
            last_receipt_json={},
            trace_id="trace-expired-contract",
        )
        db.add(agreement)
        db.flush()

        with pytest.raises(ResourceExpired, match="POLICY_VERSION has expired"):
            verify_active_policy_version(db, version.policy_version_id)
        with pytest.raises(ResourceExpired, match="CONTRACT_AGREEMENT has expired"):
            verify_active_contract(db, contract.contract_id)


def test_agent_tool_permission_is_fail_closed_outside_task_scope() -> None:
    with SessionLocal() as db:
        tool = AgentTool(
            tool_id="tool-trust-domain-t01",
            tool_code="READ_AUTHORIZED_CAPSULE",
            tool_name="Read authorized capsule",
            service_code="CAPSULE_SERVICE",
            input_schema_json={"task_id": "string"},
            output_schema_json={"capsule_hash": "string"},
            capability_label="LOCAL_REAL",
            enabled=True,
        )
        permission = AgentPermission(
            permission_id="permission-trust-domain-t01",
            agent_did=AGENT_DID,
            agent_role="IDENTITY_AGENT",
            tool_id=tool.tool_id,
            operations_json=["INVOKE"],
            scope_json={"task_ids": [TASK_ID]},
            status="ACTIVE",
            granted_by_did=ACTOR_DID,
            grant_reason="Test least-privilege task scope",
        )
        db.add(tool)
        db.flush()
        db.add(permission)
        db.flush()

        assert authorize_agent_tool(db, AGENT_DID, tool.tool_code, TASK_ID).permission_id == permission.permission_id
        with pytest.raises(AuthorizationDenied, match="least-privilege"):
            authorize_agent_tool(db, AGENT_DID, tool.tool_code, "task-history-t01")
