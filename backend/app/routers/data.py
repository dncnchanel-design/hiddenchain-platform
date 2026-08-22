from __future__ import annotations

import math
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..models import DataSpaceAgreement, DataUpload, DataUsageRequest, DidIdentity, Organization, Signature, User
from ..schemas import (
    DataUploadCreate,
    DataUsageRequestCreate,
    DataUsageRequestDecision,
    DataUsageRequestReview,
)
from ..security import sign_value
from ..services.common import add_audit_log, model_dict
from ..services.adapters import DATA_PRODUCT_CATALOG, DataSpaceConnectorAdapter
from ..services.datapackage import FrictionlessCatalogAdapter
from ..services.dataspace import DataspaceProtocolAdapter
from ..services.vault import LocalDomainVault
from ..services.trust_domain import TrustDomainError, verify_active_identity
from ..services.excel_upload import (
    MAX_EXCEL_BYTES,
    SHEET_SPECS,
    ExcelWorkbookError,
    ParsedExcelRow,
    ParsedExcelWorkbook,
    normalize_row_values,
    parse_excel_workbook,
)
from ..services.asset_registry import (
    project_upload_to_asset_registry,
    redacted_asset_projection,
)
from ..services.data_usage_requests import (
    UsageRequestError,
    create_request,
    get_request,
    list_requests,
    to_payload as usage_request_payload,
    transition_request,
)


router = APIRouter(prefix="/data", tags=["data"])


def _active_owner_identity(db: Session, org_id: str) -> DidIdentity:
    identity = db.scalar(
        select(DidIdentity)
        .where(
            DidIdentity.owner_id == org_id,
            DidIdentity.org_id == org_id,
            DidIdentity.owner_type == "ORG",
        )
        .order_by(DidIdentity.created_at.desc())
    )
    if identity is None:
        raise HTTPException(status_code=403, detail="当前主体缺少有效 DID")
    try:
        return verify_active_identity(db, identity.did_id)
    except TrustDomainError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc


GENERATOR_ASSETS = {"GENERATION_DATA", "RENEWABLE_FORECAST"}
RETAILER_ASSETS = {"RETAIL_DATA", "USER_LOAD_CURVE", "VPP_RESOURCE"}
ALL_ASSETS = GENERATOR_ASSETS | RETAILER_ASSETS | {"GRID_CONSTRAINT"}
EXCEL_METADATA_FIELDS = {
    "function_scope",
    "task_reference",
    "rule_version",
    "algorithm_code",
    "audit_requirement",
    "risk_level",
    "expected_action",
    "recommended_role",
    "sample_marker",
}


def _asset_access_error(asset_type: str, role_code: str, *, allow_admin_grid: bool = False) -> str | None:
    if role_code == "REGULATOR":
        return "监管角色仅可查看数据，不能执行上传"
    if asset_type not in ALL_ASSETS:
        return "资产类型不在系统支持范围内"
    if role_code == "GENERATOR" and asset_type not in GENERATOR_ASSETS:
        return "发电企业只能上传发电计量或新能源预测"
    if role_code == "RETAILER" and asset_type not in RETAILER_ASSETS:
        return "售电企业只能上传售电履约、用户负荷或虚拟电厂资源"
    if asset_type == "GRID_CONSTRAINT" and role_code != "EXCHANGE" and not (allow_admin_grid and role_code == "ADMIN"):
        return "调度安全边界只能由交易中心或管理员受控接入"
    if asset_type == "USER_LOAD_CURVE" and role_code not in {"RETAILER", "EXCHANGE", "ADMIN"}:
        return "用户负荷曲线只能由售电企业、交易中心或管理员接入"
    return None


def _owner_context(
    db: Session,
    payload: DataUploadCreate,
    user: User,
) -> tuple[Organization, DidIdentity]:
    owner_org_id = user.org_id
    if payload.owner_org_id and payload.owner_org_id != owner_org_id:
        raise HTTPException(status_code=403, detail="不能以其他组织名义登记或签署数据")
    owner = db.get(Organization, owner_org_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="数据提供方不存在")
    if owner.status != "ACTIVE":
        raise HTTPException(status_code=403, detail="数据提供方组织不可用")
    access_error = _asset_access_error(payload.asset_type, user.role_code)
    if access_error:
        raise HTTPException(status_code=403, detail=access_error)
    return owner, _active_owner_identity(db, owner_org_id)


