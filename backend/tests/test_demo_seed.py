from __future__ import annotations

from datetime import datetime
import base64
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Lock, Thread
import time

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import demo_seed
from app.config import settings
from app.demo_seed import (
    RESOURCE_DEFINITIONS,
    demo_seed_content_hash,
    seed_demo_authorization_request,
    seed_demo_catalog,
)
from app.migrations import apply_migrations
from app.models import AuditLog, DataUpload, DataUsageRequest, Organization, User
from app.security import canonical_json, sha256_json
from app.services import synthetic_catalog
from app.trust_models import DataAsset, DataAssetPassport, DataAssetVersion, DataSource


@pytest.fixture(autouse=True)
def reset_test_database():
    # Every test below creates its own metadata-only database under tmp_path.
    yield


def _catalog(owner, domain, key):
    connector_id = f"local-node-{owner}"
    resources = []
    for resource, name, unit in RESOURCE_DEFINITIONS[domain]:
        hourly = (domain, resource) in synthetic_catalog.HOURLY_RESOURCES
        count = 2099 * 4 * (25 if hourly else 1)
        description = {"generator_version": synthetic_catalog.SEED_VERSION, "connector_id": connector_id, "organization_label": "企业连接器", "energy_domain": domain, "resource_id": resource, "unit": unit, "period_start": "2021-01-01", "period_end": "2026-09-30", "regions": synthetic_catalog.REGIONS, "daily_rows_per_day": 4, "hourly_available": hourly, "hourly_semantics": "daily_mean" if unit == "MW" else "daily_total", "value_decimals": 6, "record_count": count}
        seed = {"version": 2, "schema_version": synthetic_catalog.SEED_VERSION, "schema_hash": sha256_json({"schema_version": synthetic_catalog.SEED_VERSION, "fields": ["record_date", "hour", "region", "organization", "value", "unit"], "unit": unit, "value_decimals": 6}), "content_hash": sha256_json({"owner": owner, "resource": resource, "test_content": True}), "record_count": count, "local_ref": f"connector://{connector_id}/{resource}/versions/2", "manifest": description, "manifest_hash": sha256_json(description)}
        resources.append({"resource_id": resource, "name": name, "unit": unit, "latest_version": 2, "record_count": count, "current_schema_version": synthetic_catalog.SEED_VERSION, "synthetic_seed": seed})
    payload = {"connector_id": connector_id, "organization_id": owner, "energy_domain": domain, "seed_catalog_version": synthetic_catalog.SEED_VERSION, "resources": resources}
    return _sign_catalog(payload, key)


def _sign_catalog(payload, key):
    signed = {field: value for field, value in payload.items() if field not in {"signature", "public_key", "signature_algorithm", "signature_valid"}}
    return {**signed, "public_key": base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode(), "signature": base64.b64encode(key.sign(canonical_json(signed).encode())).decode(), "signature_algorithm": "Ed25519", "signature_valid": True}


def _enable_verified_catalogs(monkeypatch):
    monkeypatch.setattr(demo_seed, "settings", replace(settings, app_env="demo", demo_catalog_seed=True))
    def load(_db, owners):
        verified = {}
        for owner, (domain, units) in owners.items():
            key = Ed25519PrivateKey.generate()
            payload = _catalog(owner, domain, key)
            verified[owner] = synthetic_catalog.verify_catalog(payload, public_key=payload["public_key"], connector_id=f"local-node-{owner}", owner_org_id=owner, domain=domain, units=units)
        return verified
    monkeypatch.setattr(demo_seed, "load_verified_catalogs", load)


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
        assert inventory.effective_until is None
        assert load.effective_until is None


def test_demo_catalog_repairs_only_its_known_validity_cutoff(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'demo-validity.db').as_posix()}")
    apply_migrations(engine)
    with Session(engine) as db:
        seed_demo_catalog(db)
        seed_demo_authorization_request(db)
        inventory = db.get(DataAssetVersion, "version-coal-inventory-1")
        uploaded = db.get(DataAssetVersion, "version-electricity-load-1")
        assert inventory is not None and uploaded is not None
        inventory.effective_until = datetime(2026, 8, 31, 23, 59, 59)
        uploaded.effective_until = datetime(2026, 8, 31, 23, 59, 59)
        uploaded.schema_version = "connector-csv-v1"
        frozen = (inventory.data_hash, inventory.immutable_hash, inventory.data_ref, inventory.version_no)
        grant = db.scalar(select(DataUsageRequest))
        assert grant is not None
        grant_expiry, grant_status = grant.expires_at, grant.status
        db.commit()

        seed_demo_catalog(db)
        seed_demo_catalog(db)
        db.refresh(inventory)
        db.refresh(uploaded)
        db.refresh(grant)
        assert inventory.effective_until is None
        assert (inventory.data_hash, inventory.immutable_hash, inventory.data_ref, inventory.version_no) == frozen
        assert uploaded.effective_until == datetime(2026, 8, 31, 23, 59, 59)
        assert (grant.expires_at, grant.status) == (grant_expiry, grant_status)


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
        assert not requests[0].requested_scope_json.get("region")
        assert requests[0].contract_id is None
        assert requests[0].agreement_id is None


