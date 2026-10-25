"""Offline acceptance guard/proof checks; no application DB, Vault, or network."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("language_harness_checks", ROOT / "tools/verify-assistant-language.py")
assert spec and spec.loader
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


@pytest.fixture(autouse=True)
def reset_test_database():
    # This module exercises the HTTP harness's pure guards, not application data.
    yield


@pytest.fixture
def owner():
    value = object.__new__(harness.LanguageAcceptance)
    value.args = SimpleNamespace(create_owned_requests=False, create_owned_workflows=True, accounts=None)
    value.run_id = "unit-owned-run"
    value.demo_guard_passed = value._preparing_workflows = True
    value.business_posts = 0
    value.sessions = {"exchange": {"user": {"role_code": "EXCHANGE", "org_id": "org-exchange", "permissions": ["VIEW_AUDIT"]}, "org": {"energy_domain": "electricity"}},
                      "provider": {"user": {"role_code": "GENERATOR", "org_id": "org-provider", "permissions": []}},
                      "admin": {"user": {"role_code": "ADMIN", "org_id": "org-admin", "permissions": []}}}
    value.fixtures = {"exchange": {"catalog": {"items": [{"asset_id": "asset-unit", "provider": {"org_id": "org-provider"}, "actions": {"can_request_usage": True}}]}}, "provider": {}, "admin": {}}
    for name in ("owned", "owned_sessions", "owned_requests", "owned_query_tasks", "owned_compute_jobs", "owned_settlement_tasks", "initial_request_ids", "initial_query_task_ids", "initial_settlement_task_ids"):
        setattr(value, name, set())
    value.owned_request_bindings, value.owned_confirmations = {}, {}
    return value


@pytest.mark.parametrize("guard", ["flag", "phase", "demo", "foreign_authorization", "other_actor", "bad_key", "bad_token", "changed_condition", "admin"])
def test_query_execution_cannot_escape_run_ownership(owner, monkeypatch, guard):
    condition = {"authorization_id": "owned-auth", "asset_id": "asset-unit", "provider_org_id": "org-provider", "function": "average"}
    body = {**condition, "confirmation_token": "unit-proof"}
    owner.owned_confirmations["owned-auth"] = {"account": "exchange", "confirmation_token_hash": hashlib.sha256(b"unit-proof").hexdigest(), "condition_hash": harness.digest(condition)}
    key, account = owner.run_id + "-execute-1", "exchange"
    if guard == "flag": owner.args.create_owned_workflows = False
    elif guard == "phase": owner._preparing_workflows = False
    elif guard == "demo": owner.demo_guard_passed = False
    elif guard == "foreign_authorization": body["authorization_id"] = "existing-auth"
    elif guard == "other_actor": account = "provider"
    elif guard == "bad_key": key = "another-run-execute"
    elif guard == "bad_token": body["confirmation_token"] = "different-proof"
    elif guard == "changed_condition": body["function"] = "sum"
    elif guard == "admin": account = "admin"
    monkeypatch.setattr(harness.deep.Acceptance, "call", lambda *_args, **_kwargs: pytest.fail("Guard reached HTTP"))
    with pytest.raises(harness.deep.CheckFailure, match="outside its own authorized records"):
        owner.call("/trust-space/query/execute", account, body, key=key)
    assert owner.business_posts == 0


def test_approval_guard_requires_actual_owned_provider_and_version(owner, monkeypatch):
    owner.args.create_owned_requests = True
    owner.owned_requests.add("owned-request")
    owner.owned_request_bindings["owned-request"] = {"provider_org_id": "org-provider"}
    monkeypatch.setattr(harness.deep.Acceptance, "call", lambda *_args, **_kwargs: pytest.fail("Guard reached HTTP"))
    for account, version in (("exchange", 1), ("provider", None)):
        with pytest.raises(harness.deep.CheckFailure):
            owner.call("/data/access-requests/owned-request/approve", account, {"reason": owner.run_id + " own fixture"}, match=version, key=owner.run_id + "-approve-1")


def test_confirmation_retains_only_hashed_token_and_binds_exact_execution(owner):
    body = {"asset_id": "asset-unit", "provider_org_id": "org-provider", "function": "average"}
    response = {"authorization_id": "owned-auth", "confirmation_token": "unit-proof", "asset_id": "asset-unit", "provider_org_id": "org-provider"}
    owner._register_owned_response("/trust-space/query/confirm", "exchange", body, response, True)
    stored = owner.owned_confirmations["owned-auth"]
    assert "unit-proof" not in json.dumps(stored)
    assert owner._workflow_post_allowed("/trust-space/query/execute", "exchange", {**body, **response}, {"key": owner.run_id + "-execute-1"})
    assert not owner._workflow_post_allowed("/trust-space/query/execute", "provider", {**body, **response}, {"key": owner.run_id + "-execute-1"})


def test_typed_job_context_does_not_conflate_query_and_job_ids(owner):
    owner.fixtures["exchange"]["task"] = {"entity_type": "privacy_compute_job", "entity_id": "owned-job", "job_id": "owned-job", "task_id": "owned-query"}
    assert owner.target("exchange", "task") == ("privacy_compute_job", "owned-job")
    owner.call = lambda path, account: {"path": path, "account": account}
    assert owner.reference("exchange", "task")["path"] == "/trust-space/computations/owned-job"


def test_required_fixture_missing_is_failure_instead_of_a_skipped_case(owner):
    corpus = json.loads(harness.CORPUS.read_text(encoding="utf-8"))
    case = next(row for row in corpus["cases"] if row["id"] == "task-context")
    with pytest.raises(harness.deep.CheckFailure, match="Required owned workflow target is missing"):
        owner.evaluate("exchange", case)


def receipt_fixture(owner):
    item = {"receipt_id": "receipt-unit", "evidence_kind": "EXECUTION_RECEIPT", "request_hash": "request-unit-hash", "result_hash": "result-unit-hash", "status": "CONFIRMED", "audit_event_verified": True,
            "verification_status": "MATCHED", "verify": {"matched": True}}
    output = {"job_id": "owned-job", "task_id": "owned-query", "task_kind": "TRUSTED_QUERY", "evidence_kind": "EXECUTION_RECEIPT", "verification_status": "MATCHED", "receipt_count": 1, "items": [item], "audit_log_count": 2, "report_count": 0, "evidence_count": 0,
              "explanation": "真实查询日志与执行回执；暂无正式审计报告。"}
    job = {"job_id": "owned-job", "task_id": "owned-query", "task_kind": "TRUSTED_QUERY", "status": "SUCCEEDED", "output_hash": "result-unit-hash"}
    audit = {"task": {"task_id": "owned-query"}, "execution_receipts": [deepcopy(item)], "audit_chain": [{"log_id": "one"}, {"log_id": "two"}], "reports": [], "evidence": []}
    owner.call = lambda path, _account: {"job": job} if path.startswith("/trust-space/computations/") else audit
    return output, job, audit


@pytest.mark.parametrize("action", ["VERIFY_EVIDENCE_SUMMARY", "EXPLAIN_AUDIT"])
def test_query_receipt_requires_real_scoped_native_hash_count_and_binding(owner, action):
    output, _, _ = receipt_fixture(owner)
    result = owner.validate_job_read("exchange", action, output)
    assert result["native_query_audit_matched"] and result["report_count"] == 0


@pytest.mark.parametrize("mutation", ["job_binding", "audit_binding", "receipt_missing", "request_hash", "result_hash", "job_hash", "audit_false", "verify_false", "unverified", "report_count", "log_count", "blockchain_label", "false_report"])
def test_succeeded_status_cannot_mask_missing_or_mismatched_receipt_proof(owner, mutation):
    output, job, audit = receipt_fixture(owner)
    if mutation == "job_binding": job["task_id"] = "other-query"
    elif mutation == "audit_binding": audit["task"]["task_id"] = "other-query"
    elif mutation == "receipt_missing": audit["execution_receipts"] = []
    elif mutation == "request_hash": output["items"][0]["request_hash"] = "wrong-request"
    elif mutation == "result_hash": output["items"][0]["result_hash"] = "wrong-result"
    elif mutation == "job_hash": job["output_hash"] = "other-result"
    elif mutation == "audit_false": audit["execution_receipts"][0]["audit_event_verified"] = False
    elif mutation == "verify_false": output["items"][0]["verify"]["matched"] = False
    elif mutation == "unverified": output["verification_status"] = "UNVERIFIED"
    elif mutation == "report_count": output["report_count"] = 1
    elif mutation == "log_count": output["audit_log_count"] = 1
    elif mutation == "blockchain_label": output["items"][0]["evidence_id"] = "pretend-chain-proof"
    elif mutation == "false_report": output["explanation"] = "正式审计报告已经生成。"
    with pytest.raises(harness.deep.CheckFailure):
        owner.validate_job_read("exchange", "EXPLAIN_AUDIT", output)


def test_complete_manifest_requires_every_real_account_and_exact_owned_queries(owner):
    owner.sessions, owner.fixtures = {}, {}
    manifest = {"accounts": {}, "query_execution_count": 24, "query_job_count": 24, "advance_settlement_count": 1, "failures": []}
    for index in range(12):
        account = "exchange" if index == 0 else "business-" + str(index)
        owner.sessions[account] = {"user": {"role_code": "EXCHANGE" if index == 0 else "GENERATOR", "org_id": account, "permissions": []}}
        queries = [{"entity_type": "privacy_compute_job", "entity_id": f"job-{index}-{j}", "job_id": f"job-{index}-{j}", "task_id": f"query-{index}-{j}", "authorization_id": f"auth-{index}-{j}", "status": "SUCCEEDED"} for j in range(2)]
        for row in queries:
            owner.owned_query_tasks.add(row["task_id"])
            owner.owned_compute_jobs.add(row["job_id"])
            owner.owned_confirmations[row["authorization_id"]] = {"account": account}
        owner.fixtures[account] = {"owned_workflows": queries, "task": queries[0], "requestable_asset": {"asset_id": "visible-unit"}}
        manifest["accounts"][account] = {"queries": deepcopy(queries)}
    owner.owned_settlement_tasks.add("owned-settlement")
    owner.fixtures["exchange"].update(advance_task={"entity_id": "owned-settlement"}, advance_task_detail={"task": {"ttc_state": "INIT"}})
    owner.validate_workflow_manifest(manifest)
    manifest["accounts"]["business-1"]["queries"][0]["job_id"] = "foreign-job"
    with pytest.raises(harness.deep.CheckFailure, match="Manifest queries differ"):
        owner.validate_workflow_manifest(manifest)


def test_original_corpus_denominator_and_digest_stay_fixed():
    corpus = json.loads(harness.CORPUS.read_text(encoding="utf-8"))
    assert len(corpus["cases"]) == 56
    assert harness.digest(corpus) == "2f70484e65f2ab797ff8bf0f06ec4c98b36aba07a08ee7b6950f1b0d8cef008a"
    count = 0
    for _, role in harness.deep.seed_accounts().values():
        count += sum(not row.get("roles") or role in row["roles"] or "ENTERPRISE" in row["roles"] and role in harness.ENTERPRISE for row in corpus["cases"])
    assert count == 721
