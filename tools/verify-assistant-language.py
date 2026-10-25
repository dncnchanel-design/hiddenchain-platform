"""Evaluate Chinese assistant questions through an explicitly demo loopback HTTP API.

Run backend/.venv/Scripts/python.exe -B tools/verify-assistant-language.py.
Use --self-check for an offline harness/corpus check, --matrix targeted for the
shorter 13-account matrix, or --group holdout to inspect independent paraphrases.
By default, POSTs after login only address this run's assistant sessions/plans.
--create-owned-requests explicitly enables unique run-owned authorization
fixtures and approval of those fixtures. Review envelopes must not change them.
--create-owned-workflows additionally prepares two real controlled queries per
business account and an INIT settlement through guarded normal APIs. Assistant
questions remain read-only or review-only. No backend/DB/Vault/browser access.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tools/assistant-language-cases.json"
spec = importlib.util.spec_from_file_location("deep_http_acceptance", ROOT / "tools/verify-deep-workflows.py")
assert spec is not None and spec.loader is not None
deep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deep)
require = deep.require
PREFIX = "/trust-space/assistant"
REMOTE_URL = "https://hiddenchain-platform-review.onrender.com"
ENTERPRISE = {"GENERATOR", "RETAILER", "COAL_ENTERPRISE", "HEAT_ENTERPRISE", "GAS_ENTERPRISE", "OIL_ENTERPRISE"}
ADMIN_ACTIONS = {"ASSISTANT_HELP", "SYSTEM_OVERVIEW"}
WRITE_ACTIONS = {"SUBMIT_USAGE_REQUEST", "APPROVE_USAGE_REQUEST", "REJECT_USAGE_REQUEST", "REVOKE_USAGE_AUTHORIZATION", "ADVANCE_TTC_STATE"}
LIST_ACTIONS = {"LIST_DATA_ASSETS", "LIST_VISIBLE_DATA_ASSETS", "LIST_AUTHORIZED_DATA_ASSETS", "LIST_AUTHORIZATIONS", "LIST_TASKS", "LIST_NOTIFICATIONS", "LIST_AUDIT_REPORTS"}
FORBIDDEN_KEYS = {"access_token", "refresh_token", "password", "password_hash", "private_key", "api_key", "data_ref", "payload_json", "raw_payload", "raw_records"}
INCOMPLETE = {"MODEL_UNAVAILABLE", "FIXTURE_UNAVAILABLE"}


def rows(payload: Any) -> list[dict[str, Any]]:
    return payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []


def identifiers(payload: Any) -> set[str]:
    # Notification/report DTOs also contain the related business entity/task.
    # Their own primary key must win; typed assistant rows use entity_id.
    return {str(row.get("notification_id") or row.get("report_id") or row.get("entity_id") or row.get("request_id") or row.get("job_id") or row.get("asset_id") or row.get("task_id")) for row in rows(payload)}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def assert_safe_output(value: Any) -> None:
    if isinstance(value, dict):
        require(not FORBIDDEN_KEYS.intersection(value), "Assistant output exposed a forbidden sensitive field")
        for child in value.values():
            assert_safe_output(child)
    elif isinstance(value, list):
        for child in value:
            assert_safe_output(child)


def model_unavailable(plan: dict[str, Any]) -> bool:
    codes = [str(plan.get("error_code", "")), str(plan.get("plan", {}).get("planner", ""))]
    codes.extend(str(step.get("error_code", "")) for step in plan.get("steps", []))
    return any(any(tag in code.upper() for tag in ("MODEL", "LLM", "CLASSIFIER")) and any(tag in code.upper() for tag in ("UNAVAILABLE", "NOT_CONFIGURED", "TIMEOUT", "FAILED")) for code in codes)


def cases_for(corpus: dict[str, Any], matrix: str, group: str, case_ids: set[str]) -> list[dict[str, Any]]:
    cases = [case for case in corpus["cases"] if group == "all" or case["group"] == group]
    if case_ids:
        return [case for case in cases if case["id"] in case_ids]
    if matrix == "full":
        return cases
    # One ordinary case per goal plus independent held-out goals makes a useful
    # shorter smoke run; the full run retains every paraphrase and write action.
    seen: set[str] = set()
    holdouts = {"holdout-own-inventory", "holdout-authorization", "holdout-task", "holdout-dont-approve", "holdout-injection", "holdout-electricity"}
    selected = []
    for case in cases:
        if case["group"] == "holdout" and case["id"] not in holdouts:
            continue
        if case["group"] == "common" and case["coverage"] in seen:
            continue
        selected.append(case)
        seen.add(case["coverage"])
    return selected


class LanguageAcceptance(deep.Acceptance):
    def __init__(self, base_url: str, output: Path, args: argparse.Namespace, corpus: dict[str, Any]):
        require(output.parent == ROOT / "runtime" or ROOT / "runtime" in output.parents, "Evidence must remain under PROJECT_ROOT/runtime")
        self.remote = base_url.rstrip("/") == REMOTE_URL
        if self.remote:
            require(bool(args.expected_sha and re.fullmatch(r"[0-9a-fA-F]{40}", args.expected_sha)), "Remote evaluation requires an explicit 40-hex --expected-sha")
        else:
            require(base_url.rstrip("/") == "http://127.0.0.1:8000", "Only the isolated loopback stack or exact authorized Render origin is supported")
        require(not args.proxy or args.proxy == "http://127.0.0.1:7897", "Only the explicitly authorized loopback 7897 HTTP proxy is supported")
        # Reuse the local helper's record/evidence initialization; replace its
        # unconnected client only after the stricter remote/proxy guards pass.
        super().__init__("http://127.0.0.1:8000", output, {"assistant-language"})
        self.client.close()
        self.client = deep.httpx.Client(base_url=base_url.rstrip("/") + "/api", timeout=40, trust_env=False, **({"proxy": args.proxy} if args.proxy else {}))
        self.args = args
        self.corpus = corpus
        self.fixtures: dict[str, dict[str, Any]] = {}
        self.planners: Counter[str] = Counter()
        self.model_sources: Counter[str] = Counter()
        self.model_calls = 0
        self.owned_sessions: set[str] = set()
        self.owned_requests: set[str] = set()
        self.owned_request_bindings: dict[str, dict[str, Any]] = {}
        self.owned_confirmations: dict[str, dict[str, Any]] = {}
        self.owned_query_tasks: set[str] = set()
        self.owned_compute_jobs: set[str] = set()
        self.owned_settlement_tasks: set[str] = set()
        self.initial_request_ids: set[str] = set()
        self.initial_query_task_ids: set[str] = set()
        self.initial_settlement_task_ids: set[str] = set()
        self.workflow_manifest: dict[str, Any] = {}
        self._preparing_workflows = False
        self.business_posts = 0
        self.last_observation: dict[str, Any] = {}
        self.last_references: dict[str, Any] = {}
        self.actual_environment: str | None = None
        self.demo_guard_passed = False
        self.selected_cases: list[dict[str, Any]] = []
        self.run_id = self.run_id.replace("deep-", "language-", 1)

    def call(self, path: str, account: str | None = None, body: Any = None, **kwargs: Any) -> Any:
        method = kwargs.get("method") or ("POST" if body is not None else "GET")
        workflow_post = False
        if method != "GET":
            require(method == "POST", "Harness only supports controlled assistant POSTs")
            assistant_post = path == PREFIX + "/sessions" and self._run_key(kwargs.get("key")) or any(path.startswith(f"{PREFIX}/sessions/{sid}/") for sid in self.owned_sessions)
            workflow_post = bool(getattr(self.args, "create_owned_workflows", False) and getattr(self, "_preparing_workflows", False))
            fixture_enabled = self.args.create_owned_requests or workflow_post
            fixture_create = path == "/data/access-requests" and isinstance(body, dict) and body.get("terms", {}).get("acceptance_run") == self.run_id and self._run_key(kwargs.get("key")) and account in getattr(self, "sessions", {}) and self._visible_asset(account, body.get("asset_id")) is not None
            request_id = next((request_id for request_id in self.owned_requests if path == f"/data/access-requests/{request_id}/approve"), None)
            binding = getattr(self, "owned_request_bindings", {}).get(request_id or "", {})
            fixture_approve = bool(request_id and isinstance(body, dict) and str(body.get("reason", "")).startswith(self.run_id) and self._run_key(kwargs.get("key")) and kwargs.get("match") is not None and account in self.sessions and binding.get("provider_org_id") == self.sessions[account]["user"]["org_id"])
            allowed_workflow = workflow_post and self._workflow_post_allowed(path, account, body, kwargs)
            require(assistant_post or self.demo_guard_passed and fixture_enabled and (fixture_create or fixture_approve) or allowed_workflow, "Harness attempted a mutation outside its own authorized records")
            if not assistant_post:
                self.business_posts += 1
        payload = super().call(path, account, body, **kwargs)
        if method == "POST" and isinstance(payload, dict) and payload.get("http_status", 200) < 400:
            self._register_owned_response(path, account, body, payload, workflow_post)
        if method == "GET" and workflow_post is False and getattr(self, "_preparing_workflows", False) and isinstance(payload, dict):
            query_id = next((query_id for query_id in self.owned_query_tasks if path == f"/trust-space/query/tasks/{query_id}/result"), None)
            if query_id and payload.get("http_status", 200) < 400:
                require(payload.get("task_id") == query_id and isinstance(payload.get("job_id"), str), "Owned query result changed its task/job binding")
                self.owned_compute_jobs.add(payload["job_id"])
                self.own(payload["job_id"])
        if isinstance(payload, dict) and isinstance(payload.get("plan"), dict) and "steps" in payload["plan"]:
            plan = payload["plan"]
            self.last_observation = {key: plan.get(key) for key in ("plan_id", "intent_code", "status", "allowed_actions")}
            self.last_observation["explanation"] = str(plan.get("plan", {}).get("explanation", ""))[:600]
            understanding = plan.get("plan", {}).get("understanding", {})
            self.last_observation["understanding"] = {key: understanding[key] for key in ("source", "model_used", "fallback_reason") if key in understanding}
            self.last_observation["steps"] = []
            for step in plan["steps"]:
                output = step.get("output", {})
                observed = {key: step.get(key) for key in ("action_code", "target_type", "target_id", "mode", "status", "error_code")}
                observed["output"] = {key: output[key] for key in ("status", "error_code", "raw_data_accessed", "total", "page_size", "navigation", "review_requested", "business_mutation") if key in output}
                if isinstance(output.get("items"), list):
                    observed["output"]["items"] = [{key: row[key] for key in ("entity_id", "entity_type", "asset_id", "version_id", "request_id", "notification_id", "report_id", "job_id", "task_id", "status", "access_basis", "authorization_id") if key in row} for row in output["items"]]
                self.last_observation["steps"].append(observed)
        elif method == "GET" and (isinstance(payload, list) or isinstance(payload, dict) and isinstance(payload.get("items"), list)):
            self.last_references[path] = {"ids": sorted(identifiers(payload)), "total": payload.get("total", len(rows(payload))) if isinstance(payload, dict) else len(payload)}
        return payload

    def _run_key(self, key: Any) -> bool:
        return isinstance(key, str) and key.startswith(self.run_id + "-")

    def _visible_asset(self, account: str, asset_id: str | None) -> dict[str, Any] | None:
        return next((asset for asset in rows(getattr(self, "fixtures", {}).get(account, {}).get("catalog", {})) if asset.get("asset_id") == asset_id), None)

    def _workflow_post_allowed(self, path: str, account: str | None, body: Any, options: dict[str, Any]) -> bool:
        if not self.demo_guard_passed or account not in self.sessions or not isinstance(body, dict) or not self._run_key(options.get("key")):
            return False
        if self.sessions[account]["user"]["role_code"] == "ADMIN":
            return False
        if path == "/trust-space/query/confirm":
            asset = self._visible_asset(account, body.get("asset_id"))
            if not asset or asset.get("provider", {}).get("org_id") != body.get("provider_org_id"):
                return False
            authorization_id = body.get("authorization_id")
            if authorization_id:
                binding = self.owned_request_bindings.get(authorization_id, {})
                return authorization_id in self.owned_requests and binding.get("account") == account and binding.get("asset_id") == body.get("asset_id") and binding.get("provider_org_id") == body.get("provider_org_id")
            return body.get("provider_org_id") == self.sessions[account]["user"]["org_id"] and asset.get("actions", {}).get("can_compute_own") is True
        if path == "/trust-space/query/execute":
            binding = self.owned_confirmations.get(body.get("authorization_id"), {})
            token = body.get("confirmation_token")
            condition = {key: value for key, value in body.items() if key != "confirmation_token"}
            return bool(binding.get("account") == account and isinstance(token, str) and hashlib.sha256(token.encode()).hexdigest() == binding.get("confirmation_token_hash") and digest(condition) == binding.get("condition_hash"))
        if path == "/settlement/tasks":
            session = self.sessions[account]
            return session["user"]["role_code"] == "EXCHANGE" and (session.get("org") or {}).get("energy_domain") == "electricity" and str(body.get("task_name", "")).startswith(self.run_id) and str(body.get("business_description", "")).startswith(self.run_id)
        return False

    def _register_owned_response(self, path: str, account: str | None, body: dict[str, Any], payload: dict[str, Any], workflow_post: bool) -> None:
        if path == "/data/access-requests":
            request_id = payload.get("request_id")
            require(isinstance(request_id, str) and request_id not in self.initial_request_ids, "Fixture creation returned a pre-existing request")
            asset = self._visible_asset(account, body.get("asset_id"))
            require(asset is not None and payload.get("applicant", {}).get("org_id") == self.sessions[account]["user"]["org_id"] and payload.get("provider", {}).get("org_id") == asset.get("provider", {}).get("org_id"), "Fixture request response changed its actual parties")
            require(payload.get("terms", {}).get("acceptance_run") == self.run_id, "Fixture request response is not owned by this run")
            self.owned_requests.add(request_id)
            self.own(request_id)
            self.owned_request_bindings[request_id] = {"account": account, "asset_id": body["asset_id"], "provider_org_id": asset["provider"]["org_id"]}
        elif workflow_post and path == "/trust-space/query/confirm":
            authorization_id, token = payload.get("authorization_id"), payload.get("confirmation_token")
            require(isinstance(authorization_id, str) and authorization_id not in self.initial_request_ids and isinstance(token, str) and bool(token), "Query confirmation did not issue a new run-owned binding")
            require(not body.get("authorization_id") or authorization_id == body["authorization_id"], "Query confirmation changed its owned authorization")
            condition = dict(body)
            for field in ("authorization_id", "provider_org_id", "asset_id"):
                if payload.get(field) is not None:
                    condition[field] = payload[field]
            require(condition.get("asset_id") == body.get("asset_id") and condition.get("provider_org_id") == body.get("provider_org_id"), "Query confirmation changed its actual target")
            self.owned_requests.add(authorization_id)
            self.own(authorization_id)
            self.owned_request_bindings.setdefault(authorization_id, {"account": account, "asset_id": condition["asset_id"], "provider_org_id": condition["provider_org_id"]})
            self.owned_confirmations[authorization_id] = {"account": account, "asset_id": condition["asset_id"], "provider_org_id": condition["provider_org_id"], "confirmation_token_hash": hashlib.sha256(token.encode()).hexdigest(), "condition_hash": digest(condition)}
        elif workflow_post and path == "/trust-space/query/execute":
            task_id = payload.get("task_id")
            require(isinstance(task_id, str) and task_id not in self.initial_query_task_ids, "Query execution returned a pre-existing task")
            self.owned_query_tasks.add(task_id)
            self.own(task_id)
        elif workflow_post and path == "/settlement/tasks":
            task_id = payload.get("task_id")
            require(isinstance(task_id, str) and task_id not in self.initial_settlement_task_ids, "Settlement creation returned a pre-existing task")
            self.owned_settlement_tasks.add(task_id)
            self.own(task_id)

    def save(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        statuses = dict(Counter(row["status"] for row in self.results))
        accounts = {account: {"role": session["user"]["role_code"], "status_counts": dict(Counter(row["status"] for row in self.results if row.get("account") == account)), "case_count": sum(row.get("account") == account and row["check"].startswith("assistant-language:") for row in self.results)} for account, session in self.sessions.items()}
        grouped = {group: dict(Counter(row["status"] for row in self.results if row.get("evidence", {}).get("group") == group)) for group in ("common", "holdout")}
        self.output.write_text(json.dumps({
            "run_id": self.run_id, "environment": self.actual_environment, "demo_guard_passed": self.demo_guard_passed, "base_url": str(self.client.base_url), "build": self.version,
            "required_build_sha": self.args.expected_sha, "required_build_sha_matched": self.version.get("build_sha") == self.args.expected_sha if self.args.expected_sha else None, "explicit_proxy_used": bool(self.args.proxy),
            "matrix": self.args.matrix, "group": self.args.group, "account_matrix_complete": len(self.sessions) == 13 and not self.args.accounts,
            "full_corpus_selected": self.args.matrix == "full" and self.args.group == "all" and not self.args.case,
            "planner_mode_declared": self.args.planner_mode, "planner_observations": dict(self.planners), "understanding_sources": dict(self.model_sources), "model_used_message_count": self.model_calls,
            "corpus_sha256": digest(self.corpus), "status_counts": statuses, "group_status_counts": grouped, "accounts": accounts,
            "workflow_preconditions": self.workflow_manifest,
            "all_expectations_met": bool(self.results) and not statuses.get("FAIL") and not any(statuses.get(status) for status in INCOMPLETE),
            "results": self.results,
            "boundary": {"own_run_records_only": True, "owned_assistant_records_only": not (self.args.create_owned_requests or getattr(self.args, "create_owned_workflows", False)), "owned_session_count": len(self.owned_sessions), "owned_request_count": len(self.owned_requests), "owned_requests_enabled": self.args.create_owned_requests, "owned_workflows_enabled": getattr(self.args, "create_owned_workflows", False), "owned_confirmation_count": len(self.owned_confirmations), "owned_query_task_count": len(self.owned_query_tasks), "owned_compute_job_count": len(self.owned_compute_jobs), "settlement_tasks_created": len(self.owned_settlement_tasks), "business_posts": self.business_posts, "calculations_executed": len(self.owned_query_tasks), "assistant_calculations_executed": 0, "database_accessed": False, "vault_accessed": False, "browser_used": False, "credentials_persisted": False, "tokens_persisted": False},
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(self, name: str, action: Any, **kwargs: Any) -> Any:
        self.last_observation, self.last_references = {}, {}
        started_at = datetime.now(timezone.utc).isoformat()
        result = super().check(name, action, **kwargs)
        self.results[-1]["started_at"] = started_at
        if name.startswith("assistant-language:"):
            case_id = name.split(":", 2)[2]
            case = next(case for case in self.corpus["cases"] if case["id"] == case_id)
            # The shared helper records exceptions without evidence. Retain the
            # corpus/group denominator for failures as well as successful cases.
            self.results[-1].setdefault("evidence", {}).update({"corpus_case": True, "case_id": case_id, "group": case["group"], "coverage": case["coverage"], "question": case["question"]})
            if self.results[-1]["status"] == "FAIL":
                self.results[-1]["evidence"].update({"observed_plan": self.last_observation, "http_reference_summaries": self.last_references})
            self.save()
        return result

    def reference_list(self, account: str, path: str) -> Any:
        """Read all official pages before comparing a differently sorted page."""
        payload = self.call(path, account)
        parsed = urlsplit(path)
        parameters = dict(parse_qsl(parsed.query))
        page_size = int(parameters.get("page_size", 100))
        collected = list(rows(payload))
        page = int(parameters.get("page", 1))
        total = payload.get("total") if isinstance(payload, dict) else None
        while (len(collected) < total if total is not None else len(rows(payload)) == page_size):
            require(page < 100, "Official reference list exceeds the harness's explicit 100-page budget")
            page += 1
            parameters["page"] = str(page)
            payload = self.call(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(parameters), parsed.fragment)), account)
            batch = rows(payload)
            require(batch or total is None, "Official reference pagination stopped before its declared total")
            collected.extend(batch)
        return {**payload, "items": collected, "total": total} if isinstance(payload, dict) else collected

    def setup(self) -> None:
        if getattr(self.args, "create_owned_workflows", False):
            require(not self.args.accounts, "Workflow preparation requires the complete coordinator account matrix")
        health = self.call("/health")
        self.actual_environment = str(health.get("environment", ""))[:30]
        require(health.get("environment") == "demo", "Evaluation requires explicit APP_ENV=demo before any authenticated operation")
        self.demo_guard_passed = True
        version = self.call("/version")
        self.version = {key: version[key] for key in ("build_sha", "version", "environment") if key in version}
        if self.args.expected_sha:
            require(version.get("build_sha") == self.args.expected_sha, "Server build SHA differs from the required SHA; no account login or mutation attempted")
        accounts = deep.seed_accounts()
        require(len(accounts) == 13, "Expected the complete 13-account seed matrix")
        for account, (password, role) in accounts.items():
            response = self.client.post("/auth/login", json={"username": account, "password": password})
            require(response.status_code == 200, f"Login failed for {account}: HTTP {response.status_code}")
            data = response.json()
            require(data["user"]["role_code"] == role, f"Wrong role for {account}")
            self.tokens[account] = data["access_token"]
            self.sessions[account] = {"user": data["user"], "org": data.get("org"), "menus": data["menus"]}
        if self.args.accounts:
            wanted = set(self.args.accounts.split(","))
            require(wanted <= self.sessions.keys(), "Unknown requested account")
            self.sessions = {account: session for account, session in self.sessions.items() if account in wanted}
        for account, session in self.sessions.items():
            if session["user"]["role_code"] == "ADMIN":
                self.fixtures[account] = {}
                continue
            org_id = session["user"]["org_id"]
            catalog = self.reference_list(account, "/trust-space/catalog?page_size=100")
            requests = self.reference_list(account, "/data/access-requests?page_size=100")
            tasks = self.reference_list(account, "/trust-space/ttc?page_size=100")
            self.initial_request_ids.update(row["request_id"] for row in rows(requests))
            self.initial_settlement_task_ids.update(row["task_id"] for row in rows(tasks))
            if getattr(self.args, "create_owned_workflows", False):
                computations = self.reference_list(account, "/trust-space/computations?page_size=100")
                self.initial_query_task_ids.update(row["task_id"] for row in rows(computations) if row.get("task_id"))
            own_assets = [asset for asset in rows(catalog) if asset.get("provider", {}).get("org_id") == org_id]
            task_rows = rows(tasks)
            task = next((row for row in task_rows if row.get("ttc_state") == "INIT"), task_rows[0] if task_rows else None)
            request_rows = rows(requests)
            request = next((row for row in request_rows if row.get("provider", {}).get("org_id") == org_id), request_rows[0] if request_rows else None)
            requestable = next((asset for asset in rows(catalog) if asset.get("actions", {}).get("can_request_usage") is True), None)
            fixture = {"catalog": catalog, "requests": requests, "tasks": tasks, "own_asset": own_assets[0] if own_assets else None, "asset": own_assets[0] if own_assets else rows(catalog)[0] if rows(catalog) else None, "requestable_asset": requestable, "request": request, "task": task}
            if task:
                task_id = task.get("task_id") or task.get("entity_id") or task.get("task", {}).get("task_id")
                if task_id:
                    fixture["task_detail"] = self.call(f"/trust-space/ttc/{quote(task_id, safe='')}", account)
            self.fixtures[account] = fixture
        if self.args.create_owned_requests:
            self.create_owned_requests()
        if getattr(self.args, "create_owned_workflows", False):
            self.prepare_owned_workflows()
        # The existing notification HTTP list delivers this user's outbox. Warm
        # that official read before comparing the assistant's deliberately pure
        # notification projection; no notification is marked read.
        for account, session in self.sessions.items():
            if session["user"]["role_code"] != "ADMIN":
                self.reference_list(account, "/trust-space/notifications?page_size=100")
        for account, fixture in self.fixtures.items():
            if self.sessions[account]["user"]["role_code"] not in ENTERPRISE:
                continue
            org_id = self.sessions[account]["user"]["org_id"]
            fixture["foreign_asset"] = next((other["asset"] for other in self.fixtures.values() if other.get("asset") and other["asset"].get("provider", {}).get("org_id") != org_id), None)

    def prepare_owned_workflows(self) -> None:
        require(self.demo_guard_passed and len(self.sessions) == 13 and not self.args.accounts, "Owned workflow preparation requires a guarded full coordinator")
        fixture_spec = importlib.util.spec_from_file_location("assistant_language_fixtures", ROOT / "tools/assistant-language-fixtures.py")
        require(fixture_spec is not None and fixture_spec.loader is not None, "Workflow fixture helper is unavailable")
        helper = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(helper)
        self._preparing_workflows = True
        try:
            manifest = helper.prepare_owned_workflows(self)
        finally:
            self._preparing_workflows = False
        self.validate_workflow_manifest(manifest)
        self.workflow_manifest = {**manifest, "required": True, "complete": True, "manifest_hash": digest(manifest)}
        for account, session in self.sessions.items():
            if session["user"]["role_code"] != "ADMIN":
                self.fixtures[account]["workflow_required"] = True

    def validate_workflow_manifest(self, manifest: dict[str, Any]) -> None:
        assert_safe_output(manifest)
        def safe_fields(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = str(key).lower()
                    require(not any(part in normalized for part in ("token", "password", "private_key", "raw_receipt")), "Workflow manifest contains a sensitive field")
                    require("signature" not in normalized or normalized.endswith(("_hash", "_status", "_verified")), "Workflow manifest contains signature content")
                    safe_fields(child)
            elif isinstance(value, list):
                for child in value:
                    safe_fields(child)
        safe_fields(manifest)
        business = {account for account, session in self.sessions.items() if session["user"]["role_code"] != "ADMIN"}
        require(not manifest.get("failures") and set(manifest.get("accounts", {})) == business, "Workflow preparation is incomplete")
        for account in business:
            fixture = self.fixtures[account]
            workflows = fixture.get("owned_workflows", [])
            require(digest(manifest["accounts"][account].get("queries")) == digest(workflows), "Manifest queries differ from the actual account fixtures")
            require(len(workflows) == 2 and len({row.get("job_id") for row in workflows}) == 2, "Workflow fixture needs two distinct real jobs per business account")
            for row in workflows:
                require(row.get("status") == "SUCCEEDED" and row.get("entity_type") == "privacy_compute_job" and row.get("entity_id") == row.get("job_id"), "Workflow fixture must bind a succeeded typed privacy job")
                require(row.get("task_id") in self.owned_query_tasks and row.get("job_id") in self.owned_compute_jobs and row.get("authorization_id") in self.owned_confirmations, "Workflow fixture does not belong to this run")
                require(self.owned_confirmations[row["authorization_id"]].get("account") == account, "Workflow confirmation belongs to another account")
            require(fixture.get("task", {}).get("entity_id") in {row["job_id"] for row in workflows}, "Task context is not bound to an owned job")
            if self.sessions[account]["user"]["role_code"] in {"EXCHANGE", "REGULATOR"} and "VIEW_AUDIT" in self.sessions[account]["user"].get("permissions", []):
                require(fixture.get("audit_detail", {}).get("http_status", 200) == 200 and bool(fixture.get("audit_detail")), "Own query receipt audit scope was not verified")
            negative = fixture.get("requestable_asset") or {}
            require(bool(negative), "Workflow preparation omitted the submission target")
            if negative.get("fixture_basis") == "VISIBLE_NON_REQUESTABLE_DENIAL_TARGET":
                actual = self._visible_asset(account, negative.get("asset_id"))
                require(actual is not None and actual.get("actions", {}).get("can_request_usage") is False and negative.get("actions", {}).get("can_request_usage") is False, "Negative submission fixture changed actual request capability")
        require(manifest.get("query_execution_count") == len(self.owned_query_tasks) == 24 and manifest.get("query_job_count") == len(self.owned_compute_jobs) == 24, "Owned workflow execution/job counts are incomplete")
        require(manifest.get("advance_settlement_count") == len(self.owned_settlement_tasks) == 1, "Owned INIT settlement fixture is incomplete")
        exchange = self.fixtures.get("exchange", {})
        require(exchange.get("advance_task", {}).get("entity_id") in self.owned_settlement_tasks and exchange.get("advance_task_detail", {}).get("task", {}).get("ttc_state") == "INIT", "Electricity operator needs its actual INIT settlement context")

    def create_owned_requests(self) -> None:
        created_orgs: set[str] = set()
        for provider, fixture in self.fixtures.items():
            provider_session = self.sessions[provider]
            org_id = provider_session["user"]["org_id"]
            if not fixture.get("own_asset") or org_id in created_orgs:
                continue
            domain = (provider_session.get("org") or {}).get("energy_domain")
            consumers = [account for account, session in self.sessions.items() if session["user"]["role_code"] != "ADMIN" and session["user"]["org_id"] != org_id and (session.get("org") or {}).get("energy_domain") == domain]
            consumers.sort(key=lambda account: self.sessions[account]["user"]["role_code"] != "EXCHANGE")
            if not consumers:
                self.check("owned-request-fixture:" + provider, lambda: {"_status": "FIXTURE_UNAVAILABLE", "reason": "No matching-domain applicant counterpart exists in the selected account matrix"}, account=provider)
                continue
            consumer = consumers[0]

            def create_pair(provider=provider, consumer=consumer, fixture=fixture, org_id=org_id):
                asset = self.reference(provider, "asset")
                own_created = []
                for label in ("pending", "approved"):
                    request = self.call("/data/access-requests", consumer, {
                        "asset_id": asset["asset"]["asset_id"], "asset_version_id": asset["current_version_id"],
                        "purpose": "SETTLEMENT_ANALYSIS", "usage_mode": "MPC_AGGREGATE",
                        "requested_scope": {"purpose_code": "SETTLEMENT_ANALYSIS", "algorithm_code": "CONTROLLED_SETTLEMENT_ANALYSIS_V1", "output_mode": "AGGREGATE_ONLY", "raw_data_export": False},
                        "requested_fields": ["summary", "quality_metrics"], "duration_days": 7,
                        "terms": {"accepted": True, "human_review_required": True, "output_mode": "AGGREGATE_ONLY", "raw_data_export": False, "acceptance_run": self.run_id, "acceptance_fixture": label},
                    }, key=self.key("owned-" + label))
                    self.owned_requests.add(request["request_id"])
                    self.own(request["request_id"])
                    if label == "approved":
                        request = self.call(f"/data/access-requests/{request['request_id']}/approve", provider, {"reason": self.run_id + " own revoke-review fixture"}, match=request["state_version"], key=self.key("owned-approve"))
                        for field in ("contract_id", "agreement_id"):
                            if request.get(field):
                                self.own(request[field])
                    kind = "request" if label == "pending" else "revoke_request"
                    for account, session in self.sessions.items():
                        if session["user"]["org_id"] == org_id or account == consumer and not self.fixtures[account].get("own_asset"):
                            self.fixtures[account][kind] = self.call(f"/data/access-requests/{request['request_id']}", account)
                    own_created.append({"request_id": request["request_id"], "status": request["status"]})
                created_orgs.add(org_id)
                return {"owned_requests": own_created, "provider_account": provider, "applicant_account": consumer, "matching_domain": domain, "existing_requests_changed": False}

            self.check("owned-request-fixture:" + provider, create_pair, account=provider, status="ACTUAL_SUCCESS")

    def target(self, account: str, kind: str) -> tuple[str | None, str | None]:
        fixture = self.fixtures[account].get(kind)
        if not fixture:
            return None, None
        if kind.endswith("asset"):
            return "data_asset", fixture.get("asset_id") or fixture.get("entity_id")
        if kind in {"request", "revoke_request"}:
            return "data_usage_request", fixture.get("request_id") or fixture.get("entity_id")
        if fixture.get("entity_type") and fixture.get("entity_id"):
            return fixture["entity_type"], fixture["entity_id"]
        return "settlement_task", fixture.get("task_id") or fixture.get("entity_id") or fixture.get("task", {}).get("task_id")

    def expected(self, account: str, case: dict[str, Any]) -> str:
        user = self.sessions[account]["user"]
        role, action = user["role_code"], case.get("action")
        if action and ((role == "ADMIN" and action not in ADMIN_ACTIONS) or (case.get("allowed_roles") and role not in case["allowed_roles"])):
            return "DENIAL"
        if case["expect"] != "REVIEW":
            return case["expect"]
        if action == "SUBMIT_USAGE_REQUEST":
            asset = self.fixtures[account].get(case.get("context", "asset")) or {}
            return "REVIEW" if asset.get("actions", {}).get("can_request_usage") is True else "DENIAL"
        request = self.fixtures[account].get("request") or {}
        parties = {request.get("applicant", {}).get("org_id"), request.get("provider", {}).get("org_id")}
        if action in {"APPROVE_USAGE_REQUEST", "REJECT_USAGE_REQUEST"}:
            return "REVIEW" if request.get("provider", {}).get("org_id") == user["org_id"] and "APPROVE_AUTHORIZATION" in user.get("permissions", []) else "DENIAL"
        if action == "REVOKE_USAGE_AUTHORIZATION":
            return "REVIEW" if user["org_id"] in parties else "DENIAL"
        if action == "ADVANCE_TTC_STATE":
            actions = self.fixtures[account].get(case.get("context", "task") + "_detail", {}).get("allowed_actions", [])
            return "REVIEW" if any(str(value).startswith("transition:") for value in actions) else "DENIAL"
        return "REVIEW"

    def session(self, account: str, kind: str | None) -> dict[str, Any]:
        entity_type, entity_id = self.target(account, kind) if kind else (None, None)
        created = self.call(PREFIX + "/sessions", account, {"page_path": "/trusted-space/workbench", "entity_type": entity_type, "entity_id": entity_id}, key=self.key("language-session"))
        self.owned_sessions.add(created["session_id"])
        self.own(created["session_id"])
        return created

    def message(self, account: str, session: dict[str, Any], content: str) -> dict[str, Any]:
        planned = self.call(f"{PREFIX}/sessions/{session['session_id']}/messages", account, {"content": content}, match=session["state_version"], key=self.key("language-message"))
        planner = planned.get("plan", {}).get("plan", {}).get("planner", "UNREPORTED")
        self.planners[str(planner)[:120]] += 1
        understanding = planned.get("plan", {}).get("plan", {}).get("understanding", {})
        self.model_sources[str(understanding.get("source", "UNREPORTED"))[:40]] += 1
        self.model_calls += int(understanding.get("model_used") is True)
        return planned

    def execute(self, account: str, planned: dict[str, Any]) -> dict[str, Any]:
        session, plan = planned["session"], planned["plan"]
        return self.call(f"{PREFIX}/sessions/{session['session_id']}/plans/{plan['plan_id']}/execute", account, {}, match=plan["state_version"])["plan"]

    def reference(self, account: str, kind: str) -> Any:
        target_type, target_id = self.target(account, kind)
        require(target_id, "Scoped target fixture is missing")
        path = {"data_asset": "/trust-space/assets/", "data_usage_request": "/data/access-requests/", "settlement_task": "/trust-space/ttc/", "privacy_compute_job": "/trust-space/computations/"}[target_type]
        return self.call(path + quote(target_id, safe=""), account)

    def validate_job_read(self, account: str, action: str, output: dict[str, Any]) -> dict[str, Any]:
        job_id = output["job_id"]
        detail = self.call("/trust-space/computations/" + quote(job_id, safe=""), account)
        job = detail["job"]
        require(job["job_id"] == job_id and job["task_id"] == output.get("task_id"), "Assistant job/query binding differs from its scoped native detail")
        if action == "CHECK_TTC_STATUS":
            require(output.get("status_value") == job["status"] and output.get("task_kind") == job.get("task_kind"), "Assistant task status/kind differs from the actual job")
            return {"native_job_reference_matched": True, "job_id": job_id, "task_id": job["task_id"], "job_status": job["status"]}
        require(job.get("task_kind") == "TRUSTED_QUERY" and output.get("task_kind") == "TRUSTED_QUERY", "Query receipt proof was applied to a different task kind")
        native = self.call("/trust-space/audit/tasks/" + quote(job["task_id"], safe=""), account)
        require(native["task"]["task_id"] == job["task_id"], "Native audit returned another query")
        native_receipts = {row["receipt_id"]: row for row in native.get("execution_receipts", [])}
        items = output.get("items", [])
        require(output.get("evidence_kind") == "EXECUTION_RECEIPT" and output.get("verification_status") == "MATCHED", "Completed query lacks matched execution receipt proof")
        require(native_receipts and isinstance(items, list) and {row.get("receipt_id") for row in items} == set(native_receipts), "Assistant receipt set differs from the actual scoped audit receipts")
        require(len(items) == len(native_receipts) == output.get("receipt_count"), "Assistant receipt count differs from the actual audit")
        for item in items:
            actual = native_receipts[item["receipt_id"]]
            require(not item.get("evidence_id") and item.get("evidence_kind") == "EXECUTION_RECEIPT", "Query receipt was mislabeled as blockchain evidence")
            require(item.get("verification_status") == "MATCHED" and item.get("verify", {}).get("matched") is True, "Assistant receipt did not actually verify")
            require(item.get("audit_event_verified") is True and actual.get("audit_event_verified") is True, "Query receipt audit event was not verified")
            require(all(item.get(field) == actual.get(field) and bool(actual.get(field)) for field in ("request_hash", "result_hash")), "Assistant receipt hashes differ from the actual native audit receipt")
            require(item["result_hash"] == job.get("output_hash") and actual.get("status") == item.get("status") == "CONFIRMED", "Receipt result/status does not bind to the successful computation")
        for field, native_field in (("audit_log_count", "audit_chain"), ("report_count", "reports"), ("evidence_count", "evidence")):
            require(output.get(field) == len(native.get(native_field, [])), "Assistant " + field + " differs from the scoped native audit")
        if action == "EXPLAIN_AUDIT":
            require(isinstance(output.get("explanation"), str) and bool(output["explanation"]), "Audit read omitted its explanation")
            if not native.get("reports"):
                require(output["report_count"] == 0 and "暂无正式审计报告" in output["explanation"], "Query receipt was represented as a formal audit report")
        return {"native_job_reference_matched": True, "native_query_audit_matched": True, "job_id": job_id, "task_id": job["task_id"], "receipt_count": len(items), "report_count": len(native.get("reports", [])), "verification_status": "MATCHED"}

    def validate_read(self, account: str, case: dict[str, Any], planned: dict[str, Any], expected_target: str | None = None) -> dict[str, Any]:
        plan = planned["plan"]
        require(plan["status"] == "READY", f"Expected READY read plan, got {plan['status']}")
        require(all(step.get("mode") == "READ" for step in plan["steps"]), "Read question created a non-read step")
        executed = self.execute(account, planned)
        if model_unavailable(executed):
            return {"_status": "MODEL_UNAVAILABLE", "plan_status": executed["status"]}
        require(executed["status"] == "SUCCEEDED", f"Read did not succeed: {executed['status']} / {[step.get('error_code') for step in executed['steps']]}")
        output = executed["steps"][0].get("output", {})
        assert_safe_output(output)
        require(output.get("raw_data_accessed") is False, "Read output must explicitly say raw_data_accessed=false")
        action = case["action"]
        evidence: dict[str, Any] = {"plan_status": executed["status"], "raw_data_accessed": False}
        if expected_target:
            actual_targets = {str(output.get(key)) for key in ("asset_id", "request_id", "task_id", "job_id", "report_id", "evidence_id")}
            require(expected_target in actual_targets, "Read output target differs from selected or contextual target")
            evidence["target_id"] = expected_target
        if output.get("job_id") and action in {"CHECK_TTC_STATUS", "VERIFY_EVIDENCE_SUMMARY", "EXPLAIN_AUDIT"}:
            evidence.update(self.validate_job_read(account, action, output))
        if action in LIST_ACTIONS:
            require(isinstance(output.get("items"), list) and isinstance(output.get("total"), int), "List read must return items and total")
            evidence.update({"returned": len(output["items"]), "total": output["total"]})
            if action != "LIST_DATA_ASSETS":
                for row in output["items"]:
                    require(all(key in row for key in ("entity_id", "entity_type", "label", "status", "href")), "Navigable list row is missing a contract field")
                    require(str(row["href"]).startswith("/trusted-space/"), "List row navigation escaped the controlled application")
            paths = {"LIST_DATA_ASSETS": "/trust-space/catalog?provider_org_id=" + quote(self.sessions[account]["user"]["org_id"], safe="") + "&page_size=20", "LIST_VISIBLE_DATA_ASSETS": "/trust-space/catalog?page_size=100", "LIST_AUTHORIZATIONS": "/data/access-requests?page_size=100", "LIST_NOTIFICATIONS": "/trust-space/notifications?page_size=100", "LIST_AUDIT_REPORTS": "/audit/reports?page_size=100"}
            if action in paths:
                reference = self.reference_list(account, paths[action])
                actual_ids, reference_ids = identifiers(output), identifiers(reference)
                require(actual_ids <= reference_ids, "Assistant list contains a record absent from the actual scoped HTTP list")
                require(len(actual_ids) == min(output["total"], int(output.get("page_size", 20))), "Assistant list omitted records inside its declared page")
                if isinstance(reference, dict) and "total" in reference:
                    require(output["total"] == reference["total"], "Assistant list total differs from scoped HTTP total")
                evidence["scoped_http_reference_matched"] = True
            if action == "LIST_TASKS":
                tasks = self.reference_list(account, "/trust-space/ttc?page_size=100")
                jobs = self.reference_list(account, "/trust-space/computations?page_size=100")
                allowed_ids = identifiers(tasks) | identifiers(jobs)
                # Computation DTOs also carry parent task IDs; include their job
                # IDs explicitly so this check cannot conflate task and job IDs.
                allowed_ids.update(str(row["job_id"]) for row in rows(jobs) if row.get("job_id"))
                require(identifiers(output) <= allowed_ids, "Task list returned an entity outside both scoped HTTP lists")
                evidence["scoped_http_reference_matched"] = True
            if action == "LIST_AUTHORIZED_DATA_ASSETS":
                catalog = self.reference_list(account, "/trust-space/catalog?page_size=100")
                requests = self.reference_list(account, "/data/access-requests?page_size=100")
                org_id = self.sessions[account]["user"]["org_id"]
                own_eligible = {row["asset_id"] for row in rows(catalog) if row.get("actions", {}).get("can_compute_own") and row.get("status") == "ACTIVE" and (row.get("latest_version") or {}).get("status") == "ACTIVE"}
                usable_grants = {row.get("asset_id") or row.get("asset", {}).get("asset_id") for row in rows(requests) if (row.get("asset_id") or row.get("asset", {}).get("asset_id")) and row.get("applicant", {}).get("org_id") == org_id and row.get("status") == "APPROVED" and (row.get("usage_budget") or {}).get("usable") is True}
                require(identifiers(output) <= own_eligible | usable_grants, "Authorized-data list claimed use without own eligibility or an active usable applicant grant")
                require(len(output["items"]) == min(output["total"], int(output.get("page_size", 20))), "Authorized-data list omitted records inside its page")
                if output["total"] <= len(output["items"]):
                    require(own_eligible <= identifiers(output), "Authorized-data list omitted compute-eligible own data")
                evidence.update({"own_compute_eligible_count": len(own_eligible), "active_usable_grant_asset_count": len(usable_grants), "authorization_http_reference_checked": True})
            if action == "LIST_DATA_ASSETS":
                require(output.get("organization_id") == self.sessions[account]["user"]["org_id"], "Own catalog escaped current organization")
        if case["expect"] == "NAVIGATION":
            navigation = output.get("navigation", {})
            path = str(navigation.get("path", ""))
            require(path.startswith("/trusted-space/") or action == "NAVIGATE_ELECTRICITY" and path == "#electricity", "Calculation question lacks controlled navigation")
            require(isinstance(navigation.get("question"), str) and bool(navigation["question"]), "Navigation must carry the original question")
            require(not any(key in output for key in ("result", "calculated_result", "settlement_amount", "official_result")), "Navigation returned an unrequested calculation result")
            evidence["navigation_path"] = navigation["path"]
            evidence["calculation_executed"] = False
        return evidence

    def evaluate(self, account: str, case: dict[str, Any]) -> dict[str, Any]:
        if case.get("action") == "ADVANCE_TTC_STATE" and self.fixtures[account].get("advance_task"):
            case = {**case, "context": "advance_task"}
        if case.get("action") == "REVOKE_USAGE_AUTHORIZATION" and self.fixtures[account].get("revoke_request"):
            case = {**case, "context": "revoke_request"}
        expected = self.expected(account, case)
        evidence: dict[str, Any] = {"corpus_case": True, "case_id": case["id"], "group": case["group"], "coverage": case["coverage"], "question": case["question"], "expected": expected}
        needed = case.get("requires") or case.get("context")
        role = self.sessions[account]["user"]["role_code"]
        intrinsic_denial = role == "ADMIN" and case.get("action") not in ADMIN_ACTIONS or bool(case.get("allowed_roles") and role not in case["allowed_roles"])
        if needed and not self.target(account, needed)[1] and not intrinsic_denial:
            require(not self.fixtures[account].get("workflow_required") and not getattr(self.args, "create_owned_workflows", False), "Required owned workflow target is missing: " + needed)
            return {**evidence, "_status": "FIXTURE_UNAVAILABLE", "missing_scoped_fixture": needed}
        values = {"asset_id": self.target(account, "asset")[1] or "asset-language-missing", "foreign_asset_id": self.target(account, "foreign_asset")[1] or "asset-language-missing"}
        question = case["question"].format(**values)
        before = self.reference(account, case["context"]) if expected == "REVIEW" else None
        planned = self.message(account, self.session(account, case.get("context")), question)
        plan = planned["plan"]
        evidence.update({"intent": plan.get("intent_code"), "plan_status": plan.get("status"), "error_codes": [step.get("error_code") for step in plan.get("steps", []) if step.get("error_code")]})
        understanding = plan.get("plan", {}).get("understanding", {})
        evidence.update({"understanding_source": understanding.get("source", "UNREPORTED"), "model_used": understanding.get("model_used") is True})
        if understanding.get("fallback_reason"):
            evidence["fallback_reason"] = str(understanding["fallback_reason"])[:100]
        if model_unavailable(plan):
            return {**evidence, "_status": "MODEL_UNAVAILABLE"}
        if expected in {"CLARIFY", "SAFE_BLOCK"}:
            require(plan["status"] in ({"NEEDS_INPUT"} if expected == "CLARIFY" else {"NEEDS_INPUT", "BLOCKED"}), "Unsupported/ambiguous input was actionable")
            require(not {"execute", "retry"}.intersection(plan.get("allowed_actions", [])), "Unsupported/ambiguous input offered execution or retry")
            require(not any(step.get("request_id") or step.get("invocation_id") for step in plan.get("steps", [])), "Unsupported/ambiguous input created a tool or review invocation")
            return {**evidence, "_status": "EXPECTED_CLARIFICATION" if expected == "CLARIFY" else "EXPECTED_SAFE_BLOCK"}
        expected_action = case["action"]
        pending = plan.get("plan", {}).get("pending_action")
        pending_action = pending.get("action_code") if isinstance(pending, dict) else pending
        actual_actions = {plan.get("intent_code"), pending_action} | {step.get("action_code") for step in plan.get("steps", [])}
        require(expected_action in actual_actions, f"Expected {expected_action}, got {plan.get('intent_code')}")
        if expected == "SELECT":
            require(plan["status"] == "NEEDS_INPUT", "Missing/incompatible target must ask for a selection")
            require(not {"execute", "retry"}.intersection(plan.get("allowed_actions", [])), "Selection plan offered execution or retry")
            candidates = plan.get("plan", {}).get("candidates", [])
            require(isinstance(candidates, list), "Selection candidates must be a list")
            require(all(all(key in row for key in ("entity_id", "entity_type", "label", "status")) for row in candidates), "Selection candidate is missing typed metadata")
            evidence.update({"initial_outcome": "NEEDS_SELECTION", "candidate_count": len(candidates)})
            if not case.get("followup"):
                return {**evidence, "_status": "NEEDS_SELECTION"}
            index = 1 if case["followup"] == "second" else 0
            if case["followup"] == "label":
                label_counts = Counter(row["label"] for row in candidates)
                index = next((position for position, row in enumerate(candidates) if label_counts[row["label"]] == 1), index)
            if len(candidates) <= index:
                require(not self.fixtures[account].get("workflow_required") and not getattr(self.args, "create_owned_workflows", False), "Required owned selection candidate is missing")
                return {**evidence, "_status": "FIXTURE_UNAVAILABLE", "missing_scoped_fixture": "selection_candidate_" + str(index + 1)}
            selected = candidates[index]
            if case["followup"] == "label" and sum(row["label"] == selected["label"] for row in candidates) != 1:
                require(not self.fixtures[account].get("workflow_required") and not getattr(self.args, "create_owned_workflows", False), "Required owned selection label is ambiguous")
                return {**evidence, "_status": "FIXTURE_UNAVAILABLE", "missing_scoped_fixture": "unique_candidate_label"}
            followup = selected["label"] if case["followup"] == "label" else "第二个" if index else "第一个"
            continued = self.message(account, planned["session"], followup)
            require(continued["plan"]["intent_code"] == expected_action, "Selection followup lost pending action")
            evidence.update(self.validate_read(account, case, continued, selected["entity_id"]))
            return {**evidence, "followup_kind": case["followup"], "_status": evidence.get("_status", "ACTUAL_SUCCESS")}
        if expected == "DENIAL":
            if plan["status"] == "READY":
                plan = self.execute(account, planned)
            require(plan["status"] == "BLOCKED", "Unauthorized question did not remain blocked")
            error_codes = [str(step.get("error_code") or step.get("output", {}).get("error_code") or "") for step in plan.get("steps", [])]
            require(any(code == "PROVIDER_REVIEW_REQUIRED" or any(tag in code for tag in ("DENIED", "FORBIDDEN", "PERMISSION", "ROLE_REQUIRED")) for code in error_codes), "Blocked result did not establish a permission denial")
            require(not any(step.get("request_id") for step in plan.get("steps", [])), "Unauthorized question created a review envelope")
            if case.get("action") == "SUBMIT_USAGE_REQUEST" and self.fixtures[account].get(case.get("context"), {}).get("fixture_basis") == "VISIBLE_NON_REQUESTABLE_DENIAL_TARGET":
                require("REQUEST_SCOPE_DENIED" in error_codes, "Real non-requestable asset must produce the precise request-scope denial")
                evidence["fixture_basis"] = "VISIBLE_NON_REQUESTABLE_DENIAL_TARGET"
            if case.get("action") == "ADVANCE_TTC_STATE" and self.target(account, case.get("context", "task"))[0] == "privacy_compute_job" and role != "ADMIN":
                code = "COMPUTE_TRANSITION_DENIED" if role in {"EXCHANGE", "REGULATOR"} else "ASSISTANT_ROLE_DENIED"
                require(code in error_codes, "Query job must produce the precise role/unsupported-transition denial")
            return {**evidence, "plan_status": plan["status"], "error_codes": error_codes, "_status": "EXPECTED_PERMISSION_DENIAL"}
        if expected == "REVIEW":
            require(plan["status"] == "PENDING_REVIEW", "Authorized write must produce a review envelope")
            require(all(step.get("mode") == "WRITE" for step in plan["steps"]), "Write plan has an unexpected mode")
            executed = self.execute(account, planned)
            output = executed["steps"][0].get("output", {})
            require(executed["status"] == "PENDING_REVIEW" and output.get("review_requested") is True and output.get("business_mutation") is False, "Write was not review-only")
            require(digest(before) == digest(self.reference(account, case["context"])), "Review envelope changed a business target DTO")
            return {**evidence, "_status": "REVIEW_ONLY", "review_requested": True, "business_mutation": False, "target_dto_unchanged": True}
        target_id = self.target(account, case["context"])[1] if case.get("context") else values["asset_id"] if case.get("requires") == "asset" else None
        evidence.update(self.validate_read(account, case, planned, target_id))
        return {**evidence, "_status": evidence.get("_status", "ACTUAL_SUCCESS")}

    def run_cases(self) -> None:
        self.selected_cases = cases_for(self.corpus, self.args.matrix, self.args.group, set(self.args.case or []))
        require(self.selected_cases, "No corpus cases matched")
        for account, session in self.sessions.items():
            role = session["user"]["role_code"]
            self.check("assistant-tools:" + account, lambda account=account: {"tool_count": len(rows(self.call(PREFIX + "/tools", account)))}, account=account, status="ACTUAL_SUCCESS")
            for case in self.selected_cases:
                if case.get("roles") and not (role in case["roles"] or "ENTERPRISE" in case["roles"] and role in ENTERPRISE):
                    continue
                self.check("assistant-language:" + account + ":" + case["id"], lambda account=account, case=case: self.evaluate(account, case), account=account, status="ACTUAL_SUCCESS")
        if self.args.planner_mode == "model-configured" and not self.model_calls:
            self.check("planner-mode:model-configured", lambda: {"_status": "MODEL_UNAVAILABLE", "reason": "No successful model planner was observed; deterministic fallback does not verify configured model classification."})
        if self.args.planner_mode == "offline":
            self.check("planner-mode:offline", lambda: require(self.model_calls == 0, "Model classification was used in a declared offline run") or {"model_used_message_count": 0}, status="ACTUAL_SUCCESS")


def self_check(corpus: dict[str, Any]) -> None:
    cases = corpus["cases"]
    require(len({case["id"] for case in cases}) == len(cases), "Duplicate corpus case IDs")
    require({"common", "holdout"} == {case["group"] for case in cases}, "Both ordinary and independent holdout groups are required")
    require(all(case["question"] and case["expect"] in {"READ", "NAVIGATION", "REVIEW", "SELECT", "DENIAL", "CLARIFY", "SAFE_BLOCK"} for case in cases), "Invalid corpus case")
    require({case.get("action") for case in cases} >= LIST_ACTIONS | WRITE_ACTIONS | ADMIN_ACTIONS | {"NAVIGATE_QUERY", "NAVIGATE_ELECTRICITY"}, "Corpus misses a declared action")
    require(len(cases_for(corpus, "targeted", "all", set())) >= 12, "Targeted matrix is too small")
    require(len(deep.seed_accounts()) == 13, "Expected 13 existing seed accounts")
    require(model_unavailable({"steps": [{"error_code": "ASSISTANT_MODEL_UNAVAILABLE"}]}), "Model failure classifier self-check failed")
    require(not model_unavailable({"plan": {"planner": "LOCAL_REAL_DETERMINISTIC"}}), "Offline deterministic planner is not a model outage")
    assert_safe_output({"raw_data_accessed": False, "items": [{"entity_id": "synthetic"}]})
    try:
        assert_safe_output({"nested": {"access_token": "synthetic"}})
    except deep.CheckFailure:
        pass
    else:
        raise deep.CheckFailure("Sensitive output check did not reject a token field")
    probe = object.__new__(LanguageAcceptance)
    probe.args = argparse.Namespace(create_owned_requests=False)
    probe.demo_guard_passed = False
    probe.owned_sessions, probe.owned_requests = set(), set()
    probe.run_id, probe.business_posts = "synthetic-self-check", 0
    try:
        probe.call("/data/access-requests", "synthetic", {"terms": {"acceptance_run": probe.run_id}}, key=probe.run_id)
    except deep.CheckFailure:
        pass
    else:
        raise deep.CheckFailure("Default mutation guard allowed a business POST")
    probe.sessions = {"synthetic": {"user": {"role_code": "ADMIN", "org_id": "synthetic", "permissions": []}}}
    probe.fixtures = {"synthetic": {}}
    require(probe.expected("synthetic", {"action": "LIST_DATA_ASSETS", "expect": "READ"}) == "DENIAL", "Admin business boundary self-check failed")
    require(probe.expected("synthetic", {"action": "SYSTEM_OVERVIEW", "expect": "READ", "allowed_roles": ["ADMIN"]}) == "READ", "Admin operations self-check failed")
    require(identifiers({"items": [{"notification_id": "notification-own", "entity_id": "request-related"}]}) == {"notification-own"}, "Notification primary-key self-check failed")
    require(identifiers([{"report_id": "report-own", "task_id": "task-related"}]) == {"report-own"}, "Audit report primary-key self-check failed")
    pages = iter(({"items": [{"entity_id": "first"}], "total": 2}, {"items": [{"entity_id": "second"}], "total": 2}))
    probe.call = lambda *_args, **_kwargs: next(pages)
    require(identifiers(probe.reference_list("synthetic", "/synthetic?page_size=1")) == {"first", "second"}, "Official reference pagination self-check failed")
    for base_url, expected_sha, proxy in ((REMOTE_URL, None, None), ("https://example.com", "a" * 40, None), ("http://127.0.0.1:8000", None, "http://127.0.0.1:9999")):
        try:
            LanguageAcceptance(base_url, ROOT / "runtime/self-check-not-written.json", argparse.Namespace(expected_sha=expected_sha, proxy=proxy), corpus)
        except deep.CheckFailure:
            pass
        else:
            raise deep.CheckFailure("Origin/SHA/proxy guard accepted an invalid environment")
    print(json.dumps({"self_check": "PASS", "seed_account_count": 13, "case_count": len(cases), "holdout_count": sum(case["group"] == "holdout" for case in cases)}, ensure_ascii=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--expected-sha", help="Required exact 40-hex deployed build SHA for authorized Render evaluation")
    parser.add_argument("--proxy", help="Optional explicit http://127.0.0.1:7897 proxy; environment proxy settings are ignored")
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/assistant-language-acceptance.json")
    parser.add_argument("--matrix", choices=("full", "targeted"), default="full")
    parser.add_argument("--group", choices=("all", "common", "holdout"), default="all")
    parser.add_argument("--planner-mode", choices=("auto", "offline", "model-configured"), default="auto", help="Expected environment mode; this flag never changes server configuration")
    parser.add_argument("--accounts", help="Optional comma-separated subset; evidence marks the matrix incomplete")
    parser.add_argument("--create-owned-requests", action="store_true", help="Explicitly create matching-domain run-owned pending/approved authorization fixtures; default performs no business POSTs")
    parser.add_argument("--create-owned-workflows", action="store_true", help="Explicit full-coordinator demo preparation: execute two normal controlled queries per business account and create one INIT settlement")
    parser.add_argument("--case", action="append", help="Run a case ID; repeat to select several cases")
    parser.add_argument("--self-check", action="store_true", help="Check corpus/harness without network calls or evidence writes")
    args = parser.parse_args()
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    self_check(corpus)
    if args.self_check:
        return 0
    acceptance = LanguageAcceptance(args.base_url, args.output.resolve(), args, corpus)
    try:
        acceptance.setup()
        acceptance.run_cases()
    except Exception as error:
        acceptance.check("harness-setup", lambda: (_ for _ in ()).throw(error))
    finally:
        acceptance.save()
        acceptance.client.close()
    counts = Counter(row["status"] for row in acceptance.results)
    print(json.dumps({"output": str(acceptance.output), "status_counts": dict(counts)}, ensure_ascii=True))
    return 1 if counts["FAIL"] else 2 if any(counts[status] for status in INCOMPLETE) else 0


if __name__ == "__main__":
    raise SystemExit(main())
