from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, get_current_user, require_roles
from ..models import (
    DataUpload,
    DataSpaceAgreement,
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
    SettlementImportFile,
    UsageControlCheckRequest,
    PrivacyAnalysisCreate,
    ResultConfirmRequest,
    RuleCreate,
    SettlementTaskCreate,
    DataUploadCreate,
    WorkflowRunRequest,
)
from ..security import sha256_json, sign_value
from ..services.adapters import (
    AdaptivePrivacyRouter,
    DataSpaceConnectorAdapter,
    OPAPolicyAdapter,
    PandapowerGridAdapter,
)
from ..services.common import add_audit_log, model_dict, trace_id
from ..services.datapackage import FrictionlessCatalogAdapter
from ..services.duckdb_connector import DuckDBMetadataAdapter
from ..services.solar import PvlibSolarAdapter
from ..services.workflow import (
    emit_settlement_lineage,
    run_privacy_analysis,
    run_settlement_workflow,
    task_summary,
)
from ..services.vault import LocalDomainVault


router = APIRouter(tags=["trade"])


def _import_asset_allowed(user: User, asset_type: str, owner_org_id: str) -> bool:
    if user.role_code in {"EXCHANGE", "ADMIN"}:
        return True
    if owner_org_id != user.org_id:
        return False
    if user.role_code == "GENERATOR":
        return asset_type in {"GENERATION_DATA", "RENEWABLE_FORECAST"}
    if user.role_code == "RETAILER":
        return asset_type in {"RETAIL_DATA", "USER_LOAD_CURVE", "VPP_RESOURCE"}
    return False


