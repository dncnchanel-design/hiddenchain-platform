from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas import DataUploadCreate
from app.services.credentials import JsonLdCredentialAdapter


@settings(max_examples=40, deadline=None)
@given(
    curve=st.lists(
        st.floats(min_value=0, max_value=500, allow_nan=False, allow_infinity=False),
        min_size=24,
        max_size=24,
    )
)
def test_load_curve_property_accepts_exactly_24_finite_non_negative_values(curve):
    payload = DataUploadCreate(
        asset_type="USER_LOAD_CURVE",
        trade_batch_no="TB-HYPOTHESIS",
        label="property-test-load-curve",
        local_payload={"load_curve": curve},
    )

    assert len(payload.local_payload["load_curve"]) == 24
    assert all(value >= 0 for value in payload.local_payload["load_curve"])


@settings(max_examples=30, deadline=None)
@given(
    curve=st.lists(
        st.floats(min_value=-500, max_value=-0.000001, allow_nan=False, allow_infinity=False),
        min_size=24,
        max_size=24,
    )
)
def test_load_curve_property_rejects_negative_values(curve):
    with pytest.raises(ValidationError):
        DataUploadCreate(
            asset_type="USER_LOAD_CURVE",
            trade_batch_no="TB-HYPOTHESIS",
            label="property-test-negative-load-curve",
            local_payload={"load_curve": curve},
        )


@settings(max_examples=30, deadline=None)
@given(context_url=st.text(min_size=1, max_size=96))
def test_credential_property_never_fetches_a_string_context(context_url):
    result = JsonLdCredentialAdapter.fingerprint(
        {
            "@context": context_url,
            "type": "VerifiableCredential",
        }
    )

    assert result["status"] == "EXTERNAL_CONTEXT_BLOCKED"
    assert result["remote_context_fetch"] is False
    assert "credential_hash" not in result
