from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditLog, DataContract, DataSpaceAgreement, DataUsageRequest, utc_now
from app.security import sha256_json
from app.trust_models import DataAsset, DataAssetVersion, DataSource


def _asset_reference() -> dict[str, str]:
    with SessionLocal() as db:
        asset = db.scalar(
            select(DataAsset)
            .where(DataAsset.owner_org_id == "org-generator-t01")
            .order_by(DataAsset.created_at)
        )
        assert asset is not None
        version = db.scalar(
            select(DataAssetVersion)
            .where(DataAssetVersion.asset_id == asset.asset_id)
            .order_by(DataAssetVersion.version_no.desc())
        )
        assert version is not None
        return {"asset_id": asset.asset_id, "asset_version_id": version.version_id}


def _oil_asset_reference() -> dict[str, str]:
    with SessionLocal() as db:
        source = DataSource(
            source_id="source-test-oil",
            source_code="TEST-OIL-SOURCE",
            source_name="测试石油数据连接",
            owner_org_id="org-oil-t01",
            source_type="TEST",
            connector_type="LOCAL_ADAPTER",
            security_domain="oil",
            capability_label="LOCAL_REAL",
            status="ACTIVE",
        )
        db.add(source)
        db.flush()
        asset = DataAsset(
            asset_id="asset-test-oil",
            source_id=source.source_id,
            owner_org_id="org-oil-t01",
            asset_code="TEST-OIL-INVENTORY",
            asset_name="测试石油库存",
            asset_type="OIL_DATA",
            classification="ENERGY_BUSINESS_DATA",
            sensitivity_level="L3",
            status="ACTIVE",
            metadata_json={"domain": "oil", "resource_id": "inventory"},
        )
        db.add(asset)
        db.flush()
        version = DataAssetVersion(
            version_id="version-test-oil",
            asset_id=asset.asset_id,
            version_no=1,
            schema_version="v1.0",
            schema_json={"asset_type": "OIL_DATA"},
            data_ref="local://test-oil/asset-test-oil",
            data_hash=sha256_json({"asset_id": asset.asset_id}),
            commitment=sha256_json({"asset_id": asset.asset_id, "commitment": True}),
            record_count=1,
            immutable_hash=sha256_json({"asset_id": asset.asset_id, "version": 1}),
            status="ACTIVE",
        )
        db.add(version)
        asset.current_version_id = version.version_id
        db.commit()
        return {"asset_id": asset.asset_id, "asset_version_id": version.version_id}


def _payload() -> dict:
    return {
        **_asset_reference(),
        "purpose": "SETTLEMENT_AUDIT",
        "usage_mode": "MPC_AGGREGATE",
        "requested_scope": {
            "fields": ["energy_mwh", "period"],
            "algorithm_code": "CONTROLLED_DATA_USAGE_V1",
            "max_uses": 2,
        },
        "requested_fields": ["energy_mwh", "period"],
        "duration_days": 30,
        "terms": {"output_mode": "AGGREGATE_ONLY", "raw_data_export": False},
    }


def _create(client, auth_headers, *, key: str | None = None):
    headers = dict(auth_headers["exchange"])
    if key:
        headers["Idempotency-Key"] = key
    response = client.post("/api/data/access-requests", headers=headers, json=_payload())
    assert response.status_code in {200, 201}, response.text
    return response


def _etag(payload: dict) -> dict[str, str]:
    return {"If-Match": f'"{payload["state_version"]}"'}