def test_verified_v2_upgrade_preserves_all_29_owners_v1_passports_and_existing_grants(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'verified-upgrade.db').as_posix()}")
    apply_migrations(engine)
    with Session(engine) as db:
        seed_demo_catalog(db)
        seed_demo_authorization_request(db)
        assets = db.scalars(select(DataAsset)).all()
        old_owners = {asset.asset_id: asset.owner_org_id for asset in assets}
        versions = {version.version_id: (version.data_hash, version.immutable_hash, version.data_ref, version.record_count) for version in db.scalars(select(DataAssetVersion))}
        passports = {passport.passport_id: (passport.passport_hash, passport.permitted_use_json) for passport in db.scalars(select(DataAssetPassport))}
        grant = db.scalar(select(DataUsageRequest))
        grant_before = (grant.asset_version_id, grant.status, grant.expires_at)
        _enable_verified_catalogs(monkeypatch)
        seed_demo_catalog(db)
        seed_demo_catalog(db)
        assert len(assets) == 29
        assert {asset.asset_id: asset.owner_org_id for asset in db.scalars(select(DataAsset))} == old_owners
        upgraded = db.scalars(select(DataAssetVersion).where(DataAssetVersion.schema_version == synthetic_catalog.SEED_VERSION)).all()
        assert len(upgraded) == 29
        assert all(version.schema_json["period_start"] == "2021-01-01" and version.schema_json["period_end"] == "2026-09-30" for version in upgraded)
        assert all(version.record_count == 8396 * (25 if version.schema_json["hourly_available"] else 1) for version in upgraded)
        for version_id, frozen in versions.items():
            db.expire_all()
            version = db.get(DataAssetVersion, version_id)
            assert (version.data_hash, version.immutable_hash, version.data_ref, version.record_count) == frozen
        for passport_id, frozen in passports.items():
            passport = db.get(DataAssetPassport, passport_id)
            assert (passport.passport_hash, passport.permitted_use_json) == frozen
        db.refresh(grant)
        assert (grant.asset_version_id, grant.status, grant.expires_at) == grant_before
        assert db.scalar(select(func.count(DataUpload.upload_id))) == 0


def test_new_pending_demo_request_uses_verified_current_v2(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'current-authorization.db').as_posix()}")
    apply_migrations(engine)
    with Session(engine) as db:
        seed_demo_catalog(db)
        _enable_verified_catalogs(monkeypatch)
        seed_demo_catalog(db)
        seed_demo_authorization_request(db)
        grant = db.scalar(select(DataUsageRequest))
        assert grant.asset_version_id == db.get(DataAsset, "asset-electricity-load").current_version_id == "version-electricity-load-2"


def test_user_current_or_occupied_version_two_is_not_replaced(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'user-current.db').as_posix()}")
    apply_migrations(engine)
    with Session(engine) as db:
        seed_demo_catalog(db)
        asset = db.get(DataAsset, "asset-coal-inventory")
        uploaded = DataAssetVersion(version_id="user-version", asset_id=asset.asset_id, version_no=2, schema_version="connector-csv-v1", data_ref="connector://local-node-org-coal-t01/inventory/versions/2", data_hash="d" * 64, immutable_hash="e" * 64, record_count=17)
        db.add(uploaded)
        db.flush()
        asset.current_version_id = uploaded.version_id
        db.commit()
        _enable_verified_catalogs(monkeypatch)
        seed_demo_catalog(db)
        db.refresh(asset)
        db.refresh(uploaded)
        assert asset.current_version_id == "user-version"
        assert (uploaded.schema_version, uploaded.data_hash, uploaded.record_count) == ("connector-csv-v1", "d" * 64, 17)
        assert db.get(DataAssetVersion, "version-coal-inventory-2") is None


@pytest.mark.parametrize("mutation", ["signature", "owner", "period", "count", "hash", "local_ref"])
def test_signed_catalog_rejects_tampering_or_inconsistent_manifest(mutation):
    key = Ed25519PrivateKey.generate()
    owner = "org-coal-t01"
    payload = _catalog(owner, "coal", key)
    if mutation == "signature":
        payload["signature"] = base64.b64encode(b"x" * 64).decode()
    else:
        seed = payload["resources"][0]["synthetic_seed"]
        if mutation == "owner": payload["organization_id"] = "another-owner"
        elif mutation == "period": seed["manifest"]["period_start"] = "2020-01-01"
        elif mutation == "count": seed["record_count"] -= 1
        elif mutation == "hash": seed["content_hash"] = "not-a-hash"
        elif mutation == "local_ref": seed["local_ref"] = "connector://another-node/resource/versions/2"
        payload = _sign_catalog(payload, key)
    with pytest.raises(synthetic_catalog.SyntheticCatalogError):
        synthetic_catalog.verify_catalog(payload, public_key=payload["public_key"], connector_id=f"local-node-{owner}", owner_org_id=owner, domain="coal", units={resource: unit for resource, _name, unit in RESOURCE_DEFINITIONS["coal"]})