def _persist_upload(
    db: Session,
    payload: DataUploadCreate,
    user: User,
    *,
    owner: Organization | None = None,
    signer_identity: DidIdentity | None = None,
    upload_id: str | None = None,
    excel_metadata: dict[str, Any] | None = None,
) -> tuple[DataUpload, str]:
    if owner is None or signer_identity is None:
        owner, signer_identity = _owner_context(db, payload, user)
    record_kwargs: dict[str, Any] = {
        "asset_type": payload.asset_type,
        "owner_org_id": owner.org_id,
        "trade_batch_no": payload.trade_batch_no,
        "label": payload.label,
        "data_ref": "pending",
        "data_hash": "pending",
        "commitment": "pending",
        "schema_version": payload.schema_version,
        "validation_status": "PENDING",
        "summary_json": {},
        "ingress_json": payload.ingress.model_dump(),
    }
    if upload_id:
        record_kwargs["upload_id"] = upload_id
    record = DataUpload(**record_kwargs)
    db.add(record)
    db.flush()
    data_ref, data_hash, commitment = LocalDomainVault.write(
        owner.org_id, record.upload_id, payload.local_payload
    )
    record.data_ref = data_ref
    record.data_hash = data_hash
    record.commitment = commitment
    record.validation_status = "PASSED"
    record.summary_json = {
        "record_count": payload.local_payload.get("record_count", 1),
        "period": payload.local_payload.get("period"),
        "raw_data_stored_in_business_db": False,
        "trusted_acquisition": True,
        "secure_transport": payload.ingress.model_dump(),
        **({"excel_import": excel_metadata} if excel_metadata else {}),
    }
    record.signature_value = sign_value(
        {"upload_id": record.upload_id, "data_hash": data_hash},
        signer_identity.did_id,
    )
    db.add(
        Signature(
            signer_org_id=owner.org_id,
            signer_did=signer_identity.did_id,
            target_type="DATA_UPLOAD",
            target_id=record.upload_id,
            target_hash=data_hash,
            signature_value=record.signature_value,
            verify_status="VALID",
        )
    )
    project_upload_to_asset_registry(db, record)
    add_audit_log(
        db,
        action="UPLOAD_DATA_REFERENCE",
        target_type="DATA_UPLOAD",
        target_id=record.upload_id,
        result="SUCCESS",
        user=user,
        details={
            "asset_type": payload.asset_type,
            "data_hash": data_hash,
            "raw_payload_in_db": False,
            "excel_batch": bool(excel_metadata),
        },
    )
    return record, data_ref


def _upload_response(db: Session, record: DataUpload, owner: Organization) -> dict:
    return {
        **model_dict(record),
        "owner_org_name": owner.org_name,
        "raw_payload_exposed": False,
        "formal_asset": redacted_asset_projection(db, record),
    }


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _as_number(value: Any, field: str, errors: list[dict[str, Any]], row: ParsedExcelRow) -> float | None:
    if isinstance(value, bool) or value is None or _as_text(value) == "":
        errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": field, "message": "必须填写非负数"})
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if not math.isfinite(number) or number < 0:
        errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": field, "message": "必须填写非负数"})
        return None
    return int(number) if number.is_integer() else number


def _as_positive_int(value: Any, field: str, errors: list[dict[str, Any]], row: ParsedExcelRow) -> int | None:
    number = _as_number(value, field, errors, row)
    if number is None or not float(number).is_integer() or number <= 0:
        if number is not None:
            errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": field, "message": "必须填写大于 0 的整数"})
        return None
    return int(number)


def _as_bool(value: Any, field: str, errors: list[dict[str, Any]], row: ParsedExcelRow) -> bool | None:
    normalized = _as_text(value).upper()
    if normalized in {"TRUE", "1", "是", "通过", "PASS", "PASSED"}:
        return True
    if normalized in {"FALSE", "0", "否", "未通过", "FAIL", "FAILED"}:
        return False
    errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": field, "message": "请填写通过/未通过或 TRUE/FALSE"})
    return None


