from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.demo_seed import RESOURCE_DEFINITIONS, seed_demo_catalog
from app.migrations import apply_migrations
from app.models import DataUpload, Organization, User
from app.trust_models import DataAsset, DataSource


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
