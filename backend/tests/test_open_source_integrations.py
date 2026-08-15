from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import app.services.lineage as lineage_module
from app.services.lineage import emit_run_event
from app.services.privacy import OpenDPAdapter


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
