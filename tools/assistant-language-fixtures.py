"""Build run-owned assistant prerequisites through normal, guarded demo HTTP APIs.

This module never opens databases, reads Vault files, changes permissions, or
persists credentials/confirmation tokens/signatures. The calling harness must
explicitly enable workflow creation and own every created business record.
"""
from __future__ import annotations

import math
import time
from typing import Any
from urllib.parse import quote


PROFILES = (
    ("generator", "electricity", "generation", True), ("retailer", "electricity", "load", True),
    ("coal", "coal", "production", True), ("heat", "heat", "supply", True),
    ("gas", "gas", "supply", True), ("oil", "oil", "production", True),
    ("exchange", "electricity", "price", True), ("exchange_coal", "coal", "production", False),
    ("exchange_heat", "heat", "supply", False), ("exchange_gas", "gas", "supply", False),
    ("exchange_oil", "oil", "production", False), ("regulator", "electricity", "load", False),
)
WINDOWS = (("2026-08-12", "2026-08-14"), ("2026-08-15", "2026-08-17"))


class WorkflowFixtureError(AssertionError):
    pass


def require(condition: Any, message: str) -> None:
    if not condition:
        raise WorkflowFixtureError(message)


def rows(payload: Any) -> list[dict[str, Any]]:
    return payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []


def remember(owner: Any, registry: str, record_id: str) -> None:
    require(bool(record_id), "A created record omitted its identifier")
    owner.own(record_id)
    collection = getattr(owner, registry, None)
    if isinstance(collection, set):
        collection.add(record_id)


def catalog(owner: Any, account: str) -> list[dict[str, Any]]:
    if callable(getattr(owner, "reference_list", None)):
        return rows(owner.reference_list(account, "/trust-space/catalog?page_size=100"))
    collected = []
    for page in range(1, 21):
        payload = owner.call(f"/trust-space/catalog?page={page}&page_size=100", account)
        batch = rows(payload)
        collected.extend(batch)
        if not batch or len(collected) >= payload.get("total", len(collected)):
            return collected
    raise WorkflowFixtureError("Visible catalog exceeded the explicit 20-page preparation budget")


def request_grant(owner: Any, account: str, asset: dict[str, Any], resource: str) -> dict[str, Any]:
    detail = owner.call("/trust-space/assets/" + quote(asset["asset_id"], safe=""), account)
    version = detail.get("current_version_id")
    require(version, "Selected external asset has no current version")
    purpose = "REGULATORY_CROSS_ENERGY_REVIEW" if account == "regulator" else "SETTLEMENT_ANALYSIS"
    request = owner.call("/data/access-requests", account, {
        "asset_id": asset["asset_id"], "asset_version_id": version, "purpose": purpose, "usage_mode": "MPC_AGGREGATE",
        "requested_scope": {"purpose_code": purpose, "algorithm_code": "CONTROLLED_" + purpose + "_V1",
                            "start_date": WINDOWS[0][0], "end_date": WINDOWS[-1][1], "max_uses": 2,
                            "resource": resource, "function": "average", "region": None,
                            "output_mode": "AGGREGATE_ONLY", "raw_data_export": False},
        "requested_fields": ["summary", "quality_metrics"], "duration_days": 7,
        "terms": {"accepted": True, "human_review_required": True, "output_mode": "AGGREGATE_ONLY",
                  "raw_data_export": False, "acceptance_run": owner.run_id, "acceptance_fixture": "owned-query-workflows",
                  **({"regulatory_basis": "ENERGY_REGULATION", "authority_ref": owner.run_id} if account == "regulator" else {})},
    }, key=owner.key("workflow-request-" + account))
    remember(owner, "owned_requests", request["request_id"])
    require(request["asset"]["asset_id"] == asset["asset_id"]
            and request["asset"]["version_id"] == version
            and request["applicant"]["org_id"] == owner.sessions[account]["user"]["org_id"],
            "New request does not belong to the selected applicant, asset, or version")
    provider = next((name for name, session in owner.sessions.items()
                     if session["user"]["org_id"] == request["provider"]["org_id"]), None)
    require(provider is not None and request["provider"]["org_id"] == asset["provider"]["org_id"],
            "No real logged-in provider can approve this request")
    approved = owner.call(f"/data/access-requests/{request['request_id']}/approve", provider,
                          {"reason": owner.run_id + " provider approval for two controlled assistant prerequisites"},
                          match=request["state_version"], key=owner.key("workflow-approve-" + account))
    require(approved["request_id"] == request["request_id"] and approved["status"] == "APPROVED",
            "Provider approval did not persist for this run's request")
    for key in ("contract_id", "agreement_id"):
        if approved.get(key):
            owner.own(approved[key])
    return approved