@router.post("/settlement/import-and-run")
def import_and_run_settlement(
    payload: SettlementImportFile,
    user: User = Depends(require_roles("EXCHANGE", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    """Import a validated scenario file, sign its data references, and run the proof flow.

    The same contract accepts real scene metadata or virtual simulation data.  The
    platform never treats the file flag as a security decision; schema validation,
    participant scope, DID checks and usage policy remain the gate.
    """

    asset_types = {item.asset_type for item in payload.data_assets}
    required_types = {"GENERATION_DATA", "RETAIL_DATA"}
    if not required_types.issubset(asset_types):
        raise HTTPException(status_code=400, detail="文件必须同时包含发电数据和售电数据")
    if len(asset_types) != len(payload.data_assets):
        raise HTTPException(status_code=400, detail="同一文件中不能重复导入相同类型的数据")

    participants = payload.business_validation_request.participants
    if len(participants) != 2 or {item.role_in_task for item in participants} != {"GENERATOR", "RETAILER"}:
        raise HTTPException(status_code=400, detail="验证参与方必须包含一个发电主体和一个售电主体")
    participant_by_role = {item.role_in_task: item.org_id for item in participants}
    exchange_org_id = str(payload.organizations.get("exchange", {}).get("org_id") or "")
    exchange_org = db.get(Organization, exchange_org_id) if exchange_org_id else None
    if exchange_org is None or exchange_org.org_type != "EXCHANGE":
        exchange_org_id = db.scalar(select(Organization.org_id).where(Organization.org_type == "EXCHANGE")) or ""
    if not exchange_org_id:
        raise HTTPException(status_code=400, detail="验证文件未绑定有效的交易中心主体")
    for participant in participants:
        organization = db.get(Organization, participant.org_id)
        if organization is None or organization.org_type != participant.role_in_task:
            raise HTTPException(status_code=400, detail="参与主体身份与任务角色不匹配")

    active_rule = db.get(SettlementRule, payload.business_validation_request.rule_id)
    if active_rule is None or active_rule.status != "ACTIVE":
        raise HTTPException(status_code=400, detail="文件绑定的使用规则不存在或未启用")

    # Validate the complete manifest before writing anything to a domain Vault.
    for asset in payload.data_assets:
        if not _import_asset_allowed(user, asset.asset_type, asset.owner_org_id):
            raise HTTPException(status_code=403, detail=f"无权导入{asset.asset_type}数据")
        if db.get(Organization, asset.owner_org_id) is None:
            raise HTTPException(status_code=400, detail=f"数据主体不存在：{asset.owner_org_id}")
        expected_owner = {
            "GENERATION_DATA": participant_by_role["GENERATOR"],
            "RENEWABLE_FORECAST": participant_by_role["GENERATOR"],
            "RETAIL_DATA": participant_by_role["RETAILER"],
            "USER_LOAD_CURVE": participant_by_role["RETAILER"],
            "VPP_RESOURCE": participant_by_role["RETAILER"],
            "GRID_CONSTRAINT": exchange_org_id,
        }[asset.asset_type]
        if asset.owner_org_id != expected_owner:
            raise HTTPException(status_code=400, detail=f"{asset.asset_type}数据提供方与任务角色不匹配")
        try:
            DataUploadCreate(
                asset_type=asset.asset_type,
                trade_batch_no=payload.batch.trade_batch_no,
                label=asset.label,
                local_payload=asset.local_payload,
                owner_org_id=asset.owner_org_id,
                ingress=asset.ingress,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"{asset.asset_type}数据格式校验失败：{exc}") from exc

    uploaded: list[DataUpload] = []
    new_data_refs: list[str] = []
    for asset in payload.data_assets:
        existing = db.scalar(
            select(DataUpload)
            .where(
                DataUpload.asset_type == asset.asset_type,
                DataUpload.owner_org_id == asset.owner_org_id,
                DataUpload.trade_batch_no == payload.batch.trade_batch_no,
            )
            .order_by(DataUpload.created_at.desc())
        )
        if existing is not None:
            uploaded.append(existing)
            continue

        record = DataUpload(
            asset_type=asset.asset_type,
            owner_org_id=asset.owner_org_id,
            trade_batch_no=payload.batch.trade_batch_no,
            label=asset.label,
            data_ref="pending",
            data_hash="pending",
            commitment="pending",
            schema_version="v1.0",
            validation_status="PENDING",
            summary_json={},
            ingress_json=asset.ingress.model_dump(),
        )
        db.add(record)
        db.flush()
        data_ref, data_hash, commitment = LocalDomainVault.write(
            asset.owner_org_id, record.upload_id, asset.local_payload
        )
        record.data_ref = data_ref
        record.data_hash = data_hash
        record.commitment = commitment
        new_data_refs.append(data_ref)
        record.validation_status = "PASSED"
        record.summary_json = {
            "record_count": asset.local_payload.get("record_count", 1),
            "period": asset.local_payload.get("period", payload.batch.period),
            "raw_data_stored_in_business_db": False,
            "trusted_acquisition": True,
            "secure_transport": asset.ingress.model_dump(),
        }
        did = db.scalar(select(DidIdentity).where(DidIdentity.owner_id == asset.owner_org_id))
        record.signature_value = sign_value(
            {"upload_id": record.upload_id, "data_hash": data_hash},
            did.did_id if did else asset.owner_org_id,
        )
        db.add(
            Signature(
                signer_org_id=asset.owner_org_id,
                signer_did=did.did_id if did else f"did:hiddenchain:org:{asset.owner_org_id}",
                target_type="DATA_UPLOAD",
                target_id=record.upload_id,
                target_hash=data_hash,
                signature_value=record.signature_value,
                verify_status="VALID",
            )
        )
        uploaded.append(record)

    db.flush()
    task_payload = payload.business_validation_request
    existing_task = db.scalar(
        select(SettlementTask)
        .where(
            SettlementTask.trade_batch_no == payload.batch.trade_batch_no,
            SettlementTask.task_name == task_payload.task_name,
            SettlementTask.creator_org_id == user.org_id,
        )
        .order_by(SettlementTask.created_at.desc())
    )
    if existing_task is None:
        task = SettlementTask(
            capsule_id=(
                f"HC-CAPSULE-{payload.batch.period_start.strftime('%Y%m')}-"
                f"{sha256_json({'task_name': task_payload.task_name, 'trade_batch_no': payload.batch.trade_batch_no})[:8].upper()}"
            ),
            task_name=task_payload.task_name,
            trade_batch_no=payload.batch.trade_batch_no,
            period_start=payload.batch.period_start,
            period_end=payload.batch.period_end,
            rule_id=active_rule.rule_id,
            creator_org_id=user.org_id,
            status="DRAFT",
            current_stage="任务创建",
        )
        db.add(task)
        db.flush()
        for participant in participants:
            db.add(
                TaskParticipant(
                    task_id=task.task_id,
                    org_id=participant.org_id,
                    role_in_task=participant.role_in_task,
                    data_status="READY",
                    confirm_status="PENDING",
                )
            )
    else:
        task = existing_task

    for upload in uploaded:
        upload.task_id = task.task_id
    add_audit_log(
        db,
        action="IMPORT_AND_RUN_SETTLEMENT",
        target_type="SETTLEMENT_TASK",
        target_id=task.task_id,
        result="SUCCESS",
        user=user,
        details={"fixture_id": payload.fixture_id, "asset_count": len(uploaded)},
    )
    db.flush()
    try:
        result = run_settlement_workflow(
            db,
            task_id=task.task_id,
            actor=user,
            compute_mode=task_payload.compute_mode,
            algorithm_code=task_payload.algorithm_code,
            commit=False,
        )
    except (PermissionError, ValueError, OSError, KeyError) as exc:
        db.rollback()
        for data_ref in new_data_refs:
            LocalDomainVault.delete(data_ref)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    analysis = None
    analysis_request = payload.privacy_analysis_request
    if analysis_request:
        analysis_ids = [
            item.upload_id
            for item in uploaded
            if item.asset_type == "USER_LOAD_CURVE"
        ]
        if analysis_ids:
            datasets = [db.get(DataUpload, item) for item in analysis_ids]
            if all(item and item.asset_type == "USER_LOAD_CURVE" for item in datasets):
                analysis_record = PrivacyAnalysisJob(
                    analysis_name=analysis_request.analysis_name,
                    analysis_type=analysis_request.analysis_type,
                    dataset_ids_json=analysis_ids,
                    privacy_level=analysis_request.privacy_level,
                    privacy_budget=analysis_request.privacy_budget,
                    purpose=analysis_request.scenario_code,
                    output_json={},
                    status="RUNNING",
                )
                db.add(analysis_record)
                db.flush()
                try:
                    run_privacy_analysis(db, analysis_record, commit=False)
                except (ValueError, OSError, KeyError) as exc:
                    db.rollback()
                    for data_ref in new_data_refs:
                        LocalDomainVault.delete(data_ref)
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                analysis = {
                    **model_dict(analysis_record),
                    "result_json": analysis_record.output_json,
                    "raw_records_returned": False,
                }

    task.verification_profile_json = {
        **(task.verification_profile_json or {}),
        "mode": "VIRTUAL_SIMULATION" if payload.is_simulated else "SCENE_DATA_METADATA",
        "is_simulated": payload.is_simulated,
    }
    db.commit()
    result["task"] = task_summary(db, task)
    result["verification_profile"] = result["task"].get("verification_profile")
    summary_result = next(
        (item for item in result.get("results", []) if item.get("result_scope") == "SUMMARY"),
        None,
    )
    lineage_trace = next(
        (
            item.get("trace_id")
            for item in result.get("data_space", {}).get("agreements", [])
            if item.get("trace_id")
        ),
        trace_id(),
    )
    lineage = emit_settlement_lineage(
        task,
        uploads=uploaded,
        result_hash=(summary_result or {}).get("result_hash", ""),
        trace_id_value=lineage_trace,
    )
    return {
        "fixture_id": payload.fixture_id,
        "uploads": [model_dict(item) for item in uploaded],
        "privacy_analysis": analysis,
        "lineage": lineage,
        **result,
    }


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
        "raw_data_transferred": False,
        "trusted_acquisition": "校验通过后才登记 DataRef",
        "secure_transport": "HTTPS/MQTT/WebSocket 接口边界已预留",
        "maturity_note": "虚拟仿真验证实现；真实 EDC、隐私计算引擎和联盟链通过适配器替换。",
        "mvp_adapters": {
            "policy": OPAPolicyAdapter.status(),
            "grid": PandapowerGridAdapter.status(),
            "solar_resource": PvlibSolarAdapter.status(),
            "data_package": FrictionlessCatalogAdapter.status(),
            "metadata_analytics": DuckDBMetadataAdapter.status(),
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
    user: User = Depends(require_roles("EXCHANGE", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
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
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(PrivacyComputeJob).order_by(PrivacyComputeJob.created_at.desc())
    scoped_ids = _task_ids_for_user(db, user)
    if scoped_ids is not None:
        query = query.where(PrivacyComputeJob.task_id.in_(scoped_ids or ["__none__"]))
    return [model_dict(item) for item in db.scalars(query).all()]


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
    payload = model_dict(job)
    if user.role_code in {"GENERATOR", "RETAILER"}:
        payload["result_json"] = {
            "output_hash": job.output_hash,
            "raw_data_exposed": False,
            "status": job.status,
        }
    return payload


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
    user: User = Depends(require_roles("GENERATOR", "RETAILER", "EXCHANGE")),
    db: Session = Depends(get_db),
) -> dict:
    result = db.get(SettlementResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="结算结果不存在")
    if user.role_code in {"GENERATOR", "RETAILER"} and result.org_id != user.org_id:
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
        return {
            "result_id": result.result_id,
            "confirm_status": result.confirm_status,
            "signature": existing.signature_value,
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
    return {"result_id": result.result_id, "confirm_status": result.confirm_status, "signature": signature_value}


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
        output_json={"compute_strategy": strategy},
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
