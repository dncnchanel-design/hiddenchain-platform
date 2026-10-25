"""Pure HTTP-sequence tests: no backend imports, network, database, or Vault."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("assistant_language_fixture_builder", ROOT / "tools/assistant-language-fixtures.py")
builder = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(builder)


@pytest.fixture(autouse=True)
def reset_test_database():
    # Override the shared backend autouse fixture for this pure module in CI.
    yield


class FakeOwner:
    """An in-memory API contract simulator, never an application data fixture."""
    def __init__(self):
        self.args = SimpleNamespace(create_owned_workflows=True)
        self._preparing_workflows = self.demo_guard_passed = True
        self.actual_environment = "demo"
        self.run_id = "unit-workflow-run"
        self.sessions = {}
        self.assets = {}
        for name, domain, resource, own in builder.PROFILES:
            role = {"generator": "GENERATOR", "retailer": "RETAILER", "coal": "COAL_ENTERPRISE", "heat": "HEAT_ENTERPRISE", "gas": "GAS_ENTERPRISE", "oil": "OIL_ENTERPRISE", "regulator": "REGULATOR"}.get(name, "EXCHANGE")
            self.sessions[name] = {"user": {"user_id": "user-" + name, "org_id": "org-" + name, "role_code": role, "permissions": ["VIEW_AUDIT"]}}
            if own:
                self.assets[name] = {"asset_id": "asset-" + name, "domain": domain, "metadata": {"resource_id": resource},
                                     "provider": {"org_id": "org-" + name}, "owner": name}
        self.fixtures = {name: {} for name in self.sessions}
        self.owned, self.owned_requests, self.owned_query_tasks, self.owned_compute_jobs, self.owned_settlement_tasks = (set() for _ in range(5))
        self.owned_confirmations = {}
        self.requests, self.tasks, self.jobs, self.settlements = {}, {}, {}, {}
        self.calls, self.checks = [], []
        self.counter = 0
        self.bad_result_account = self.missing_requestable_account = self.denied_audit_account = self.hidden_job_account = None
        self.misbound_result_account = self.misbound_receipt_account = None

    def own(self, record_id):
        self.owned.add(record_id)
        return record_id

    def key(self, label):
        self.counter += 1
        return f"{self.run_id}-{label}-{self.counter}"

    def check(self, label, action, **kwargs):
        context = {key: value for key, value in kwargs.items() if key != "status"}
        try:
            result = action()
        except Exception as error:
            self.checks.append({"check": label, "status": "FAIL", "error": str(error), **context})
            return None
        self.checks.append({"check": label, "status": "PASS", **context})
        return result

    def visible_assets(self, account):
        domain = next(row[1] for row in builder.PROFILES if row[0] == account)
        role = self.sessions[account]["user"]["role_code"]
        output = []
        for name, asset in self.assets.items():
            visible = account == "regulator" or (asset["domain"] == domain and (role == "EXCHANGE" or domain == "electricity" or name == account))
            if visible:
                output.append({**asset, "actions": {"can_compute_own": name == account,
                               "can_request_usage": name != account and account != self.missing_requestable_account}})
        return deepcopy(output)

    def grant(self, account, asset, request_id, own=False):
        return {"request_id": request_id, "status": "APPROVED" if own else "SUBMITTED", "state_version": 1,
                "asset": {"asset_id": asset["asset_id"], "version_id": "version-" + asset["owner"], "version_no": 2},
                "provider": asset["provider"], "applicant": {"user_id": "user-" + account, "org_id": "org-" + account},
                "terms": {"authorization_source": "SELF_OWNED_QUERY"} if own else {},
                "requested_scope": {"max_uses": 1 if own else 2}}

    def call(self, path, account=None, body=None, **kwargs):
        method = kwargs.get("method") or ("POST" if body is not None else "GET")
        self.calls.append((method, path, account, deepcopy(body), deepcopy(kwargs)))
        if method == "POST":
            assert self._preparing_workflows and kwargs.get("key", "").startswith(self.run_id)
        if path.startswith("/trust-space/catalog?"):
            items = self.visible_assets(account)
            return {"items": items, "total": len(items)}
        if path.startswith("/trust-space/assets/"):
            asset = next(a for a in self.assets.values() if a["asset_id"] == path.rsplit("/", 1)[1])
            return {"asset": asset, "current_version_id": "version-" + asset["owner"]}
        if path == "/data/access-requests":
            assert body["terms"]["acceptance_run"] == self.run_id and body["requested_scope"]["max_uses"] == 2
            if account == "regulator":
                assert body["purpose"] == "REGULATORY_CROSS_ENERGY_REVIEW" and body["terms"]["regulatory_basis"] == "ENERGY_REGULATION"
            asset = next(a for a in self.assets.values() if a["asset_id"] == body["asset_id"])
            record = self.grant(account, asset, f"request-{account}")
            self.requests[record["request_id"]] = record
            return deepcopy(record)
        if path.startswith("/data/access-requests/"):
            request_id = path.split("/")[3]
            record = self.requests[request_id]
            if path.endswith("/approve"):
                assert request_id in self.owned_requests and record["provider"]["org_id"] == self.sessions[account]["user"]["org_id"]
                assert kwargs["match"] == record["state_version"] and body["reason"].startswith(self.run_id)
                record.update(status="APPROVED", state_version=2)
            return deepcopy(record)
        if path == "/trust-space/query/confirm":
            asset = next(a for a in self.assets.values() if a["asset_id"] == body["asset_id"])
            request_id = body.get("authorization_id")
            if not request_id:
                request_id = f"self-{account}-{len(self.requests)}"
                self.requests[request_id] = self.grant(account, asset, request_id, True)
            assert self.requests[request_id]["status"] == "APPROVED"
            result = {"confirmed": True, "authorization_id": request_id, "provider_org_id": asset["provider"]["org_id"],
                      "asset_id": asset["asset_id"], "confirmation_token": "memory-only-confirmation-" + str(self.counter)}
            self.owned_confirmations[request_id] = {"body": {**body, **{k: result[k] for k in ("authorization_id", "provider_org_id", "asset_id")}}, "token": result["confirmation_token"]}
            return result
        if path == "/trust-space/query/execute":
            confirmation = self.owned_confirmations[body["authorization_id"]]
            assert {k: v for k, v in body.items() if k != "confirmation_token"} == confirmation["body"]
            assert body["confirmation_token"] == confirmation["token"]
            task_id = "query-" + str(len(self.tasks))
            job_id = "job-" + task_id
            self.tasks[task_id] = {"task_id": task_id, "status": "QUEUED", "account": account, "body": deepcopy(body), "job_id": job_id}
            self.jobs[job_id] = {"job_id": job_id, "task_id": task_id, "status": "SUCCEEDED", "task_kind": "TRUSTED_QUERY", "output_hash": "a" * 64,
                                 "privacy_guarantees": {"api_raw_records_returned": False}}
            self.owned_query_tasks.add(task_id)
            return {"task_id": task_id, "status": "QUEUED"}
        if path.startswith("/trust-space/query/tasks/"):
            task_id = path.split("/")[4]
            task = self.tasks[task_id]
            assert task["account"] == account
            if path.endswith("/result"):
                grant = self.requests[task["body"]["authorization_id"]]
                self.owned_compute_jobs.add(task["job_id"])
                return {"task_id": "another-query" if account == self.misbound_result_account else task_id,
                        "request_item_id": "item-" + task_id,
                        "job_id": task["job_id"], "asset_version_id": grant["asset"]["version_id"], "dataset_version": 2,
                        "record_count": 11 if account == self.bad_result_account else 12, "raw_records_returned": False,
                        "digital_signature": "已验证", "privacy_verification": {"status": "VERIFIED"}, "result": 123.45}
            task["status"] = "SUCCEEDED"
            return {"task_id": task_id, "status": task["status"]}
        if path.startswith("/trust-space/computations?"):
            items = [job for job in self.jobs.values() if self.tasks[job["task_id"]]["account"] == account]
            if account == self.hidden_job_account:
                items = items[:1]
            return {"items": deepcopy(items), "total": len(items)}
        if path.startswith("/trust-space/computations/"):
            job = self.jobs[path.rsplit("/", 1)[1]]
            return {"job": deepcopy(job), "receipts": [{"evidence_id": "receipt-" + job["job_id"], "biz_type": "TRUSTED_QUERY",
                    "biz_id": "another-item" if account == self.misbound_receipt_account else "item-" + job["task_id"],
                    "evidence_hash": job["output_hash"], "chain_code": None, "tx_hash": None, "audit_event_verified": True}]}
        if path.startswith("/trust-space/audit/tasks/"):
            if account == self.denied_audit_account:
                return {"http_status": 403, "detail": {"code": "AUDIT_SCOPE_DENIED"}}
            task_id = path.rsplit("/", 1)[1]
            return {"task": {"task_id": task_id}, "audit_chain": [{"log_id": "log-" + task_id}],
                    "execution_receipts": [{"receipt_id": "receipt-" + task_id, "audit_event_verified": True, "result_hash": "a" * 64}]}
        if path == "/rules":
            return [{"rule_id": "rule-demo-business-v1", "status": "ACTIVE"}]
        if path == "/settlement/tasks":
            assert account == "exchange" and body["task_name"].startswith(self.run_id)
            assert {row["role_in_task"] for row in body["participants"]} == {"GENERATOR", "RETAILER"}
            self.settlements["settlement-one"] = {"task_id": "settlement-one", "status": "READY", "ttc_state": "INIT"}
            return {"task_id": "settlement-one", "readiness": {"preflight_passed": True}}
        if path.startswith("/trust-space/ttc/"):
            return {"task": deepcopy(self.settlements[path.rsplit("/", 1)[1]]), "allowed_actions": ["view", "transition:CANCELLED"]}
        raise AssertionError("Unexpected HTTP contract path: " + path)


def test_all_twelve_accounts_receive_two_distinct_typed_real_flow_jobs_and_separate_settlement():
    owner = FakeOwner()
    result = builder.prepare_owned_workflows(owner)
    assert result["failures"] == []
    assert result["query_execution_count"] == result["query_job_count"] == 24
    assert result["advance_settlement_count"] == 1
    assert len(owner.owned_query_tasks) == len(owner.owned_compute_jobs) == 24
    assert len([call for call in owner.calls if call[0] == "POST" and call[1].endswith("/approve")]) == 5
    for account, *_ in builder.PROFILES:
        fixture = owner.fixtures[account]
        assert len(fixture["task_candidates"]) == 2
        assert fixture["task"]["entity_type"] == "privacy_compute_job"
        assert fixture["task"]["job_id"] != fixture["task"]["task_id"]
        assert fixture["audit_task_id"] == fixture["task"]["task_id"]
    assert owner.fixtures["exchange"]["advance_task"]["entity_type"] == "settlement_task"
    assert not any(path.endswith("/run") or "/transitions" in path for _, path, *_ in owner.calls)


def test_manifest_excludes_confirmation_tokens_signatures_and_raw_bodies():
    owner = FakeOwner()
    result = builder.prepare_owned_workflows(owner)
    serialized = json.dumps(result)
    assert "memory-only-confirmation" not in serialized and "confirmation_token" not in serialized
    assert "node_signature" not in serialized and "raw_payload" not in serialized
    assert all(row["record_count"] == 12 for account in result["accounts"].values() for row in account["queries"])


@pytest.mark.parametrize("guard", ["flag", "preparing", "demo"])
def test_no_business_or_read_http_without_explicit_authorized_preparation(guard):
    owner = FakeOwner()
    if guard == "flag":
        owner.args.create_owned_workflows = False
    elif guard == "preparing":
        owner._preparing_workflows = False
    else:
        owner.actual_environment = "production"
    with pytest.raises(builder.WorkflowFixtureError):
        builder.prepare_owned_workflows(owner)
    assert owner.calls == []


def test_four_enterprises_use_actual_nonrequestable_visible_assets_as_denial_targets():
    owner = FakeOwner()
    result = builder.prepare_owned_workflows(owner)
    for account in ("coal", "heat", "gas", "oil"):
        target = owner.fixtures[account]["requestable_asset"]
        assert target["actions"]["can_request_usage"] is False
        assert target["fixture_basis"] == "VISIBLE_NON_REQUESTABLE_DENIAL_TARGET"
        assert result["accounts"][account]["application_fixture_basis"] == target["fixture_basis"]
    assert not any(call[1] == "/data/access-requests" and call[2] in {"coal", "heat", "gas", "oil"} for call in owner.calls)


def test_unavailable_external_resource_is_a_real_failure_and_no_fake_peer_is_created():
    owner = FakeOwner()
    owner.missing_requestable_account = "exchange_coal"
    result = builder.prepare_owned_workflows(owner)
    assert "exchange_coal" in result["failures"] and "task" not in owner.fixtures["exchange_coal"]
    assert result["query_execution_count"] == 22
    assert not any(call[1] == "/data/access-requests" and call[2] == "exchange_coal" for call in owner.calls)


def test_low_record_count_or_missing_visibility_does_not_claim_ready_prerequisites():
    for attribute in ("bad_result_account", "hidden_job_account"):
        owner = FakeOwner()
        setattr(owner, attribute, "generator")
        result = builder.prepare_owned_workflows(owner)
        assert "generator" in result["failures"] and "task" not in owner.fixtures["generator"]
        assert any(row["status"] == "FAIL" and row["account"] == "generator" for row in owner.checks)


@pytest.mark.parametrize("attribute", ["misbound_result_account", "misbound_receipt_account"])
def test_success_status_cannot_hide_another_query_or_request_item_receipt(attribute):
    owner = FakeOwner()
    setattr(owner, attribute, "generator")
    result = builder.prepare_owned_workflows(owner)
    assert "generator" in result["failures"] and "task" not in owner.fixtures["generator"]
    assert any(row["status"] == "FAIL" and row["account"] == "generator" for row in owner.checks)


def test_missing_audit_permission_is_preserved_as_a_real_denial_but_own_jobs_remain_ready():
    owner = FakeOwner()
    owner.denied_audit_account = "exchange_coal"
    owner.sessions["exchange_coal"]["user"]["permissions"] = []
    result = builder.prepare_owned_workflows(owner)
    assert result["failures"] == []
    assert owner.fixtures["exchange_coal"]["audit_access_basis"] == {"http_status": 403, "allowed": False, "code": "AUDIT_SCOPE_DENIED"}
    assert len(owner.fixtures["exchange_coal"]["task_candidates"]) == 2


def test_audit_authorized_applicant_cannot_hide_a_403_as_an_expected_permission_denial():
    owner = FakeOwner()
    owner.denied_audit_account = "regulator"
    result = builder.prepare_owned_workflows(owner)
    assert "regulator" in result["failures"]
    assert "task" not in owner.fixtures["regulator"]
