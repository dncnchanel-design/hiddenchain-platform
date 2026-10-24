from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import islice
import base64
import hashlib
import importlib
import json
import math
import sys

import pytest
from fastapi.testclient import TestClient

from connector.app.synthetic_data import GENERATOR_VERSION, HOURLY_RESOURCES, PERIOD_END, PERIOD_START, REGIONS, UNITS, fingerprint, iter_records, manifest, record_bytes, record_count


def test_requested_period_and_seven_connector_volume_are_exact():
    assert PERIOD_START == date(2021, 1, 1) and PERIOD_END == date(2026, 9, 30)
    assert (PERIOD_END - PERIOD_START).days + 1 == 2099
    counts = {domain: sum(record_count(domain, resource) for resource in resources) for domain, resources in UNITS.items()}
    assert counts["electricity"] == 436592
    assert counts["heat"] == 461780
    assert counts["electricity"] * 3 + sum(count for domain, count in counts.items() if domain != "electricity") == 2124188


@pytest.mark.parametrize(("domain", "resource", "unit"), [(domain, resource, unit) for domain, resources in UNITS.items() for resource, unit in resources.items()])
def test_every_resource_has_finite_positive_reproducible_rows_and_correct_hour_semantics(domain, resource, unit):
    first = list(iter_records("local-node-test", "测试连接器", domain, resource, unit, start=date(2024, 2, 28), end=date(2024, 3, 1)))
    assert first == list(iter_records("local-node-test", "测试连接器", domain, resource, unit, start=date(2024, 2, 28), end=date(2024, 3, 1)))
    assert len(first) == record_count(domain, resource, date(2024, 2, 28), date(2024, 3, 1))
    assert {row[1] for row in first} == {"2024-02-28", "2024-02-29", "2024-03-01"}
    assert {row[3] for row in first} == set(REGIONS)
    assert all(row[0] == resource and row[6] == unit and math.isfinite(row[5]) and row[5] > 0 for row in first)
    grouped = defaultdict(list)
    for row in first:
        grouped[row[1], row[3]].append(row)
    for rows in grouped.values():
        if (domain, resource) in HOURLY_RESOURCES:
            assert len(rows) == 25 and [row[2] for row in rows[1:]] == list(range(24))
            factor = 24 if unit == "MW" else 1
            assert sum(row[5] for row in rows[1:]) == pytest.approx(rows[0][5] * factor, abs=0.000001)
        else:
            assert len(rows) == 1 and rows[0][2] is None


def test_manifest_fingerprint_binds_period_units_resource_and_connector():
    description = manifest("node-coal", "煤炭连接器", "coal", "inventory", "吨")
    assert description["generator_version"] == GENERATOR_VERSION
    assert description["record_count"] == 8396
    assert len(fingerprint(description)) == 64
    for field, other in (("period_end", "2026-10-01"), ("connector_id", "other-node"), ("unit", "MWh"), ("resource_id", "production")):
        assert fingerprint({**description, field: other}) != fingerprint(description)


def test_generator_is_lazy_and_covers_last_day_without_a_full_list():
    rows = iter_records("node", "煤炭连接器", "coal", "inventory", "吨")
    assert iter(rows) is rows
    assert len(list(islice(rows, 4))) == 4
    assert list(iter_records("node", "煤炭连接器", "coal", "inventory", "吨", start=PERIOD_END, end=PERIOD_END))[-1][1] == "2026-09-30"
    with pytest.raises(ValueError):
        list(iter_records("node", "煤炭连接器", "coal", "inventory", "MWh"))


def test_domain_seasonality_temperature_and_annual_growth_are_plausible():
    def daily(domain, resource, day):
        return next(iter_records("node", "企业连接器", domain, resource, UNITS[domain][resource], start=day, end=day))[5]
    assert daily("heat", "supply", date(2025, 1, 15)) > daily("heat", "supply", date(2025, 7, 16)) * 3
    assert daily("gas", "supply", date(2025, 1, 15)) > daily("gas", "supply", date(2025, 7, 16)) * 1.5
    assert daily("heat", "supply_temperature", date(2025, 1, 15)) > daily("heat", "return_temperature", date(2025, 1, 15)) + 20
    assert daily("coal", "production", date(2026, 1, 1)) > daily("coal", "production", date(2021, 1, 1))