def run_query(owner: Any, account: str, domain: str, resource: str, asset: dict[str, Any],
              window: tuple[str, str], grant: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    condition = {"provider_org_id": asset["provider"]["org_id"], "asset_id": asset["asset_id"],
                 "energy_domain": domain, "resource": resource, "function": "average",
                 "start_date": window[0], "end_date": window[1], "region": None, "decimals": 2}
    if grant:
        require(grant["request_id"] in owner.owned_requests, "A pre-existing authorization cannot be reused as this run's fixture")
        condition["authorization_id"] = grant["request_id"]
    confirmed = owner.call("/trust-space/query/confirm", account, condition, key=owner.key("workflow-confirm-" + account))
    require(confirmed.get("confirmed") is True and confirmed.get("confirmation_token"), "Query confirmation omitted its confirmation proof")
    require(confirmed["asset_id"] == asset["asset_id"] and confirmed["provider_org_id"] == asset["provider"]["org_id"],
            "Query confirmation changed the selected asset or provider")
    remember(owner, "owned_requests", confirmed["authorization_id"])
    approved = owner.call("/data/access-requests/" + confirmed["authorization_id"], account)
    require(approved["status"] == "APPROVED" and approved["applicant"]["user_id"] == owner.sessions[account]["user"]["user_id"],
            "Confirmed approval belongs to another actor or is not approved")
    if grant:
        require(approved["request_id"] == grant["request_id"], "Explicit provider approval was substituted")
    else:
        require(approved["terms"].get("authorization_source") == "SELF_OWNED_QUERY"
                and approved["requested_scope"].get("max_uses") == 1,
                "Owned confirmation did not create a narrow single-use approval")
    # The confirmation token and full body remain in this stack frame only.
    body = {**condition, **{key: confirmed[key] for key in ("authorization_id", "provider_org_id", "asset_id")},
            "confirmation_token": confirmed["confirmation_token"]}
    task = owner.call("/trust-space/query/execute", account, body, key=owner.key("workflow-execute-" + account))
    remember(owner, "owned_query_tasks", task["task_id"])
    deadline = time.monotonic() + 120
    while task["status"] not in {"SUCCEEDED", "FAILED"} and time.monotonic() < deadline:
        task = owner.call("/trust-space/query/tasks/" + task["task_id"], account)
        if task["status"] not in {"SUCCEEDED", "FAILED"}:
            time.sleep(0.25)
    require(task["status"] == "SUCCEEDED", "Owned query did not succeed; failure_code=" + str(task.get("failure_code")))
    result = owner.call("/trust-space/query/tasks/" + task["task_id"] + "/result", account)
    require(result.get("task_id") == task["task_id"] and result.get("request_item_id"),
            "Controlled result changed the owned query or omitted its real request item")
    value = result.get("result")
    require(result.get("record_count") == 12 and result.get("raw_records_returned") is False
            and result.get("digital_signature") == "已验证"
            and result.get("privacy_verification", {}).get("status") == "VERIFIED",
            "Query result lacks twelve records and verified non-export/signature evidence")
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), "Average result is not a finite controlled scalar")
    require(result.get("asset_version_id") == approved["asset"]["version_id"]
            and result.get("dataset_version") == approved["asset"]["version_no"], "Query changed the approved immutable data version")
    remember(owner, "owned_compute_jobs", result["job_id"])
    detail = owner.call("/trust-space/computations/" + result["job_id"], account)
    job = detail["job"]
    require(job["job_id"] == result["job_id"] and job["task_id"] == task["task_id"]
            and job.get("task_kind") == "TRUSTED_QUERY" and job.get("status") == "SUCCEEDED",
            "Standalone job detail does not match the completed query")
    require(job.get("privacy_guarantees", {}).get("api_raw_records_returned") is False, "Job detail lacks the API non-export guarantee")
    receipts = detail.get("receipts", [])
    require(receipts and all(row.get("audit_event_verified") is True
                             and row.get("biz_type") == "TRUSTED_QUERY"
                             and row.get("biz_id") == result["request_item_id"]
                             and row.get("evidence_hash") == job["output_hash"]
                             and row.get("chain_code") is None and row.get("tx_hash") is None
                             for row in receipts), "Standalone query receipt does not bind the verified request item and result")
    summary = {"entity_type": "privacy_compute_job", "entity_id": job["job_id"], "job_id": job["job_id"],
               "task_id": task["task_id"], "request_item_id": result["request_item_id"],
               "authorization_id": confirmed["authorization_id"], "asset_id": asset["asset_id"],
               "asset_version_id": result["asset_version_id"], "dataset_version": result["dataset_version"],
               "status": job["status"], "record_count": 12, "output_hash": job["output_hash"],
               "receipt_count": len(receipts), "raw_records_returned": False,
               "signature_verified": True, "privacy_verification": "VERIFIED"}
    audit = {}
    if owner.sessions[account]["user"]["role_code"] in {"EXCHANGE", "REGULATOR"}:
        audit = owner.call("/trust-space/audit/tasks/" + task["task_id"], account, expected=(200, 403, 404))
        has_audit_permission = "VIEW_AUDIT" in owner.sessions[account]["user"].get("permissions", [])
        require(not has_audit_permission or audit.get("http_status") not in {403, 404},
                "An audit-authorized applicant cannot read its own native query audit")
        if audit.get("http_status") not in {403, 404}:
            require(has_audit_permission, "Native audit read escaped the account's explicit VIEW_AUDIT permission")
            require(audit["task"]["task_id"] == task["task_id"] and bool(audit.get("audit_chain"))
                    and bool(audit.get("execution_receipts")), "Native query audit omitted its real logs or execution receipts")
            require(all(row.get("audit_event_verified") is True and row.get("result_hash") == job["output_hash"]
                        for row in audit["execution_receipts"]), "Native audit receipt is not bound to the actual verified result")
    return summary, detail, audit


