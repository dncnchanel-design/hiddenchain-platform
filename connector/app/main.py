from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import math
import os
import secrets
import sqlite3
import statistics
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DOMAIN_LABELS = {
    "electricity": "电力",
    "coal": "煤炭",
    "heat": "热能",
    "gas": "天然气",
    "oil": "石油",
}

RESOURCE_DEFINITIONS: dict[str, list[tuple[str, str, str]]] = {
    "electricity": [
        ("generation", "发电量", "MWh"),
        ("supply", "供电量", "MWh"),
        ("load", "用电负荷", "MW"),
        ("price", "交易价格", "元/MWh"),
    ],
    "coal": [
        ("production", "煤炭产量", "吨"),
        ("supply", "煤炭供应量", "吨"),
        ("consumption", "煤炭消费量", "吨"),
        ("inventory", "煤炭库存", "吨"),
        ("transport", "煤炭运输量", "吨"),
        ("price", "煤炭价格", "元/吨"),
    ],
    "heat": [
        ("supply", "供热量", "GJ"),
        ("load", "热负荷", "MW"),
        ("fuel", "燃料消耗", "吨标准煤"),
        ("loss", "管网损耗率", "%"),
        ("supply_temperature", "供水温度", "℃"),
        ("return_temperature", "回水温度", "℃"),
        ("price", "供热价格", "元/GJ"),
    ],
    "gas": [
        ("supply", "天然气供应量", "万立方米"),
        ("consumption", "天然气消费量", "万立方米"),
        ("storage", "天然气储量", "万立方米"),
        ("pipeline_flow", "管道流量", "万立方米/日"),
        ("pressure", "管网压力", "MPa"),
        ("price", "天然气价格", "元/立方米"),
    ],
    "oil": [
        ("production", "石油产量", "吨"),
        ("refining", "石油炼化量", "吨"),
        ("inventory", "石油库存", "吨"),
        ("transport", "石油运输量", "吨"),
        ("sales", "石油销售量", "吨"),
        ("price", "石油价格", "元/吨"),
    ],
}

FUNCTION_LABELS = {
    "sum": "求和",
    "average": "平均值",
    "max": "最大值",
    "min": "最小值",
    "count": "计数",
    "median": "中位数",
    "growth_rate": "增长率",
    "yoy": "同比",
    "mom": "环比",
    "group_by": "分组汇总",
    "threshold": "阈值判断",
    "trend": "趋势",
    "psi": "PSI",
    "mpc_aggregation": "MPC 聚合份额",
}

DOMAIN = os.getenv("ENERGY_DOMAIN", "electricity").strip().lower()
if DOMAIN not in RESOURCE_DEFINITIONS:
    raise RuntimeError("ENERGY_DOMAIN is not supported")
CONNECTOR_NAME = os.getenv("CONNECTOR_NAME", f"{DOMAIN_LABELS[DOMAIN]}企业连接器")
CONNECTOR_ID = os.getenv("CONNECTOR_ID", f"connector-{DOMAIN}")
ORGANIZATION_ID = os.getenv("ORGANIZATION_ID", "").strip()
BUILD_SHA = (
    os.getenv("RENDER_GIT_COMMIT")
    or os.getenv("GIT_COMMIT")
    or os.getenv("SOURCE_VERSION")
    or "UNAVAILABLE"
)
DATABASE_PATH = Path(os.getenv("CONNECTOR_DATABASE_PATH", "/app/runtime/connector.db"))
MIN_GROUP_SIZE = max(3, int(os.getenv("PRIVACY_MIN_GROUP_SIZE", "3")))
MAX_DECIMALS = min(6, max(0, int(os.getenv("PRIVACY_MAX_DECIMALS", "2"))))
QUERY_BUDGET = max(1, int(os.getenv("PRIVACY_QUERY_BUDGET", "80")))
NONCE_TTL_SECONDS = max(60, int(os.getenv("REQUEST_NONCE_TTL_SECONDS", "300")))
INGEST_MAX_BYTES = max(1024, int(os.getenv("CONNECTOR_INGEST_MAX_BYTES", str(5 * 1024 * 1024))))
TICKET_CLOCK_SKEW_SECONDS = max(0, int(os.getenv("INGEST_TICKET_CLOCK_SKEW_SECONDS", "60")))
RECEIPT_LOOKUP_GRACE_SECONDS = 7 * 24 * 60 * 60
INGEST_REQUIRED_COLUMNS = {"record_date", "value"}
INGEST_OPTIONAL_COLUMNS = {"hour", "region", "organization", "unit"}
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
CONNECTOR_CORS_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv("CONNECTOR_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
)
CONNECTOR_SEED_SYNTHETIC_DATA = os.getenv("CONNECTOR_SEED_SYNTHETIC_DATA", "false").strip().lower() == "true"
DEMO_SEED_VERSION = "hiddenchain-demo-seed-v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def _load_private_key() -> Ed25519PrivateKey:
    encoded = os.getenv("CONNECTOR_SIGNING_PRIVATE_KEY", "").strip()
    if not encoded:
        raise RuntimeError("CONNECTOR_SIGNING_PRIVATE_KEY must be configured")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except Exception:
        decoded = b""
    seed = decoded if len(decoded) == 32 else hashlib.sha256(encoded.encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public_key_text(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


PRIVATE_KEY = _load_private_key()
PUBLIC_KEY = _public_key_text(PRIVATE_KEY)


def _database() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _base_value(resource: str) -> float:
    return 50 + int(hashlib.sha256(f"{DOMAIN}:{resource}".encode()).hexdigest()[:4], 16) % 500


def _seed_records(connection: sqlite3.Connection) -> None:
    exists = connection.execute("SELECT COUNT(*) AS total FROM records").fetchone()["total"]
    if exists:
        return
    start = date(2025, 9, 1)
    regions = ["东部片区", "西部片区", "南部片区", "北部片区"]
    hourly_resources = {"load", "supply"} if DOMAIN in {"electricity", "heat", "gas"} else set()
    rows: list[tuple[Any, ...]] = []
    for resource, _name, unit in RESOURCE_DEFINITIONS[DOMAIN]:
        base = _base_value(resource)
        for day_index in range(365):
            current = start + timedelta(days=day_index)
            for region_index, region in enumerate(regions):
                seasonal = 1 + 0.16 * math.sin(day_index / 365 * math.tau)
                value = base * seasonal + region_index * 7 + (day_index % 11)
                rows.append((resource, current.isoformat(), None, region, f"{CONNECTOR_NAME}{region}", value, unit))
                if resource in hourly_resources:
                    for hour in range(24):
                        hourly = value / 24 * (0.75 + 0.35 * math.sin((hour - 7) / 24 * math.tau) ** 2)
                        rows.append((resource, current.isoformat(), hour, region, f"{CONNECTOR_NAME}{region}", hourly, unit))
    connection.executemany(
        "INSERT INTO records(resource, record_date, hour, region, organization, value, unit) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()


def _demo_seed_content_hash(connector_id: str, domain: str, resource: str) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "generator_version": DEMO_SEED_VERSION,
                "connector_id": connector_id,
                "energy_domain": domain,
                "resource_id": resource,
            }
        )
    ).hexdigest()