def test_cross_energy_requests_are_provider_gated_for_enterprise_and_regulator(
    client, auth_headers
):
    reference = _asset_reference()
    payload = {
        **reference,
        "purpose": "CROSS_ENERGY_BALANCE",
        "usage_mode": "MPC_AGGREGATE",
        "requested_scope": {"fields": ["energy_mwh", "period"], "max_uses": 2},
        "requested_fields": ["energy_mwh", "period"],
        "duration_days": 7,
        "terms": {
            "output_mode": "AGGREGATE_ONLY",
            "raw_data_export": False,
            "regulatory_basis": "ENERGY_REGULATION",
            "authority_ref": "ER-2026-CROSS-001",
        },
    }

    enterprise_request = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["heat"], "Idempotency-Key": "cross-energy-heat-001"},
        json=payload,
    )
    assert enterprise_request.status_code == 201, enterprise_request.text
    enterprise_body = enterprise_request.json()
    assert enterprise_body["applicant"]["org_id"] == "org-heat-t01"
    assert enterprise_body["provider"]["org_id"] == "org-generator-t01"
    assert enterprise_body["cross_energy"] is True
    assert enterprise_body["access_control"]["provider_decision_required"] is True

    provider_inbox = client.get(
        "/api/data/access-requests?inbox=true&page=1&page_size=20",
        headers=auth_headers["generator"],
    )
    assert provider_inbox.status_code == 200
    assert any(
        item["request_id"] == enterprise_body["request_id"]
        for item in provider_inbox.json()["items"]
    )

    rejected = client.post(
        f"/api/data/access-requests/{enterprise_body['request_id']}/reject",
        headers={**auth_headers["generator"], **_etag(enterprise_body)},
        json={"reason": "企业策略不允许本次跨能源用途"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "REJECTED"

    regulator_request = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["regulator"], "Idempotency-Key": "cross-energy-regulator-001"},
        json={**payload, "purpose": "REGULATORY_CROSS_ENERGY_REVIEW"},
    )
    assert regulator_request.status_code == 201, regulator_request.text
    regulator_body = regulator_request.json()
    assert regulator_body["applicant"]["org_id"] == "org-regulator-t01"
    assert regulator_body["cross_energy"] is True
    assert regulator_body["access_control"]["provider_decision_required"] is True

    not_whitelisted = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["regulator"], "Idempotency-Key": "cross-energy-regulator-denied-001"},
        json={**payload, "purpose": "GENERAL_DATA_LOOKUP"},
    )
    assert not_whitelisted.status_code == 422
    assert not_whitelisted.json()["detail"]["code"] == "REGULATORY_PURPOSE_NOT_WHITELISTED"


def test_electricity_and_oil_application_channel_is_closed(client, auth_headers):
    electricity_to_oil = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["exchange"], "Idempotency-Key": "electricity-oil-001"},
        json={
            **_oil_asset_reference(),
            "purpose": "CONTROLLED_OTHER",
            "usage_mode": "MPC_AGGREGATE",
            "requested_scope": {"output_mode": "AGGREGATE_ONLY", "max_uses": 1},
            "requested_fields": ["summary"],
            "duration_days": 7,
            "terms": {"output_mode": "AGGREGATE_ONLY", "raw_data_export": False},
        },
    )
    assert electricity_to_oil.status_code == 403
    assert electricity_to_oil.json()["detail"]["code"] == "CROSS_ENERGY_APPLICATION_DISABLED"

    oil_to_electricity = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["oil"], "Idempotency-Key": "oil-electricity-001"},
        json={
            **_asset_reference(),
            "purpose": "CONTROLLED_OTHER",
            "usage_mode": "MPC_AGGREGATE",
            "requested_scope": {"output_mode": "AGGREGATE_ONLY", "max_uses": 1},
            "requested_fields": ["summary"],
            "duration_days": 7,
            "terms": {"output_mode": "AGGREGATE_ONLY", "raw_data_export": False},
        },
    )
    assert oil_to_electricity.status_code == 403
    assert oil_to_electricity.json()["detail"]["code"] == "CROSS_ENERGY_APPLICATION_DISABLED"


