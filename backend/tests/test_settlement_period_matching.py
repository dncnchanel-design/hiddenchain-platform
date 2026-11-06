from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from sqlalchemy import select

from app.database import SessionLocal
from app.models import DataUpload
from app.services.settlement_period import matches_period, parse_period, payload_period, select_period_upload
from app.services.vault import LocalDomainVault


@pytest.mark.parametrize("value, expected", [
    ("2024-02", (date(2024, 2, 1), date(2024, 2, 29))),
    ("2026-07-03", (date(2026, 7, 3), date(2026, 7, 3))),
    (None, None), ("2026-02-30", None), ("2026-7", None),
    ("2026-07-01/2026-07-30", (date(2026, 7, 1), date(2026, 7, 30))),
    ("2026-07-30/2026-07-01", None), ("七月", None),
])
def test_parse_period(value, expected):
    assert parse_period(value) == expected


def test_explicit_period_fields_must_be_complete_and_consistent():
    bounds = {"period_start": "2026-07-01", "period_end": "2026-07-30"}
    assert payload_period(bounds) == (date(2026, 7, 1), date(2026, 7, 30))
    assert payload_period({**bounds, "period": "2026-07"}) is None
    assert payload_period({"period_start": "2026-07-01"}) is None


def test_mismatched_period_blocks_preflight_and_execution(client, auth_headers):
    payload = {
        "task_name": "期间不匹配", "trade_batch_no": "TB-2026-07-T01",
        "period_start": "2026-07-01", "period_end": "2026-07-30",
        "rule_id": "rule-settlement-v1",
        "participants": [{"org_id": "org-generator-t01", "role_in_task": "GENERATOR"},
                         {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}],
    }
    task = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json=payload)
    assert task.status_code == 201, task.text
    assert not task.json()["readiness"]["preflight_passed"]
    response = client.post(f"/api/settlement/tasks/{task.json()['task_id']}/run",
                           headers={**auth_headers["exchange"], "If-Match": task.headers["etag"]},
                           json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"})
    assert response.status_code != 200


def test_selection_is_only_a_hint_and_signed_payload_is_checked_separately():
    task = SimpleNamespace(trade_batch_no="TB-2026-07-T01", period_start=date(2026, 7, 1), period_end=date(2026, 7, 31))
    with SessionLocal() as db:
        old = db.scalar(select(DataUpload).where(DataUpload.owner_org_id == "org-generator-t01", DataUpload.asset_type == "GENERATION_DATA", DataUpload.trade_batch_no == task.trade_batch_no))
        ref, digest, commitment = LocalDomainVault.write(old.owner_org_id, "period-newer", {"period": "2026-08", "energy_mwh": 1})
        db.add(DataUpload(upload_id="period-newer", owner_org_id=old.owner_org_id, asset_type=old.asset_type,
                          trade_batch_no=old.trade_batch_no, label="newer", data_ref=ref, data_hash=digest,
                          commitment=commitment, schema_version="v1", validation_status="PASSED",
                          created_at=old.created_at + timedelta(days=1), summary_json={"period": "2026-08"}))
        db.flush()
        selected, has_candidates = select_period_upload(db, task, old.owner_org_id, old.asset_type)
        assert has_candidates and selected.upload_id == old.upload_id
        # Metadata is only a hint; it cannot override the signed Vault period.
        newer = db.get(DataUpload, "period-newer")
        newer.summary_json = {"period": "2026-07"}
        db.flush()
        selected, _ = select_period_upload(db, task, old.owner_org_id, old.asset_type)
        assert selected.upload_id == newer.upload_id
        assert not matches_period(selected, task)
        LocalDomainVault.write(old.owner_org_id, old.upload_id, {"period": "2026-07", "energy_mwh": 0})
        assert not matches_period(old, task)


def test_uploaded_explicit_bounds_are_available_for_matching(client, auth_headers):
    response = client.post("/api/data/uploads", headers=auth_headers["generator"], json={
        "asset_type": "GENERATION_DATA", "trade_batch_no": "RANGE-TEST", "label": "自定义期间数据",
        "local_payload": {"period_start": "2026-07-02", "period_end": "2026-07-30", "energy_mwh": 10},
    })
    assert response.status_code == 201, response.text
    task = SimpleNamespace(trade_batch_no="RANGE-TEST", period_start=date(2026, 7, 2), period_end=date(2026, 7, 30))
    with SessionLocal() as db:
        upload, has_candidates = select_period_upload(db, task, "org-generator-t01", "GENERATION_DATA")
        assert has_candidates and upload is not None
        assert upload.upload_id == response.json()["upload_id"]


def test_forged_period_summary_never_authorizes_compute(client, auth_headers):
    response = client.post("/api/data/uploads", headers=auth_headers["generator"], json={
        "asset_type": "GENERATION_DATA", "trade_batch_no": "TB-2026-07-T01", "label": "错期数据",
        "local_payload": {"period": "2026-08", "energy_mwh": 10},
    })
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        upload = db.get(DataUpload, response.json()["upload_id"])
        upload.summary_json = {**upload.summary_json, "period": "2026-07"}
        db.commit()
    task = client.get("/api/settlement/tasks/task-ready-t01", headers=auth_headers["exchange"])
    response = client.post("/api/settlement/tasks/task-ready-t01/run",
                           headers={**auth_headers["exchange"], "If-Match": task.headers["etag"]},
                           json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"})
    assert response.status_code != 200
    assert "期间" in response.text