@pytest.fixture
def legacy_connector(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENERGY_DOMAIN", "coal")
    monkeypatch.setenv("CONNECTOR_ID", "local-node-org-coal-t01")
    monkeypatch.setenv("ORGANIZATION_ID", "org-coal-t01")
    monkeypatch.setenv("CONNECTOR_NAME", "煤炭企业连接器")
    monkeypatch.setenv("CONNECTOR_SIGNING_PRIVATE_KEY", base64.b64encode(bytes(range(32))).decode())
    monkeypatch.setenv("CONNECTOR_DATABASE_PATH", str(tmp_path / "synthetic-coal.db"))
    monkeypatch.setenv("CONNECTOR_SEED_SYNTHETIC_DATA", "false")
    sys.modules.pop("connector.app.main", None)
    module = importlib.import_module("connector.app.main")
    module._initialize()
    monkeypatch.setattr(module, "CONNECTOR_SEED_SYNTHETIC_DATA", True)
    with module._database() as connection:
        module._seed_records(connection)
        module._seed_demo_versions(connection)
    yield module
    sys.modules.pop("connector.app.main", None)


def test_seed_only_database_upgrades_with_immutable_v1_and_a_signed_current_manifest(legacy_connector):
    module = legacy_connector
    with module._database() as connection:
        old = [tuple(row) for row in connection.execute("SELECT version_id, content_hash, local_ref, record_count FROM resource_versions ORDER BY resource_id")]
        old_rows = hashlib.sha256(json.dumps([tuple(row) for row in connection.execute("SELECT * FROM version_records ORDER BY record_id")], ensure_ascii=False).encode()).hexdigest()
        module._seed_demo_v2_versions(connection)
        module._seed_demo_v2_versions(connection)
        assert connection.execute("SELECT COUNT(*) FROM synthetic_dataset_manifests").fetchone()[0] == len(UNITS["coal"])
        assert old == [tuple(row) for row in connection.execute("SELECT version_id, content_hash, local_ref, record_count FROM resource_versions WHERE version_no = 1 ORDER BY resource_id")]
        assert old_rows == hashlib.sha256(json.dumps([tuple(row) for row in connection.execute("SELECT * FROM version_records WHERE version_id LIKE '%-v1' ORDER BY record_id")], ensure_ascii=False).encode()).hexdigest()
        latest = module._latest_local_version(connection, "inventory")
        assert latest["version_no"] == 2
        bounds = connection.execute("SELECT MIN(record_date), MAX(record_date), COUNT(*) FROM version_records WHERE version_id = ?", (latest["version_id"],)).fetchone()
        assert tuple(bounds) == ("2021-01-01", "2026-09-30", 8396)
        digest = hashlib.sha256()
        for row in connection.execute("SELECT resource, record_date, hour, region, organization, value, unit FROM version_records WHERE version_id = ? ORDER BY record_id", (latest["version_id"],)):
            digest.update(record_bytes(tuple(row)))
        assert digest.hexdigest() == latest["content_hash"]
    with TestClient(module.app) as client:
        response = client.get("/catalog")
        assert response.status_code == 200
        catalog = response.json()
        signed = {key: value for key, value in catalog.items() if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}}
        module.PRIVATE_KEY.public_key().verify(base64.b64decode(catalog["signature"]), module._canonical(signed))
        resource = next(item for item in catalog["resources"] if item["resource_id"] == "inventory")
        seed = resource["synthetic_seed"]
        assert resource["latest_version"] == seed["version"] == 2
        assert seed["manifest"]["record_count"] == seed["record_count"] == resource["record_count"]
        assert seed["manifest_hash"] == fingerprint(seed["manifest"])
        payload = module.ComputeRequest(task_id="task-early-period", authorization_id="authorization-early-period", dataset_version=2, dataset_local_ref=seed["local_ref"], dataset_content_hash=seed["content_hash"], resource="inventory", function="average", start_date="2021-01-01", end_date="2021-01-31")
        rows, unit, version, _ref, _hash = module._query_values(payload)
        assert len(rows) == 124 and unit == "吨" and version == 2
        assert module._compute(payload, rows) > 0


@pytest.mark.parametrize("schema_version", ["connector-csv-v1", "unknown-upload-schema"])
def test_occupied_csv_or_unknown_version_two_is_preserved_without_allocating_version_three(legacy_connector, schema_version):
    module = legacy_connector
    with module._database() as connection:
        connection.execute("INSERT INTO resource_versions(version_id, resource_id, resource_name, version_no, classification, schema_version, schema_hash, content_hash, record_count, byte_size, local_ref, created_at) VALUES ('user-version', 'inventory', '用户库存', 2, 'L2', ?, ?, ?, 1, 10, ?, '2026-10-24')", (schema_version, "c" * 64, "d" * 64, f"connector://{module.CONNECTOR_ID}/inventory/versions/2"))
        connection.execute("INSERT INTO version_records(version_id, resource, record_date, hour, region, organization, value, unit) VALUES ('user-version', 'inventory', '2025-01-01', NULL, '本方', '用户企业', 1234, '吨')")
        connection.commit()
        frozen = tuple(connection.execute("SELECT * FROM resource_versions WHERE version_id = 'user-version'").fetchone())
        module._seed_demo_v2_versions(connection)
        assert tuple(connection.execute("SELECT * FROM resource_versions WHERE version_id = 'user-version'").fetchone()) == frozen
        assert connection.execute("SELECT MAX(version_no) FROM resource_versions WHERE resource_id = 'inventory'").fetchone()[0] == 2
        assert connection.execute("SELECT value FROM version_records WHERE version_id = 'user-version'").fetchone()[0] == 1234
        assert connection.execute("SELECT COUNT(*) FROM synthetic_dataset_manifests WHERE version_id = 'user-version'").fetchone()[0] == 0
    resource = next(item for item in module.catalog()["resources"] if item["resource_id"] == "inventory")
    assert resource["current_schema_version"] == schema_version and resource["synthetic_seed"] is None


def test_v2_generation_failure_rolls_back_only_the_new_version(legacy_connector, monkeypatch):
    module = legacy_connector
    def interrupted(*_args, **_kwargs):
        yield "production", "2021-01-01", None, "东部片区", "企业", 1.0, "吨"
        raise RuntimeError("interrupted")
    monkeypatch.setattr(module.synthetic_data, "iter_records", interrupted)
    with module._database() as connection:
        with pytest.raises(RuntimeError, match="interrupted"):
            module._seed_demo_v2_versions(connection)
        assert connection.execute("SELECT COUNT(*) FROM resource_versions WHERE version_no = 2").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM resource_versions WHERE version_no = 1").fetchone()[0] == 6
        assert connection.execute("SELECT COUNT(*) FROM synthetic_dataset_manifests").fetchone()[0] == 0


def test_v2_is_not_generated_in_production_even_with_the_seed_switch(legacy_connector, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with legacy_connector._database() as connection:
        legacy_connector._seed_demo_v2_versions(connection)
        assert connection.execute("SELECT COUNT(*) FROM synthetic_dataset_manifests").fetchone()[0] == 0
