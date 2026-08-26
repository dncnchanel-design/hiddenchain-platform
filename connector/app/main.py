from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import secrets
import sqlite3
import statistics
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


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
DATABASE_PATH = Path(os.getenv("CONNECTOR_DATABASE_PATH", "/app/runtime/connector.db"))
MIN_GROUP_SIZE = max(3, int(os.getenv("PRIVACY_MIN_GROUP_SIZE", "3")))
MAX_DECIMALS = min(6, max(0, int(os.getenv("PRIVACY_MAX_DECIMALS", "2"))))
QUERY_BUDGET = max(1, int(os.getenv("PRIVACY_QUERY_BUDGET", "80")))
NONCE_TTL_SECONDS = max(60, int(os.getenv("REQUEST_NONCE_TTL_SECONDS", "300")))


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
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
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


def _initialize() -> None:
    with _database() as connection:
        connection.executescript(
            """
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
            """
        )
        _seed_records(connection)


class ComputeRequest(BaseModel):
    task_id: str = Field(min_length=6, max_length=96)
    authorization_id: str = Field(min_length=6, max_length=96)
    request_item_id: str | None = Field(default=None, min_length=6, max_length=96)
    provider_org_id: str | None = Field(default=None, min_length=3, max_length=96)
    rule_version: str | None = Field(default=None, max_length=32)
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


def _verify_platform_request(payload: BaseModel, timestamp: str, nonce: str, signature: str, presented_public_key: str | None) -> None:
    provider_org_id = getattr(payload, "provider_org_id", None)
    if provider_org_id and not ORGANIZATION_ID:
        raise HTTPException(503, "主体节点未绑定组织身份")
    if provider_org_id and ORGANIZATION_ID and provider_org_id != ORGANIZATION_ID:
        raise HTTPException(403, "请求主体与本地节点身份不一致")
    public_text = os.getenv("PLATFORM_SIGNING_PUBLIC_KEY", "").strip()
    if not public_text:
        if os.getenv("ALLOW_DEMO_KEY_REGISTRATION", "false").lower() not in {"1", "true", "yes", "on"} or not presented_public_key:
            raise HTTPException(503, "平台签名公钥未配置")
        with _database() as connection:
            registered = connection.execute("SELECT config_value FROM connector_config WHERE config_key = 'platform_public_key'").fetchone()
            if registered and registered["config_value"] != presented_public_key:
                raise HTTPException(401, "平台签名公钥与首次登记信息不一致")
            if not registered:
                connection.execute("INSERT INTO connector_config(config_key, config_value) VALUES ('platform_public_key', ?)", (presented_public_key,))
                connection.commit()
        public_text = presented_public_key
    try:
        occurred_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(401, "请求时间无效") from exc
    now = int(datetime.now(UTC).timestamp())
    if abs(now - occurred_at) > NONCE_TTL_SECONDS:
        raise HTTPException(401, "请求已过期")
    signed_payload = payload.model_dump(mode="json")
    # Keep the legacy connector test/protocol compatible while making the
    # subject-bound fields part of every new request when supplied.
    for field_name in ("request_item_id", "provider_org_id", "rule_version"):
        if signed_payload.get(field_name) is None:
            signed_payload.pop(field_name, None)
    message = {"timestamp": timestamp, "nonce": nonce, "payload": signed_payload}
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_text))
        public_key.verify(base64.b64decode(signature), _canonical(message))
    except Exception as exc:
        raise HTTPException(401, "平台数字签名验证失败") from exc
    with _database() as connection:
        connection.execute("DELETE FROM request_nonces WHERE occurred_at < ?", (now - NONCE_TTL_SECONDS,))
        try:
            connection.execute("INSERT INTO request_nonces(nonce, occurred_at) VALUES (?, ?)", (nonce, now))
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "检测到重复请求") from exc


def _query_values(payload: ComputeRequest) -> tuple[list[sqlite3.Row], str]:
    if payload.resource not in {item[0] for item in RESOURCE_DEFINITIONS[DOMAIN]}:
        raise HTTPException(422, "未找到该中文数据资源对应的受控资源")
    if payload.function not in FUNCTION_LABELS:
        raise HTTPException(422, "仅允许使用平台公布的固定函数")
    if payload.end_date < payload.start_date:
        raise HTTPException(422, "结束日期不能早于开始日期")
    clauses = ["resource = ?", "record_date BETWEEN ? AND ?"]
    params: list[Any] = [payload.resource, payload.start_date.isoformat(), payload.end_date.isoformat()]
    if payload.region:
        clauses.append("region = ?")
        params.append(payload.region)
    if payload.hour is None:
        clauses.append("hour IS NULL")
    else:
        clauses.append("hour = ?")
        params.append(payload.hour)
    sql = "SELECT record_date, hour, region, organization, value, unit FROM records WHERE " + " AND ".join(clauses) + " ORDER BY record_date, region"
    with _database() as connection:
        rows = connection.execute(sql, params).fetchall()
    if len(rows) < MIN_GROUP_SIZE:
        raise HTTPException(403, f"可用记录少于隐私保护下限 {MIN_GROUP_SIZE} 条")
    return rows, rows[0]["unit"]


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


