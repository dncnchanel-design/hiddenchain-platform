"""Demo-only bridge from verified connector aggregates to controlled settlement."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import VAULT_DIR, settings
from ..models import ConnectorIngestionReceipt, ConnectorIngestionTicket, DataUpload, DidIdentity, Organization, Signature, User
from ..security import canonical_json, sha256_json, sign_value
from ..trust_models import DataAssetPassport
from .asset_registry import project_upload_to_asset_registry
from .common import add_audit_log
from .trust_domain import TrustDomainError, verify_active_identity


class SettlementPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    trade_batch_no: str = Field(min_length=3, max_length=64)
    period_start: str
    period_end: str

    @field_validator("period_start", "period_end")
    @classmethod
    def strict_day(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("结算日期必须是 YYYY-MM-DD")
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def valid_window(self) -> "SettlementPeriod":
        if not 1 <= self.day_count <= 366:
            raise ValueError("结算期间必须按起止顺序填写，且不超过366天")
        return self

    @property
    def day_count(self) -> int:
        return (date.fromisoformat(self.period_end) - date.fromisoformat(self.period_start)).days + 1


class SettlementBinding(SettlementPeriod):
    schema_version: Literal["connector-settlement-binding-v1"] = "connector-settlement-binding-v1"

    @field_validator("trade_batch_no", mode="before")
    @classmethod
    def trim_batch(cls, value: Any) -> Any:
        # Normalize user input before the platform signs it, never signed receipts.
        return value.strip() if isinstance(value, str) else value


class SettlementSummary(SettlementPeriod):
    schema_version: Literal["connector-settlement-summary-v1"]
    asset_type: Literal["GENERATION_DATA", "RETAIL_DATA"]
    aggregation: Literal["SUM"]
    unit: Literal["MWh"]
    energy_mwh: str = Field(pattern=r"^(0|[1-9][0-9]{0,12})(\.[0-9]{1,6})?$")
    record_count: int = Field(ge=1, le=366)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_records_returned: Literal[False]

    @field_validator("raw_records_returned", mode="before")
    @classmethod
    def no_raw_records(cls, value: Any) -> bool:
        if value is not False:
            raise ValueError("结算回执不能返回原始记录")
        return False

    @model_validator(mode="after")
    def validate_aggregate(self) -> "SettlementSummary":
        if Decimal(self.energy_mwh) > Decimal("1000000000000"):
            raise ValueError("结算汇总电量超过限额")
        if self.record_count != self.day_count:
            raise ValueError("结算汇总必须每日一条完整覆盖期间")
        return self


def settlement_asset_type(organization: Organization, role_code: str, resource_id: str, app_env: str) -> str | None:
    if app_env not in {"development", "test", "demo"} or organization.energy_domain != "electricity" or organization.status != "ACTIVE":
        return None
    if organization.org_type != role_code:
        return None
    return {("GENERATOR", "generation"): "GENERATION_DATA", ("RETAILER", "supply"): "RETAIL_DATA"}.get((role_code, resource_id))


def validate_settlement_receipt(db: Session, ticket: ConnectorIngestionTicket, summary: SettlementSummary | None, user: User, *, content_hash: str, record_count: int, app_env: str) -> None:
    binding = ticket.settlement_binding_json or None
    if binding is None and summary is None:
        return
    organization = db.get(Organization, ticket.org_id)
    expected_type = settlement_asset_type(organization, user.role_code, ticket.resource_id, app_env) if organization else None
    if expected_type is None:
        raise HTTPException(403, "当前主体、资源或环境不支持新批次演示结算接入")
    if binding is None or summary is None:
        raise HTTPException(422, "结算回执必须与票据的结算绑定同时提供")
    if any(getattr(summary, key) != binding.get(key) for key in ("trade_batch_no", "period_start", "period_end")):
        raise HTTPException(422, "结算回执的批次或期间与票据绑定不一致")
    if summary.asset_type != expected_type or summary.content_hash != content_hash or summary.claims_hash != ticket.claims_hash or summary.record_count != record_count:
        raise HTTPException(422, "结算回执的类型、源内容、票据哈希或记录数不一致")


def settlement_upload_id(receipt: ConnectorIngestionReceipt) -> str:
    return str(uuid5(NAMESPACE_URL, f"hiddenchain:connector-settlement-v1:{receipt.ticket_id}:{receipt.receipt_id}"))


def settlement_projection(receipt: ConnectorIngestionReceipt) -> dict[str, Any] | None:
    summary = receipt.signed_payload_json.get("settlement_summary")
    if not isinstance(summary, dict):
        return None
    return {"status": "REGISTERED", "upload_id": settlement_upload_id(receipt), **{key: summary[key] for key in ("trade_batch_no", "period_start", "period_end", "asset_type", "energy_mwh")}}


def persist_settlement_aggregate(db: Session, receipt: ConnectorIngestionReceipt, summary: SettlementSummary, user: User, *, public_key: str, new_files: list[Path]) -> DataUpload:
    """Persist only a verified aggregate; the caller owns commit and cleanup."""
    if settings.app_env not in {"development", "test", "demo"}:
        raise HTTPException(403, "生产环境不启用聚合 Vault 桥接")
    identity = db.scalar(select(DidIdentity).where(DidIdentity.owner_type == "ORG", DidIdentity.owner_id == receipt.org_id, DidIdentity.org_id == receipt.org_id).order_by(DidIdentity.created_at.desc()))
    if identity is None:
        raise HTTPException(403, "当前主体缺少有效 DID")
    try:
        verify_active_identity(db, identity.did_id)
    except TrustDomainError as exc:
        raise HTTPException(403, "当前主体 DID 不可用") from exc
    upload_id = settlement_upload_id(receipt)
    payload = {
        "schema_version": "connector-settlement-input-v1",
        "energy_mwh": summary.energy_mwh,
        "period_start": summary.period_start,
        "period_end": summary.period_end,
        "record_count": summary.record_count,
        "source": {
            "signed_receipt": receipt.signed_payload_json,
            "signature": receipt.node_signature,
            "public_key": public_key,
            "signature_algorithm": "Ed25519",
            "raw_records_returned": False,
        },
    }
    data_hash = sha256_json(payload)
    commitment = sign_value({"org_id": receipt.org_id, "upload_id": upload_id, "hash": data_hash}, receipt.org_id)
    # The upload identity is stable, but each transaction owns its own file.
    # A failed transaction must never delete a concurrent retry's object.
    object_id = f"{upload_id}-{uuid4().hex}"
    data_ref = f"vault://{receipt.org_id}/{object_id}"
    record = DataUpload(upload_id=upload_id, owner_org_id=receipt.org_id, asset_type=summary.asset_type,
        trade_batch_no=summary.trade_batch_no, label=f"连接器日度结算汇总 {summary.trade_batch_no}",
        data_ref=data_ref, data_hash=data_hash, commitment=commitment, schema_version="connector-settlement-input-v1", validation_status="PASSED",
        summary_json={"record_count": summary.record_count, "period_start": summary.period_start, "period_end": summary.period_end,
            "source_receipt_id": receipt.receipt_id, "source_asset_version_id": receipt.asset_version_id, "source_content_hash": receipt.content_hash,
            "aggregate_only": True, "raw_data_stored_in_business_db": False, "trusted_acquisition": True},
        ingress_json={"source_type": "CONNECTOR_SIGNED_AGGREGATE", "protocol": "SIGNED_RECEIPT", "encryption": "NOT_PROVIDED", "attestation": "Ed25519; no TEE attestation"})
    db.add(record)
    # Flush all receipt/upload uniqueness constraints before touching the file.
    db.flush()
    directory = VAULT_DIR / receipt.org_id
    path = directory / f"{object_id}.json"
    if not path.resolve().is_relative_to(VAULT_DIR.resolve()) or len(Path(receipt.org_id).parts) != 1:
        raise HTTPException(422, "主体 Vault 路径无效")
    directory.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        new_files.append(path)
        handle.write(canonical_json(payload))
    record.signature_value = sign_value({"upload_id": upload_id, "data_hash": data_hash}, identity.did_id)
    db.add(Signature(signer_org_id=receipt.org_id, signer_did=identity.did_id, target_type="DATA_UPLOAD", target_id=upload_id, target_hash=data_hash, signature_value=record.signature_value, verify_status="VALID"))
    version = project_upload_to_asset_registry(db, record)
    passport = db.scalar(select(DataAssetPassport).where(DataAssetPassport.asset_version_id == version.version_id))
    if passport is not None:
        passport.provenance_json = {**passport.provenance_json, "source": "CONNECTOR_SIGNED_SETTLEMENT_AGGREGATE", "source_receipt_id": receipt.receipt_id, "source_asset_version_id": receipt.asset_version_id}
        passport.evidence_refs_json = [receipt.receipt_id]
    add_audit_log(db, action="CONNECTOR_SETTLEMENT_AGGREGATE_REGISTERED", target_type="DATA_UPLOAD", target_id=upload_id, result="SUCCESS", user=user,
        details={"receipt_id": receipt.receipt_id, "trade_batch_no": summary.trade_batch_no, "data_hash": data_hash, "raw_data_centrally_stored": False, "aggregate_only": True})
    return record
