from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

import app.services.lineage as lineage_module
from app.services.lineage import emit_run_event
from app.services.arrow_connector import ArrowConnectorAdapter
from app.services.credentials import JsonLdCredentialAdapter
from app.services.datapackage import FrictionlessCatalogAdapter
from app.services.dataspace import DataspaceProtocolAdapter
from app.services.duckdb_connector import DuckDBMetadataAdapter
from app.services.odcs_connector import OpenDataContractAdapter
from app.services.privacy import OpenDPAdapter
from app.services.prometheus import prometheus_status
from app.services.rate_limit import limiter, rate_limit_status
from app.services.solar import PvlibSolarAdapter


def test_security_workflows_pin_every_action_to_a_commit():
    workflows_dir = Path(__file__).parents[2] / ".github" / "workflows"
    uses_lines = [
        line.strip()
        for workflow in workflows_dir.glob("*.yml")
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("uses:")
    ]

    assert uses_lines
    assert all(re.search(r"@[0-9a-f]{40}(?:\s|$)", line) for line in uses_lines)


def test_opendp_release_returns_redacted_curve_and_controls():
    curve, controls = OpenDPAdapter.release_curve(
        [[22.0, 21.0, 20.0], [18.0, 19.0, 21.0]],
        epsilon=1.0,
    )

    assert len(curve) == 3
    assert all(0 <= value <= 200 for value in curve)
    assert controls["engine"] == "OpenDP"
    assert controls["raw_data_exposed"] is False
    assert controls["composition_count"] == 3


def test_pvlib_solar_adapter_returns_derived_metrics_only():
    result = PvlibSolarAdapter.evaluate(
        latitude=39.9042,
        longitude=116.4074,
        timestamp_utc=datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc),
        surface_tilt=30,
        surface_azimuth=180,
        ghi_wm2=800,
        dni_wm2=650,
        dhi_wm2=150,
    )

    assert result["status"] == "CALCULATED"
    assert result["adapter"] == "PVLIB_SOLAR_RESOURCE_0_15"
    assert len(result["input_hash"]) == 64
    assert result["raw_data_exposed"] is False
    assert result["plane_of_array_irradiance_wm2"]["poa_global"] >= 0


def test_pyld_canonicalizes_did_vc_with_stable_fingerprint():
    credential = {
        "type": ["VerifiableCredential", "EnergyMarketParticipantCredential"],
        "issuer": "did:hiddenchain:regulator:demo",
        "credentialSubject": {
            "id": "did:hiddenchain:org:demo",
            "orgType": "GENERATOR",
        },
    }
    reordered = {
        "credentialSubject": {
            "orgType": "GENERATOR",
            "id": "did:hiddenchain:org:demo",
        },
        "issuer": "did:hiddenchain:regulator:demo",
        "type": ["VerifiableCredential", "EnergyMarketParticipantCredential"],
    }

    first = JsonLdCredentialAdapter.fingerprint(credential)
    second = JsonLdCredentialAdapter.fingerprint(reordered)

    assert first["status"] == "CANONICALIZED"
    assert first["credential_hash"] == second["credential_hash"]
    assert first["normalization"] == "URDNA2015"
    assert first["remote_context_fetch"] is False
    assert first["raw_data_exposed"] is False


def test_pyld_blocks_remote_credential_contexts():
    result = JsonLdCredentialAdapter.fingerprint(
        {
            "@context": "https://attacker.invalid/credential-context.jsonld",
            "type": "VerifiableCredential",
        }
    )

    assert result["status"] == "EXTERNAL_CONTEXT_BLOCKED"
    assert "credential_hash" not in result
    assert result["raw_data_exposed"] is False


def test_prometheus_endpoint_is_protected_and_has_no_business_labels(client, auth_headers):
    assert prometheus_status()["package_available"] is True
    assert client.get("/api/metrics/prometheus").status_code == 401

    response = client.get("/api/metrics/prometheus", headers=auth_headers["regulator"])
    assert response.status_code == 200
    assert "hiddenchain_http_requests_total" in response.text
    assert "data_product_id" not in response.text


