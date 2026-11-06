from __future__ import annotations

import math
from fractions import Fraction

import pytest

from connector.tests.test_connector_ingest import (
    _claims,
    _post_ingest,
    _signed_headers,
    _verify_signed_response,
    connector,
)


def _upload_period(connector, first, second):
    raw = "record_date,value,region\n" + "".join(
        f"2026-08-{day:02},{value},region-{index}\n"
        for day, values in ((1, first), (2, second))
        for index, value in enumerate(values)
    )
    response = _post_ingest(
        connector["client"], connector["platform_key"],
        _claims(jti="recheck-psi-ticket"), raw.encode(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _query_psi(connector, receipt, function="psi", **changes):
    module = connector["module"]
    request = module._canonical_request_payload(module.ComputeRequest(
        task_id="recheck-psi-task", authorization_id="recheck-psi-auth",
        request_item_id="recheck-psi-item", provider_org_id="org-coal-t01",
        dataset_version=receipt["version"], dataset_local_ref=receipt["local_ref"],
        dataset_content_hash=receipt["content_hash"], resource="inventory", function=function,
        start_date="2026-08-01", end_date="2026-08-02", **changes,
    ))
    return connector["client"].post(
        "/compute", json=request,
        headers=_signed_headers(module, connector["platform_key"], request, "recheck-psi-nonce"),
    )


def _reference_psi(first, second):
    """Independent exact-rational bins, before display rounding."""
    low, high = min(map(Fraction, first)), max(map(Fraction, first))
    edges = [low + (high - low) * i / 10 for i in range(1, 10)]
    def frequencies(values):
        counts = [0] * 10
        for value in map(Fraction, values):
            counts[sum(value >= edge for edge in edges)] += 1
        return [(count + 0.5) / (len(values) + 5) for count in counts]
    before, after = frequencies(first), frequencies(second)
    return sum((q - p) * math.log(q / p) for p, q in zip(before, after))


@pytest.mark.parametrize("second", [("1e308",) * 3, ("-1", "0", "1")])
def test_uploaded_large_finite_values_do_not_issue_an_incorrect_psi(connector, second):
    first = ("-1e308", "0", "1e308")
    receipt = _upload_period(connector, first, second)
    response = _query_psi(connector, receipt)
    assert response.status_code == 200, response.text
    assert response.json()["result"] == round(_reference_psi(first, second), 2)
    _verify_signed_response(connector["connector_key"], response.json())


@pytest.mark.parametrize("first,second", [((1, 2, 3), (4, 5, 6, 7, 8)), ((1, 2, 3, 4, 5), (6, 7, 8))])
def test_psi_honors_signed_minimum_for_both_periods_before_releasing_or_charging(connector, first, second):
    receipt = _upload_period(connector, first, second)
    response = _query_psi(connector, receipt, minimum_record_count=5)
    assert response.status_code == 422, response.text
    with connector["module"]._database() as db:
        assert db.execute("SELECT COUNT(*) FROM query_log").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM local_execution_receipts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ingest_audit_chain WHERE event_json LIKE '%LOCAL_CONTROLLED_RESULT_ISSUED%'").fetchone()[0] == 0


def test_growth_rate_honors_signed_minimum_at_both_endpoints(connector):
    receipt = _upload_period(connector, (1, 2, 3), (4, 5, 6))
    response = _query_psi(connector, receipt, function="growth_rate", minimum_record_count=5)
    assert response.status_code == 422, response.text
    with connector["module"]._database() as db:
        assert db.execute("SELECT COUNT(*) FROM query_log").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM local_execution_receipts").fetchone()[0] == 0
