from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DataUpload, DidIdentity
from ..security import sha256_json
from ..trust_models import (
    AssetQuality,
    DataAsset,
    DataAssetPassport,
    DataAssetVersion,
    DataSource,
)


SENSITIVITY_BY_ASSET_TYPE = {
    "GENERATION_DATA": "L4",
    "RETAIL_DATA": "L4",
    "USER_LOAD_CURVE": "L4",
    "VPP_RESOURCE": "L3",
    "RENEWABLE_FORECAST": "L3",
    "GRID_CONSTRAINT": "L4",
}


def project_upload_to_asset_registry(
    db: Session,
    upload: DataUpload,
) -> DataAssetVersion:
    """Project a legacy upload reference into the formal asset/passport model.

    Only references, hashes, quality metadata and policy intent are copied.  The
    provider payload remains in its configured domain vault.
    """

    source_code = f"DOMAIN_SOURCE:{upload.owner_org_id}"
    source = db.scalar(select(DataSource).where(DataSource.source_code == source_code))
    if source is None:
        ingress = upload.ingress_json or {}
        source = DataSource(
            source_code=source_code,
            source_name=f"Controlled source for {upload.owner_org_id}",
            owner_org_id=upload.owner_org_id,
            source_type=str(ingress.get("source_type") or "UNSPECIFIED"),
            connector_type=str(ingress.get("protocol") or "LOCAL_ADAPTER"),
            endpoint_ref=None,
            security_domain=f"org:{upload.owner_org_id}",
            capability_label="DEMO",
            status="ACTIVE",
            metadata_json={
                "transport_encryption": ingress.get("encryption", "NOT_PROVIDED"),
                "attestation": ingress.get("attestation", "NOT_PROVIDED"),
                "boundary": "Local vault adapter; no independent EDC data plane attestation",
            },
        )
        db.add(source)
        db.flush()

    asset_code = f"{upload.asset_type}:{upload.trade_batch_no}"
    asset = db.scalar(
        select(DataAsset).where(
            DataAsset.owner_org_id == upload.owner_org_id,
            DataAsset.asset_code == asset_code,
        )
    )
    if asset is None:
        sensitivity = SENSITIVITY_BY_ASSET_TYPE.get(upload.asset_type, "L3")
        asset = DataAsset(
            source_id=source.source_id,
            owner_org_id=upload.owner_org_id,
            asset_code=asset_code,
            asset_name=upload.label,
            asset_type=upload.asset_type,
            classification="ENERGY_BUSINESS_DATA",
            sensitivity_level=sensitivity,
            status="ACTIVE",
            metadata_json={
                "trade_batch_no": upload.trade_batch_no,
                "legacy_upload_compatibility": True,
            },
        )
        db.add(asset)
        db.flush()

    existing = db.scalar(
        select(DataAssetVersion).where(
            DataAssetVersion.asset_id == asset.asset_id,
            DataAssetVersion.data_hash == upload.data_hash,
        )
    )
    if existing is not None:
        return existing

    version_no = int(
        db.scalar(
            select(func.max(DataAssetVersion.version_no)).where(
                DataAssetVersion.asset_id == asset.asset_id
            )
        )
        or 0
    ) + 1
    immutable_payload = {
        "asset_id": asset.asset_id,
        "version_no": version_no,
        "schema_version": upload.schema_version,
        "data_hash": upload.data_hash,
        "commitment": upload.commitment,
        "data_ref_hash": sha256_json({"data_ref": upload.data_ref}),
    }
    version = DataAssetVersion(
        asset_id=asset.asset_id,
        version_no=version_no,
        schema_version=upload.schema_version,
        schema_json={
            "asset_type": upload.asset_type,
            "schema_version": upload.schema_version,
            "raw_payload_in_registry": False,
        },
        data_ref=upload.data_ref,
        data_hash=upload.data_hash,
        commitment=upload.commitment,
        record_count=int((upload.summary_json or {}).get("record_count") or 0),
        immutable_hash=sha256_json(immutable_payload),
        status="ACTIVE",
    )
    db.add(version)
    db.flush()
    asset.current_version_id = version.version_id

    identity = db.scalar(
        select(DidIdentity).where(DidIdentity.owner_id == upload.owner_org_id)
    )
    owner_did = (
        identity.did_id
        if identity is not None
        else f"did:hiddenchain:org:{upload.owner_org_id}"
    )
    passport_payload = {
        "asset_version_id": version.version_id,
        "owner_did": owner_did,
        "classification": asset.classification,
        "sensitivity_level": asset.sensitivity_level,
        "data_hash": version.data_hash,
        "commitment": version.commitment,
        "permitted_purposes": ["POWER_SETTLEMENT", "GRID_SECURITY_CHECK", "VPP_AGGREGATION"],
    }
    passport = DataAssetPassport(
        asset_version_id=version.version_id,
        passport_version=1,
        owner_did=owner_did,
        provenance_json={
            "source_id": source.source_id,
            "legacy_upload_id": upload.upload_id,
            "data_hash": upload.data_hash,
            "commitment": upload.commitment,
        },
        classification_json={
            "classification": asset.classification,
            "sensitivity_level": asset.sensitivity_level,
        },
        permitted_use_json={
            "output_mode": "AGGREGATE_ONLY",
            "raw_data_export": False,
            "purposes": passport_payload["permitted_purposes"],
        },
        policy_refs_json=[],
        evidence_refs_json=[],
        passport_hash=sha256_json(passport_payload),
        status="ACTIVE",
    )
    quality_payload = {
        "asset_version_id": version.version_id,
        "validation_status": upload.validation_status,
        "record_count": version.record_count,
        "trusted_acquisition": bool(upload.ingress_json),
    }
    db.add_all(
        [
            passport,
            AssetQuality(
                asset_version_id=version.version_id,
                profile_version="ASSET_QUALITY_V1",
                metrics_json=quality_payload,
                decision="PASSED" if upload.validation_status == "PASSED" else "REJECTED",
                quality_hash=sha256_json(quality_payload),
                evidence_refs_json=[],
                evaluated_by_did=owner_did,
            ),
        ]
    )
    db.flush()
    return version


def redacted_asset_projection(db: Session, upload: DataUpload) -> dict[str, Any] | None:
    version = db.scalar(
        select(DataAssetVersion)
        .join(DataAsset, DataAsset.asset_id == DataAssetVersion.asset_id)
        .where(
            DataAsset.owner_org_id == upload.owner_org_id,
            DataAssetVersion.data_hash == upload.data_hash,
        )
        .order_by(DataAssetVersion.created_at.desc())
    )
    if version is None:
        return None
    asset = db.get(DataAsset, version.asset_id)
    passport = db.scalar(
        select(DataAssetPassport).where(
            DataAssetPassport.asset_version_id == version.version_id
        )
    )
    quality = db.scalar(
        select(AssetQuality).where(AssetQuality.asset_version_id == version.version_id)
    )
    return {
        "asset_id": asset.asset_id if asset else None,
        "asset_version_id": version.version_id,
        "version_no": version.version_no,
        "immutable_hash": version.immutable_hash,
        "passport_id": passport.passport_id if passport else None,
        "passport_hash": passport.passport_hash if passport else None,
        "quality_decision": quality.decision if quality else None,
        "raw_payload_exposed": False,
    }
