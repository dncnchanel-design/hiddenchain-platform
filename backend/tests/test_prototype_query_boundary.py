from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditLog, BlockchainEvidence, DataUpload, DataUsageRequest, utc_now
from app.trust_models import DataAsset


def _metadata_only_asset(*, record_count=None, summaries=()):
    """Synthetic catalog/upload metadata is not a controlled energy result."""
    with SessionLocal() as db:
        asset = db.scalar(
            select(DataAsset)
            .where(DataAsset.owner_org_id == "org-generator-t01")
            .order_by(DataAsset.created_at)
        )
        assert asset is not None
        asset.metadata_json = {
            "domain": "electricity",
            "resource_id": "generation",
            **({"record_count": record_count} if record_count is not None else {}),
        }
        uploads = db.scalars(
            select(DataUpload)
            .where(DataUpload.owner_org_id == asset.owner_org_id)
            .order_by(DataUpload.upload_id)
        ).all()
        assert len(uploads) >= len(summaries)
        for index, upload in enumerate(uploads):
            upload.summary_json = summaries[index] if index < len(summaries) else {}
        asset_id = asset.asset_id
        db.commit()
        return asset_id


def _assert_not_executed(body):
    assert body["result"] is None
    assert body["decision"]["action"] == "deny"
    assert body["decision"]["label"] == "禁止提供"
    assert "未执行" in body["decision"]["reason"]
    assert "确认" in body["decision"]["reason"]
    assert body["execution_status"] == "NOT_EXECUTED"
    assert body["replacement_path"] == "/trusted-space/query"
    assert body["parse_endpoint"] == "/api/trust-space/query/parse"
    assert body["raw_data_returned"] is False
    execution = next(item for item in body["plan"] if item["stage"] == "受控执行")
    assert execution["status"] == "未执行"


@pytest.mark.parametrize(
    "record_count,summaries",
    [
        (None, ()),
        (12345, ()),
        (None, ({"generation": 12, "period": "2026-07"}, {"generation": 88, "period": "2026-08"})),
        (None, ({"energy_mwh": [7, 11], "period": "2020-01"},)),
        (None, ({"load_curve": [9, 21], "record_count": 300},)),
    ],
    ids=["missing-values", "metadata-record-count", "cross-month-values", "unverified-energy-array", "unrelated-load-array"],
)
def test_legacy_query_never_returns_metadata_as_energy(client, auth_headers, record_count, summaries):
    _metadata_only_asset(record_count=record_count, summaries=summaries)
    for question in ("查询2026年7月平均发电量", "查询2020年1月平均发电量"):
        response = client.post(
            "/api/prototype/query",
            headers=auth_headers["generator"],
            json={"text": question},
        )
        assert response.status_code == 200
        _assert_not_executed(response.json())


@pytest.mark.parametrize("role", ["generator", "regulator", "retailer"])
def test_legacy_query_does_not_record_or_project_success(client, auth_headers, role):
    asset_id = _metadata_only_asset(record_count=9876)
    if role == "retailer":
        with SessionLocal() as db:
            asset = db.get(DataAsset, asset_id)
            db.add(DataUsageRequest(
                asset_id=asset.asset_id,
                asset_version_id=asset.current_version_id,
                applicant_user_id="user-retailer",
                applicant_org_id="org-retailer-t01",
                provider_org_id=asset.owner_org_id,
                applicant_did="did:hiddenchain:org:org-retailer-t01",
                provider_did="did:hiddenchain:org:org-generator-t01",
                purpose="合成回归验证",
                usage_mode="AGGREGATE",
                duration_days=1,
                expires_at=utc_now() + timedelta(days=1),
                status="APPROVED",
                trace_id="prototype-query-boundary-test",
            ))
            db.commit()
    response = client.post(
        "/api/prototype/query",
        headers=auth_headers[role],
        json={"text": "查询2026年7月平均发电量"},
    )
    assert response.status_code == 200
    body = response.json()
    with SessionLocal() as db:
        records = db.scalars(select(AuditLog).where(AuditLog.target_type == "PROTOTYPE_QUERY")).all()
        assert len(records) == 1
        audit = records[0]
        assert audit.result == "DENIED"
        assert audit.action_code == "PROTOTYPE_QUERY_DENIED"
        assert audit.details_json["prototype_action"] == "deny"
        assert audit.details_json["execution_status"] == "NOT_EXECUTED"
        assert audit.details_json["reason"] == body["decision"]["reason"]
        assert db.get(BlockchainEvidence, body["audit_id"]) is not None
        audit_id = audit.log_id
    projected = client.get("/api/prototype/audit", headers=auth_headers["regulator"])
    assert projected.status_code == 200
    row = next(item for item in projected.json()["records"] if item["id"] == audit_id)
    assert row["action"] == "deny"
    assert row["action_name"] == "禁止提供"
    assert row["result"] == "DENIED"
    _assert_not_executed(body)


def test_legacy_query_preserves_business_role_authorization(client, auth_headers):
    _metadata_only_asset()
    payload = {"text": "查询2026年7月平均发电量"}
    assert client.post("/api/prototype/query", json=payload).status_code == 401
    assert client.post("/api/prototype/query", headers=auth_headers["admin"], json=payload).status_code == 403
    denied = client.post("/api/prototype/query", headers=auth_headers["retailer"], json=payload)
    assert denied.status_code == 200
    _assert_not_executed(denied.json())
    assert "没有该数据资源的有效授权" in denied.json()["decision"]["reason"]


def test_unrecognized_legacy_query_still_points_to_confirmed_query_flow(client, auth_headers):
    response = client.post(
        "/api/prototype/query",
        headers=auth_headers["generator"],
        json={"text": "你好"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"] is None
    assert body["decision"]["action"] == "deny"
    assert body["execution_status"] == "NOT_EXECUTED"
    assert body["replacement_path"] == "/trusted-space/query"
    assert body["parse_endpoint"] == "/api/trust-space/query/parse"