def _row_to_payload(
    row: ParsedExcelRow,
    workbook: ParsedExcelWorkbook,
    user: User,
) -> tuple[DataUploadCreate | None, dict[str, Any], list[dict[str, Any]]]:
    values = normalize_row_values(row.values)
    errors: list[dict[str, Any]] = []
    allowed_types = SHEET_SPECS[row.sheet_name]
    asset_type = _as_text(values.get("asset_type")) or (allowed_types[0] if len(allowed_types) == 1 else "")
    if asset_type not in allowed_types:
        errors.append({
            "sheet": row.sheet_name,
            "row": row.row_number,
            "field": "资产类型",
            "message": f"该工作表只允许：{'、'.join(allowed_types)}",
        })
    # The Excel page is a controlled batch boundary.  It may be used by an
    # administrator to load the complete template into the administrator's
    # own organization for review; direct single-record grid registration
    # remains exchange-only in _owner_context.
    role_error = _asset_access_error(asset_type, user.role_code, allow_admin_grid=True) if asset_type else None
    if role_error:
        errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": "资产类型", "message": role_error})

    label = _as_text(values.get("label"))
    batch = _as_text(values.get("trade_batch_no"))
    period = _as_text(values.get("period"))
    if len(label) < 2 or len(label) > 128:
        errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": "数据资产名称", "message": "长度必须在 2 至 128 个字符之间"})
    if len(batch) < 3 or len(batch) > 64:
        errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": "批次编号", "message": "长度必须在 3 至 64 个字符之间"})
    if not period:
        errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": "数据期间", "message": "必须填写数据期间"})
    record_count = _as_positive_int(values.get("record_count"), "记录数", errors, row)
    local_payload: dict[str, Any] = {"record_count": record_count or 1, "period": period}

    if asset_type in {"GENERATION_DATA", "RETAIL_DATA"}:
        energy = _as_number(values.get("energy_mwh"), "电量MWh", errors, row)
        if energy is not None:
            local_payload["energy_mwh"] = energy
    elif asset_type == "RENEWABLE_FORECAST":
        forecast_energy = _as_number(values.get("forecast_energy_mwh"), "预测电量MWh", errors, row)
        accuracy = _as_number(values.get("forecast_accuracy_pct"), "预测准确率%", errors, row)
        if accuracy is not None and accuracy > 100:
            errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": "预测准确率%", "message": "不能超过 100"})
        if forecast_energy is not None:
            local_payload["forecast_energy_mwh"] = forecast_energy
        if accuracy is not None:
            local_payload["forecast_accuracy_pct"] = accuracy
    elif asset_type == "USER_LOAD_CURVE":
        curve: list[float | int] = []
        for hour in range(24):
            value = _as_number(values.get(f"load_{hour:02d}"), f"负荷{hour:02d}时", errors, row)
            curve.append(value if value is not None else 0)
        if len(curve) == 24 and not any(
            error["field"].startswith("负荷") for error in errors
        ):
            local_payload["load_curve"] = curve
    elif asset_type == "VPP_RESOURCE":
        for source_key, field_name in (
            ("adjustable_capacity_mw", "可调容量MW"),
            ("storage_energy_mwh", "储能电量MWh"),
            ("response_minutes", "响应时间分钟"),
        ):
            value = _as_number(values.get(source_key), field_name, errors, row)
            if value is not None:
                local_payload[source_key] = value
    elif asset_type == "GRID_CONSTRAINT":
        passed = _as_bool(values.get("n_minus_one_passed"), "N-1校核", errors, row)
        residual = _as_number(values.get("max_residual_imbalance_mwh"), "剩余偏差上限MWh", errors, row)
        margin = _as_number(values.get("congestion_margin_pct"), "拥塞裕度%", errors, row)
        if margin is not None and margin > 100:
            errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": "拥塞裕度%", "message": "不能超过 100"})
        if passed is not None:
            local_payload["n_minus_one_passed"] = passed
        if residual is not None:
            local_payload["max_residual_imbalance_mwh"] = residual
        if margin is not None:
            local_payload["congestion_margin_pct"] = margin

    metadata = {
        key: _as_text(values[key])
        for key in EXCEL_METADATA_FIELDS
        if key in values and _as_text(values[key])
    }
    metadata.update({"sheet_name": row.sheet_name, "excel_row": row.row_number, "file_digest": workbook.file_digest})
    ingress = {
        "source_type": _as_text(values.get("source_type")) or "EXCEL_BATCH_UPLOAD",
        "protocol": _as_text(values.get("protocol")) or "HTTPS",
        "stage": "BUSINESS",
        "encryption": _as_text(values.get("encryption")) or "TLS1.3",
        "attestation": _as_text(values.get("attestation")) or "NOT_PROVIDED",
    }
    try:
        payload = DataUploadCreate.model_validate({
            "asset_type": asset_type,
            "trade_batch_no": batch,
            "label": label,
            "schema_version": "v1.0",
            "ingress": ingress,
            "local_payload": local_payload,
        })
    except ValidationError as exc:
        for item in exc.errors():
            location = ".".join(str(part) for part in item.get("loc", ())) or "数据"
            errors.append({"sheet": row.sheet_name, "row": row.row_number, "field": location, "message": str(item.get("msg", "格式错误"))})
        payload = None
    return payload if not errors else None, metadata, errors


