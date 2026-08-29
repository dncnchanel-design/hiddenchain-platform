from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fastapi import APIRouter, Depends, HTTPException, Response, status
import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import require_roles
from ..models import (
    ConnectorIngestionReceipt,
    ConnectorIngestionTicket,
    DidIdentity,
    LocalSubjectNode,
    Organization,
    User,
    utc_now,
)
from ..security import canonical_json, sha256_json
from ..services.common import add_audit_log
from ..services.local_data_boundary import parse_subject_map, subject_node_config
from ..trust_models import DataAsset, DataAssetPassport, DataAssetVersion, DataSource


router = APIRouter(prefix="/trust-space/connectors", tags=["connector-ingestion"])

CONNECTOR_OWNER_ROLES = (
    "GENERATOR",
    "RETAILER",
    "COAL_ENTERPRISE",
    "HEAT_ENTERPRISE",
    "GAS_ENTERPRISE",
    "OIL_ENTERPRISE",
    "EXCHANGE",
)
MAX_INGEST_BYTES = 5 * 1024 * 1024
TICKET_LIFETIME_SECONDS = 5 * 60
RECEIPT_REGISTRATION_GRACE = timedelta(days=7)
HASH_PATTERN = r"^[0-9a-f]{64}$"

RESOURCE_DETAILS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "electricity": (
        ("generation", "发电量", "MWh"),
        ("supply", "供电量", "MWh"),
        ("load", "用电负荷", "MW"),
        ("price", "交易价格", "元/MWh"),
    ),
    "coal": (
        ("production", "煤炭产量", "吨"),
        ("supply", "煤炭供应量", "吨"),
        ("consumption", "煤炭消费量", "吨"),
        ("inventory", "煤炭库存", "吨"),
        ("transport", "煤炭运输量", "吨"),
        ("price", "煤炭价格", "元/吨"),
    ),
    "heat": (
        ("supply", "供热量", "GJ"),
        ("load", "热负荷", "MW"),
        ("fuel", "燃料消耗", "吨标准煤"),
        ("loss", "管网损耗率", "%"),
        ("supply_temperature", "供水温度", "℃"),
        ("return_temperature", "回水温度", "℃"),
        ("price", "供热价格", "元/GJ"),
    ),
    "gas": (
        ("supply", "天然气供应量", "万立方米"),
        ("consumption", "天然气消费量", "万立方米"),
        ("storage", "天然气储量", "万立方米"),
        ("pipeline_flow", "管道流量", "万立方米/日"),
        ("pressure", "管网压力", "MPa"),
        ("price", "天然气价格", "元/立方米"),
    ),
    "oil": (
        ("production", "石油产量", "吨"),
        ("refining", "石油炼化量", "吨"),
        ("inventory", "石油库存", "吨"),
        ("transport", "石油运输量", "吨"),
        ("sales", "石油销售量", "吨"),
        ("price", "石油价格", "元/吨"),
    ),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TicketRequest(StrictModel):
    resource_id: str = Field(min_length=1, max_length=96)
    classification: Literal["L1", "L2", "L3"] = "L3"


class ReceiptRegistration(StrictModel):
    receipt_id: str = Field(min_length=8, max_length=96)
    ticket_id: str = Field(min_length=8, max_length=64)
    connector_id: str = Field(min_length=3, max_length=96)
    organization_id: str = Field(min_length=3, max_length=96)
    energy_domain: str = Field(min_length=2, max_length=24)
    resource_id: str = Field(min_length=1, max_length=96)
    resource_name: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1)
    schema_version: str = Field(min_length=1, max_length=32)
    schema_hash: str = Field(pattern=HASH_PATTERN)
    content_hash: str = Field(pattern=HASH_PATTERN)
    record_count: int = Field(ge=1)
    byte_size: int = Field(ge=1)
    local_ref: str = Field(min_length=16, max_length=512)
    audit_sequence: int = Field(ge=1)
    audit_hash: str = Field(pattern=HASH_PATTERN)
    issued_at: str = Field(min_length=20, max_length=48)
    signature: str = Field(min_length=16, max_length=256)
    public_key: str = Field(min_length=16, max_length=128)
    signature_algorithm: Literal["Ed25519"]
    signature_valid: Literal[True]