def test_regulatory_request_preserves_whitelist_terms_and_masked_output(client, auth_headers):
    reference = _asset_reference()
    response = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["regulator"], "Idempotency-Key": "regulatory-masked-query-001"},
        json={
            **reference,
            "purpose": "REGULATORY_CROSS_ENERGY_REVIEW",
            "usage_mode": "MASKED_QUERY",
            "requested_scope": {
                "output_mode": "MASKED_QUERY",
                "raw_data_export": False,
                "max_uses": 2,
            },
            "requested_fields": ["summary", "quality_metrics"],
            "duration_days": 30,
            "terms": {
                "output_mode": "MASKED_QUERY",
                "raw_data_export": False,
                "regulatory_basis": "ENERGY_REGULATION",
                "authority_ref": "ER-2026-COAL-001",
            },
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["purpose"] == "REGULATORY_CROSS_ENERGY_REVIEW"
    assert body["terms"]["regulatory_basis"] == "ENERGY_REGULATION"
    assert body["terms"]["authority_ref"] == "ER-2026-COAL-001"
    approved = client.post(
        f"/api/data/access-requests/{body['request_id']}/approve",
        headers={**auth_headers["generator"], **_etag(body)},
        json={"reason": "能源监管事项已核验，允许脱敏汇总查询"},
    )
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        request_row = db.get(DataUsageRequest, body["request_id"])
        contract = db.get(DataContract, request_row.contract_id) if request_row else None
        assert contract is not None
        assert contract.policy_json["constraint"]["output_mode"] == "MASKED_QUERY"


def test_all_five_application_purposes_reach_provider_approval(client, auth_headers):
    purposes = (
        "SETTLEMENT_ANALYSIS",
        "CROSS_CHECK",
        "MODEL_TRAINING",
        "AUDIT_REVIEW",
        "CONTROLLED_OTHER",
    )
    for index, purpose in enumerate(purposes):
        created = client.post(
            "/api/data/access-requests",
            headers={**auth_headers["exchange"], "Idempotency-Key": f"five-purpose-{index}"},
            json={
                **_payload(),
                "purpose": purpose,
                "requested_scope": {
                    **_payload()["requested_scope"],
                    "purpose_code": purpose,
                    "algorithm_code": f"CONTROLLED_{purpose}_V1",
                },
            },
        )
        assert created.status_code == 201, created.text
        submitted = created.json()
        approved = client.post(
            f"/api/data/access-requests/{submitted['request_id']}/approve",
            headers={**auth_headers["generator"], **_etag(submitted)},
            json={"reason": f"已审核{purpose}用途，允许受控处理"},
        )
        assert approved.status_code == 200, approved.text
        approved_body = approved.json()
        assert approved_body["status"] == "APPROVED"
        assert approved_body["contract_id"]
        assert approved_body["agreement_id"]


def test_raw_data_export_is_rejected_before_provider_review(client, auth_headers):
    response = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["heat"], "Idempotency-Key": "raw-export-boundary-001"},
        json={
            **_payload(),
            "terms": {"output_mode": "RAW", "raw_data_export": True},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "RAW_DATA_EXPORT_NOT_AVAILABLE"


def test_access_request_openapi_create_scope_and_idempotency(client, auth_headers):
    schema = client.get("/api/openapi.json").json()
    paths = schema["paths"]
    for path in (
        "/api/data/access-requests",
        "/api/data/access-requests/{request_id}",
        "/api/data/access-requests/{request_id}/review",
        "/api/data/access-requests/{request_id}/approve",
        "/api/data/access-requests/{request_id}/reject",
        "/api/data/access-requests/{request_id}/withdraw",
        "/api/data/access-requests/{request_id}/revoke",
    ):
        assert path in paths

    first = _create(client, auth_headers, key="usage-request-idempotency-001")
    body = first.json()
    assert first.status_code == 201
    assert body["status"] == "SUBMITTED"
    assert body["applicant"]["org_id"] == "org-exchange-t01"
    assert body["provider"]["org_id"] == "org-generator-t01"
    assert body["capability"]["signature"] == "NOT_PROVIDED"
    assert not body["request_id"].startswith("REQ-")

    replay = _create(client, auth_headers, key="usage-request-idempotency-001")
    assert replay.status_code == 200
    assert replay.json()["request_id"] == body["request_id"]
    assert replay.json()["idempotent_replay"] is True

    conflict_payload = {**_payload(), "purpose": "DIFFERENT_SCOPE"}
    conflict = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["exchange"], "Idempotency-Key": "usage-request-idempotency-001"},
        json=conflict_payload,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_REBINDING"

    exchange_items = client.get(
        "/api/data/access-requests?page=1&page_size=1",
        headers=auth_headers["exchange"],
    )
    provider_items = client.get(
        "/api/data/access-requests?inbox=true&page=1&page_size=1",
        headers=auth_headers["generator"],
    )
    retailer_items = client.get(
        "/api/data/access-requests",
        headers=auth_headers["retailer"],
    )
    exchange_mine = client.get(
        "/api/data/access-requests?mine=true&page=1&page_size=1",
        headers=auth_headers["exchange"],
    )
    generator_mine = client.get(
        "/api/data/access-requests?mine=true&page=1&page_size=1",
        headers=auth_headers["generator"],
    )
    assert exchange_items.status_code == provider_items.status_code == retailer_items.status_code == 200
    assert exchange_mine.status_code == generator_mine.status_code == 200
    assert exchange_items.json()["total"] == 1
    assert provider_items.json()["total"] == 1
    assert retailer_items.json()["total"] == 0
    assert exchange_mine.json()["total"] == 1
    assert generator_mine.json()["total"] == 0

    denied_detail = client.get(
        f"/api/data/access-requests/{body['request_id']}",
        headers=auth_headers["retailer"],
    )
    assert denied_detail.status_code == 403
    assert denied_detail.json()["detail"]["code"] == "REQUEST_SCOPE_DENIED"