def _prepare_excel(
    content: bytes,
    user: User,
) -> tuple[ParsedExcelWorkbook | None, list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        workbook = parse_excel_workbook(content)
    except ExcelWorkbookError as exc:
        return None, [], [{"sheet": "工作簿", "row": 0, "field": "文件", "message": str(exc)}]
    prepared: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row in workbook.rows:
        payload, metadata, row_errors = _row_to_payload(row, workbook, user)
        errors.extend(row_errors)
        if payload is not None:
            deterministic_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"hiddenchain:excel:{user.org_id}:{workbook.file_digest}:{row.sheet_name}:{row.row_number}",
            ))
            prepared.append({"payload": payload, "metadata": metadata, "upload_id": deterministic_id, "row": row})
    return workbook, prepared, errors


def _excel_result(
    workbook: ParsedExcelWorkbook | None,
    prepared: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    *,
    file_name: str,
    user: User,
    imported_count: int = 0,
    idempotent_replay: bool = False,
) -> dict[str, Any]:
    return {
        "valid": workbook is not None and not errors and len(prepared) == sum((workbook.sheet_row_counts if workbook else {}).values()),
        "file_name": file_name,
        "file_digest": workbook.file_digest if workbook else None,
        "role_code": user.role_code,
        "owner_org_id": user.org_id,
        "sheet_count": len(workbook.sheet_names) if workbook else 0,
        "row_count": sum((workbook.sheet_row_counts if workbook else {}).values()),
        "prepared_count": len(prepared),
        "imported_count": imported_count,
        "idempotent_replay": idempotent_replay,
        "sheets": [
            {"name": name, "row_count": workbook.sheet_row_counts[name], "allowed_asset_types": list(SHEET_SPECS[name])}
            for name in (workbook.sheet_names if workbook else ())
        ],
        "errors": errors[:500],
    }


async def _read_excel_file(file: UploadFile) -> tuple[str, bytes]:
    file_name = file.filename or ""
    if not file_name.lower().endswith(".xlsx"):
        raise HTTPException(status_code=415, detail="只支持 .xlsx 格式的 Excel 文件")
    content = await file.read(MAX_EXCEL_BYTES + 1)
    if len(content) > MAX_EXCEL_BYTES:
        raise HTTPException(status_code=413, detail="Excel 文件不能超过 8 MB")
    return file_name, content


