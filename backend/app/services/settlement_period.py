from __future__ import annotations

import calendar
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DataUpload, SettlementTask
from .adapters import LocalControlledComputeAdapter


def parse_period(value: object) -> tuple[date, date] | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}", value):
            start = date.fromisoformat(value + "-01")
            return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            day = date.fromisoformat(value)
            return day, day
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}", value):
            start, end = (date.fromisoformat(item) for item in value.split("/"))
            return (start, end) if start <= end else None
    except ValueError:
        pass
    return None


def payload_period(payload: dict) -> tuple[date, date] | None:
    raw = payload.get("period")
    has_fields = "period_start" in payload or "period_end" in payload
    parsed = parse_period(raw) if raw is not None else None
    if not has_fields:
        return parsed
    start, end = payload.get("period_start"), payload.get("period_end")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    fields = parse_period(f"{start}/{end}")
    if fields is None or (raw is not None and parsed != fields):
        return None
    return fields


def select_period_upload(db: Session, task: SettlementTask, org_id: str, asset_type: str) -> tuple[DataUpload | None, bool]:
    candidates = db.scalars(
        select(DataUpload).where(
            DataUpload.owner_org_id == org_id,
            DataUpload.asset_type == asset_type,
            DataUpload.trade_batch_no == task.trade_batch_no,
            DataUpload.validation_status == "PASSED",
        ).order_by(DataUpload.created_at.desc(), DataUpload.upload_id.desc())
    ).all()
    for upload in candidates:
        # Summary metadata is only a candidate hint. The signed Vault payload
        # is checked after authorization and frozen input verification.
        if payload_period(upload.summary_json or {}) == (task.period_start, task.period_end):
            return upload, True
    return None, bool(candidates)


def matches_period(upload: DataUpload, task: SettlementTask) -> bool:
    try:
        payload = LocalControlledComputeAdapter._verified_vault_payload(upload)
        return payload_period(payload) == (task.period_start, task.period_end)
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
        return False
