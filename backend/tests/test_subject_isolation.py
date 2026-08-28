from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.trust_models import DataAsset


def _asset_id(owner_org_id: str) -> str:
    with SessionLocal() as db:
        asset = db.scalar(
            select(DataAsset)
            .where(DataAsset.owner_org_id == owner_org_id)
            .order_by(DataAsset.created_at)
        )
        assert asset is not None
        return asset.asset_id


def test_each_subject_has_same_energy_catalog_and_regulator_has_metadata_catalog(client, auth_headers):
    generator = client.get(
        "/api/trust-space/catalog?page=1&page_size=100",
        headers=auth_headers["generator"],
    )
    retailer = client.get(
        "/api/trust-space/catalog?page=1&page_size=100",
        headers=auth_headers["retailer"],
    )
    exchange = client.get(
        "/api/trust-space/catalog?page=1&page_size=100",
        headers=auth_headers["exchange"],
    )
    regulator = client.get(
        "/api/trust-space/catalog?page=1&page_size=100",
        headers=auth_headers["regulator"],
    )
    assert generator.status_code == retailer.status_code == exchange.status_code == regulator.status_code == 200
    electricity_subjects = {"org-generator-t01", "org-retailer-t01", "org-exchange-t01"}
    assert {
        item["provider"]["org_id"] for item in generator.json()["items"]
    } == electricity_subjects
    assert {
        item["provider"]["org_id"] for item in retailer.json()["items"]
    } == electricity_subjects
    assert {
        item["provider"]["org_id"] for item in exchange.json()["items"]
    } == electricity_subjects
    assert all(item["domain"] == "electricity" for item in exchange.json()["items"])
    assert all(
        item["actions"]["can_request_usage"]
        for item in exchange.json()["items"]
        if item["provider"]["org_id"] != "org-exchange-t01"
    )
    assert regulator.json()["total"] >= generator.json()["total"]
    assert regulator.json()["items"]

    generator_asset = _asset_id("org-generator-t01")
    retailer_asset = _asset_id("org-retailer-t01")
    assert client.get(
        f"/api/trust-space/assets/{retailer_asset}",
        headers=auth_headers["generator"],
    ).status_code == 200

    oil = client.get(
        "/api/trust-space/catalog?domain=oil&page=1&page_size=100",
        headers=auth_headers["exchange"],
    )
    assert oil.status_code == 200
    assert oil.json()["items"] == []
    assert client.get(
        f"/api/trust-space/assets/{generator_asset}",
        headers=auth_headers["regulator"],
    ).status_code == 200


def test_subject_rule_is_versioned_revocable_and_owner_scoped(client, auth_headers):
    body = {
        "rule_code": "GENERATION_DAILY_VARIANCE",
        "energy_domain": "electricity",
        "resource_id": "generation",
        "function_code": "variance",
        "mode": "ENTERPRISE_APPROVAL",
        "scope": {"granularity": "DAY", "fields": ["generation_mwh"]},
        "limits": {"max_days": 31},
    }
    first = client.post(
        "/api/data/access-rules",
        headers=auth_headers["generator"],
        json=body,
    )
    assert first.status_code == 201, first.text
    assert first.json()["owner_org_id"] == "org-generator-t01"
    assert first.json()["version"] == "v1"

    second = client.post(
        "/api/data/access-rules",
        headers=auth_headers["generator"],
        json=body,
    )
    assert second.status_code == 201, second.text
    assert second.json()["version"] == "v2"
    assert second.json()["rule_hash"] != first.json()["rule_hash"]

    own_rules = client.get(
        "/api/data/access-rules",
        headers=auth_headers["generator"],
    )
    other_rules = client.get(
        "/api/data/access-rules",
        headers=auth_headers["retailer"],
    )
    regulator_rules = client.get(
        "/api/data/access-rules",
        headers=auth_headers["regulator"],
    )
    assert own_rules.status_code == other_rules.status_code == regulator_rules.status_code == 200
    assert all(item["owner_org_id"] == "org-generator-t01" for item in own_rules.json()["items"])
    assert all(item["owner_org_id"] == "org-retailer-t01" for item in other_rules.json()["items"])
    assert {
        item["owner_org_id"] for item in regulator_rules.json()["items"]
    } >= {"org-generator-t01"}
    assert regulator_rules.json()["metadata_only"] is True

    revoked = client.post(
        f"/api/data/access-rules/{second.json()['rule_id']}/revoke",
        headers=auth_headers["generator"],
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "REVOKED"
    assert client.post(
        f"/api/data/access-rules/{second.json()['rule_id']}/revoke",
        headers=auth_headers["retailer"],
    ).status_code == 404


def test_rule_management_is_not_a_regulator_or_other_subject_bypass(client, auth_headers):
    payload = {
        "rule_code": "SHOULD_NOT_BE_CREATED",
        "resource_id": "generation",
        "function_code": "average",
        "mode": "AUTO_CALL",
    }
    assert client.post(
        "/api/data/access-rules",
        headers=auth_headers["regulator"],
        json=payload,
    ).status_code == 403
    assert client.post(
        "/api/data/access-rules",
        headers=auth_headers["retailer"],
        json=payload,
    ).status_code == 201