def _resource(domain: str, resource_id: str) -> tuple[str, str] | None:
    return next(
        ((name, unit) for code, name, unit in RESOURCE_DETAILS.get(domain, ()) if code == resource_id),
        None,
    )


def _private_key() -> Ed25519PrivateKey:
    encoded = settings.platform_signing_private_key.strip()
    if not encoded:
        raise HTTPException(status_code=503, detail="平台一次性凭证签名密钥未配置")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except Exception:
        decoded = b""
    seed = decoded if len(decoded) == 32 else hashlib.sha256(encoded.encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public_key(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def _active_node(db: Session, org_id: str) -> tuple[LocalSubjectNode, dict[str, Any]]:
    node = db.scalar(
        select(LocalSubjectNode)
        .where(LocalSubjectNode.org_id == org_id, LocalSubjectNode.status == "ACTIVE")
        .order_by(LocalSubjectNode.created_at.desc())
    )
    config = subject_node_config(db, org_id)
    if node is None or config is None:
        raise HTTPException(status_code=503, detail="当前组织尚未登记企业连接器")
    endpoint = str(config.get("endpoint") or "").strip()
    parsed = urlparse(endpoint)
    allowed_scheme = parsed.scheme == "https" or (
        settings.app_env in {"development", "test", "demo"}
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1"}
    )
    if not endpoint or not allowed_scheme or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(status_code=503, detail="企业连接器端点未安全配置")
    browser_endpoints = parse_subject_map(settings.subject_node_browser_endpoints_json)
    browser_endpoint = browser_endpoints.get(org_id, endpoint).strip()
    browser_parsed = urlparse(browser_endpoint)
    browser_allowed = browser_parsed.scheme == "https" or (
        settings.app_env in {"development", "test", "demo"}
        and browser_parsed.scheme == "http"
        and browser_parsed.hostname in {"localhost", "127.0.0.1"}
    )
    if (
        not browser_allowed
        or not browser_parsed.netloc
        or browser_parsed.username
        or browser_parsed.password
    ):
        raise HTTPException(status_code=503, detail="企业连接器浏览器直达端点未安全配置")
    return node, {
        **config,
        "endpoint": endpoint,
        "browser_endpoint": browser_endpoint,
    }


def _owner_context(db: Session, user: User) -> tuple[Organization, LocalSubjectNode, dict[str, Any]]:
    if "MANAGE_CONNECTOR" not in set(user.permissions_json or []):
        raise HTTPException(status_code=403, detail="当前账号没有管理本主体连接器的权限")
    organization = db.get(Organization, user.org_id)
    if organization is None or organization.status != "ACTIVE" or not organization.energy_domain:
        raise HTTPException(status_code=403, detail="当前组织没有有效的能源主体范围")
    node, config = _active_node(db, user.org_id)
    return organization, node, config


def _receipt_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="连接器回执时间无效") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail="连接器回执时间必须携带时区")
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _receipt_signed_payload(payload: ReceiptRegistration) -> dict[str, Any]:
    return payload.model_dump(
        exclude={"signature", "public_key", "signature_algorithm", "signature_valid"}
    )


def _receipt_projection(item: ConnectorIngestionReceipt, *, replay: bool) -> dict[str, Any]:
    return {
        "receipt_id": item.receipt_id,
        "ticket_id": item.ticket_id,
        "connector_id": item.connector_id,
        "organization_id": item.org_id,
        "energy_domain": item.energy_domain,
        "resource_id": item.resource_id,
        "resource_name": item.resource_name,
        "status": item.status,
        "registered_at": item.registered_at.isoformat(),
        "asset": {
            "asset_id": item.asset_id,
            "asset_version_id": item.asset_version_id,
            "version": item.version_no,
        },
        "raw_data_centrally_stored": False,
        "idempotent_replay": replay,
    }


