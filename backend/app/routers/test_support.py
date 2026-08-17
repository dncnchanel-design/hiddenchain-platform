from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_roles
from ..models import (
    AnomalyEvent,
    BlockchainEvidence,
    DataUpload,
    DidIdentity,
    Organization,
    PrivacyAnalysisJob,
    SettlementRule,
    SettlementTask,
    Signature,
    TaskParticipant,
    User,
)
from ..schemas import DataUploadCreate
from ..test_schemas import AnomalyInjectCreate, SettlementImportFile
from ..security import sha256_json, sign_value
from ..services.common import add_audit_log, model_dict, trace_id
from ..services.vault import LocalDomainVault
from ..services.workflow import emit_settlement_lineage, run_privacy_analysis, run_settlement_workflow, task_summary


router = APIRouter(tags=["test-support"])


@router.get("/auth/test-users")
def test_users() -> list[dict]:
    """Return deterministic credentials only in development and test apps."""

    return [
        {"role": "GENERATOR", "username": "generator", "password": "generator123", "label": "发电企业"},
        {"role": "RETAILER", "username": "retailer", "password": "retailer123", "label": "售电企业"},
        {"role": "EXCHANGE", "username": "exchange", "password": "exchange123", "label": "交易中心"},
        {"role": "REGULATOR", "username": "regulator", "password": "regulator123", "label": "监管方"},
        {"role": "ADMIN", "username": "admin", "password": "admin123", "label": "系统管理员"},
    ]


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
    """Load a non-production test fixture and execute its validation flow."""

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
        analysis_ids = [item.upload_id for item in uploaded if item.asset_type == "USER_LOAD_CURVE"]
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


@router.post("/anomalies/inject", status_code=status.HTTP_201_CREATED)
def inject_anomaly(
    payload: AnomalyInjectCreate,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    task = db.get(SettlementTask, payload.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    titles = {
        "HASH_MISMATCH": "证据哈希不一致",
        "UNAUTHORIZED_ACCESS": "越权访问已阻断",
        "MISSING_SIGNATURE": "结算签名缺失",
        "POLICY_DENIED": "数据用途策略拒绝",
    }
    existing_open = db.scalar(
        select(AnomalyEvent).where(
            AnomalyEvent.task_id == task.task_id,
            AnomalyEvent.status == "OPEN",
        )
    )
    previous_task_status = (
        existing_open.evidence_json.get("previous_task_status", task.status)
        if existing_open
        else task.status
    )
    previous_risk_level = (
        existing_open.evidence_json.get("previous_risk_level", task.risk_level)
        if existing_open
        else task.risk_level
    )
    event = AnomalyEvent(
        task_id=task.task_id,
        event_type=payload.event_type,
        risk_level="HIGH" if payload.event_type in {"HASH_MISMATCH", "MISSING_SIGNATURE"} else "MEDIUM",
        title=titles[payload.event_type],
        description="测试环境注入的可追溯异常，不代表生产事件。",
        evidence_json={
            "injected": True,
            "actor": user.username,
            "capsule_id": task.capsule_id,
            "previous_task_status": previous_task_status,
            "previous_risk_level": previous_risk_level,
        },
        status="OPEN",
    )
    db.add(event)
    db.flush()
    if payload.mutate_evidence and payload.event_type == "HASH_MISMATCH":
        evidence = db.scalar(
            select(BlockchainEvidence)
            .where(BlockchainEvidence.task_id == task.task_id)
            .order_by(BlockchainEvidence.block_height.desc())
        )
        if evidence:
            evidence.payload_json = {**evidence.payload_json, "tampered_test_flag": True}
            event.evidence_json = {**event.evidence_json, "evidence_id": evidence.evidence_id}
    task.risk_level = event.risk_level
    task.status = "EXCEPTION"
    task.current_stage = "风险事件待处置"
    add_audit_log(
        db,
        action="INJECT_TEST_ANOMALY",
        target_type="ANOMALY_EVENT",
        target_id=event.event_id,
        result="SUCCESS",
        user=user,
        details={"event_type": event.event_type, "mutate_evidence": payload.mutate_evidence},
    )
    db.commit()
    db.refresh(event)
    return model_dict(event)


@router.get("/trusted-execution/example")
def execution_example() -> dict:
    return {
        "description": "能源局查询上月电煤库存变化与火电出力、电网负荷平衡趋势的跨能源受控调用",
        "request": {
            "question": "分析上月由于电煤库存变化引起的火电出力与电网负荷平衡趋势",
            "consumer_role": "ENERGY_BUREAU",
            "purpose": "CROSS_ENERGY_TREND",
            "target_data_types": ["COAL_INVENTORY", "POWER_THERMAL_OUTPUT", "GRID_LOAD"],
            "group_by": ["region", "period"],
            "output_mode": "SUMMARY",
        },
        "expected_policy": {
            "COAL_INVENTORY": "AGGREGATE",
            "POWER_THERMAL_OUTPUT": "AGGREGATE",
            "GRID_LOAD": "AGGREGATE",
            "raw_data_returned": False,
        },
    }