def test_duration_policy_is_server_sourced_and_validated(client, auth_headers):
    reference = _asset_reference()
    asset_response = client.get(
        f"/api/trust-space/assets/{reference['asset_id']}",
        headers=auth_headers["regulator"],
    )
    assert asset_response.status_code == 200, asset_response.text
    policy = asset_response.json()["duration_policy"]
    assert policy["policy_version"] == "TRUSTED_SPACE_USAGE_DURATION_V1"
    assert policy["source"] == "SERVER_DEFAULT_POLICY"
    assert policy["is_default"] is True
    assert policy["min_days"] <= policy["default_days"] <= policy["max_days"]

    regulatory_payload = {
        **_payload(),
        "purpose": "REGULATORY_CROSS_ENERGY_REVIEW",
        "terms": {
            "output_mode": "AGGREGATE_ONLY",
            "raw_data_export": False,
            "regulatory_basis": "ENERGY_REGULATION",
            "authority_ref": "DURATION-REG-001",
        },
    }
    omitted_duration = {key: value for key, value in regulatory_payload.items() if key != "duration_days"}
    created = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["regulator"], "Idempotency-Key": "duration-policy-default-001"},
        json=omitted_duration,
    )
    assert created.status_code == 201, created.text
    assert created.json()["duration_days"] == policy["default_days"]
    assert created.json()["duration_policy"] == policy

    invalid = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["regulator"], "Idempotency-Key": "duration-policy-invalid-001"},
        json={**regulatory_payload, "duration_days": policy["max_days"] + 1},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "DURATION_OUT_OF_POLICY"