def _discover_demo_connector_public_key(
    *,
    config: dict[str, Any],
    ticket: ConnectorIngestionTicket,
) -> str:
    """Discover a demo connector key from its configured HTTPS identity endpoint.

    The signed receipt is deliberately not a source of trust for its own key.
    Production must keep using an explicitly provisioned key.
    """

    if settings.app_env not in {"development", "test", "demo"}:
        raise HTTPException(status_code=503, detail="企业连接器签名公钥未登记")
    endpoint = str(config.get("endpoint") or "").rstrip("/")
    try:
        response = httpx.get(
            f"{endpoint}/health",
            timeout=min(max(float(settings.connector_timeout_seconds), 1.0), 10.0),
            follow_redirects=False,
        )
        response.raise_for_status()
        identity = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="无法验证企业连接器签名身份") from exc
    if not isinstance(identity, dict):
        raise HTTPException(status_code=503, detail="企业连接器身份响应无效")
    expected_identity = {
        "connector_id": ticket.connector_id,
        "organization_id": ticket.org_id,
        "energy_domain": ticket.energy_domain,
    }
    if any(identity.get(key) != value for key, value in expected_identity.items()):
        raise HTTPException(status_code=503, detail="企业连接器身份与签发凭证范围不一致")
    public_key = str(identity.get("public_key") or "")
    try:
        decoded = base64.b64decode(public_key, validate=True)
    except Exception:
        decoded = b""
    if len(decoded) != 32:
        raise HTTPException(status_code=503, detail="企业连接器签名公钥无效")
    return public_key