def _dashboard_series(payload: DashboardRequest) -> tuple[list[dict[str, Any]], str, int]:
    if payload.resource not in {item[0] for item in RESOURCE_DEFINITIONS[DOMAIN]}:
        raise HTTPException(422, "未找到该能源域的受控数据资源")
    if payload.end_date < payload.start_date:
        raise HTTPException(422, "结束日期不能早于开始日期")
    sql = (
        "SELECT record_date, value, unit FROM records "
        "WHERE resource = ? AND record_date BETWEEN ? AND ? AND hour IS NULL "
        "ORDER BY record_date"
    )
    with _database() as connection:
        rows = connection.execute(
            sql,
            (payload.resource, payload.start_date.isoformat(), payload.end_date.isoformat()),
        ).fetchall()
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
    return points, unit, sum(len(values) for _day, values in valid_days)


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


@app.on_event("startup")
def startup() -> None:
    _initialize()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "就绪",
        "connector": CONNECTOR_NAME,
        "organization_id": ORGANIZATION_ID or None,
        "energy_domain": DOMAIN,
        "raw_data_centrally_stored": False,
        "public_key": PUBLIC_KEY,
    }


@app.get("/catalog")
def catalog() -> dict[str, Any]:
    return {
        "energy_domain": DOMAIN,
        "organization_id": ORGANIZATION_ID or None,
        "resources": [
            {"resource_id": resource, "name": name, "unit": unit, "granularity": "日度及受支持的小时级"}
            for resource, name, unit in RESOURCE_DEFINITIONS[DOMAIN]
        ],
        "functions": [{"code": code, "name": label} for code, label in FUNCTION_LABELS.items()],
        "notice": "这里只发布目录信息，原始数据保存在企业连接器中。",
    }


@app.post("/dashboard")
def dashboard_metrics(
    payload: DashboardRequest,
    x_request_timestamp: str = Header(alias="X-Request-Timestamp"),
    x_request_nonce: str = Header(alias="X-Request-Nonce"),
    x_request_signature: str = Header(alias="X-Request-Signature"),
    x_platform_public_key: str | None = Header(default=None, alias="X-Platform-Public-Key"),
) -> dict[str, Any]:
    _verify_platform_request(payload, x_request_timestamp, x_request_nonce, x_request_signature, x_platform_public_key)
    trend, unit, record_count = _dashboard_series(payload)
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
        "generated_at": datetime.now(UTC).isoformat(),
        "privacy": {
            "granularity": "day",
            "minimum_group_size": MIN_GROUP_SIZE,
            "raw_records_returned": False,
        },
        "raw_records_returned": False,
    }
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
    request_hash = hashlib.sha256(_canonical(payload.model_dump(mode="json"))).hexdigest()
    if payload.request_item_id:
        with _database() as connection:
            prior = connection.execute(
                "SELECT request_hash, result_hash, result_json FROM local_execution_receipts WHERE request_item_id = ?",
                (payload.request_item_id,),
            ).fetchone()
        if prior is not None:
            return json.loads(prior["result_json"])
    query_hash = hashlib.sha256(_canonical(payload.model_dump(mode="json"))).hexdigest()
    now = int(datetime.now(UTC).timestamp())
    with _database() as connection:
        record = connection.execute("SELECT repeated_count FROM query_log WHERE query_hash = ?", (query_hash,)).fetchone()
        if record and record["repeated_count"] >= 3:
            raise HTTPException(429, "相同或近似查询次数已达到隐私保护上限")
        total = connection.execute("SELECT COALESCE(SUM(repeated_count), 0) AS total FROM query_log").fetchone()["total"]
        if total >= QUERY_BUDGET:
            raise HTTPException(429, "本连接器查询预算已用尽")
        connection.execute(
            "INSERT INTO query_log(query_hash, repeated_count, occurred_at) VALUES (?, 1, ?) ON CONFLICT(query_hash) DO UPDATE SET repeated_count = repeated_count + 1, occurred_at = excluded.occurred_at",
            (query_hash, now),
        )
        connection.commit()
    rows, unit = _query_values(payload)
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
        "generated_at": datetime.now(UTC).isoformat(),
        "privacy": {"minimum_group_size": MIN_GROUP_SIZE, "raw_records_returned": False, "decimals": decimals},
        "capability": "本地受控计算" if payload.function != "mpc_aggregation" else "本地计算份额",
    }
    if payload.function == "trend":
        envelope["trend"] = _daily_trend(rows, decimals)
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
        with _database() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO local_execution_receipts(request_item_id, request_hash, result_hash, result_json, occurred_at) VALUES (?, ?, ?, ?, ?)",
                (payload.request_item_id, request_hash, result_hash, json.dumps(response, ensure_ascii=False, sort_keys=True), now),
            )
            connection.commit()
    return response