def test_provider_review_approve_creates_contract_agreement_and_audit(
    client, auth_headers
):
    created = _create(client, auth_headers)
    request = created.json()
    request_id = request["request_id"]

    missing_version = client.post(
        f"/api/data/access-requests/{request_id}/approve",
        headers=auth_headers["generator"],
        json={"reason": "同意受控聚合"},
    )
    assert missing_version.status_code == 428
    assert missing_version.json()["detail"]["code"] == "IF_MATCH_REQUIRED"

    applicant_approve = client.post(
        f"/api/data/access-requests/{request_id}/approve",
        headers={**auth_headers["exchange"], **_etag(request)},
        json={"reason": "申请方不能审批"},
    )
    assert applicant_approve.status_code == 403
    assert applicant_approve.json()["detail"]["code"] == "PROVIDER_REVIEW_REQUIRED"

    reviewed = client.post(
        f"/api/data/access-requests/{request_id}/review",
        headers={**auth_headers["generator"], **_etag(request)},
        json={"note": "已核对资产护照"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "UNDER_REVIEW"

    approved = client.post(
        f"/api/data/access-requests/{request_id}/approve",
        headers={**auth_headers["generator"], **_etag(reviewed.json())},
        json={"reason": "同意受控聚合，不导出原始记录"},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "APPROVED"
    assert approved_body["contract_id"]
    assert approved_body["agreement_id"]
    assert approved_body["decision_capability_label"] == "LOCAL_REAL"
    assert approved_body["capability"]["external_anchor"] == "BLOCKED"

    with SessionLocal() as db:
        request_row = db.get(DataUsageRequest, request_id)
        assert request_row is not None
        contract = db.get(DataContract, request_row.contract_id)
        agreement = db.get(DataSpaceAgreement, request_row.agreement_id)
        assert contract is not None and contract.task_id is None and contract.status == "ACTIVE"
        assert contract.policy_json["constraint"]["output_mode"] == "AGGREGATE_ONLY"
        assert agreement is not None and agreement.task_id is None and agreement.state == "ACTIVE"
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.target_type == "DATA_USAGE_REQUEST",
                AuditLog.target_id == request_id,
                AuditLog.action_code == "DATA_USAGE_REQUEST_APPROVE",
            )
        )
        assert audit is not None
        assert audit.details_json["signature_status"] == "NOT_PROVIDED"

    replay = client.post(
        f"/api/data/access-requests/{request_id}/approve",
        headers={**auth_headers["generator"], "If-Match": '"2"'},
        json={"reason": "重复审批"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True


def test_reject_invalid_transition_and_withdraw_scope(client, auth_headers):
    created = _create(client, auth_headers).json()
    request_id = created["request_id"]
    rejected = client.post(
        f"/api/data/access-requests/{request_id}/reject",
        headers={**auth_headers["generator"], **_etag(created)},
        json={"reason": "用途不符合当前授权策略"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"

    replay = client.post(
        f"/api/data/access-requests/{request_id}/reject",
        headers={**auth_headers["generator"], "If-Match": '"1"'},
        json={"reason": "重复拒绝"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True

    illegal = client.post(
        f"/api/data/access-requests/{request_id}/approve",
        headers={**auth_headers["generator"], "If-Match": '"2"'},
        json={"reason": "不能越过拒绝状态"},
    )
    assert illegal.status_code == 409
    assert illegal.json()["detail"]["code"] == "INVALID_REQUEST_TRANSITION"

    withdrawn = _create(client, auth_headers).json()
    response = client.post(
        f"/api/data/access-requests/{withdrawn['request_id']}/withdraw",
        headers={**auth_headers["exchange"], **_etag(withdrawn)},
        json={"reason": "申请方撤回"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REVOKED"

    provider_withdraw = client.post(
        f"/api/data/access-requests/{withdrawn['request_id']}/withdraw",
        headers={**auth_headers["generator"], "If-Match": '"2"'},
        json={"reason": "越权撤回"},
    )
    assert provider_withdraw.status_code == 403


def test_approve_revoke_updates_contract_and_agreement_and_stale_version_is_409(
    client, auth_headers
):
    created = _create(client, auth_headers).json()
    approved = client.post(
        f"/api/data/access-requests/{created['request_id']}/approve",
        headers={**auth_headers["generator"], **_etag(created)},
        json={"reason": "批准"},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()

    stale = client.post(
        f"/api/data/access-requests/{created['request_id']}/revoke",
        headers={**auth_headers["generator"], "If-Match": '"1"'},
        json={"reason": "旧版本撤销"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "REQUEST_VERSION_CONFLICT"

    revoked = client.post(
        f"/api/data/access-requests/{created['request_id']}/revoke",
        headers={**auth_headers["generator"], **_etag(approved_body)},
        json={"reason": "资产策略变更"},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "REVOKED"
    with SessionLocal() as db:
        contract = db.get(DataContract, approved_body["contract_id"])
        agreement = db.get(DataSpaceAgreement, approved_body["agreement_id"])
        assert contract is not None and contract.status == "REVOKED"
        assert agreement is not None and agreement.state == "REVOKED"


def test_approve_failure_rolls_back_contract_and_agreement(client, auth_headers, monkeypatch):
    created = _create(client, auth_headers).json()

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit sink unavailable")

    monkeypatch.setattr("app.services.data_usage_requests.add_audit_log", fail_audit)
    failed = client.post(
        f"/api/data/access-requests/{created['request_id']}/approve",
        headers={**auth_headers["generator"], **_etag(created)},
        json={"reason": "应当回滚"},
    )
    assert failed.status_code == 500
    assert failed.json()["detail"]["code"] == "REQUEST_TRANSITION_FAILED"
    with SessionLocal() as db:
        request = db.get(DataUsageRequest, created["request_id"])
        assert request is not None
        assert request.status == "SUBMITTED"
        assert request.contract_id is None
        assert request.agreement_id is None
        assert db.scalar(
            select(DataContract).where(DataContract.purpose == "SETTLEMENT_AUDIT")
        ) is None


def test_idempotency_is_scoped_by_applicant_org_and_approval_expires(client, auth_headers):
    exchange = _create(client, auth_headers, key="org-scoped-key-001").json()
    generator = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["generator"], "Idempotency-Key": "org-scoped-key-001"},
        json=_payload(),
    )
    assert generator.status_code == 201, generator.text
    assert generator.json()["request_id"] != exchange["request_id"]

    approved = client.post(
        f"/api/data/access-requests/{exchange['request_id']}/approve",
        headers={**auth_headers["generator"], **_etag(exchange)},
        json={"reason": "短期批准"},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    with SessionLocal() as db:
        request = db.get(DataUsageRequest, body["request_id"])
        assert request is not None
        request.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    expired = client.get(
        f"/api/data/access-requests/{body['request_id']}",
        headers=auth_headers["exchange"],
    )
    assert expired.status_code == 200
    assert expired.json()["status"] == "EXPIRED"
    with SessionLocal() as db:
        contract = db.get(DataContract, body["contract_id"])
        agreement = db.get(DataSpaceAgreement, body["agreement_id"])
        assert contract is not None and contract.status == "EXPIRED"
        assert agreement is not None and agreement.state == "EXPIRED"