@router.get("/catalog")
def connector_catalog(
    user: User = Depends(require_roles(*CONNECTOR_OWNER_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    organization, node, config = _owner_context(db, user)
    receipts = db.scalars(
        select(ConnectorIngestionReceipt)
        .where(ConnectorIngestionReceipt.org_id == user.org_id)
        .order_by(
            ConnectorIngestionReceipt.resource_id,
            ConnectorIngestionReceipt.version_no.desc(),
        )
    ).all()
    latest: dict[str, ConnectorIngestionReceipt] = {}
    for receipt in receipts:
        latest.setdefault(receipt.resource_id, receipt)
    resources = []
    for resource_id, resource_name, unit in RESOURCE_DETAILS[organization.energy_domain]:
        current = latest.get(resource_id)
        resources.append(
            {
                "resource_id": resource_id,
                "resource_name": resource_name,
                "unit": unit,
                "schema_version": "connector-csv-v1",
                "required_columns": ["record_date", "value"],
                "optional_columns": ["hour", "region", "organization", "unit"],
                "current_version": current.version_no if current else None,
                "record_count": current.record_count if current else None,
                "status": "REGISTERED" if current else "NOT_REGISTERED",
            }
        )
    return {
        "connector": {
            "connector_id": node.node_code,
            "organization_id": organization.org_id,
            "organization_name": organization.org_name,
            "energy_domain": organization.energy_domain,
            "endpoint": config["browser_endpoint"],
            "status": node.status,
            "capability_state": "LOCAL_REAL",
        },
        "resources": resources,
        "upload_contract": {
            "mode": "BROWSER_TO_SUBJECT_CONNECTOR",
            "file_format": "csv",
            "max_bytes": MAX_INGEST_BYTES,
            "ticket_lifetime_seconds": TICKET_LIFETIME_SECONDS,
        },
    }


@router.post("/tickets", status_code=status.HTTP_201_CREATED)
def issue_ingestion_ticket(
    payload: TicketRequest,
    user: User = Depends(require_roles(*CONNECTOR_OWNER_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    organization, node, config = _owner_context(db, user)
    resource = _resource(organization.energy_domain or "", payload.resource_id)
    if resource is None:
        raise HTTPException(status_code=422, detail="请从当前能源域的规范资源目录中选择")
    resource_name, _unit = resource
    now = datetime.now(UTC)
    issued_at = int(now.timestamp())
    expires_at = issued_at + TICKET_LIFETIME_SECONDS
    ticket_id = secrets.token_urlsafe(24)
    claims = {
        "iss": "hiddenchain-platform",
        "jti": ticket_id,
        "subject_user_id": user.user_id,
        "organization_id": organization.org_id,
        "connector_id": node.node_code,
        "energy_domain": organization.energy_domain,
        "resource_id": payload.resource_id,
        "resource_name": resource_name,
        "classification": payload.classification,
        "schema_version": "connector-csv-v1",
        "file_format": "csv",
        "max_bytes": MAX_INGEST_BYTES,
        "purpose": "LOCAL_DATASET_INGEST",
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    private_key = _private_key()
    ticket = {
        "claims": claims,
        "signature": base64.b64encode(
            private_key.sign(canonical_json(claims).encode())
        ).decode(),
        "public_key": _public_key(private_key),
        "algorithm": "Ed25519",
    }
    db.add(
        ConnectorIngestionTicket(
            ticket_id=ticket_id,
            user_id=user.user_id,
            org_id=organization.org_id,
            node_id=node.node_id,
            connector_id=node.node_code,
            energy_domain=organization.energy_domain,
            resource_id=payload.resource_id,
            resource_name=resource_name,
            classification=payload.classification,
            schema_version="connector-csv-v1",
            file_format="csv",
            purpose="LOCAL_DATASET_INGEST",
            max_bytes=MAX_INGEST_BYTES,
            claims_hash=sha256_json(claims),
            status="ISSUED",
            issued_at=datetime.fromtimestamp(issued_at, UTC).replace(tzinfo=None),
            expires_at=datetime.fromtimestamp(expires_at, UTC).replace(tzinfo=None),
        )
    )
    add_audit_log(
        db,
        action="CONNECTOR_INGESTION_TICKET_ISSUED",
        target_type="CONNECTOR_INGESTION_TICKET",
        target_id=ticket_id,
        result="SUCCESS",
        user=user,
        details={
            "connector_id": node.node_code,
            "energy_domain": organization.energy_domain,
            "resource_id": payload.resource_id,
            "file_format": "csv",
            "max_bytes": MAX_INGEST_BYTES,
        },
    )
    db.commit()
    return {
        "ticket": ticket,
        "upload_url": f"{str(config['browser_endpoint']).rstrip('/')}/ingest",
        "receipt_lookup_url": f"{str(config['browser_endpoint']).rstrip('/')}/ingest/receipts/lookup",
        "connector": {
            "connector_id": node.node_code,
            "organization_id": organization.org_id,
            "energy_domain": organization.energy_domain,
        },
    }


@router.post("/receipts", status_code=status.HTTP_201_CREATED)
def register_ingestion_receipt(
    payload: ReceiptRegistration,
    response: Response,
    user: User = Depends(require_roles(*CONNECTOR_OWNER_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ticket = db.get(ConnectorIngestionTicket, payload.ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="未找到一次性接入凭证")
    if ticket.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="不能登记其他组织的连接器回执")
    if "MANAGE_CONNECTOR" not in set(user.permissions_json or []):
        raise HTTPException(status_code=403, detail="当前账号没有登记连接器回执的权限")
    signed_payload = _receipt_signed_payload(payload)
    signed_hash = sha256_json(signed_payload)
    existing = db.get(ConnectorIngestionReceipt, payload.receipt_id)
    existing_for_ticket = db.scalar(
        select(ConnectorIngestionReceipt).where(
            ConnectorIngestionReceipt.ticket_id == ticket.ticket_id
        )
    )
    prior = existing or existing_for_ticket
    if prior is not None:
        if (
            prior.receipt_id != payload.receipt_id
            or sha256_json(prior.signed_payload_json) != signed_hash
            or prior.node_signature != payload.signature
        ):
            raise HTTPException(status_code=409, detail="回执编号或一次性凭证已绑定其他内容")
        response.status_code = status.HTTP_200_OK
        return _receipt_projection(prior, replay=True)

    expected = {
        "connector_id": ticket.connector_id,
        "organization_id": ticket.org_id,
        "energy_domain": ticket.energy_domain,
        "resource_id": ticket.resource_id,
        "resource_name": ticket.resource_name,
        "schema_version": ticket.schema_version,
    }
    mismatched = [key for key, value in expected.items() if getattr(payload, key) != value]
    if mismatched:
        raise HTTPException(status_code=422, detail="连接器回执与一次性凭证绑定范围不一致")
    if payload.byte_size > ticket.max_bytes:
        raise HTTPException(status_code=422, detail="连接器回执声明的文件大小超出凭证限额")
    expected_ref = (
        f"connector://{ticket.connector_id}/{ticket.resource_id}/versions/{payload.version}"
    )
    if payload.local_ref != expected_ref:
        raise HTTPException(status_code=422, detail="连接器本地版本引用与回执范围不一致")
    issued_at = _receipt_time(payload.issued_at)
    now = utc_now()
    if issued_at < ticket.issued_at - timedelta(minutes=1) or issued_at > ticket.expires_at + timedelta(minutes=1):
        raise HTTPException(status_code=422, detail="连接器回执不在一次性凭证有效期内")
    if now > ticket.expires_at + RECEIPT_REGISTRATION_GRACE:
        raise HTTPException(status_code=410, detail="回执补登记期已过，请重新接入该资源")

    node, config = _active_node(db, ticket.org_id)
    if node.node_code != ticket.connector_id:
        raise HTTPException(status_code=409, detail="凭证签发后企业连接器身份已变更")
    expected_public_key = str(config.get("public_key") or "")
    if not expected_public_key:
        expected_public_key = _discover_demo_connector_public_key(
            config=config,
            ticket=ticket,
        )
        node.public_key = expected_public_key
    if payload.public_key != expected_public_key:
        raise HTTPException(status_code=422, detail="企业连接器回执公钥与登记身份不一致")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(expected_public_key)).verify(
            base64.b64decode(payload.signature),
            canonical_json(signed_payload).encode(),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail="企业连接器回执数字签名校验失败") from exc

    source_code = f"SUBJECT-CONNECTOR-{hashlib.sha256(ticket.connector_id.encode()).hexdigest()[:24]}"
    source = db.scalar(select(DataSource).where(DataSource.source_code == source_code))
    if source is None:
        source = DataSource(
            source_code=source_code,
            source_name=f"{ticket.resource_name}企业连接器",
            owner_org_id=ticket.org_id,
            source_type="ENTERPRISE_CONNECTOR",
            connector_type="SUBJECT_LOCAL_INGESTION",
            endpoint_ref=config["endpoint"],
            security_domain=f"{ticket.org_id}:{ticket.energy_domain}",
            capability_label="LOCAL_REAL",
            status="ACTIVE",
            metadata_json={
                "connector_id": ticket.connector_id,
                "energy_domain": ticket.energy_domain,
                "metadata_only": True,
            },
        )
        db.add(source)
        db.flush()
    asset_code = f"CONNECTOR_{ticket.energy_domain}_{ticket.resource_id}".upper()
    asset = db.scalar(
        select(DataAsset).where(
            DataAsset.owner_org_id == ticket.org_id,
            DataAsset.asset_code == asset_code,
        )
    )
    if asset is None:
        asset = DataAsset(
            source_id=source.source_id,
            owner_org_id=ticket.org_id,
            asset_code=asset_code,
            asset_name=ticket.resource_name,
            asset_type="CONNECTOR_RESOURCE",
            classification="ENERGY_BUSINESS_DATA",
            sensitivity_level=ticket.classification,
            status="ACTIVE",
            metadata_json={},
        )
        db.add(asset)
        db.flush()
    prior_version = db.scalar(
        select(DataAssetVersion).where(
            DataAssetVersion.asset_id == asset.asset_id,
            DataAssetVersion.version_no == payload.version,
        )
    )
    if prior_version is not None:
        raise HTTPException(status_code=409, detail="该连接器资源版本已登记其他回执")
    version = DataAssetVersion(
        asset_id=asset.asset_id,
        version_no=payload.version,
        schema_version=payload.schema_version,
        schema_json={
            "schema_hash": payload.schema_hash,
            "required_columns": ["record_date", "value"],
            "metadata_only": True,
        },
        data_ref=payload.local_ref,
        data_hash=payload.content_hash,
        commitment=sha256_json(
            {
                "connector_id": ticket.connector_id,
                "content_hash": payload.content_hash,
                "version": payload.version,
            }
        ),
        record_count=payload.record_count,
        immutable_hash=signed_hash,
        status="ACTIVE",
    )
    db.add(version)
    db.flush()
    asset.source_id = source.source_id
    asset.asset_name = ticket.resource_name
    asset.sensitivity_level = ticket.classification
    asset.status = "ACTIVE"
    asset.current_version_id = version.version_id
    asset.metadata_json = {
        "connector_id": ticket.connector_id,
        "domain": ticket.energy_domain,
        "resource_id": ticket.resource_id,
        "ingestion_receipt_id": payload.receipt_id,
        "raw_data_centrally_stored": False,
    }
    owner_did = db.scalar(
        select(DidIdentity.did_id)
        .where(
            DidIdentity.owner_type == "ORG",
            DidIdentity.owner_id == ticket.org_id,
            DidIdentity.credential_status == "VALID",
        )
        .order_by(DidIdentity.created_at.desc())
    )
    if owner_did:
        db.add(
            DataAssetPassport(
                asset_version_id=version.version_id,
                owner_did=owner_did,
                provenance_json={
                    "source": "SUBJECT_CONNECTOR_SIGNED_RECEIPT",
                    "connector_id": ticket.connector_id,
                    "receipt_id": payload.receipt_id,
                },
                classification_json={"sensitivity_level": ticket.classification},
                permitted_use_json={
                    "default_action": "DENY",
                    "output_mode": "AGGREGATE_ONLY",
                    "raw_data_export": False,
                },
                policy_refs_json=[],
                evidence_refs_json=[payload.receipt_id],
                passport_hash=sha256_json(
                    {
                        "asset_id": asset.asset_id,
                        "asset_version_id": version.version_id,
                        "receipt_hash": signed_hash,
                    }
                ),
                status="ACTIVE",
            )
        )
    receipt = ConnectorIngestionReceipt(
        receipt_id=payload.receipt_id,
        ticket_id=ticket.ticket_id,
        connector_id=ticket.connector_id,
        org_id=ticket.org_id,
        energy_domain=ticket.energy_domain,
        resource_id=ticket.resource_id,
        resource_name=ticket.resource_name,
        version_no=payload.version,
        schema_version=payload.schema_version,
        schema_hash=payload.schema_hash,
        content_hash=payload.content_hash,
        record_count=payload.record_count,
        byte_size=payload.byte_size,
        local_ref=payload.local_ref,
        audit_sequence=payload.audit_sequence,
        audit_hash=payload.audit_hash,
        node_signature=payload.signature,
        signed_payload_json=signed_payload,
        asset_id=asset.asset_id,
        asset_version_id=version.version_id,
        status="VERIFIED",
        issued_at=issued_at,
        registered_at=now,
    )
    db.add(receipt)
    ticket.status = "REGISTERED"
    ticket.registered_at = now
    add_audit_log(
        db,
        action="CONNECTOR_INGESTION_RECEIPT_REGISTERED",
        target_type="CONNECTOR_INGESTION_RECEIPT",
        target_id=payload.receipt_id,
        result="SUCCESS",
        user=user,
        details={
            "ticket_id": ticket.ticket_id,
            "connector_id": ticket.connector_id,
            "resource_id": ticket.resource_id,
            "version": payload.version,
            "content_hash": payload.content_hash,
            "record_count": payload.record_count,
            "raw_data_centrally_stored": False,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="连接器回执或资源版本已被登记") from exc
    db.refresh(receipt)
    return _receipt_projection(receipt, replay=False)


@router.get("/receipts/{ticket_id}")
def get_ingestion_receipt(
    ticket_id: str,
    user: User = Depends(require_roles(*CONNECTOR_OWNER_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ticket = db.get(ConnectorIngestionTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="未找到一次性接入凭证")
    if ticket.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="不能查看其他组织的连接器回执")
    receipt = db.scalar(
        select(ConnectorIngestionReceipt).where(
            ConnectorIngestionReceipt.ticket_id == ticket_id
        )
    )
    if receipt is None:
        return {
            "ticket_id": ticket.ticket_id,
            "status": ticket.status,
            "receipt_id": None,
            "raw_data_centrally_stored": False,
        }
    return _receipt_projection(receipt, replay=True)