def assert_visible_jobs(owner: Any, account: str, wanted: set[str]) -> None:
    missing = set(wanted)
    for page in range(1, 21):
        payload = owner.call(f"/trust-space/computations?page={page}&page_size=100", account)
        batch = rows(payload)
        missing -= {row.get("job_id") for row in batch}
        if not missing:
            return
        if not batch or page * 100 >= payload.get("total", page * 100):
            break
    raise WorkflowFixtureError("Two newly completed jobs are not both visible through the official computation list")


def prepare_account(owner: Any, account: str, domain: str, resource: str, own: bool) -> dict[str, Any]:
    visible = catalog(owner, account)
    org_id = owner.sessions[account]["user"]["org_id"]
    candidates = [asset for asset in visible if asset.get("domain") == domain and asset.get("metadata", {}).get("resource_id") == resource
                  and ((asset["provider"]["org_id"] == org_id and asset.get("actions", {}).get("can_compute_own") is True)
                       if own else (asset["provider"]["org_id"] != org_id and asset.get("actions", {}).get("can_request_usage") is True))]
    require(candidates, "No real visible asset has the required resource and account computation/request capability")
    asset = candidates[0]
    fixture = owner.fixtures.setdefault(account, {})
    requestable = next((item for item in visible if item.get("actions", {}).get("can_request_usage") is True), None)
    if requestable:
        fixture["requestable_asset"] = requestable
    else:
        denied = next((item for item in visible if item.get("actions", {}).get("can_request_usage") is False), None)
        require(denied is not None, "No real visible asset can anchor the non-requestable denial test")
        fixture["requestable_asset"] = {**denied, "fixture_basis": "VISIBLE_NON_REQUESTABLE_DENIAL_TARGET"}
    grant = None if own else request_grant(owner, account, asset, resource)
    summaries, details, audits = [], [], []
    for window in WINDOWS:
        summary, detail, audit = run_query(owner, account, domain, resource, asset, window, grant)
        summaries.append(summary)
        details.append(detail)
        audits.append(audit)
        fixture["owned_workflows"] = list(summaries)
    require(len({item["job_id"] for item in summaries}) == len({item["task_id"] for item in summaries}) == 2,
            "Preparation replayed one job instead of creating two distinct query executions")
    assert_visible_jobs(owner, account, {item["job_id"] for item in summaries})
    fixture.update(task=dict(summaries[0]), task_candidates=list(summaries), task_detail=details[0],
                   evidence=dict(summaries[0]), audit=dict(summaries[0]), audit_task_id=summaries[0]["task_id"], audit_detail=audits[0])
    denied_status = audits[0].get("http_status")
    detail_code = audits[0].get("detail")
    access = {"http_status": (denied_status or 200) if audits[0] else None, "allowed": bool(audits[0]) and denied_status not in {403, 404}}
    if isinstance(detail_code, dict) and detail_code.get("code"):
        access["code"] = detail_code["code"]
    fixture["audit_access_basis"] = access
    return {"queries": summaries, "query_job_count": 2, "query_execution_count": 2,
            "application_fixture_basis": fixture["requestable_asset"].get("fixture_basis", "VISIBLE_REQUESTABLE_ASSET"),
            "audit_access_basis": access}