def test_failed_handshake_audits_failure_and_keeps_v1(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'failed-handshake.db').as_posix()}")
    apply_migrations(engine)
    with Session(engine) as db:
        seed_demo_catalog(db)
        enabled = replace(settings, app_env="demo", demo_catalog_seed=True)
        monkeypatch.setattr(demo_seed, "settings", enabled)
        monkeypatch.setattr(synthetic_catalog, "settings", enabled)
        monkeypatch.setattr(synthetic_catalog, "subject_node_config", lambda _db, owner: {"endpoint": "http://unused.invalid", "node_code": f"local-node-{owner}"})
        monkeypatch.setattr(synthetic_catalog, "_fetch_catalog", lambda request: (request["owner"], None, "SYNTHETIC_CATALOG_UNAVAILABLE"))
        seed_demo_catalog(db)
        assert db.scalar(select(func.count(DataAssetVersion.version_id))) == 29
        failures = db.scalars(select(AuditLog).where(AuditLog.action_code == "DEMO_SYNTHETIC_CATALOG_SYNC")).all()
        assert len(failures) == 7 and all(item.result == "FAILED" for item in failures)


def test_startup_metadata_handshake_recovers_from_a_real_delayed_http_listener():
    key = Ed25519PrivateKey.generate()
    owner, domain = "org-coal-t01", "coal"
    catalog = _catalog(owner, domain, key)
    health = {"connector_id": f"local-node-{owner}", "organization_id": owner, "energy_domain": domain, "public_key": catalog["public_key"]}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(health if self.path == "/health" else catalog).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler, bind_and_activate=False)
    server.server_bind()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}"
    with pytest.raises(httpx.HTTPError):
        httpx.get(f"{endpoint}/health", timeout=0.2)
    def delayed_start():
        time.sleep(0.6)
        server.server_activate()
        server.serve_forever(poll_interval=0.05)
    thread = Thread(target=delayed_start, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        result_owner, verified, error = synthetic_catalog._fetch_catalog({"owner": owner, "domain": domain, "node": {"endpoint": endpoint, "node_code": health["connector_id"], "public_key": None}, "units": {resource: unit for resource, _name, unit in RESOURCE_DEFINITIONS[domain]}, "deadline": time.monotonic() + 5})
        assert result_owner == owner and error is None and len(verified) == 6
        assert 0.6 <= time.monotonic() - started < 5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_startup_metadata_retries_availability_but_never_an_identity_mismatch(monkeypatch):
    key = Ed25519PrivateKey.generate()
    owner, domain = "org-coal-t01", "coal"
    catalog = _catalog(owner, domain, key)
    health = {"connector_id": f"local-node-{owner}", "organization_id": owner, "energy_domain": domain, "public_key": catalog["public_key"]}
    request = {"owner": owner, "domain": domain, "node": {"endpoint": "http://node.test", "node_code": health["connector_id"], "public_key": None}, "units": {resource: unit for resource, _name, unit in RESOURCE_DEFINITIONS[domain]}, "deadline": time.monotonic() + 5}
    calls = []

    def transient_then_ready(url, **_kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise httpx.ConnectError("listener not yet ready")
        return httpx.Response(200, json=health if url.endswith("/health") else catalog, request=httpx.Request("GET", url))

    monkeypatch.setattr(synthetic_catalog.httpx, "get", transient_then_ready)
    monkeypatch.setattr(synthetic_catalog.time, "sleep", lambda _seconds: None)
    result_owner, verified, error = synthetic_catalog._fetch_catalog(request)
    assert result_owner == owner and error is None and len(verified) == 6
    assert calls == ["http://node.test/health", "http://node.test/health", "http://node.test/catalog"]

    calls.clear()

    def wrong_identity(url, **_kwargs):
        calls.append(url)
        return httpx.Response(200, json={**health, "organization_id": "another-owner"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(synthetic_catalog.httpx, "get", wrong_identity)
    assert synthetic_catalog._fetch_catalog(request) == (owner, None, "SYNTHETIC_CONNECTOR_IDENTITY_INVALID")
    assert calls == ["http://node.test/health"]


def test_every_configured_subject_can_start_its_handshake_while_other_nodes_are_cold(monkeypatch):
    enabled = replace(settings, app_env="demo", demo_catalog_seed=True)
    monkeypatch.setattr(synthetic_catalog, "settings", enabled)
    owners = {f"org-{name}-t01": ("electricity", {"load": "MW"}) for name in ("generator", "retailer", "exchange", "coal", "heat", "gas", "oil")}
    monkeypatch.setattr(synthetic_catalog, "subject_node_config", lambda _db, owner: {"endpoint": "http://unused.invalid", "node_code": f"local-node-{owner}"})
    started, lock, all_started = set(), Lock(), Event()

    def fetch(request):
        with lock:
            started.add(request["owner"])
            if started == set(owners):
                all_started.set()
        assert all_started.wait(2), "Cold nodes must not prevent other subjects receiving their first request"
        return request["owner"], {}, None

    monkeypatch.setattr(synthetic_catalog, "_fetch_catalog", fetch)
    assert set(synthetic_catalog.load_verified_catalogs(None, owners)) == set(owners)