@router.get("/catalog")
def data_catalog(
    asset_type: str | None = None,
    trade_batch_no: str | None = None,
    owner_org_id: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    if user.role_code in {"GENERATOR", "RETAILER"}:
        owner_org_id = user.org_id
    entries = DataSpaceConnectorAdapter.catalog(
        db,
        asset_type=asset_type,
        trade_batch_no=trade_batch_no,
        owner_org_id=owner_org_id,
    )
    return {
        "protocol_version": DataSpaceConnectorAdapter.protocol_version,
        "catalog_id": "catalog://hiddenchain/energy-v1",
        "semantic_version": "energy-v1",
        "supported_asset_types": sorted(DATA_PRODUCT_CATALOG),
        "entries": entries,
        "raw_data_exposed": False,
    }


@router.get("/catalog/package")
def data_catalog_package(
    asset_type: str | None = None,
    trade_batch_no: str | None = None,
    owner_org_id: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    if user.role_code in {"GENERATOR", "RETAILER"}:
        owner_org_id = user.org_id
    entries = DataSpaceConnectorAdapter.catalog(
        db,
        asset_type=asset_type,
        trade_batch_no=trade_batch_no,
        owner_org_id=owner_org_id,
    )
    try:
        return FrictionlessCatalogAdapter.build(entries)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="标准数据目录适配器暂不可用") from exc


@router.get("/catalog/dataspace")
def data_catalog_dataspace_protocol(
    asset_type: str | None = None,
    trade_batch_no: str | None = None,
    owner_org_id: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    if user.role_code in {"GENERATOR", "RETAILER"}:
        owner_org_id = user.org_id
    entries = DataSpaceConnectorAdapter.catalog(
        db,
        asset_type=asset_type,
        trade_batch_no=trade_batch_no,
        owner_org_id=owner_org_id,
    )
    return DataspaceProtocolAdapter.build(entries)


@router.get("/agreements")
def list_data_space_agreements(
    task_id: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(DataSpaceAgreement).order_by(DataSpaceAgreement.created_at.desc())
    if task_id:
        query = query.where(DataSpaceAgreement.task_id == task_id)
    records = db.scalars(query).all()
    if user.role_code in {"GENERATOR", "RETAILER"}:
        records = [
            item
            for item in records
            if item.provider_org_id == user.org_id or item.consumer_org_id == user.org_id
        ]
    org_names = {org.org_id: org.org_name for org in db.scalars(select(Organization)).all()}
    return [
        {
            **model_dict(item),
            "provider_org_name": org_names.get(item.provider_org_id),
            "consumer_org_name": org_names.get(item.consumer_org_id),
        }
        for item in records
    ]


def _usage_request_error(exc: UsageRequestError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.detail},
    )


@router.post("/access-requests", status_code=status.HTTP_201_CREATED)
def create_data_usage_request(
    payload: DataUsageRequestCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(require_roles("GENERATOR", "RETAILER", "EXCHANGE")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        request, replay = create_request(
            db,
            payload,
            user,
            idempotency_key=idempotency_key,
        )
        if replay:
            response.status_code = status.HTTP_200_OK
        result = usage_request_payload(db, request, user)
        result["idempotent_replay"] = replay
        return result
    except UsageRequestError as exc:
        raise _usage_request_error(exc) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "REQUEST_CREATE_FAILED", "message": "申请创建失败，数据库未写入"},
        ) from exc


@router.get("/access-requests")
def list_data_usage_requests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    inbox: bool = Query(default=False),
    mine: bool = Query(default=False),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        records, total = list_requests(
            db,
            user,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
            provider_inbox=inbox,
            applicant_outbox=mine,
        )
        return {
            "items": [usage_request_payload(db, item, user) for item in records],
            "total": total,
            "page": page,
            "page_size": page_size,
            "inbox": inbox,
            "mine": mine,
        }
    except UsageRequestError as exc:
        raise _usage_request_error(exc) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "REQUEST_LIST_FAILED", "message": "申请列表读取失败"},
        ) from exc


@router.get("/access-requests/{request_id}")
def get_data_usage_request(
    request_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        request = get_request(db, request_id, user)
        return usage_request_payload(db, request, user)
    except UsageRequestError as exc:
        raise _usage_request_error(exc) from exc


def _transition_data_usage_request(
    request_id: str,
    *,
    action: str,
    reason: str,
    if_match: str | None,
    user: User,
    db: Session,
) -> dict[str, Any]:
    try:
        request = get_request(db, request_id, user)
        request, replay = transition_request(
            db,
            request,
            user,
            action=action,
            reason=reason,
            if_match=if_match,
        )
        payload = usage_request_payload(db, request, user)
        payload["idempotent_replay"] = replay
        return payload
    except UsageRequestError as exc:
        raise _usage_request_error(exc) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "REQUEST_TRANSITION_FAILED", "message": "申请状态变更失败，数据库未写入"},
        ) from exc


