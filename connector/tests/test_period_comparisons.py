from __future__ import annotations

import base64
import importlib
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
import time
import math

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@pytest.fixture
def platform_key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def connector(monkeypatch, tmp_path, platform_key):
    monkeypatch.setenv("ENERGY_DOMAIN", "electricity")
    monkeypatch.setenv("CONNECTOR_ID", "rate-test-connector")
    monkeypatch.setenv("ORGANIZATION_ID", "rate-test-org")
    monkeypatch.setenv("CONNECTOR_SIGNING_PRIVATE_KEY", base64.b64encode(bytes(range(32))).decode())
    monkeypatch.setenv("CONNECTOR_DATABASE_PATH", str(tmp_path / "rates.db"))
    monkeypatch.setenv("CONNECTOR_SEED_SYNTHETIC_DATA", "false")
    monkeypatch.setenv("PLATFORM_SIGNING_PUBLIC_KEY", base64.b64encode(platform_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())
    sys.modules.pop("connector.app.main", None)
    module = importlib.import_module("connector.app.main")
    module._initialize()
    yield module
    sys.modules.pop("connector.app.main", None)


def payload(module, function="growth_rate", **changes):
    values = {"task_id": "rate-task-001", "authorization_id": "rate-auth-001", "dataset_version": 1, "dataset_local_ref": "connector://rate-test-connector/load/versions/1", "dataset_content_hash": "a" * 64, "resource": "load", "function": function, "start_date": date(2026, 6, 1), "end_date": date(2026, 6, 2)}
    return module.ComputeRequest(**{**values, **changes})


def rows(first=(100, 300, 200), last=(200, 200, 200)):
    return [{"record_date": day, "region": region, "organization": region, "hour": None, "value": value, "unit": "MW"} for day, values in (("2026-06-01", first), ("2026-06-02", last)) for region, value in zip(("A", "B", "C"), values)]


def test_growth_compares_matching_regional_totals_instead_of_cross_region_rows(connector):
    values = rows()
    assert connector._compute(payload(connector), values) == pytest.approx(0)
    assert connector._compute(payload(connector), list(reversed(values))) == pytest.approx(0)
    assert connector._compute(payload(connector), rows(last=(200, 600, 400))) == pytest.approx(100)


def test_trend_growth_does_not_calculate_from_display_rounded_values(connector):
    result = connector._compute(payload(connector, "trend"), rows(first=(0.004,) * 3, last=(0.008,) * 3))
    assert result["变化率"] == pytest.approx(100)


def test_trend_does_not_report_a_fake_rate_for_zero_baseline(connector):
    with pytest.raises(HTTPException) as undefined:
        connector._compute(payload(connector, "trend"), rows(first=(0,) * 3, last=(10,) * 3))
    assert undefined.value.status_code == 422


@pytest.mark.parametrize("condition", ["single_day", "missing_requested_start", "different_regions", "zero_base"])
def test_growth_rejects_incomparable_or_zero_baselines(connector, condition):
    values = rows()
    if condition == "single_day":
        values = values[:3]
    elif condition == "missing_requested_start":
        for value in values:
            if value["record_date"] == "2026-06-01": value["record_date"] = "2026-05-31"
    elif condition == "different_regions":
        values[-1]["region"] = "D"
    else:
        values = rows(first=(0, 0, 0))
    with pytest.raises(HTTPException) as error:
        connector._compute(payload(connector), values)
    assert error.value.status_code == 422


def seed_values(module, *, period="2026-06", factor=1, version=1):
    with module._database() as db:
        version_id = f"rate-load-v{version}"
        db.execute("INSERT OR IGNORE INTO resource_versions(version_id, resource_id, resource_name, version_no, classification, schema_version, schema_hash, content_hash, record_count, byte_size, local_ref, created_at) VALUES (?, 'load', '用电负荷', ?, 'L2', 'test', ?, ?, 6, 0, ?, ?)", (version_id, version, "c" * 64, "a" * 64 if version == 1 else "b" * 64, f"connector://rate-test-connector/load/versions/{version}", datetime.now(UTC).isoformat()))
        for day in (1, 2):
            for region, value in zip(("A", "B", "C"), (100, 300, 200)):
                db.execute("INSERT INTO version_records(version_id, resource, record_date, hour, region, organization, value, unit) VALUES (?, 'load', ?, NULL, ?, ?, ?, 'MW')", (version_id, f"{period}-{day:02}", region, region, value * factor))
        db.commit()


def request_dict(module, function="average", **changes):
    return payload(module, function, request_item_id="rate-item-001", provider_org_id="rate-test-org", **changes).model_dump(mode="json", exclude_none=False)


def signed_headers(module, key, request, nonce):
    timestamp = str(int(time.time()))
    canonical = {key: value for key, value in request.items() if key not in {"request_item_id", "provider_org_id", "rule_version", "comparison_start_date", "comparison_end_date", "minimum_record_count"} or value is not None}
    return {"X-Request-Timestamp": timestamp, "X-Request-Nonce": nonce, "X-Request-Signature": base64.b64encode(key.sign(module._canonical({"timestamp": timestamp, "nonce": nonce, "payload": canonical}))).decode()}


def seed_full_month(module, period, days):
    seed_values(module, period=period)
    with module._database() as db:
        for day in range(3, days + 1):
            for region, value in zip(("A", "B", "C"), (100, 300, 200)):
                db.execute("INSERT INTO version_records(version_id, resource, record_date, hour, region, organization, value, unit) VALUES ('rate-load-v1', 'load', ?, NULL, ?, ?, ?, 'MW')", (f"{period}-{day:02}", region, region, value))
        db.commit()


@pytest.mark.parametrize(("minimum", "side"), [(94, "current"), (92, "baseline")])
def test_signed_rule_record_minimum_is_enforced_in_each_period_before_releasing_or_charging(connector, platform_key, minimum, side):
    seed_full_month(connector, "2026-05", 31)  # 93 current records.
    seed_full_month(connector, "2026-04", 30)  # 90 baseline records.
    request = request_dict(connector, "mom", start_date="2026-05-01", end_date="2026-05-31", comparison_start_date="2026-04-01", comparison_end_date="2026-04-30")
    request["minimum_record_count"] = minimum
    with TestClient(connector.app) as client:
        response = client.post("/compute", json=request, headers=signed_headers(connector, platform_key, request, "minimum-" + side + "-nonce"))
    assert response.status_code == 403, response.text
    assert str(minimum) in response.json()["detail"]
    with connector._database() as db:
        assert db.execute("SELECT COALESCE(SUM(repeated_count),0) FROM query_log").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM local_execution_receipts").fetchone()[0] == 0


def test_signed_rule_record_minimum_allows_sufficient_periods_and_cannot_be_lowered(connector, platform_key):
    seed_full_month(connector, "2026-05", 31)
    seed_full_month(connector, "2026-04", 30)
    request = request_dict(connector, "mom", start_date="2026-05-01", end_date="2026-05-31", comparison_start_date="2026-04-01", comparison_end_date="2026-04-30")
    request["minimum_record_count"] = 90
    with TestClient(connector.app) as client:
        response = client.post("/compute", json=request, headers=signed_headers(connector, platform_key, request, "minimum-sufficient-nonce"))
        headers = signed_headers(connector, platform_key, request, "minimum-tamper-nonce")
        tampered = client.post("/compute", json={**request, "minimum_record_count": 3}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["privacy"]["minimum_group_size"] == 90
    assert response.json()["result"] == 0
    assert tampered.status_code == 401


@pytest.mark.parametrize(("function", "period"), [("yoy", "2025-06"), ("mom", "2026-05")])
def test_signed_comparison_reads_only_its_bound_version_and_signed_baseline(connector, platform_key, function, period):
    seed_values(connector, period=period)
    seed_values(connector, factor=1.2)
    seed_values(connector, period=period, version=2)
    seed_values(connector, factor=10, version=2)
    request = request_dict(connector, function, comparison_start_date=period + "-01", comparison_end_date=period + "-02")
    with TestClient(connector.app) as client:
        response = client.post("/compute", json=request, headers=signed_headers(connector, platform_key, request, "comparison-nonce-001"))
    assert response.status_code == 200, response.text
    assert response.json()["result"] == pytest.approx(20)
    assert response.json()["unit"] == "%"
    assert response.json()["dataset_version"] == 1 and response.json()["raw_records_returned"] is False


@pytest.mark.parametrize("condition", ["missing_binding", "wrong_calendar", "missing_day", "different_regions"])
def test_comparison_rejects_unbound_or_incomplete_baselines_without_spending_budget(connector, platform_key, condition):
    seed_values(connector, period="2025-06")
    seed_values(connector, factor=1.2)
    changes = {"comparison_start_date": "2025-06-01", "comparison_end_date": "2025-06-02"}
    if condition == "missing_binding": changes = {}
    elif condition == "wrong_calendar": changes["comparison_start_date"] = "2025-05-01"
    elif condition == "missing_day":
        with connector._database() as db:
            db.execute("DELETE FROM version_records WHERE version_id = 'rate-load-v1' AND record_date = '2025-06-02'")
            db.commit()
    else:
        with connector._database() as db:
            db.execute("UPDATE version_records SET region = 'D' WHERE record_date LIKE '2025-%' AND region = 'C'")
            db.commit()
    request = request_dict(connector, "yoy", **changes)
    with TestClient(connector.app) as client:
        response = client.post("/compute", json=request, headers=signed_headers(connector, platform_key, request, "bad-comparison-nonce-001"))
    assert response.status_code == 422, response.text
    with connector._database() as db:
        assert db.execute("SELECT COALESCE(SUM(repeated_count),0) FROM query_log").fetchone()[0] == 0


@pytest.mark.parametrize(("function", "changes", "expected_unit"), [("count", {}, "条"), ("threshold", {"threshold": 150}, "条"), ("growth_rate", {}, "%"), ("trend", {}, "MW"), ("psi", {}, "无量纲")])
def test_controlled_result_units_match_the_actual_operation(connector, platform_key, function, changes, expected_unit):
    seed_values(connector)
    request = request_dict(connector, function, **changes)
    with TestClient(connector.app) as client:
        response = client.post("/compute", json=request, headers=signed_headers(connector, platform_key, request, "unit-nonce-001"))
    assert response.status_code == 200, response.text
    assert response.json()["unit"] == expected_unit


def test_invalid_function_parameters_do_not_consume_privacy_budget(connector, platform_key):
    seed_values(connector)
    request = request_dict(connector, "threshold")
    with TestClient(connector.app) as client:
        response = client.post("/compute", json=request, headers=signed_headers(connector, platform_key, request, "invalid-threshold-nonce-001"))
    assert response.status_code == 422
    with connector._database() as db:
        assert db.execute("SELECT COALESCE(SUM(repeated_count),0) FROM query_log").fetchone()[0] == 0


def test_concurrent_idempotent_requests_charge_the_connector_only_once(connector, platform_key, monkeypatch):
    seed_values(connector)
    barrier, compute = Barrier(2), connector._compute
    def both_read_before_commit(request, values):
        result = compute(request, values)
        barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(connector, "_compute", both_read_before_commit)
    request = request_dict(connector)
    with TestClient(connector.app) as client:
        def execute(index):
            return client.post("/compute", json=request, headers=signed_headers(connector, platform_key, request, f"parallel-rate-nonce-{index}"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(execute, (1, 2))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    with connector._database() as db:
        assert db.execute("SELECT COALESCE(SUM(repeated_count),0) FROM query_log").fetchone()[0] == 1


def test_psi_matches_an_independently_derived_ten_bin_distribution_formula(connector):
    # Baseline bins 0/5/9 each contain one observation. Current bins 5/9
    # contain one/two. With the documented 0.5 pseudocount and N=3, only
    # bins 0 and 9 contribute: (-1/8)ln(1/3)+(1/8)ln(5/3)=ln(5)/8.
    values = rows(first=(0, 10, 20), last=(10, 20, 30))
    assert connector._compute(payload(connector, "psi"), values) == pytest.approx(math.log(5) / 8)
    assert connector._compute(payload(connector, "psi"), list(reversed(values))) == pytest.approx(math.log(5) / 8)


def test_psi_constant_distributions_remain_zero_and_shifted_distributions_are_positive(connector):
    assert connector._compute(payload(connector, "psi"), rows(first=(5, 5, 5), last=(5, 5, 5))) == pytest.approx(0)
    assert connector._compute(payload(connector, "psi"), rows(first=(5, 5, 5), last=(6, 6, 6))) > 0


@pytest.mark.parametrize("values", [rows()[:3], rows()[:4]])
def test_psi_rejects_missing_periods_or_insufficient_observations(connector, values):
    with pytest.raises(HTTPException) as denied:
        connector._compute(payload(connector, "psi"), values)
    assert denied.value.status_code == 422


@pytest.mark.parametrize(("function", "start", "end", "first", "last"), [
    ("mom", "2024-03-01", "2024-03-31", "2024-02-01", "2024-02-29"),
    ("yoy", "2024-02-01", "2024-02-29", "2023-02-01", "2023-02-28"),
    ("yoy", "2024-02-29", "2024-02-29", "2023-02-28", "2023-02-28"),
    ("mom", "2026-01-12", "2026-01-22", "2025-12-12", "2025-12-22"),
    ("mom", "2026-04-01", "2026-06-30", "2026-03-01", "2026-05-31"),
])
def test_connector_calendar_contract_matches_platform_month_and_leap_semantics(connector, function, start, end, first, last):
    request = payload(connector, function, start_date=start, end_date=end, comparison_start_date=first, comparison_end_date=last)
    assert tuple(day.isoformat() for day in connector._comparison_period(request)) == (first, last)


def test_failing_result_signature_rolls_back_privacy_budget_and_receipt_together(connector, platform_key, monkeypatch):
    seed_values(connector)
    class FailingKey:
        def sign(self, _payload):
            raise RuntimeError("isolated signing failure")
    monkeypatch.setattr(connector, "PRIVATE_KEY", FailingKey())
    request = request_dict(connector)
    with TestClient(connector.app) as client, pytest.raises(RuntimeError, match="isolated signing failure"):
        client.post("/compute", json=request, headers=signed_headers(connector, platform_key, request, "failed-signature-nonce-001"))
    with connector._database() as db:
        assert db.execute("SELECT COALESCE(SUM(repeated_count),0) FROM query_log").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM local_execution_receipts").fetchone()[0] == 0