def _seed_demo_versions(connection: sqlite3.Connection) -> None:
    for resource, resource_name, _unit in RESOURCE_DEFINITIONS[DOMAIN]:
        if connection.execute(
            "SELECT 1 FROM resource_versions WHERE resource_id = ? LIMIT 1", (resource,)
        ).fetchone():
            continue
        version_id = f"demo-seed-{DOMAIN}-{resource}-v1"
        record_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE resource = ?", (resource,)
            ).fetchone()[0]
        )
        local_ref = f"connector://{CONNECTOR_ID}/{resource}/versions/1"
        content_hash = _demo_seed_content_hash(CONNECTOR_ID, DOMAIN, resource)
        connection.execute(
            """
            INSERT INTO resource_versions(
              version_id, resource_id, resource_name, version_no, classification,
              schema_version, schema_hash, content_hash, record_count, byte_size,
              local_ref, created_at
            ) VALUES (?, ?, ?, 1, 'L2', ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                version_id,
                resource,
                resource_name,
                DEMO_SEED_VERSION,
                hashlib.sha256(f"{DEMO_SEED_VERSION}:{DOMAIN}:{resource}".encode()).hexdigest(),
                content_hash,
                record_count,
                local_ref,
                datetime.now(UTC).isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO version_records(
              version_id, resource, record_date, hour, region, organization, value, unit
            )
            SELECT ?, resource, record_date, hour, region, organization, value, unit
            FROM records WHERE resource = ?
            """,
            (version_id, resource),
        )
    connection.commit()