def prepare_advance_settlement(owner: Any) -> dict[str, Any]:
    rules = rows(owner.call("/rules", "exchange"))
    active = [rule for rule in rules if rule.get("status") == "ACTIVE"]
    rule = next((rule for rule in active if rule.get("rule_id") == "rule-demo-business-v1"), active[0] if active else None)
    require(rule is not None, "No active real settlement rule is available")
    created = owner.call("/settlement/tasks", "exchange", {
        "task_name": owner.run_id + " assistant advance-review prerequisite", "trade_batch_no": "DEMO-2026-08-E2E",
        "period_start": "2026-08-01", "period_end": "2026-08-31", "rule_id": rule["rule_id"],
        "participants": [{"org_id": owner.sessions[account]["user"]["org_id"], "role_in_task": role}
                         for account, role in (("generator", "GENERATOR"), ("retailer", "RETAILER"))],
        "business_description": owner.run_id + " normal INIT settlement; no forced execution state",
    }, key=owner.key("workflow-settlement"))
    remember(owner, "owned_settlement_tasks", created["task_id"])
    require(created.get("readiness", {}).get("preflight_passed") is True, "New settlement cannot run through the native readiness checks")
    detail = owner.call("/trust-space/ttc/" + created["task_id"], "exchange")
    require(detail["task"].get("ttc_state") == "INIT" and any(str(value).startswith("transition:") for value in detail.get("allowed_actions", [])),
            "Native INIT settlement has no reviewable transition")
    target = {"entity_type": "settlement_task", "entity_id": created["task_id"], "task_id": created["task_id"], "status": detail["task"]["status"], "ttc_state": "INIT"}
    owner.fixtures["exchange"].update(advance_task=target, advance_task_detail=detail)
    return {**target, "preflight_passed": True, "transition_count": sum(str(value).startswith("transition:") for value in detail["allowed_actions"])}


def prepare_owned_workflows(owner: Any) -> dict[str, Any]:
    """Prepare two legitimate typed query jobs per business account, never fake state."""
    require(getattr(owner.args, "create_owned_workflows", False) is True and getattr(owner, "_preparing_workflows", False) is True,
            "Owned workflow preparation requires the explicit CLI flag and harness mutation guard")
    require(getattr(owner, "demo_guard_passed", False) is True and getattr(owner, "actual_environment", None) == "demo",
            "APP_ENV=demo must be verified before preparing business prerequisites")
    require({row[0] for row in PROFILES} <= owner.sessions.keys(), "All twelve real business/provider sessions are required for complete prerequisites")
    manifest = {"accounts": {}, "query_execution_count": 0, "query_job_count": 0, "advance_settlement_count": 0, "failures": []}
    owner.workflow_fixture_manifest = manifest
    prior_tasks, prior_jobs = set(owner.owned_query_tasks), set(owner.owned_compute_jobs)
    for account, domain, resource, own in PROFILES:
        evidence = owner.check("owned-workflow-fixture:" + account,
                               lambda account=account, domain=domain, resource=resource, own=own: prepare_account(owner, account, domain, resource, own),
                               account=account, status="ACTUAL_SUCCESS")
        if evidence is None:
            manifest["failures"].append(account)
        else:
            manifest["accounts"][account] = evidence
        # Count actually created/observed IDs even if a later proof check fails.
        manifest["query_execution_count"] = len(owner.owned_query_tasks - prior_tasks)
        manifest["query_job_count"] = len(owner.owned_compute_jobs - prior_jobs)
    settlement = owner.check("owned-workflow-fixture:advance-settlement", lambda: prepare_advance_settlement(owner), account="exchange", status="ACTUAL_SUCCESS")
    if settlement is None:
        manifest["failures"].append("exchange:advance-settlement")
    else:
        manifest["advance_settlement"] = settlement
        manifest["advance_settlement_count"] = 1
    return manifest
