from sqlalchemy import select

from app.database import SessionLocal
from app.trust_models import DataAssetVersion


def test_catalog_publishes_only_valid_declared_date_coverage(client, auth_headers):
    with SessionLocal() as db:
        version = db.scalar(select(DataAssetVersion).order_by(DataAssetVersion.created_at))
        asset_id, version_id = version.asset_id, version.version_id
    for schema, expected in [
        ({"period_start": "2021-01-01", "period_end": "2026-09-30"}, ("2021-01-01", "2026-09-30")),
        ({"period_start": "2026-09-30", "period_end": "2021-01-01"}, (None, None)),
        ({"period_start": "invalid", "period_end": "2026-09-30"}, (None, None)),
        ({}, (None, None)),
    ]:
        with SessionLocal() as db:
            db.get(DataAssetVersion, version_id).schema_json = schema
            db.commit()
        response = client.get("/api/trust-space/catalog?page_size=100", headers=auth_headers["regulator"])
        assert response.status_code == 200, response.text
        asset = next(item for item in response.json()["items"] if item["asset_id"] == asset_id)
        assert (asset["latest_version"].get("period_start"), asset["latest_version"].get("period_end")) == expected


def test_catalog_filter_options_cover_the_visible_scope_before_pagination_and_search(client, auth_headers):
    for account in ("regulator", "generator"):
        complete = client.get("/api/trust-space/catalog?page_size=100", headers=auth_headers[account]).json()
        expected = {
            "asset_types": sorted({item["asset_type"] for item in complete["items"]}),
            "domains": sorted({item["domain"] for item in complete["items"] if item["domain"]}),
        }
        for query in ("?page_size=1", "?page_size=1&query=no-matching-acceptance-asset"):
            response = client.get("/api/trust-space/catalog" + query, headers=auth_headers[account])
            assert response.status_code == 200
            assert response.json()["filter_options"] == expected