def _initialize() -> None:
    with _database() as connection:
        connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS records(
              record_id INTEGER PRIMARY KEY AUTOINCREMENT,
              resource TEXT NOT NULL,
              record_date TEXT NOT NULL,
              hour INTEGER,
              region TEXT NOT NULL,
              organization TEXT NOT NULL,
              value REAL NOT NULL,
              unit TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_records_query ON records(resource, record_date, hour, region);
            CREATE TABLE IF NOT EXISTS request_nonces(
              nonce TEXT PRIMARY KEY,
              occurred_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS query_log(
              query_hash TEXT PRIMARY KEY,
              repeated_count INTEGER NOT NULL DEFAULT 1,
              occurred_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS local_execution_receipts(
              request_item_id TEXT PRIMARY KEY,
              request_hash TEXT NOT NULL,
              result_hash TEXT NOT NULL,
              result_json TEXT NOT NULL,
              occurred_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connector_config(
              config_key TEXT PRIMARY KEY,
              config_value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ingest_tickets(
              ticket_id TEXT PRIMARY KEY,
              claims_hash TEXT NOT NULL,
              subject_user_id TEXT NOT NULL,
              organization_id TEXT NOT NULL,
              connector_id TEXT NOT NULL,
              energy_domain TEXT NOT NULL,
              resource_id TEXT NOT NULL,
              issued_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL,
              consumed_at INTEGER NOT NULL,
              status TEXT NOT NULL,
              receipt_id TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS resource_versions(
              version_id TEXT PRIMARY KEY,
              resource_id TEXT NOT NULL,
              resource_name TEXT NOT NULL,
              version_no INTEGER NOT NULL,
              classification TEXT NOT NULL,
              schema_version TEXT NOT NULL,
              schema_hash TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              record_count INTEGER NOT NULL,
              byte_size INTEGER NOT NULL,
              local_ref TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              UNIQUE(resource_id, version_no)
            );
            CREATE INDEX IF NOT EXISTS ix_resource_versions_latest
              ON resource_versions(resource_id, version_no DESC);
            CREATE TABLE IF NOT EXISTS version_records(
              record_id INTEGER PRIMARY KEY AUTOINCREMENT,
              version_id TEXT NOT NULL REFERENCES resource_versions(version_id) ON DELETE RESTRICT,
              resource TEXT NOT NULL,
              record_date TEXT NOT NULL,
              hour INTEGER,
              region TEXT NOT NULL,
              organization TEXT NOT NULL,
              value REAL NOT NULL,
              unit TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_version_records_query
              ON version_records(version_id, record_date, hour, region);
            CREATE TABLE IF NOT EXISTS ingest_receipts(
              receipt_id TEXT PRIMARY KEY,
              ticket_id TEXT NOT NULL UNIQUE REFERENCES ingest_tickets(ticket_id) ON DELETE RESTRICT,
              receipt_json TEXT NOT NULL,
              issued_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ingest_audit_chain(
              audit_sequence INTEGER PRIMARY KEY,
              previous_hash TEXT NOT NULL,
              audit_hash TEXT NOT NULL UNIQUE,
              event_json TEXT NOT NULL,
              occurred_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS trg_ingest_audit_chain_no_update
            BEFORE UPDATE ON ingest_audit_chain
            BEGIN
              SELECT RAISE(ABORT, 'ingest audit chain is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_ingest_audit_chain_no_delete
            BEFORE DELETE ON ingest_audit_chain
            BEGIN
              SELECT RAISE(ABORT, 'ingest audit chain is append-only');
            END;
            """
        )
        if CONNECTOR_SEED_SYNTHETIC_DATA:
            _seed_records(connection)
            _seed_demo_versions(connection)


class ComputeRequest(BaseModel):
    task_id: str = Field(min_length=6, max_length=96)
    authorization_id: str = Field(min_length=6, max_length=96)
    request_item_id: str | None = Field(default=None, min_length=6, max_length=96)
    provider_org_id: str | None = Field(default=None, min_length=3, max_length=96)
    rule_version: str | None = Field(default=None, max_length=32)
    dataset_version: int = Field(ge=1)
    dataset_local_ref: str = Field(min_length=16, max_length=512)
    dataset_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource: str
    function: str
    start_date: date
    end_date: date
    region: str | None = None
    hour: int | None = Field(default=None, ge=0, le=23)
    threshold: float | None = None
    group_by: str | None = None
    decimals: int = Field(default=2, ge=0, le=6)


class DashboardRequest(BaseModel):
    request_id: str = Field(min_length=6, max_length=96)
    provider_org_id: str = Field(min_length=3, max_length=96)
    resource: str = Field(min_length=1, max_length=64)
    aggregation: str = Field(pattern="^(sum|average|max|min)$")
    start_date: date
    end_date: date
    decimals: int = Field(default=2, ge=0, le=6)


class IngestTicketClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    iss: Literal["hiddenchain-platform"]
    jti: str = Field(min_length=8, max_length=160)
    subject_user_id: str = Field(min_length=3, max_length=160)
    organization_id: str = Field(min_length=3, max_length=160)
    connector_id: str = Field(min_length=3, max_length=160)
    energy_domain: Literal["electricity", "coal", "heat", "gas", "oil"]
    resource_id: str = Field(min_length=1, max_length=96)
    resource_name: str = Field(min_length=1, max_length=160)
    classification: Literal["L1", "L2", "L3"]
    schema_version: Literal["connector-csv-v1"]
    file_format: Literal["csv"]
    max_bytes: int = Field(ge=1)
    purpose: Literal["LOCAL_DATASET_INGEST"]
    issued_at: int
    expires_at: int


class IngestTicketEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claims: IngestTicketClaims
    signature: str = Field(min_length=1, max_length=512)
    public_key: str = Field(min_length=1, max_length=512)
    algorithm: Literal["Ed25519"]


def _canonical_request_payload(payload: BaseModel) -> dict[str, Any]:
    """Normalize optional subject-bound fields before signing or hashing."""

    signed_payload = payload.model_dump(mode="json")
    for field_name in ("request_item_id", "provider_org_id", "rule_version"):
        if signed_payload.get(field_name) is None:
            signed_payload.pop(field_name, None)
    return signed_payload


def _now_epoch() -> int:
    return int(datetime.now(UTC).timestamp())


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _append_local_audit(
    connection: sqlite3.Connection,
    event: dict[str, Any],
) -> tuple[int, str, str, dict[str, Any]]:
    """Append a metadata-only event to the connector's immutable hash chain."""

    prior = connection.execute(
        "SELECT audit_sequence, audit_hash FROM ingest_audit_chain "
        "ORDER BY audit_sequence DESC LIMIT 1"
    ).fetchone()
    sequence = int(prior["audit_sequence"]) + 1 if prior else 1
    previous_hash = str(prior["audit_hash"]) if prior else "0" * 64
    occurred_at = str(event.get("occurred_at") or _utc_now_iso())
    audit_event = {
        **event,
        "connector_id": CONNECTOR_ID,
        "organization_id": ORGANIZATION_ID or None,
        "energy_domain": DOMAIN,
        "occurred_at": occurred_at,
    }
    event_json = _canonical(audit_event).decode()
    audit_hash = hashlib.sha256((previous_hash + event_json).encode()).hexdigest()
    connection.execute(
        """
        INSERT INTO ingest_audit_chain(
          audit_sequence, previous_hash, audit_hash, event_json, occurred_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (sequence, previous_hash, audit_hash, event_json, occurred_at),
    )
    return sequence, previous_hash, audit_hash, audit_event


def _platform_public_key_candidate(presented_public_key: str | None) -> tuple[str, bool]:
    public_text = os.getenv("PLATFORM_SIGNING_PUBLIC_KEY", "").strip()
    if public_text:
        if presented_public_key and not secrets.compare_digest(public_text, presented_public_key):
            raise HTTPException(401, "平台签名公钥与连接器配置不一致")
        return public_text, False
    if (
        os.getenv("ALLOW_DEMO_KEY_REGISTRATION", "false").lower()
        not in {"1", "true", "yes", "on"}
        or not presented_public_key
    ):
        raise HTTPException(503, "平台签名公钥未配置")
    with _database() as connection:
        registered = connection.execute(
            "SELECT config_value FROM connector_config WHERE config_key = 'platform_public_key'"
        ).fetchone()
    if registered:
        if not secrets.compare_digest(str(registered["config_value"]), presented_public_key):
            raise HTTPException(401, "平台签名公钥与首次登记信息不一致")
        return presented_public_key, False
    return presented_public_key, True


def _register_demo_public_key(public_text: str) -> None:
    connection = _database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        registered = connection.execute(
            "SELECT config_value FROM connector_config WHERE config_key = 'platform_public_key'"
        ).fetchone()
        if registered and not secrets.compare_digest(str(registered["config_value"]), public_text):
            raise HTTPException(401, "平台签名公钥与首次登记信息不一致")
        if not registered:
            connection.execute(
                "INSERT INTO connector_config(config_key, config_value) VALUES ('platform_public_key', ?)",
                (public_text,),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _verify_ed25519(public_text: str, signature_text: str, payload: Any) -> None:
    try:
        public_bytes = base64.b64decode(public_text, validate=True)
        signature_bytes = base64.b64decode(signature_text, validate=True)
        if len(public_bytes) != 32 or len(signature_bytes) != 64:
            raise ValueError("invalid Ed25519 material")
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature_bytes, _canonical(payload))
    except Exception as exc:
        raise HTTPException(401, "平台数字签名验证失败") from exc


def _verify_platform_request(payload: BaseModel, timestamp: str, nonce: str, signature: str, presented_public_key: str | None) -> None:
    provider_org_id = getattr(payload, "provider_org_id", None)
    if provider_org_id and not ORGANIZATION_ID:
        raise HTTPException(503, "主体节点未绑定组织身份")
    if provider_org_id and ORGANIZATION_ID and provider_org_id != ORGANIZATION_ID:
        raise HTTPException(403, "请求主体与本地节点身份不一致")
    public_text, should_register = _platform_public_key_candidate(presented_public_key)
    try:
        occurred_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(401, "请求时间无效") from exc
    now = _now_epoch()
    if abs(now - occurred_at) > NONCE_TTL_SECONDS:
        raise HTTPException(401, "请求已过期")
    signed_payload = _canonical_request_payload(payload)
    message = {"timestamp": timestamp, "nonce": nonce, "payload": signed_payload}
    _verify_ed25519(public_text, signature, message)
    if should_register:
        _register_demo_public_key(public_text)
    with _database() as connection:
        connection.execute("DELETE FROM request_nonces WHERE occurred_at < ?", (now - NONCE_TTL_SECONDS,))
        try:
            connection.execute("INSERT INTO request_nonces(nonce, occurred_at) VALUES (?, ?)", (nonce, now))
            request_kind = "COMPUTE" if isinstance(payload, ComputeRequest) else "DASHBOARD"
            _append_local_audit(
                connection,
                {
                    "action": f"PLATFORM_{request_kind}_REQUEST_AUTHENTICATED",
                    "task_id": getattr(payload, "task_id", None),
                    "request_id": getattr(payload, "request_id", None),
                    "request_item_id": getattr(payload, "request_item_id", None),
                    "provider_org_id": provider_org_id,
                    "request_hash": hashlib.sha256(_canonical(signed_payload)).hexdigest(),
                },
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "检测到重复请求") from exc


def _resource_definition(resource_id: str) -> tuple[str, str]:
    match = next(
        ((name, unit) for code, name, unit in RESOURCE_DEFINITIONS[DOMAIN] if code == resource_id),
        None,
    )
    if match is None:
        raise HTTPException(422, "票据资源不属于当前能源域固定目录")
    return match


def _verify_ingest_ticket(
    envelope: IngestTicketEnvelope,
    *,
    allow_expired_lookup: bool = False,
) -> tuple[IngestTicketClaims, str, str | None]:
    claims = envelope.claims
    public_text, should_register = _platform_public_key_candidate(envelope.public_key)
    claims_payload = claims.model_dump(mode="json")
    _verify_ed25519(public_text, envelope.signature, claims_payload)
    if not ORGANIZATION_ID:
        raise HTTPException(503, "主体节点未绑定组织身份")
    if claims.organization_id != ORGANIZATION_ID:
        raise HTTPException(403, "票据组织与本地节点身份不一致")
    if claims.connector_id != CONNECTOR_ID:
        raise HTTPException(403, "票据连接器与本地节点身份不一致")
    if claims.energy_domain != DOMAIN:
        raise HTTPException(403, "票据能源域与本地节点身份不一致")
    resource_name, _unit = _resource_definition(claims.resource_id)
    if claims.resource_name != resource_name:
        raise HTTPException(422, "票据资源名称与固定目录不一致")
    now = _now_epoch()
    if claims.issued_at > now + TICKET_CLOCK_SKEW_SECONDS:
        raise HTTPException(401, "票据签发时间无效")
    if claims.expires_at <= claims.issued_at:
        raise HTTPException(401, "票据有效期无效")
    if allow_expired_lookup:
        if now > claims.expires_at + RECEIPT_LOOKUP_GRACE_SECONDS:
            raise HTTPException(410, "回执补查窗口已结束")
    elif now > claims.expires_at:
        raise HTTPException(401, "票据已过期")
    return (
        claims,
        hashlib.sha256(_canonical(claims_payload)).hexdigest(),
        public_text if should_register else None,
    )


async def _read_ingest_file(file: UploadFile, ticket_max_bytes: int) -> bytes:
    limit = min(ticket_max_bytes, INGEST_MAX_BYTES)
    chunks: list[bytes] = []
    byte_size = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        byte_size += len(chunk)
        if byte_size > limit:
            raise HTTPException(413, "CSV 文件超过票据或连接器大小上限")
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(422, "CSV 文件不能为空")
    return b"".join(chunks)


def _parse_ingest_csv(
    raw: bytes,
    claims: IngestTicketClaims,
) -> tuple[list[tuple[str, int | None, str, str, float, str]], str]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "CSV 文件必须使用 UTF-8 编码") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        columns = list(reader.fieldnames or [])
        if len(columns) != len(set(columns)):
            raise HTTPException(422, "CSV 列名不能重复")
        missing = INGEST_REQUIRED_COLUMNS - set(columns)
        unexpected = set(columns) - INGEST_REQUIRED_COLUMNS - INGEST_OPTIONAL_COLUMNS
        if missing or unexpected:
            raise HTTPException(422, "CSV 必须包含 record_date、value，且只能使用公布的可选列")
        _resource_name, default_unit = _resource_definition(claims.resource_id)
        parsed: list[tuple[str, int | None, str, str, float, str]] = []
        for row in reader:
            if None in row:
                raise HTTPException(422, "CSV 行字段数量与表头不一致")
            if not any(str(value or "").strip() for value in row.values()):
                continue
            try:
                record_date = date.fromisoformat(str(row["record_date"] or "").strip()).isoformat()
            except ValueError as exc:
                raise HTTPException(422, "record_date 必须是有效的 YYYY-MM-DD 日期") from exc
            try:
                value = float(str(row["value"] or "").strip())
            except ValueError as exc:
                raise HTTPException(422, "value 必须是有限数值") from exc
            if not math.isfinite(value):
                raise HTTPException(422, "value 必须是有限数值")
            hour_text = str(row.get("hour") or "").strip()
            hour: int | None = None
            if hour_text:
                try:
                    hour = int(hour_text)
                except ValueError as exc:
                    raise HTTPException(422, "hour 必须是 0 到 23 的整数") from exc
                if hour < 0 or hour > 23:
                    raise HTTPException(422, "hour 必须是 0 到 23 的整数")
            region = str(row.get("region") or "").strip()
            organization = str(row.get("organization") or ORGANIZATION_ID).strip()
            unit = str(row.get("unit") or default_unit).strip()
            if not organization or not unit or any(len(item) > 256 for item in (region, organization, unit)):
                raise HTTPException(422, "CSV 文本字段无效或过长")
            parsed.append((record_date, hour, region, organization, value, unit))
    except csv.Error as exc:
        raise HTTPException(422, "CSV 格式无效") from exc
    if not parsed:
        raise HTTPException(422, "CSV 至少需要一行有效记录")
    schema = {"schema_version": claims.schema_version, "columns": columns}
    return parsed, hashlib.sha256(_canonical(schema)).hexdigest()


def _commit_ingest(
    claims: IngestTicketClaims,
    claims_hash: str,
    raw: bytes,
    records: list[tuple[str, int | None, str, str, float, str]],
    schema_hash: str,
    demo_public_key: str | None,
) -> dict[str, Any]:
    consumed_at = _now_epoch()
    receipt_issued_at = _utc_now_iso()
    content_hash = hashlib.sha256(raw).hexdigest()
    receipt_id = f"receipt-{secrets.token_hex(16)}"
    version_id = f"version-{secrets.token_hex(16)}"
    connection = _database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if demo_public_key:
            registered = connection.execute(
                "SELECT config_value FROM connector_config WHERE config_key = 'platform_public_key'"
            ).fetchone()
            if registered and not secrets.compare_digest(
                str(registered["config_value"]), demo_public_key
            ):
                raise HTTPException(401, "平台签名公钥与首次登记信息不一致")
            if not registered:
                connection.execute(
                    "INSERT INTO connector_config(config_key, config_value) VALUES ('platform_public_key', ?)",
                    (demo_public_key,),
                )
        if connection.execute(
            "SELECT 1 FROM ingest_tickets WHERE ticket_id = ?",
            (claims.jti,),
        ).fetchone():
            raise HTTPException(409, "一次性接入票据已使用")
        previous_version = connection.execute(
            "SELECT COALESCE(MAX(version_no), 0) AS version_no FROM resource_versions WHERE resource_id = ?",
            (claims.resource_id,),
        ).fetchone()["version_no"]
        version = int(previous_version) + 1
        local_ref = f"connector://{CONNECTOR_ID}/{claims.resource_id}/versions/{version}"
        connection.execute(
            """
            INSERT INTO ingest_tickets(
              ticket_id, claims_hash, subject_user_id, organization_id, connector_id,
              energy_domain, resource_id, issued_at, expires_at, consumed_at, status, receipt_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONSUMED', ?)
            """,
            (
                claims.jti,
                claims_hash,
                claims.subject_user_id,
                claims.organization_id,
                claims.connector_id,
                claims.energy_domain,
                claims.resource_id,
                claims.issued_at,
                claims.expires_at,
                consumed_at,
                receipt_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO resource_versions(
              version_id, resource_id, resource_name, version_no, classification,
              schema_version, schema_hash, content_hash, record_count, byte_size,
              local_ref, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                claims.resource_id,
                claims.resource_name,
                version,
                claims.classification,
                claims.schema_version,
                schema_hash,
                content_hash,
                len(records),
                len(raw),
                local_ref,
                receipt_issued_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO version_records(
              version_id, resource, record_date, hour, region, organization, value, unit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (version_id, claims.resource_id, record_date, hour, region, organization, value, unit)
                for record_date, hour, region, organization, value, unit in records
            ],
        )
        audit_event = {
            "action": "LOCAL_DATASET_INGESTED",
            "ticket_id": claims.jti,
            "receipt_id": receipt_id,
            "resource_id": claims.resource_id,
            "version": version,
            "content_hash": content_hash,
            "record_count": len(records),
            "occurred_at": receipt_issued_at,
        }
        audit_sequence, _previous_hash, audit_hash, _audit_event = _append_local_audit(
            connection,
            audit_event,
        )
        receipt_payload = {
            "receipt_id": receipt_id,
            "ticket_id": claims.jti,
            "connector_id": CONNECTOR_ID,
            "organization_id": ORGANIZATION_ID,
            "energy_domain": DOMAIN,
            "resource_id": claims.resource_id,
            "resource_name": claims.resource_name,
            "version": version,
            "schema_version": claims.schema_version,
            "schema_hash": schema_hash,
            "content_hash": content_hash,
            "record_count": len(records),
            "byte_size": len(raw),
            "local_ref": local_ref,
            "audit_sequence": audit_sequence,
            "audit_hash": audit_hash,
            "issued_at": receipt_issued_at,
        }
        signed_receipt = _signed_response(receipt_payload)
        connection.execute(
            "INSERT INTO ingest_receipts(receipt_id, ticket_id, receipt_json, issued_at) VALUES (?, ?, ?, ?)",
            (
                receipt_id,
                claims.jti,
                json.dumps(signed_receipt, ensure_ascii=False, sort_keys=True),
                receipt_issued_at,
            ),
        )
        connection.commit()
        return signed_receipt
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise HTTPException(409, "接入票据或资源版本发生冲突") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _latest_local_version(connection: sqlite3.Connection, resource: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT version_id, version_no, record_count
        FROM resource_versions
        WHERE resource_id = ?
        ORDER BY version_no DESC
        LIMIT 1
        """,
        (resource,),
    ).fetchone()


def _query_values(payload: ComputeRequest) -> tuple[list[sqlite3.Row], str, int, str, str]:
    if payload.resource not in {item[0] for item in RESOURCE_DEFINITIONS[DOMAIN]}:
        raise HTTPException(422, "未找到该中文数据资源对应的受控资源")
    if payload.function not in FUNCTION_LABELS:
        raise HTTPException(422, "仅允许使用平台公布的固定函数")
    if payload.end_date < payload.start_date:
        raise HTTPException(422, "结束日期不能早于开始日期")
    with _database() as connection:
        bound = connection.execute(
            """
            SELECT version_id, version_no, local_ref, content_hash
            FROM resource_versions
            WHERE resource_id = ? AND version_no = ? AND local_ref = ? AND content_hash = ?
            LIMIT 1
            """,
            (
                payload.resource,
                payload.dataset_version,
                payload.dataset_local_ref,
                payload.dataset_content_hash,
            ),
        ).fetchone()
        if bound is None:
            raise HTTPException(409, "授权数据版本与连接器本地版本不一致")
        clauses = ["version_id = ?", "record_date BETWEEN ? AND ?"]
        params: list[Any] = [
            bound["version_id"],
            payload.start_date.isoformat(),
            payload.end_date.isoformat(),
        ]
        if payload.region:
            clauses.append("region = ?")
            params.append(payload.region)
        if payload.hour is None:
            clauses.append("hour IS NULL")
        else:
            clauses.append("hour = ?")
            params.append(payload.hour)
        sql = (
            "SELECT record_date, hour, region, organization, value, unit FROM version_records"
            + " WHERE "
            + " AND ".join(clauses)
            + " ORDER BY record_date, region"
        )
        rows = connection.execute(sql, params).fetchall()
    if len(rows) < MIN_GROUP_SIZE:
        raise HTTPException(403, f"可用记录少于隐私保护下限 {MIN_GROUP_SIZE} 条")
    return (
        rows,
        rows[0]["unit"],
        int(bound["version_no"]),
        str(bound["local_ref"]),
        str(bound["content_hash"]),
    )


def _daily_trend(rows: list[sqlite3.Row], decimals: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(str(row["record_date"]), []).append(float(row["value"]))
    return [
        {"date": day, "value": round(statistics.fmean(values), decimals)}
        for day, values in sorted(grouped.items())
    ]


def _compute(payload: ComputeRequest, rows: list[sqlite3.Row]) -> Any:
    values = [float(row["value"]) for row in rows]
    function = payload.function
    if function in {"sum", "mpc_aggregation"}:
        return sum(values)
    if function == "average":
        return statistics.fmean(values)
    if function == "max":
        return max(values)
    if function == "min":
        return min(values)
    if function == "count":
        return len(values)
    if function == "median":
        return statistics.median(values)
    if function in {"growth_rate", "yoy", "mom"}:
        if values[0] == 0:
            raise HTTPException(422, "基期数值为零，无法计算增长率")
        return (values[-1] - values[0]) / abs(values[0]) * 100
    if function == "threshold":
        if payload.threshold is None:
            raise HTTPException(422, "阈值判断必须填写阈值")
        return {"满足": sum(value >= payload.threshold for value in values), "不满足": sum(value < payload.threshold for value in values)}
    if function == "trend":
        points = _daily_trend(rows, payload.decimals)
        if len(points) < 2:
            raise HTTPException(422, "趋势分析至少需要两个日期的受控汇总")
        point_values = [point["value"] for point in points]
        middle = max(1, len(point_values) // 2)
        previous = statistics.fmean(point_values[:middle])
        current = statistics.fmean(point_values[middle:])
        return {"方向": "上升" if current > previous else "下降" if current < previous else "平稳", "变化率": 0 if previous == 0 else (current - previous) / abs(previous) * 100}
    if function == "group_by":
        field = payload.group_by or "region"
        if field not in {"region", "record_date", "organization"}:
            raise HTTPException(422, "分组字段仅支持地区、日期或机构")
        grouped: dict[str, list[float]] = {}
        for row in rows:
            grouped.setdefault(str(row[field]), []).append(float(row["value"]))
        return {key: sum(items) for key, items in grouped.items() if len(items) >= MIN_GROUP_SIZE}
    if function == "psi":
        middle = max(1, len(values) // 2)
        first = statistics.fmean(values[:middle])
        second = statistics.fmean(values[middle:])
        return abs(second - first) / max(abs(first), 1e-9)
    raise HTTPException(422, "固定函数尚未启用")


def _dashboard_series(payload: DashboardRequest) -> tuple[list[dict[str, Any]], str, int, int | str]:
    if payload.resource not in {item[0] for item in RESOURCE_DEFINITIONS[DOMAIN]}:
        raise HTTPException(422, "未找到该能源域的受控数据资源")
    if payload.end_date < payload.start_date:
        raise HTTPException(422, "结束日期不能早于开始日期")
    with _database() as connection:
        latest = _latest_local_version(connection, payload.resource)
        if latest:
            sql = (
                "SELECT record_date, value, unit FROM version_records "
                "WHERE version_id = ? AND record_date BETWEEN ? AND ? AND hour IS NULL "
                "ORDER BY record_date"
            )
            params = (latest["version_id"], payload.start_date.isoformat(), payload.end_date.isoformat())
            dataset_version: int | str = int(latest["version_no"])
        else:
            sql = (
                "SELECT record_date, value, unit FROM records "
                "WHERE resource = ? AND record_date BETWEEN ? AND ? AND hour IS NULL "
                "ORDER BY record_date"
            )
            params = (payload.resource, payload.start_date.isoformat(), payload.end_date.isoformat())
            dataset_version = "synthetic-v1"
        rows = connection.execute(sql, params).fetchall()
    grouped: dict[str, list[float]] = {}
    unit = next(unit for resource, _name, unit in RESOURCE_DEFINITIONS[DOMAIN] if resource == payload.resource)
    for row in rows:
        grouped.setdefault(str(row["record_date"]), []).append(float(row["value"]))
        unit = str(row["unit"])
    valid_days = [(day, values) for day, values in sorted(grouped.items()) if len(values) >= MIN_GROUP_SIZE]
    if not valid_days:
        raise HTTPException(403, f"可用日度记录少于隐私保护下限 {MIN_GROUP_SIZE} 条")
    decimals = min(payload.decimals, MAX_DECIMALS)
    points: list[dict[str, Any]] = []
    for day, values in valid_days:
        if payload.aggregation == "sum":
            value = sum(values)
        elif payload.aggregation == "max":
            value = max(values)
        elif payload.aggregation == "min":
            value = min(values)
        else:
            value = statistics.fmean(values)
        points.append({"date": day, "value": round(value, decimals)})
    return points, unit, sum(len(values) for _day, values in valid_days), dataset_version


def _signed_response(envelope: dict[str, Any]) -> dict[str, Any]:
    signature = PRIVATE_KEY.sign(_canonical(envelope))
    return {
        **envelope,
        "signature": base64.b64encode(signature).decode(),
        "public_key": PUBLIC_KEY,
        "signature_algorithm": "Ed25519",
        "signature_valid": True,
    }


app = FastAPI(title=f"{DOMAIN_LABELS[DOMAIN]}可信数据空间连接器", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CONNECTOR_CORS_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    _initialize()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "就绪",
        "connector": CONNECTOR_NAME,
        "connector_id": CONNECTOR_ID,
        "organization_id": ORGANIZATION_ID or None,
        "energy_domain": DOMAIN,
        "build_sha": BUILD_SHA,
        "raw_data_centrally_stored": False,
        "public_key": PUBLIC_KEY,
    }


@app.get("/catalog")
def catalog() -> dict[str, Any]:
    with _database() as connection:
        resources = []
        for resource, name, unit in RESOURCE_DEFINITIONS[DOMAIN]:
            latest = _latest_local_version(connection, resource)
            resources.append(
                {
                    "resource_id": resource,
                    "name": name,
                    "unit": unit,
                    "granularity": "日度及受支持的小时级",
                    "latest_version": int(latest["version_no"]) if latest else None,
                    "record_count": int(latest["record_count"]) if latest else 0,
                    "upload_capability": {
                        "enabled": True,
                        "schema_version": "connector-csv-v1",
                        "file_format": "csv",
                        "required_columns": sorted(INGEST_REQUIRED_COLUMNS),
                        "optional_columns": sorted(INGEST_OPTIONAL_COLUMNS),
                        "server_max_bytes": INGEST_MAX_BYTES,
                    },
                }
            )
    return {
        "connector_id": CONNECTOR_ID,
        "energy_domain": DOMAIN,
        "organization_id": ORGANIZATION_ID or None,
        "resources": resources,
        "functions": [{"code": code, "name": label} for code, label in FUNCTION_LABELS.items()],
        "notice": "这里只发布目录信息，原始数据保存在企业连接器中。",
    }


@app.post("/ingest", status_code=201)
async def ingest_dataset(
    ticket: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if len(ticket.encode("utf-8")) > 16 * 1024:
        raise HTTPException(422, "接入票据过大")
    try:
        envelope = IngestTicketEnvelope.model_validate_json(ticket)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, "接入票据格式无效") from exc
    claims, claims_hash, demo_public_key = _verify_ingest_ticket(envelope)
    try:
        raw = await _read_ingest_file(file, claims.max_bytes)
    finally:
        await file.close()
    records, schema_hash = _parse_ingest_csv(raw, claims)
    return _commit_ingest(
        claims,
        claims_hash,
        raw,
        records,
        schema_hash,
        demo_public_key,
    )


@app.post("/ingest/receipts/lookup")
def lookup_ingest_receipt(envelope: IngestTicketEnvelope) -> dict[str, Any]:
    claims, claims_hash, _demo_public_key = _verify_ingest_ticket(
        envelope,
        allow_expired_lookup=True,
    )
    with _database() as connection:
        record = connection.execute(
            """
            SELECT t.claims_hash, t.status, r.receipt_json
            FROM ingest_tickets AS t
            LEFT JOIN ingest_receipts AS r ON r.ticket_id = t.ticket_id
            WHERE t.ticket_id = ?
            """,
            (claims.jti,),
        ).fetchone()
    if record is None:
        raise HTTPException(404, "未找到已消费票据的接入回执")
    if not secrets.compare_digest(str(record["claims_hash"]), claims_hash):
        raise HTTPException(409, "票据编号已绑定其他接入声明")
    if record["status"] != "CONSUMED" or not record["receipt_json"]:
        raise HTTPException(404, "票据尚未完成接入，不能补查回执")
    return json.loads(record["receipt_json"])


@app.post("/dashboard")
def dashboard_metrics(
    payload: DashboardRequest,
    x_request_timestamp: str = Header(alias="X-Request-Timestamp"),
    x_request_nonce: str = Header(alias="X-Request-Nonce"),
    x_request_signature: str = Header(alias="X-Request-Signature"),
    x_platform_public_key: str | None = Header(default=None, alias="X-Platform-Public-Key"),
) -> dict[str, Any]:
    _verify_platform_request(payload, x_request_timestamp, x_request_nonce, x_request_signature, x_platform_public_key)
    request_payload = _canonical_request_payload(payload)
    request_hash = hashlib.sha256(_canonical(request_payload)).hexdigest()
    trend, unit, record_count, dataset_version = _dashboard_series(payload)
    resource_name = next(name for resource, name, _unit in RESOURCE_DEFINITIONS[DOMAIN] if resource == payload.resource)
    envelope = {
        "request_id": payload.request_id,
        "provider_org_id": ORGANIZATION_ID or payload.provider_org_id,
        "connector_id": CONNECTOR_ID,
        "energy_domain": DOMAIN,
        "resource": payload.resource,
        "resource_name": resource_name,
        "aggregation": payload.aggregation,
        "unit": unit,
        "latest": trend[-1],
        "trend": trend,
        "record_count": record_count,
        "dataset_version": dataset_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "privacy": {
            "granularity": "day",
            "minimum_group_size": MIN_GROUP_SIZE,
            "raw_records_returned": False,
            "raw_data_exported": False,
            "execution_environment": "SUBJECT_CONNECTOR",
            "attestation_status": "CONNECTOR_SIGNED",
            "non_export_attestation": {
                "status": "SIGNED",
                "issuer": CONNECTOR_ID,
                "boundary": "CONNECTOR_LOCAL_DATA",
                "request_hash": request_hash,
                "result_scope": "AGGREGATE_ONLY",
                "raw_data_exported": False,
            },
        },
        "privacy_verification": {
            "mode": "SIGNED_CONNECTOR_NON_EXPORT",
            "request_hash": request_hash,
            "raw_data_exported": False,
            "result_scope": "AGGREGATE_ONLY",
        },
        "raw_records_returned": False,
    }
    result_payload_hash = hashlib.sha256(_canonical(envelope)).hexdigest()
    connection = _database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        audit_sequence, previous_audit_hash, audit_hash, audit_event = _append_local_audit(
            connection,
            {
                "action": "DASHBOARD_AGGREGATE_ISSUED",
                "request_id": payload.request_id,
                "provider_org_id": payload.provider_org_id,
                "resource_id": payload.resource,
                "request_hash": request_hash,
                "result_payload_hash": result_payload_hash,
                "record_count": record_count,
                "dataset_version": dataset_version,
                "raw_records_returned": False,
                "raw_data_exported": False,
            },
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    envelope.update(
        {
            "audit_sequence": audit_sequence,
            "previous_audit_hash": previous_audit_hash,
            "audit_hash": audit_hash,
            "audit_event": audit_event,
        }
    )
    return _signed_response(envelope)


@app.post("/compute")
def compute(
    payload: ComputeRequest,
    x_request_timestamp: str = Header(alias="X-Request-Timestamp"),
    x_request_nonce: str = Header(alias="X-Request-Nonce"),
    x_request_signature: str = Header(alias="X-Request-Signature"),
    x_platform_public_key: str | None = Header(default=None, alias="X-Platform-Public-Key"),
) -> dict[str, Any]:
    _verify_platform_request(payload, x_request_timestamp, x_request_nonce, x_request_signature, x_platform_public_key)
    request_payload = _canonical_request_payload(payload)
    request_hash = hashlib.sha256(_canonical(request_payload)).hexdigest()
    if payload.request_item_id:
        with _database() as connection:
            prior = connection.execute(
                "SELECT request_hash, result_hash, result_json FROM local_execution_receipts WHERE request_item_id = ?",
                (payload.request_item_id,),
            ).fetchone()
        if prior is not None:
            if not secrets.compare_digest(str(prior["request_hash"]), request_hash):
                raise HTTPException(409, "请求项编号已绑定其他受控计算条件")
            cached = json.loads(prior["result_json"])
            cached_privacy = cached.get("privacy") if isinstance(cached, dict) else None
            cached_claim = (
                cached_privacy.get("non_export_attestation")
                if isinstance(cached_privacy, dict)
                else None
            )
            if isinstance(cached_claim, dict) and cached_claim.get("request_hash") == request_hash:
                connection = _database()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    _append_local_audit(
                        connection,
                        {
                            "action": "LOCAL_CONTROLLED_RESULT_REPLAYED",
                            "task_id": payload.task_id,
                            "request_item_id": payload.request_item_id,
                            "provider_org_id": payload.provider_org_id,
                            "request_hash": request_hash,
                            "result_hash": prior["result_hash"],
                        },
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()
                return cached
            raise HTTPException(409, "本地执行回执已损坏，拒绝重放")
    rows, unit, dataset_version, dataset_local_ref, dataset_content_hash = _query_values(payload)
    query_hash = hashlib.sha256(_canonical(request_payload)).hexdigest()
    now = int(datetime.now(UTC).timestamp())
    connection = _database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        record = connection.execute("SELECT repeated_count FROM query_log WHERE query_hash = ?", (query_hash,)).fetchone()
        if record and record["repeated_count"] >= 3:
            _append_local_audit(
                connection,
                {
                    "action": "PRIVACY_QUERY_BUDGET_REJECTED",
                    "task_id": payload.task_id,
                    "request_item_id": payload.request_item_id,
                    "request_hash": request_hash,
                    "reason": "REPEATED_QUERY_LIMIT",
                },
            )
            connection.commit()
            raise HTTPException(429, "相同或近似查询次数已达到隐私保护上限")
        total = connection.execute("SELECT COALESCE(SUM(repeated_count), 0) AS total FROM query_log").fetchone()["total"]
        if total >= QUERY_BUDGET:
            _append_local_audit(
                connection,
                {
                    "action": "PRIVACY_QUERY_BUDGET_REJECTED",
                    "task_id": payload.task_id,
                    "request_item_id": payload.request_item_id,
                    "request_hash": request_hash,
                    "reason": "CONNECTOR_BUDGET_EXHAUSTED",
                },
            )
            connection.commit()
            raise HTTPException(429, "本连接器查询预算已用尽")
        connection.execute(
            "INSERT INTO query_log(query_hash, repeated_count, occurred_at) VALUES (?, 1, ?) ON CONFLICT(query_hash) DO UPDATE SET repeated_count = repeated_count + 1, occurred_at = excluded.occurred_at",
            (query_hash, now),
        )
        _append_local_audit(
            connection,
            {
                "action": "PRIVACY_QUERY_BUDGET_CONSUMED",
                "task_id": payload.task_id,
                "request_item_id": payload.request_item_id,
                "provider_org_id": payload.provider_org_id,
                "request_hash": request_hash,
                "repeated_count": int(record["repeated_count"]) + 1 if record else 1,
                "connector_budget_used": int(total) + 1,
                "connector_budget_limit": QUERY_BUDGET,
            },
        )
        connection.commit()
    except HTTPException:
        if connection.in_transaction:
            connection.rollback()
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    decimals = min(payload.decimals, MAX_DECIMALS)
    result = _compute(payload, rows)
    if isinstance(result, float):
        result = round(result, decimals)
    elif isinstance(result, dict):
        result = {key: round(value, decimals) if isinstance(value, float) else value for key, value in result.items()}
    envelope = {
        "task_id": payload.task_id,
        "authorization_id": payload.authorization_id,
        "request_item_id": payload.request_item_id,
        "provider_org_id": ORGANIZATION_ID or payload.provider_org_id,
        "rule_version": payload.rule_version,
        "connector_id": CONNECTOR_ID,
        "energy_domain": DOMAIN,
        "resource_name": next(name for code, name, _unit in RESOURCE_DEFINITIONS[DOMAIN] if code == payload.resource),
        "function_name": FUNCTION_LABELS[payload.function],
        "result": result,
        "unit": unit,
        "record_count": len(rows),
        "dataset_version": dataset_version,
        "dataset_local_ref": dataset_local_ref,
        "dataset_content_hash": dataset_content_hash,
        "generated_at": datetime.now(UTC).isoformat(),
        "raw_records_returned": False,
        "privacy": {
            "minimum_group_size": MIN_GROUP_SIZE,
            "raw_records_returned": False,
            "raw_data_exported": False,
            "decimals": decimals,
            "execution_environment": "SUBJECT_CONNECTOR",
            "attestation_status": "CONNECTOR_SIGNED",
            "non_export_attestation": {
                "status": "SIGNED",
                "issuer": CONNECTOR_ID,
                "boundary": "CONNECTOR_LOCAL_DATA",
                "request_hash": request_hash,
                "result_scope": "AGGREGATE_ONLY",
                "raw_data_exported": False,
            },
        },
        "privacy_verification": {
            "mode": "SIGNED_CONNECTOR_NON_EXPORT",
            "request_hash": request_hash,
            "raw_data_exported": False,
            "result_scope": "AGGREGATE_ONLY",
        },
        "capability": "本地受控计算" if payload.function != "mpc_aggregation" else "本地计算份额",
    }
    if payload.function == "trend":
        envelope["trend"] = _daily_trend(rows, decimals)
    result_payload_hash = hashlib.sha256(_canonical(envelope)).hexdigest()
    connection = _database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if payload.request_item_id:
            prior = connection.execute(
                "SELECT request_hash, result_hash, result_json FROM local_execution_receipts WHERE request_item_id = ?",
                (payload.request_item_id,),
            ).fetchone()
            if prior is not None:
                if not secrets.compare_digest(str(prior["request_hash"]), request_hash):
                    raise HTTPException(409, "请求项编号已绑定其他受控计算条件")
                cached = json.loads(prior["result_json"])
                _append_local_audit(
                    connection,
                    {
                        "action": "LOCAL_CONTROLLED_RESULT_REPLAYED",
                        "task_id": payload.task_id,
                        "request_item_id": payload.request_item_id,
                        "provider_org_id": payload.provider_org_id,
                        "request_hash": request_hash,
                        "result_hash": prior["result_hash"],
                    },
                )
                connection.commit()
                return cached
        audit_sequence, previous_audit_hash, audit_hash, audit_event = _append_local_audit(
            connection,
            {
                "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
                "task_id": payload.task_id,
                "authorization_id": payload.authorization_id,
                "request_item_id": payload.request_item_id,
                "provider_org_id": payload.provider_org_id,
                "request_hash": request_hash,
                "result_payload_hash": result_payload_hash,
                "record_count": len(rows),
                "dataset_version": dataset_version,
                "dataset_local_ref": dataset_local_ref,
                "dataset_content_hash": dataset_content_hash,
                "raw_records_returned": False,
                "raw_data_exported": False,
            },
        )
        envelope.update(
            {
                "audit_sequence": audit_sequence,
                "previous_audit_hash": previous_audit_hash,
                "audit_hash": audit_hash,
                "audit_event": audit_event,
            }
        )
        signature = PRIVATE_KEY.sign(_canonical(envelope))
        response = {
            **envelope,
            "signature": base64.b64encode(signature).decode(),
            "public_key": PUBLIC_KEY,
            "signature_algorithm": "Ed25519",
            "signature_valid": True,
        }
        if payload.request_item_id:
            result_hash = hashlib.sha256(_canonical(envelope)).hexdigest()
            connection.execute(
                "INSERT INTO local_execution_receipts(request_item_id, request_hash, result_hash, result_json, occurred_at) VALUES (?, ?, ?, ?, ?)",
                (payload.request_item_id, request_hash, result_hash, json.dumps(response, ensure_ascii=False, sort_keys=True), now),
            )
        connection.commit()
        return response
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