def test_frictionless_catalog_package_contains_metadata_only(client, auth_headers):
    response = client.get(
        "/api/data/catalog/package?trade_batch_no=TB-2026-07-DEMO",
        headers=auth_headers["regulator"],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["adapter"] == FrictionlessCatalogAdapter.code
    assert payload["profile"] == "data-package"
    assert payload["resource_count"] >= 1
    assert payload["raw_data_exposed"] is False
    descriptor_text = json.dumps(payload["descriptor"], ensure_ascii=False)
    assert "data_ref" not in descriptor_text
    assert "password_hash" not in descriptor_text
    assert "connector://hiddenchain/products/DP-" in descriptor_text
    assert payload["columnar_interop"]["code"] == ArrowConnectorAdapter.code
    assert payload["columnar_interop"]["installed"] is True
    assert payload["columnar_interop"]["raw_data_exposed"] is False
    assert payload["columnar_interop"]["resources"]
    assert payload["duckdb_analytics"]["code"] == DuckDBMetadataAdapter.code
    assert payload["duckdb_analytics"]["version"] == DuckDBMetadataAdapter.version
    assert payload["duckdb_analytics"]["installed"] is True
    assert payload["duckdb_analytics"]["read_only_query"] is True
    assert payload["duckdb_analytics"]["raw_data_exposed"] is False
    assert payload["duckdb_analytics"]["groups"]
    assert payload["duckdb_analytics"]["query_hash"]
    assert payload["odcs_contracts"]["code"] == OpenDataContractAdapter.code
    assert payload["odcs_contracts"]["version"] == OpenDataContractAdapter.version
    assert payload["odcs_contracts"]["contract_count"] == payload["resource_count"]
    assert payload["odcs_contracts"]["schema_validation"]["valid"] is True
    assert payload["odcs_contracts"]["raw_data_exposed"] is False
    odcs_text = json.dumps(payload["odcs_contracts"], ensure_ascii=False)
    assert "vault://" not in odcs_text
    assert "data_ref" not in odcs_text
    assert "energy_mwh" in descriptor_text


def test_dataspace_protocol_catalog_is_valid_and_metadata_only(client, auth_headers):
    response = client.get(
        "/api/data/catalog/dataspace?trade_batch_no=TB-2026-07-DEMO",
        headers=auth_headers["regulator"],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["adapter"] == DataspaceProtocolAdapter.code
    assert payload["version"] == "2024-1"
    assert payload["schema_validation"] == {"valid": True, "errors": []}
    descriptor = payload["descriptor"]
    assert descriptor["@context"] == DataspaceProtocolAdapter.context
    assert descriptor["@type"] == "dcat:Catalog"
    assert len(descriptor["dcat:dataset"]) == payload["dataset_count"]
    assert all(item["@type"] == "dcat:Dataset" for item in descriptor["dcat:dataset"])
    descriptor_text = json.dumps(descriptor, ensure_ascii=False)
    assert "vault://" not in descriptor_text
    assert "data_ref" not in descriptor_text
    assert "load_curve" not in descriptor_text
    assert payload["raw_data_exposed"] is False


def test_dataspace_local_json_schema_profile_rejects_missing_policy():
    descriptor = DataspaceProtocolAdapter.build(
        [
            {
                "data_product_id": "DP-schema-test",
                "label": "Schema profile test",
                "asset_type": "GENERATION_DATA",
                "semantic_ref": "energy:GenerationMeasurement",
                "owner_did": "did:hiddenchain:org:test",
                "usage": {"allowed_purposes": ["POWER_SETTLEMENT"]},
                "transport": {"protocol": "HTTPS"},
            }
        ]
    )["descriptor"]
    descriptor["dcat:dataset"][0].pop("odrl:hasPolicy")

    errors = DataspaceProtocolAdapter.validate(descriptor)

    assert errors
    assert any("odrl:hasPolicy" in error for error in errors)


def test_openlineage_event_is_standard_and_contains_no_raw_payload(tmp_path, monkeypatch):
    patched_settings = replace(
        lineage_module.settings,
        openlineage_enabled=True,
        openlineage_path=str(tmp_path / "events.jsonl"),
        openlineage_http_url="",
    )
    monkeypatch.setattr(lineage_module, "settings", patched_settings)

    result = emit_run_event(
        run_id="req-test-lineage",
        job_name="test-job",
        event_type="COMPLETE",
        trace_id="trace-test-lineage",
        input_datasets=[],
        output_name="result/test",
        output_hash="hash-result",
        result_status="SUCCEEDED",
        policy_hash="hash-policy",
    )

    assert result["emitted"] is True
    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").strip())
    assert event["eventType"] == "COMPLETE"
    assert event["schemaURL"].startswith("https://openlineage.io/spec/")
    assert event["run"]["facets"]["hiddenchain_security"]["rawDataExported"] is False
    assert "data_ref" not in json.dumps(event, ensure_ascii=False)
    assert "load_curve" not in json.dumps(event, ensure_ascii=False)


def test_health_and_lineage_endpoint_expose_safe_integration_status(client, auth_headers):
    health = client.get("/api/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["mvp_adapters"]["differential_privacy"]["installed"] is True
    assert payload["mvp_adapters"]["solar_resource"]["installed"] is True
    assert payload["integrations"]["prometheus"]["package_available"] is True
    assert payload["integrations"]["rate_limiting"]["code"] == "SLOWAPI_RATE_LIMIT_0_1_10"
    assert payload["integrations"]["rate_limiting"]["installed"] is True
    assert payload["integrations"]["rate_limiting"]["protected_routes"] == ["POST /api/auth/login"]
    assert payload["integrations"]["rate_limiting"]["raw_data_exposed"] is False
    assert payload["integrations"]["data_package"]["installed"] is True
    assert payload["integrations"]["columnar_connector"]["installed"] is True
    assert payload["integrations"]["columnar_connector"]["raw_data_exposed"] is False
    assert payload["integrations"]["credential_canonicalization"]["installed"] is True
    assert payload["integrations"]["credential_canonicalization"]["remote_context_fetch"] is False
    assert payload["integrations"]["dataspace_protocol"]["version"] == "2024-1"
    assert payload["integrations"]["dataspace_protocol"]["schema_validation"] == "JSON_SCHEMA_DRAFT_2019_09_LOCAL_PROFILE"
    assert payload["integrations"]["dataspace_protocol"]["raw_data_exposed"] is False
    assert payload["integrations"]["lineage"]["raw_data_policy"]

    response = client.get(
        "/api/audit/lineage/unknown-run",
        headers=auth_headers["regulator"],
    )
    assert response.status_code == 200
    assert response.json() == {
        "run_id": "unknown-run",
        "events": [],
        "event_count": 0,
        "raw_data_included": False,
    }


def test_slowapi_throttles_repeated_login_attempts(client):
    limiter.reset()
    try:
        responses = [
            client.post(
                "/api/auth/login",
                json={"username": "unknown-rate-limited-user", "password": "invalid"},
            )
            for _ in range(11)
        ]

        assert all(response.status_code == 401 for response in responses[:10])
        assert responses[-1].status_code == 429
        assert "Rate limit exceeded" in responses[-1].text
        assert rate_limit_status()["raw_data_exposed"] is False
    finally:
        limiter.reset()


def test_solar_endpoint_keeps_input_out_of_response(client, auth_headers):
    response = client.post(
        "/api/energy/solar/evaluate",
        headers=auth_headers["generator"],
        json={
            "latitude": 31.2304,
            "longitude": 121.4737,
            "timestamp_utc": "2026-07-15T04:00:00Z",
            "surface_tilt": 25,
            "surface_azimuth": 180,
            "ghi_wm2": 700,
            "dni_wm2": 520,
            "dhi_wm2": 180,
        },
    )

    assert response.status_code == 200
    assert response.json()["raw_data_exposed"] is False
    assert "ghi_wm2" not in response.text
