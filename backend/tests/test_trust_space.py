from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.trust_models import DataAsset


def _asset_by_owner(owner_org_id: str) -> DataAsset:
    with SessionLocal() as db:
        asset = db.scalar(
            select(DataAsset)
            .where(DataAsset.owner_org_id == owner_org_id)
            .order_by(DataAsset.created_at)
        )
        assert asset is not None
        return asset


def test_trust_space_openapi_contract_and_role_context_is_dynamic(client, auth_headers):
    schema = client.get("/api/openapi.json").json()
    for path in (
        "/api/trust-space/context",
        "/api/trust-space/workbench",
        "/api/trust-space/identity",
        "/api/trust-space/catalog",
        "/api/trust-space/assets/{asset_id}",
    ):
        assert path in schema["paths"]

    generator = client.get("/api/trust-space/context", headers=auth_headers["generator"])
    exchange = client.get("/api/trust-space/context", headers=auth_headers["exchange"])
    assert generator.status_code == exchange.status_code == 200
    generator_body = generator.json()
    exchange_body = exchange.json()
    assert generator_body["actor"]["role_code"] == "GENERATOR"
    assert generator_body["current_subject"]["org_id"] == "org-generator-t01"
    assert exchange_body["actor"]["role_code"] == "EXCHANGE"
    assert exchange_body["current_subject"]["org_id"] == "org-exchange-t01"
    assert generator_body["current_subject"]["org_id"] != exchange_body["current_subject"]["org_id"]
    assert generator_body["role_capabilities"]["can_view_all_assets"] is False
    assert exchange_body["role_capabilities"]["can_view_all_assets"] is True
    assert generator_body["identity_ref"]["source_of_truth"] == "did_identities"
    assert generator_body["capabilities"]["data_space_connector"]["capability_state"] == "ADAPTER"
    assert generator_body["capabilities"]["data_space_connector"]["readiness"] == "NOT_CONFIGURED"
    assert generator_body["capabilities"]["tee"]["capability_state"] == "BLOCKED"
    assert generator_body["capabilities"]["blockchain_anchor"]["capability_state"] == "DEMO"
    upload_menu = next(menu for menu in generator_body["visible_menus"] if menu["code"] == "excel-upload")
    assert upload_menu["title"] == "数据上传"
    assert upload_menu["path"] == "/trusted-space/upload"


def test_workbench_respects_provider_scope_and_returns_real_empty_shape(client, auth_headers):
    generator = client.get("/api/trust-space/workbench", headers=auth_headers["generator"])
    exchange = client.get("/api/trust-space/workbench", headers=auth_headers["exchange"])
    assert generator.status_code == exchange.status_code == 200
    generator_body = generator.json()
    exchange_body = exchange.json()
    assert isinstance(generator_body["kpis"]["visible_assets"], int)
    assert isinstance(generator_body["recent_assets"], list)
    assert isinstance(generator_body["recent_tasks"], list)
    assert isinstance(generator_body["recent_usage_requests"], list)
    assert generator_body["capability_state"] == "LOCAL_REAL"
    assert all(item["owner_org_id"] == "org-generator-t01" for item in generator_body["recent_assets"])
    for task in generator_body["recent_tasks"]:
        estimate = task["phase_progress_estimate"]
        assert estimate["source"] == "TTC_STATE_PHASE_ESTIMATE_V1"
        assert "非实时执行进度" in estimate["label"]
    assert exchange_body["kpis"]["visible_assets"] >= generator_body["kpis"]["visible_assets"]
    assert isinstance(exchange_body["empty_state"], bool)
    assert exchange_body["source_of_truth"] == "authoritative database read model"


def test_catalog_filters_pagination_and_provider_visibility(client, auth_headers):
    exchange = client.get(
        "/api/trust-space/catalog?page=1&page_size=1",
        headers=auth_headers["exchange"],
    )
    assert exchange.status_code == 200, exchange.text
    exchange_body = exchange.json()
    assert exchange_body["total"] >= 1
    assert len(exchange_body["items"]) <= 1
    assert exchange_body["items"][0]["capability_state"] == "LOCAL_REAL"
    first = exchange_body["items"][0]

    filtered = client.get(
        "/api/trust-space/catalog"
        f"?asset_type={first['asset_type']}&provider_org_id={first['provider']['org_id']}",
        headers=auth_headers["exchange"],
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] >= 1
    assert all(
        item["asset_type"] == first["asset_type"]
        and item["provider"]["org_id"] == first["provider"]["org_id"]
        for item in filtered.json()["items"]
    )

    generator = client.get("/api/trust-space/catalog?page_size=100", headers=auth_headers["generator"])
    assert generator.status_code == 200
    generator_items = generator.json()["items"]
    assert generator_items
    assert all(item["provider"]["org_id"] == "org-generator-t01" for item in generator_items)

    no_match = client.get(
        "/api/trust-space/catalog?q=asset-that-does-not-exist",
        headers=auth_headers["exchange"],
    )
    assert no_match.status_code == 200
    assert no_match.json()["total"] == 0
    assert no_match.json()["items"] == []
    assert no_match.json()["empty_state"] is True


def test_identity_reports_recorded_did_and_honest_connector_boundary(client, auth_headers):
    response = client.get("/api/trust-space/identity", headers=auth_headers["generator"])
    assert response.status_code == 200
    body = response.json()
    assert body["subject"]["org_id"] == "org-generator-t01"
    assert body["did"]["did_id"] == "did:hiddenchain:org:org-generator-t01"
    assert body["did"]["credential_status"] == "VALID"
    assert body["did"]["source_of_truth"] == "did_identities"
    assert body["connector"]["readiness"] == "NOT_CONFIGURED"
    assert body["connector"]["external_edc_runtime"] == "NOT_CONFIGURED"
    assert body["connector"]["capability_state"] in {"ADAPTER", "NOT_CONFIGURED"}
    assert body["capability_matrix"]["tee"]["capability_state"] == "BLOCKED"
    assert body["capability_matrix"]["blockchain"]["capability_state"] == "DEMO"
    assert body["capability_matrix"]["connector_control_plane"]["readiness"] == "NOT_CONFIGURED"


def test_asset_detail_uses_real_id_and_enforces_visibility(client, auth_headers):
    generator_asset = _asset_by_owner("org-generator-t01")
    retailer_asset = _asset_by_owner("org-retailer-t01")

    detail = client.get(
        f"/api/trust-space/assets/{generator_asset.asset_id}",
        headers=auth_headers["generator"],
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["asset"]["asset_id"] == generator_asset.asset_id
    assert body["versions"]
    assert body["versions"][0]["passport"] is not None
    assert body["versions"][0]["quality"] is not None
    assert body["source_of_truth"] == "data_assets/data_asset_versions/data_asset_passports"
    assert body["evidence_summary"]["capability_state"] == "LOCAL_REAL"

    exchange_detail = client.get(
        f"/api/trust-space/assets/{retailer_asset.asset_id}",
        headers=auth_headers["exchange"],
    )
    assert exchange_detail.status_code == 200
    assert exchange_detail.json()["asset"]["asset_id"] == retailer_asset.asset_id

    cross_scope = client.get(
        f"/api/trust-space/assets/{retailer_asset.asset_id}",
        headers=auth_headers["generator"],
    )
    assert cross_scope.status_code == 404
    unknown = client.get(
        "/api/trust-space/assets/asset-does-not-exist",
        headers=auth_headers["exchange"],
    )
    assert unknown.status_code == 404