@router.post("/access-requests/{request_id}/review")
def review_data_usage_request(
    request_id: str,
    payload: DataUsageRequestReview,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _transition_data_usage_request(
        request_id,
        action="review",
        reason=payload.note,
        if_match=if_match,
        user=user,
        db=db,
    )


@router.post("/access-requests/{request_id}/approve")
def approve_data_usage_request(
    request_id: str,
    payload: DataUsageRequestDecision,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _transition_data_usage_request(
        request_id,
        action="approve",
        reason=payload.reason,
        if_match=if_match,
        user=user,
        db=db,
    )


@router.post("/access-requests/{request_id}/reject")
def reject_data_usage_request(
    request_id: str,
    payload: DataUsageRequestDecision,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _transition_data_usage_request(
        request_id,
        action="reject",
        reason=payload.reason,
        if_match=if_match,
        user=user,
        db=db,
    )


@router.post("/access-requests/{request_id}/withdraw")
def withdraw_data_usage_request(
    request_id: str,
    payload: DataUsageRequestDecision | None = None,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        request = get_request(db, request_id, user)
        if user.role_code != "ADMIN" and request.applicant_org_id != user.org_id:
            raise UsageRequestError(403, "APPLICANT_WITHDRAW_REQUIRED", "仅申请方可以撤回自己的申请")
    except UsageRequestError as exc:
        raise _usage_request_error(exc) from exc
    return _transition_data_usage_request(
        request_id,
        action="revoke",
        reason=payload.reason if payload else "申请方撤回",
        if_match=if_match,
        user=user,
        db=db,
    )


@router.post("/access-requests/{request_id}/revoke")
def revoke_data_usage_request(
    request_id: str,
    payload: DataUsageRequestDecision,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        request = get_request(db, request_id, user)
        if user.role_code != "ADMIN" and request.provider_org_id != user.org_id:
            raise UsageRequestError(403, "PROVIDER_REVOKE_REQUIRED", "仅资产提供方可以撤销授权")
    except UsageRequestError as exc:
        raise _usage_request_error(exc) from exc
    return _transition_data_usage_request(
        request_id,
        action="revoke",
        reason=payload.reason,
        if_match=if_match,
        user=user,
        db=db,
    )


@router.get("/uploads")
def list_uploads(
    asset_type: str | None = None,
    task_id: str | None = None,
    trade_batch_no: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(DataUpload).order_by(DataUpload.created_at.desc())
    if asset_type:
        query = query.where(DataUpload.asset_type == asset_type)
    if task_id:
        query = query.where(DataUpload.task_id == task_id)
    if trade_batch_no:
        query = query.where(DataUpload.trade_batch_no == trade_batch_no)
    if user.role_code in {"GENERATOR", "RETAILER"}:
        query = query.where(DataUpload.owner_org_id == user.org_id)
    records = db.scalars(query).all()
    org_names = {org.org_id: org.org_name for org in db.scalars(select(Organization)).all()}
    return [
        {
            **model_dict(item),
            "owner_org_name": org_names.get(item.owner_org_id),
            "raw_payload_exposed": False,
            "trusted_acquisition": bool(item.ingress_json),
            "secure_transport": item.ingress_json or {
                "protocol": "HTTPS",
                "encryption": "NOT_PROVIDED",
                "attestation": "NOT_PROVIDED",
            },
            "formal_asset": redacted_asset_projection(db, item),
        }
        for item in records
    ]


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
def create_upload(
    payload: DataUploadCreate,
    user: User = Depends(require_roles("GENERATOR", "RETAILER", "EXCHANGE", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    owner, signer_identity = _owner_context(db, payload, user)
    record, _ = _persist_upload(
        db,
        payload,
        user,
        owner=owner,
        signer_identity=signer_identity,
    )
    db.commit()
    db.refresh(record)
    return _upload_response(db, record, owner)


@router.post("/uploads/excel/validate")
async def validate_excel_upload(
    file: UploadFile = File(...),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
) -> dict[str, Any]:
    file_name, content = await _read_excel_file(file)
    workbook, prepared, errors = _prepare_excel(content, user)
    return _excel_result(workbook, prepared, errors, file_name=file_name, user=user)


@router.post("/uploads/excel/import")
async def import_excel_upload(
    file: UploadFile = File(...),
    user: User = Depends(require_roles("GENERATOR", "RETAILER", "EXCHANGE", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    file_name, content = await _read_excel_file(file)
    workbook, prepared, errors = _prepare_excel(content, user)
    result = _excel_result(workbook, prepared, errors, file_name=file_name, user=user)
    if not workbook or errors or not prepared or not result["valid"]:
        raise HTTPException(status_code=422, detail=f"Excel 校验失败，共 {len(errors)} 个错误")

    upload_ids = [item["upload_id"] for item in prepared]
    existing = db.scalars(select(DataUpload).where(DataUpload.upload_id.in_(upload_ids))).all()
    if existing:
        matching = [
            item for item in existing
            if item.summary_json.get("excel_import", {}).get("file_digest") == workbook.file_digest
        ]
        if len(existing) == len(prepared) and len(matching) == len(prepared):
            result["idempotent_replay"] = True
            result["imported_count"] = 0
            return result
        raise HTTPException(status_code=409, detail="该 Excel 批次已经部分存在，请更换文件或批次后重试")

    owner: Organization | None = None
    signer_identity: DidIdentity | None = None
    data_refs: list[str] = []
    try:
        owner = db.get(Organization, user.org_id)
        if owner is None or owner.status != "ACTIVE":
            raise HTTPException(status_code=403, detail="当前组织不可用")
        signer_identity = _active_owner_identity(db, user.org_id)
        for item in prepared:
            data_refs.append(f"{LocalDomainVault.scheme}{owner.org_id}/{item['upload_id']}")
            record, data_ref = _persist_upload(
                db,
                item["payload"],
                user,
                owner=owner,
                signer_identity=signer_identity,
                upload_id=item["upload_id"],
                excel_metadata=item["metadata"],
            )
        add_audit_log(
            db,
            action="UPLOAD_EXCEL_BATCH",
            target_type="EXCEL_IMPORT",
            target_id=workbook.file_digest,
            result="SUCCESS",
            user=user,
            details={
                "file_name": file_name,
                "sheet_count": len(workbook.sheet_names),
                "row_count": len(prepared),
                "atomic": True,
            },
        )
        db.commit()
    except HTTPException:
        db.rollback()
        for data_ref in data_refs:
            LocalDomainVault.delete(data_ref)
        raise
    except Exception as exc:
        db.rollback()
        for data_ref in data_refs:
            LocalDomainVault.delete(data_ref)
        raise HTTPException(status_code=500, detail="Excel 批量导入失败，数据库未写入数据") from exc

    result["imported_count"] = len(prepared)
    result["idempotent_replay"] = False
    return result


@router.post("/{upload_id}/sign")
def sign_upload(
    upload_id: str,
    user: User = Depends(require_roles("GENERATOR", "RETAILER", "EXCHANGE")),
    db: Session = Depends(get_db),
) -> dict:
    upload = db.get(DataUpload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="数据记录不存在")
    if upload.owner_org_id != user.org_id:
        raise HTTPException(status_code=403, detail="不能签署其他主体的数据")
    signer_identity = _active_owner_identity(db, upload.owner_org_id)
    if upload.signature_value:
        existing = db.scalar(
            select(Signature)
            .where(
                Signature.target_type == "DATA_UPLOAD",
                Signature.target_id == upload.upload_id,
                Signature.target_hash == upload.data_hash,
                Signature.signer_org_id == upload.owner_org_id,
                Signature.signer_did == signer_identity.did_id,
                Signature.verify_status == "VALID",
            )
            .order_by(Signature.created_at.desc())
        )
        if existing:
            return {"signature_id": existing.signature_id, "verify_status": existing.verify_status}
    signer_did = signer_identity.did_id
    signature_value = sign_value(
        {"upload_id": upload.upload_id, "data_hash": upload.data_hash},
        signer_did,
    )
    signature = Signature(
        signer_org_id=upload.owner_org_id,
        signer_did=signer_did,
        target_type="DATA_UPLOAD",
        target_id=upload.upload_id,
        target_hash=upload.data_hash,
        signature_value=signature_value,
        verify_status="VALID",
    )
    db.add(signature)
    upload.signature_value = signature_value
    add_audit_log(
        db,
        action="SIGN_DATA_COMMITMENT",
        target_type="DATA_UPLOAD",
        target_id=upload.upload_id,
        result="SUCCESS",
        user=user,
        details={"signature_id": signature.signature_id},
    )
    db.commit()
    return {"signature_id": signature.signature_id, "verify_status": "VALID"}
