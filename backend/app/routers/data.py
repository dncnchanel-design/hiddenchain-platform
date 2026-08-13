from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, get_current_user, require_roles
from ..models import DataSpaceAgreement, DataUpload, DidIdentity, Organization, Signature, User
from ..schemas import DataUploadCreate
from ..security import sign_value
from ..services.common import add_audit_log, model_dict
from ..services.adapters import DATA_PRODUCT_CATALOG, DataSpaceConnectorAdapter
from ..services.vault import LocalDomainVault


router = APIRouter(prefix="/data", tags=["data"])


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
    return [model_dict(item) for item in records]


@router.get("/uploads")
def list_uploads(
    asset_type: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(DataUpload).order_by(DataUpload.created_at.desc())
    if asset_type:
        query = query.where(DataUpload.asset_type == asset_type)
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
            "secure_transport": item.ingress_json or {"protocol": "HTTPS", "encryption": "TLS1.3"},
        }
        for item in records
    ]


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
def create_upload(
    payload: DataUploadCreate,
    user: User = Depends(require_roles("GENERATOR", "RETAILER", "EXCHANGE", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    owner_org_id = user.org_id
    if payload.owner_org_id and user.role_code in {"EXCHANGE", "ADMIN"}:
        owner_org_id = payload.owner_org_id
    owner = db.get(Organization, owner_org_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="数据提供方不存在")
    if user.role_code == "GENERATOR" and payload.asset_type not in {
        "GENERATION_DATA",
        "RENEWABLE_FORECAST",
    }:
        raise HTTPException(status_code=403, detail="发电企业只能登记计量数据或新能源出力预测")
    if user.role_code == "RETAILER" and payload.asset_type not in {
        "RETAIL_DATA",
        "USER_LOAD_CURVE",
        "VPP_RESOURCE",
    }:
        raise HTTPException(status_code=403, detail="售电企业只能登记售电、用户负荷或虚拟电厂资源数据")
    if payload.asset_type == "GRID_CONSTRAINT" and user.role_code not in {"EXCHANGE", "ADMIN"}:
        raise HTTPException(status_code=403, detail="调度安全边界只能由交易中心受控接入")

    if payload.asset_type == "USER_LOAD_CURVE" and user.role_code not in {"RETAILER", "EXCHANGE", "ADMIN"}:
        raise HTTPException(status_code=403, detail="用户负荷曲线只能由售电企业或受控管理角色接入")

    record = DataUpload(
        asset_type=payload.asset_type,
        owner_org_id=owner_org_id,
        trade_batch_no=payload.trade_batch_no,
        label=payload.label,
        data_ref="pending",
        data_hash="pending",
        commitment="pending",
        schema_version=payload.schema_version,
        validation_status="PENDING",
        summary_json={},
        ingress_json=payload.ingress.model_dump(),
    )
    db.add(record)
    db.flush()
    data_ref, data_hash, commitment = LocalDomainVault.write(
        owner_org_id, record.upload_id, payload.local_payload
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
    }
    did = db.scalar(select(DidIdentity).where(DidIdentity.owner_id == owner_org_id))
    record.signature_value = sign_value(
        {"upload_id": record.upload_id, "data_hash": data_hash},
        did.did_id if did else owner_org_id,
    )
    db.add(
        Signature(
            signer_org_id=owner_org_id,
            signer_did=did.did_id if did else f"did:hiddenchain:org:{owner_org_id}",
            target_type="DATA_UPLOAD",
            target_id=record.upload_id,
            target_hash=data_hash,
            signature_value=record.signature_value,
            verify_status="VALID",
        )
    )
    add_audit_log(
        db,
        action="UPLOAD_DATA_REFERENCE",
        target_type="DATA_UPLOAD",
        target_id=record.upload_id,
        result="SUCCESS",
        user=user,
        details={"asset_type": payload.asset_type, "data_hash": data_hash, "raw_payload_in_db": False},
    )
    db.commit()
    db.refresh(record)
    return {**model_dict(record), "owner_org_name": owner.org_name, "raw_payload_exposed": False}


@router.post("/{upload_id}/sign")
def sign_upload(
    upload_id: str,
    user: User = Depends(require_roles("GENERATOR", "RETAILER", "EXCHANGE", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    upload = db.get(DataUpload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="数据记录不存在")
    if user.role_code in {"GENERATOR", "RETAILER"} and upload.owner_org_id != user.org_id:
        raise HTTPException(status_code=403, detail="不能签署其他主体的数据")
    if upload.signature_value:
        existing = db.scalar(
            select(Signature)
            .where(
                Signature.target_type == "DATA_UPLOAD",
                Signature.target_id == upload.upload_id,
                Signature.target_hash == upload.data_hash,
                Signature.verify_status == "VALID",
            )
            .order_by(Signature.created_at.desc())
        )
        if existing:
            return {"signature_id": existing.signature_id, "verify_status": existing.verify_status}
    did = db.scalar(select(DidIdentity).where(DidIdentity.owner_id == upload.owner_org_id))
    signer_did = did.did_id if did else f"did:hiddenchain:org:{upload.owner_org_id}"
    signature_value = sign_value({"data_hash": upload.data_hash}, signer_did)
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
