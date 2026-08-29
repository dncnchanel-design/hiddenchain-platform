from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.demo_seed import (
    RESOURCE_DEFINITIONS,
    demo_seed_content_hash,
    seed_demo_authorization_request,
    seed_demo_catalog,
)
from app.migrations import apply_migrations
from app.models import DataUpload, DataUsageRequest, Organization, User
from app.trust_models import DataAsset, DataAssetVersion, DataSource


def test_demo_seed_contains_five_energy_domains_without_central_raw_data(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'trusted-demo.db').as_posix()}")
    apply_migrations(engine)
    with Session(engine) as db:
        seed_demo_catalog(db)
        assert db.scalar(select(func.count(Organization.org_id))) == 13
        assert db.scalar(select(func.count(User.user_id))) == 13
        assert db.scalar(select(func.count(DataUpload.upload_id))) == 0
        assert db.scalar(select(func.count(DataAsset.asset_id))) == sum(map(len, RESOURCE_DEFINITIONS.values()))
        assert set(db.scalars(select(Organization.energy_domain).where(Organization.energy_domain.is_not(None)))) == {
            "electricity",
            "coal",
            "heat",
            "gas",
            "oil",
        }
        assert all(source.metadata_json.get("raw_data_centrally_stored") is False for source in db.scalars(select(DataSource)))
        assert all(asset.asset_name and asset.asset_name.isascii() is False for asset in db.scalars(select(DataAsset)))
        inventory = db.get(DataAssetVersion, "version-coal-inventory-1")
        load = db.get(DataAssetVersion, "version-electricity-load-1")
        assert inventory is not None and load is not None
        assert inventory.data_ref == "connector://local-node-org-coal-t01/inventory/versions/1"
        assert inventory.data_hash == demo_seed_content_hash(
            "org-coal-t01", "coal", "inventory"
        )
        assert inventory.record_count == 1460
        assert load.record_count == 36500


def test_demo_seed_contains_one_pending_regulatory_authorization(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'trusted-demo-authorization.db').as_posix()}")
    apply_migrations(engine)
    with Session(engine) as db:
        seed_demo_catalog(db)
        seed_demo_authorization_request(db)
        seed_demo_authorization_request(db)

        requests = db.scalars(select(DataUsageRequest)).all()
        assert len(requests) == 1
        assert requests[0].applicant_org_id == "org-regulator-t01"
        assert requests[0].provider_org_id == "org-retailer-t01"
        assert requests[0].purpose == "REGULATORY_CROSS_ENERGY_REVIEW"
        assert requests[0].status == "SUBMITTED"
        assert requests[0].contract_id is None
        assert requests[0].agreement_id is None
