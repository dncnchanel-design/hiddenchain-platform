"""Exercise shipped HTTP contracts on an isolated, explicitly demo loopback stack.

Run with backend/.venv/Scripts/python.exe -B tools/verify-deep-workflows.py.
Only this run's requests, sessions, and settlement tasks are mutated. No CSV,
database connection, raw payload, global policy, or deployment operation is used.
Browser-only interactions are listed in the companion acceptance document.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable
from urllib.parse import quote, urlparse
import uuid

import httpx


ROOT = Path(__file__).resolve().parents[1]
AREAS = {"accounts", "authorization", "contract", "settlement", "assistant", "electricity", "queries", "own-queries", "notifications"}
FUNCTIONS = ("sum", "average", "max", "min", "count", "median", "growth_rate", "yoy", "mom", "group_by", "threshold", "trend", "psi", "mpc_aggregation")
UI_QUERY_FUNCTIONS = {"sum", "average", "max", "min", "count", "trend"}


class CheckFailure(AssertionError):
    pass


def require(condition: Any, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def seed_accounts() -> dict[str, tuple[str, str]]:
    """Read existing local fixture credentials; never copy them to evidence."""
    tree = ast.parse((ROOT / "backend/app/seed.py").read_text(encoding="utf-8"))
    rows = next(node.value.elts for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "USERS" for target in node.targets))
    return {ast.literal_eval(row.elts[2]): (ast.literal_eval(row.elts[3]), ast.literal_eval(row.elts[5])) for row in rows}


class Acceptance:
    def __init__(self, base_url: str, output: Path, areas: set[str]):
        parsed = urlparse(base_url)
        require(parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port == 8000, "Only the authorized isolated http://127.0.0.1:8000 stack is supported")
        require(output == ROOT or ROOT in output.parents, "Evidence path must remain inside PROJECT_ROOT")
        require(output.suffix.lower() == ".json" and not output.is_dir(), "Evidence output must be a JSON file")
        self.output = output
        self.areas = areas
        self.run_id = "deep-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:7]
        self.client = httpx.Client(base_url=base_url.rstrip("/") + "/api", timeout=40, trust_env=False)
        self.tokens: dict[str, str] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.results: list[dict[str, Any]] = []
        self.owned: set[str] = set()
        self.calls: list[dict[str, Any]] = []
        self.counter = 0
        self.query_results: dict[str, dict[str, Any]] = {}
        self.query_grant: dict[str, Any] | None = None
        self.settlement_task: dict[str, Any] | None = None
        self.version: dict[str, Any] = {}

    def key(self, label: str) -> str:
        self.counter += 1
        return f"{self.run_id}-{label}-{self.counter}"

    def call(self, path: str, account: str | None = None, body: Any = None, *, method: str | None = None, match: Any = None, key: str | None = None, expected: tuple[int, ...] = (200, 201, 202, 204)) -> Any:
        headers = {}
        if account:
            headers["Authorization"] = "Bearer " + self.tokens[account]
        if match is not None:
            headers["If-Match"] = f'"{match}"'
        if key:
            headers["Idempotency-Key"] = key
        response = self.client.request(method or ("POST" if body is not None else "GET"), path, json=body, headers=headers)
        # Never persist request bodies, headers, credentials, signatures, or tokens.
        self.calls.append({"method": response.request.method, "path": path, "account": account, "http_status": response.status_code})
        if response.status_code not in expected:
            detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
            code = detail.get("code", "") if isinstance(detail, dict) else ""
            raise CheckFailure(f"{response.request.method} {path}: HTTP {response.status_code} {code}; expected {expected}")
        if not response.content:
            return None
        payload = response.json()
        if response.status_code >= 400:
            return {"http_status": response.status_code, "detail": payload.get("detail")}
        return payload

    def save(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        counts = dict(Counter(item["status"] for item in self.results))
        payload = {"run_id": self.run_id, "environment": "demo", "base_url": str(self.client.base_url), "build": self.version, "status_counts": counts, "results": self.results, "boundary": {"own_run_records_only": True, "csv_uploaded": False, "database_accessed": False, "global_policy_changed": False, "browser_interactions_verified": False}}
        self.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(self, name: str, action: Callable[[], dict[str, Any]], *, account: str | None = None, ui: str = "CURRENT_UI", status: str = "PASS") -> dict[str, Any] | None:
        self.calls = []
        started = time.monotonic()
        try:
            evidence = action()
            actual_status = evidence.pop("_status", status)
            item = {"check": name, "status": actual_status, "account": account, "ui_surface": ui, "evidence": evidence}
        except Exception as error:
            item = {"check": name, "status": "FAIL", "account": account, "ui_surface": ui, "error": f"{type(error).__name__}: {str(error)[:400]}"}
            evidence = None
        item["http_calls"] = self.calls
        item["elapsed_seconds"] = round(time.monotonic() - started, 3)
        self.results.append(item)
        self.save()
        print(json.dumps({"check": name, "status": item["status"], **({"error": item["error"]} if "error" in item else {})}, ensure_ascii=True), flush=True)
        return evidence

    def own(self, value: str) -> str:
        self.owned.add(value)
        return value

    def asset(self, asset_id: str, account: str = "generator") -> dict[str, Any]:
        return self.call(f"/trust-space/assets/{quote(asset_id, safe='')}", account)

    def request(self, *, approve: bool = False, scope: dict[str, Any] | None = None, consumer: str = "generator", asset_id: str = "asset-electricity-load") -> dict[str, Any]:
        asset = self.asset(asset_id, consumer)
        regulatory = consumer == "regulator"
        purpose = "REGULATORY_CROSS_ENERGY_REVIEW" if regulatory else "SETTLEMENT_ANALYSIS"
        created = self.call("/data/access-requests", consumer, {
            "asset_id": asset["asset"]["asset_id"], "asset_version_id": asset["current_version_id"],
            "purpose": purpose, "usage_mode": "MPC_AGGREGATE",
            "requested_scope": {"purpose_code": purpose, "algorithm_code": f"CONTROLLED_{purpose}_V1", "output_mode": "AGGREGATE_ONLY", "raw_data_export": False, **(scope or {})},
            "requested_fields": ["summary", "quality_metrics"], "duration_days": 7,
            "terms": {"accepted": True, "human_review_required": True, "output_mode": "AGGREGATE_ONLY", "raw_data_export": False, "acceptance_run": self.run_id, **({"regulatory_basis": "ENERGY_REGULATION", "authority_ref": self.run_id} if regulatory else {})},
        }, key=self.key("usage"))
        self.own(created["request_id"])
        if approve:
            provider = next(account for account, session in self.sessions.items() if session["user"]["org_id"] == created["provider"]["org_id"])
            created = self.call(f"/data/access-requests/{created['request_id']}/approve", provider, {"reason": self.run_id + " isolated acceptance approval"}, match=created["state_version"], key=self.key("approve"))
            for field in ("contract_id", "agreement_id"):
                if created.get(field):
                    self.own(created[field])
        return created

    def setup(self) -> None:
        health = self.call("/health")
        require(health.get("environment") == "demo", "Mutation checks require explicit APP_ENV=demo")
        self.version = self.call("/version")
        # Keep only public release metadata.
        self.version = {key: self.version[key] for key in ("build_sha", "version", "environment") if key in self.version}
        for account, (password, role) in seed_accounts().items():
            response = self.client.post("/auth/login", json={"username": account, "password": password})
            require(response.status_code == 200, f"Login failed for {account}: HTTP {response.status_code}")
            data = response.json()
            require(data["user"]["role_code"] == role, f"Wrong role for {account}")
            self.tokens[account] = data["access_token"]
            self.sessions[account] = {"user": data["user"], "org": data.get("org"), "menus": data["menus"]}

    def accounts(self) -> None:
        for account in self.sessions:
            def check_account(account=account):
                session = self.sessions[account]
                if account == "admin":
                    for path in ("/admin/overview", "/admin/system", "/admin/agents", "/metrics/summary", "/audit/logs"):
                        self.call(path, account)
                    denied = self.call("/trust-space/catalog", account, expected=(403,))
                    return {"management_endpoints": 5, "business_denied": denied["http_status"], "account_edit_ui": "NOT_PRESENT"}
                context = self.call("/trust-space/context", account)
                identity = self.call("/trust-space/identity", account)
                directory = self.call("/trust-space/identities", account)
                did = identity["did"]["did_id"]
                self.call(f"/trust-space/identity/{quote(did, safe='')}/document", account)
                require(context["actor"]["username"] == account, "Actor mismatch")
                require(context["current_subject"]["org_id"] == session["user"]["org_id"], "Organization mismatch")
                return {"role": session["user"]["role_code"], "menu_count": len(session["menus"]), "identity_directory_count": directory["total"], "did_document_read": True}
            self.check(f"account-scope:{account}", check_account, account=account)

    def authorizations(self) -> None:
        holder: dict[str, Any] = {}
        def review():
            request = self.request()
            reviewed = self.call(f"/data/access-requests/{request['request_id']}/review", "retailer", {"note": self.run_id + " review"}, match=request["state_version"])
            require(reviewed["status"] == "UNDER_REVIEW", "Review did not persist")
            holder["review"] = reviewed
            return {"request_id": reviewed["request_id"], "status": reviewed["status"]}
        self.check("authorization:review", review, account="retailer")
        def reject():
            request = holder.get("review") or self.request()
            rejected = self.call(f"/data/access-requests/{request['request_id']}/reject", "retailer", {"reason": self.run_id + " reject"}, match=request["state_version"])
            require(rejected["status"] == "REJECTED", "Reject did not persist")
            return {"request_id": rejected["request_id"], "status": rejected["status"]}
        self.check("authorization:reject", reject, account="retailer")
        def outbound_action():
            request = self.request()
            displayed = self.call(f"/data/access-requests/{request['request_id']}", "generator")
            holder["withdraw"] = displayed
            action = "withdraw" if "withdraw" in displayed["actions"] else "revoke"
            response = self.call(f"/data/access-requests/{request['request_id']}/{action}", "generator", {"reason": self.run_id + " outbound UI action"}, match=displayed["state_version"], expected=(200, 403))
            require(response.get("status") == "REVOKED", f"UI-emitted action {action} failed with HTTP {response.get('http_status')}; DTO actions={displayed['actions']}")
            holder["withdraw"] = response
            return {"request_id": request["request_id"], "emitted_action": action, "status": response["status"]}
        self.check("authorization:actual-outbound-ui-action", outbound_action, account="generator")
        def withdraw():
            request = holder.get("withdraw") or self.request()
            response = self.call(f"/data/access-requests/{request['request_id']}/withdraw", "generator", {"reason": self.run_id + " explicit withdraw"}, match=request["state_version"])
            require(response["status"] == "REVOKED", "Withdraw did not persist")
            return {"request_id": request["request_id"], "status": response["status"]}
        self.check("authorization:withdraw-api", withdraw, account="generator", ui="API_AND_OUTBOUND_WITHDRAW_LABEL")
        def default_budget():
            grant = self.request(approve=True)
            budget = grant.get("usage_budget")
            require(budget is not None and budget["remaining_uses"] == 1 and budget["usable"] is True, "UI-default budget must report one usable calculation")
            return {"request_id": grant["request_id"], "usage_budget": budget}
        self.check("authorization:ui-default-one-use-budget", default_budget, account="generator")

    def contracts(self) -> None:
        grant = self.request(approve=True)
        contract_id = grant["contract_id"]
        def detail():
            data = self.call(f"/trust-space/contracts/{contract_id}", "generator")
            return {"contract_id": contract_id, "agreement_state": data["agreement"]["state"], "allowed_actions": data["allowed_actions"]}
        self.check("contract:normal-ui-generated-state", detail, account="generator")
        def comment():
            data = self.call(f"/trust-space/contracts/{contract_id}", "generator")
            version = data["events"][-1]["state_version"] if data["events"] else 0
            key = self.key("contract-comment")
            body = {"event_type": "COMMENT", "message": self.run_id + " controlled aggregate comment", "terms": {}, "attachments": []}
            event = self.call(f"/trust-space/contracts/{contract_id}/events", "generator", body, match=version, key=key)
            replay = self.call(f"/trust-space/contracts/{contract_id}/events", "generator", body, match=version, key=key)
            require(replay["event_id"] == event["event_id"] and replay["idempotent_replay"], "Contract comment replay changed event")
            return {"contract_id": contract_id, "event_id": event["event_id"], "idempotent_replay": True}
        self.check("contract:comment-and-replay", comment, account="generator")
        for action in ("counter", "accept", "reject"):
            def closed_action(action=action):
                data = self.call(f"/trust-space/contracts/{contract_id}", "generator")
                version = data["events"][-1]["state_version"] if data["events"] else 0
                require(data["agreement"]["state"] == "ACTIVE" and action not in data["allowed_actions"], "Unexpected normal approval state; inspect a newly reachable negotiation flow")
                response = self.call(f"/trust-space/contracts/{contract_id}/{action}", "generator", {"message": self.run_id + " closed-state probe", "terms": {}, "attachments": []}, match=version, key=self.key(action), expected=(409,))
                return {"_status": "NOT_REACHABLE_FROM_CURRENT_UI", "contract_id": contract_id, "normal_created_state": "ACTIVE", "disabled_action": action, "closed_state_response": response, "reason": "Current approval creates ACTIVE agreement; no shipped UI/HTTP creation flow leaves a controllable pending negotiation. No database fixture fabricated."}
            self.check(f"contract:{action}", closed_action, account="generator")

    def create_task(self, label: str) -> dict[str, Any]:
        task = self.call("/settlement/tasks", "exchange", {"task_name": self.run_id + " " + label, "trade_batch_no": "DEMO-2026-08-E2E", "period_start": "2026-08-01", "period_end": "2026-08-31", "rule_id": "rule-demo-business-v1", "participants": [{"org_id": "org-generator-t01", "role_in_task": "GENERATOR"}, {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}], "business_description": self.run_id}, key=self.key("task"))
        self.own(task["task_id"])
        return task

    def settlements(self) -> None:
        def cancel():
            task = self.create_task("manual cancellation")
            detail = self.call(f"/trust-space/ttc/{task['task_id']}", "exchange")
            require("transition:CANCELLED" in detail["allowed_actions"], "INIT task does not expose its supported cancel")
            result = self.call(f"/trust-space/ttc/{task['task_id']}/transitions", "exchange", {"to_state": "CANCELLED", "trigger": "TRUSTED_SPACE_UI", "reason": self.run_id + " own task cancel"}, match=detail["task"]["state_version"])
            require(result["ttc_state"] == "CANCELLED", "TTC cancellation did not persist")
            events = self.call(f"/trust-space/ttc/{task['task_id']}/events?limit=1", "exchange")
            require(events["items"], "Cancellation event not visible")
            self.call(f"/trust-space/ttc/{task['task_id']}/events?cursor={events.get('next_cursor') or '1'}&limit=1", "exchange")
            return {"task_id": task["task_id"], "state": result["ttc_state"], "cursor_events_read": True}
        self.check("ttc:manual-cancel-and-event-cursor", cancel, account="exchange")
        def interrupt():
            task = self.create_task("interrupt availability probe")
            detail = self.call(f"/trust-space/ttc/{task['task_id']}", "exchange")
            require("transition:INTERRUPTED" not in detail["allowed_actions"], "Unexpected interrupt availability at INIT")
            response = self.call(f"/trust-space/ttc/{task['task_id']}/transitions", "exchange", {"to_state": "INTERRUPTED", "trigger": "TRUSTED_SPACE_UI", "reason": self.run_id + " own task interrupt probe"}, match=detail["task"]["state_version"], expected=(409,))
            return {"_status": "NOT_REACHABLE_FROM_CURRENT_UI", "task_id": task["task_id"], "current_state": detail["task"]["ttc_state"], "response": response, "reason": "Interruption needs RULE_FROZEN/COMPUTE_EXEC/ANCHOR_RETRY; normal synchronous run exposes no stable controllable intermediate state. No forced timing/database state created."}
        self.check("ttc:manual-interruption-availability", interrupt, account="exchange")
        def execute():
            task = self.create_task("result objection")
            require(task["readiness"]["preflight_passed"], "Demo seed readiness is not available")
            self.call(f"/settlement/tasks/{task['task_id']}/run", "exchange", {"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"}, match=task["state_version"], key=self.key("run"))
            task = self.call(f"/settlement/tasks/{task['task_id']}", "exchange")
            self.settlement_task = task
            return {"task_id": task["task_id"], "status": task["status"], "ttc_state": task["ttc"]["state"]}
        if not self.check("settlement:own-task-run", execute, account="exchange"):
            return
        task_id = self.settlement_task["task_id"]
        def events():
            jobs = self.call("/trust-space/computations?page_size=100", "exchange")
            job = next(item for item in jobs["items"] if item["task_id"] == task_id)
            self.own(job["job_id"])
            self.settlement_task["deep_job_id"] = job["job_id"]
            detail = self.call(f"/trust-space/computations/{job['job_id']}", "exchange")
            page = self.call(f"/trust-space/computations/{job['job_id']}/events?limit=1", "exchange")
            require(page["items"], "Completed job should retain real compute events")
            self.call(f"/trust-space/computations/{job['job_id']}/events?cursor={page.get('next_cursor') or '1'}&limit=1", "exchange")
            return {"job_id": job["job_id"], "status": detail["job"]["status"], "events_read": True, "allowed_actions": detail["allowed_actions"]}
        self.check("mpc:event-cursor", events, account="exchange")
        for action in ("retry", "cancel"):
            def control(action=action):
                job_id = self.settlement_task.get("deep_job_id")
                require(job_id, "No own compute job was generated")
                detail = self.call(f"/trust-space/computations/{job_id}", "exchange")
                require(action not in detail["allowed_actions"], f"Unexpected {action} permission on completed job")
                response = self.call(f"/trust-space/computations/{job_id}/{action}", "exchange", {"reason": self.run_id + " completed control probe"}, match=detail["job"]["state_version"], key=self.key(action), expected=(409,))
                return {"_status": "EXPECTED_BLOCKED" if action == "retry" else "NOT_REACHABLE_FROM_CURRENT_UI", "job_id": job_id, "disabled_reason": detail.get("action_reasons", {}).get(action), "response": response, "reason": "Synchronous local executor has no requeue worker; a cancellable QUEUED/PENDING local job cannot be created by the normal shipped UI/HTTP flow."}
            self.check(f"mpc:{action}-capability", control, account="exchange")
        def rejection():
            reports = self.call("/audit/reports", "regulator")
            report = next(item for item in reports if item["task_id"] == task_id and item["status"] == "GENERATED")
            self.own(report["report_id"])
            self.call(f"/audit/reports/{report['report_id']}/decision", "regulator", {"decision": "APPROVE", "opinion": self.run_id + " approve for own result objection"}, key=self.key("audit"))
            listing = self.call(f"/trust-space/results?task_id={task_id}", "generator")
            result = next(item for item in listing["items"] if item.get("org_id") == self.sessions["generator"]["user"]["org_id"])
            self.own(result["result_id"])
            current = self.call(f"/settlement/tasks/{task_id}", "generator")
            key = self.key("result-reject")
            body = {"decision": "REJECT", "opinion": self.run_id + " own result objection"}
            rejected = self.call(f"/trust-space/results/{result['result_id']}/confirm", "generator", body, match=current["state_version"], key=key)
            require(rejected["confirm_status"] == "REJECTED", "Result objection did not persist")
            replay = self.call(f"/trust-space/results/{result['result_id']}/confirm", "generator", body, match=current["state_version"], key=key)
            require(replay.get("idempotent_replay"), "Result objection was not idempotent")
            return {"task_id": task_id, "result_id": result["result_id"], "confirm_status": rejected["confirm_status"], "idempotent_replay": True}
        self.check("result:reject-and-replay", rejection, account="generator")

    def assistant_session(self, account: str, entity_type: str, entity_id: str) -> dict[str, Any]:
        session = self.call("/trust-space/assistant/sessions", account, {"page_path": "/trusted-space/assets/" + entity_id if entity_type == "data_asset" else "/trusted-space/ttc/" + entity_id, "entity_type": entity_type, "entity_id": entity_id}, key=self.key("assistant-session"))
        self.own(session["session_id"])
        return session

    def assistant_message(self, account: str, session: dict[str, Any], content: str) -> dict[str, Any]:
        return self.call(f"/trust-space/assistant/sessions/{session['session_id']}/messages", account, {"content": content}, match=session["state_version"], key=self.key("message"))

    def assistant_action(self, account: str, session: dict[str, Any], plan: dict[str, Any], action: str) -> dict[str, Any]:
        return self.call(f"/trust-space/assistant/sessions/{session['session_id']}/plans/{plan['plan_id']}/{action}", account, {} if action == "execute" else None, method="POST", match=plan["state_version"], key=self.key(action))

    def assistants(self) -> None:
        for account in self.sessions:
            if account == "admin":
                continue
            def asset_plan(account=account):
                catalog = self.call("/trust-space/catalog?page_size=100", account)
                own_org = self.sessions[account]["user"]["org_id"]
                asset = next((item for item in catalog["items"] if item["provider"]["org_id"] == own_org), catalog["items"][0])
                session = self.assistant_session(account, "data_asset", asset["asset_id"])
                message = self.assistant_message(account, session, "检查资产完整性")
                require(message["plan"]["status"] == "READY", "Asset read plan is not READY")
                executed = self.assistant_action(account, message["session"], message["plan"], "execute")
                require(executed["plan"]["status"] == "SUCCEEDED", "Asset read plan did not succeed")
                return {"session_id": session["session_id"], "intent": executed["plan"]["intent_code"], "status": executed["plan"]["status"]}
            self.check(f"assistant:own-visible-asset:{account}", asset_plan, account=account)
        def controls():
            session = self.assistant_session("exchange", "data_asset", "asset-electricity-load")
            message = self.assistant_message("exchange", session, "请安排一场会议")
            require(message["plan"]["status"] == "BLOCKED", "Unknown intent was not blocked")
            retried = self.assistant_action("exchange", message["session"], message["plan"], "retry")
            require(retried["plan"]["status"] == "READY", "Retry did not reopen the blocked plan")
            cancelled = self.assistant_action("exchange", retried["session"], retried["plan"], "cancel")
            require(cancelled["plan"]["status"] == "CANCELLED", "Cancel did not persist")
            fresh = self.assistant_session("exchange", "data_asset", "asset-electricity-load")
            ready = self.assistant_message("exchange", fresh, "检查资产完整性")
            direct_cancel = self.assistant_action("exchange", ready["session"], ready["plan"], "cancel")
            require(direct_cancel["plan"]["status"] == "CANCELLED", "READY cancellation failed")
            return {"retry_from_blocked": True, "cancel_after_retry": True, "cancel_ready": True, "session_id": session["session_id"]}
        self.check("assistant:retry-and-cancel", controls, account="exchange")
        grant = self.request()
        task = self.settlement_task or self.create_task("assistant task target")
        shortcuts = [("generator", "data_usage_request", grant["request_id"], "查询授权申请状态"), ("exchange", "settlement_task", task["task_id"], "检查可信任务状态"), ("exchange", "settlement_task", task["task_id"], "核验证据摘要"), ("regulator", "settlement_task", task["task_id"], "解释审计报告")]
        for account, entity_type, entity_id, text in shortcuts:
            def shortcut(account=account, entity_type=entity_type, entity_id=entity_id, text=text):
                session = self.assistant_session(account, entity_type, entity_id)
                message = self.assistant_message(account, session, text)
                require(message["plan"]["status"] == "READY", "Shortcut did not create a readable plan")
                executed = self.assistant_action(account, message["session"], message["plan"], "execute")
                require(executed["plan"]["status"] == "SUCCEEDED", "Shortcut execution did not succeed")
                return {"session_id": session["session_id"], "intent": executed["plan"]["intent_code"], "status": executed["plan"]["status"]}
            self.check("assistant:shortcut:" + text, shortcut, account=account)
        writes = [("exchange", "data_asset", "asset-electricity-load", "提交申请"), ("retailer", "data_usage_request", grant["request_id"], "批准申请"), ("retailer", "data_usage_request", grant["request_id"], "拒绝申请"), ("retailer", "data_usage_request", grant["request_id"], "撤销授权"), ("exchange", "settlement_task", task["task_id"], "推进任务")]
        for account, entity_type, entity_id, text in writes:
            def write_review(account=account, entity_type=entity_type, entity_id=entity_id, text=text):
                before = self.call(f"/data/access-requests/{entity_id}", account) if entity_type == "data_usage_request" else self.call(f"/trust-space/ttc/{entity_id}", account) if entity_type == "settlement_task" else self.asset(entity_id, account)
                session = self.assistant_session(account, entity_type, entity_id)
                message = self.assistant_message(account, session, text)
                require(message["plan"]["status"] == "PENDING_REVIEW", "Write intent should create only a review draft")
                executed = self.assistant_action(account, message["session"], message["plan"], "execute")
                output = executed["plan"]["steps"][0]["output"]
                require(executed["plan"]["status"] == "PENDING_REVIEW" and output["business_mutation"] is False and output["review_requested"] is True, "Write draft changed business state")
                after = self.call(f"/data/access-requests/{entity_id}", account) if entity_type == "data_usage_request" else self.call(f"/trust-space/ttc/{entity_id}", account) if entity_type == "settlement_task" else self.asset(entity_id, account)
                require(before == after, "Assistant review changed target business DTO")
                return {"session_id": session["session_id"], "intent": executed["plan"]["intent_code"], "review_requested": True, "business_mutation": False}
            self.check("assistant:write-review:" + text, write_review, account=account)

    def electricity(self) -> None:
        catalog = self.call("/trust-space/assistant/electricity/catalog", "generator")
        for scenario in catalog["scenarios"]:
            def reuse(scenario=scenario):
                session = self.assistant_session("generator", "electricity_calculation", self.run_id)
                prepared = self.call("/trust-space/assistant/electricity/prepare", "generator", {"session_id": session["session_id"], "question": scenario["example"], "scenario": scenario["id"]}, key=self.key("electricity-prepare"))
                require(not prepared["missing"], "Full catalog example is incomplete")
                calculated = self.call(f"/trust-space/assistant/electricity/{prepared['id']}/calculate", "generator", {"parameters": prepared["parameters"], "confirmed": True, "state_version": prepared["state_version"]})
                require(calculated["status"] == "SUCCEEDED", "Initial calculation failed")
                self.own(calculated["id"])
                saved = self.call(f"/trust-space/assistant/electricity/{calculated['id']}/save", "generator", {})
                require(saved["saved"] is True, "Save was not persisted")
                fresh = self.assistant_session("generator", "electricity_calculation", self.run_id)
                reused = self.call("/trust-space/assistant/electricity/prepare", "generator", {"session_id": fresh["session_id"], "question": "复用已保存案例的参数，重新计算。", "scenario": scenario["id"], "based_on": calculated["id"]}, key=self.key("reuse"))
                require(reused["parameters"] == calculated["parameters"] and reused["status"] != "SUCCEEDED" and not reused.get("result"), "Reuse should retain inputs and require fresh confirmation")
                again = self.call(f"/trust-space/assistant/electricity/{reused['id']}/calculate", "generator", {"parameters": reused["parameters"], "confirmed": True, "state_version": reused["state_version"]})
                require(again["status"] == "SUCCEEDED" and again["result"]["summary"] == calculated["result"]["summary"], "Deterministic reuse changed result")
                history = self.call(f"/trust-space/assistant/electricity/sessions/{fresh['session_id']}", "generator")
                require(any(item["id"] == reused["id"] for item in history["items"]), "New session history lost reused record")
                cases = self.call("/trust-space/assistant/electricity/cases", "generator")
                require(any(item["id"] == calculated["id"] for item in cases["items"]), "Saved case not in personal library")
                denied = self.call(f"/trust-space/assistant/electricity/sessions/{fresh['session_id']}", "retailer", expected=(403, 404))
                return {"scenario": scenario["id"], "original_id": calculated["id"], "reused_id": reused["id"], "requires_reconfirmation": True, "deterministic_summary": True, "history_persisted": True, "cross_account_denied": denied["http_status"]}
            self.check("electricity:save-reuse-new-history:" + scenario["id"], reuse, account="generator")

    def query(self, function: str, *, extras: dict[str, Any] | None = None, dates: tuple[str, str] = ("2026-06-01", "2026-06-03"), failure: bool = False) -> dict[str, Any]:
        require(self.query_grant is not None, "Query grant setup missing")
        grant = self.query_grant
        condition = {"authorization_id": grant["request_id"], "provider_org_id": grant["provider"]["org_id"], "asset_id": grant["asset"]["asset_id"], "energy_domain": "electricity", "resource": "load", "function": function, "start_date": dates[0], "end_date": dates[1], "region": (extras or {}).get("region"), "decimals": 2}
        condition.update({field: value for field, value in (extras or {}).items() if field in {"hour", "threshold", "group_by"}})
        confirmation = self.call("/trust-space/query/confirm", "generator", condition, expected=(200, 400, 403, 409, 422) if failure else (200,))
        if failure and "http_status" in confirmation:
            return {"rejected_stage": "confirm", "response": confirmation, "task_created": False}
        body = {**condition, **(extras or {}), **{field: confirmation[field] for field in ("authorization_id", "provider_org_id", "asset_id") if confirmation.get(field) is not None}, "confirmation_token": confirmation["confirmation_token"]}
        key = self.key("query-" + function)
        task = self.call("/trust-space/query/execute", "generator", body, key=key, expected=(200, 201, 202, 400, 403, 409, 422) if failure else (200, 201, 202))
        if failure and "http_status" in task:
            return {"rejected_stage": "execute", "response": task, "task_created": False}
        self.own(task["task_id"])
        deadline = time.monotonic() + 60
        while task["status"] not in {"SUCCEEDED", "FAILED"} and time.monotonic() < deadline:
            task = self.call(f"/trust-space/query/tasks/{task['task_id']}", "generator")
            if task["status"] not in {"SUCCEEDED", "FAILED"}:
                time.sleep(0.15)
        if failure:
            require(task["status"] == "FAILED", "Invalid parameters were not blocked")
            denied = self.call(f"/trust-space/query/tasks/{task['task_id']}/result", "generator", expected=(409,))
            return {"task_id": task["task_id"], "failure_code": task.get("failure_code"), "failure_summary": task.get("failure_summary"), "result_http_status": denied["http_status"]}
        require(task["status"] == "SUCCEEDED", f"Query failed: {task.get('failure_code')} {task.get('failure_summary')}")
        result = self.call(f"/trust-space/query/tasks/{task['task_id']}/result", "generator")
        require(result.get("raw_records_returned") is False, "Raw rows escaped controlled query")
        require(result.get("digital_signature") == "已验证" and result.get("privacy_verification", {}).get("status") == "VERIFIED", "Connector signature/non-export attestation was not verified")
        require(result.get("asset_version_id") == grant["asset"]["version_id"] and result.get("dataset_version") == grant["asset"]["version_no"], "Execution did not retain the approved immutable version")
        replay = self.call("/trust-space/query/execute", "generator", body, key=key)
        require(replay["task_id"] == task["task_id"], "Idempotent replay changed task")
        return result

    def queries(self) -> None:
        self.query_grant = self.request(approve=True, scope={"max_uses": 40, "start_date": "2021-01-01", "end_date": "2026-09-30"})
        for function in FUNCTIONS:
            def fixed(function=function):
                extras = {"threshold": 1500} if function == "threshold" else {"group_by": "region"} if function == "group_by" else {}
                result = self.query(function, extras=extras)
                self.query_results[function] = result
                require(result["record_count"] == 12, "Expected 3 days × 4 regions in the immutable v2 seed")
                if function == "count": require(result["result"] == 12, "Count does not match record count")
                if function in {"count", "threshold"}: require(result.get("unit") == "条", "Count output has an energy unit")
                if function in {"growth_rate", "yoy", "mom"}: require(result.get("unit") == "%", "Rate output is missing percent unit")
                if function == "trend": require(result.get("unit") == "MW" and len(result.get("trend") or []) == 3, "Trend must retain the signed MW series for every date")
                if function == "psi": require(isinstance(result["result"], (float, int)) and math.isfinite(result["result"]) and result["result"] >= 0 and result.get("unit") in {"无量纲", "", "1"}, "PSI must be finite, nonnegative, and dimensionless")
                return {"task_id": result["task_id"], "function": function, "result": result["result"], "record_count": result["record_count"], "unit": result.get("unit"), "execution_contract_passed": True, "business_semantics": "CHECKED_SEPARATELY" if function in {"growth_rate", "yoy", "mom", "psi"} else "CONTROLLED_FUNCTION_OUTPUT", "natural_language_ui_supported": function in UI_QUERY_FUNCTIONS}
            self.check("query:function:" + function, fixed, account="generator", ui="CURRENT_UI" if function in UI_QUERY_FUNCTIONS else "API_ONLY_NO_CURRENT_NATURAL_LANGUAGE_ENTRY")
        def identities():
            values = {name: self.query_results[name]["result"] for name in ("sum", "average", "max", "min", "median", "count", "mpc_aggregation")}
            require(abs(values["sum"] - values["average"] * values["count"]) <= 0.1, "Sum / average / count disagree beyond decimal rounding")
            require(values["min"] <= values["median"] <= values["max"] and values["min"] <= values["average"] <= values["max"], "Summary ordering invalid")
            require(values["mpc_aggregation"] == values["sum"], "Local aggregation does not match the same authorized inputs")
            return {"sum_average_count_consistent": True, "min_median_max_consistent": True, "local_aggregation_matches_sum": True}
        self.check("query:aggregate-identities", identities, account="generator")
        parameter_cases = [("hour", "average", {"hour": 8}, 12), ("region", "average", {"region": "北部片区"}, 3), ("group-date", "group_by", {"group_by": "record_date"}, 12), ("group-organization", "group_by", {"group_by": "organization"}, 12), ("threshold-all", "threshold", {"threshold": 0}, 12)]
        for name, function, extras, count in parameter_cases:
            def parameters(name=name, function=function, extras=extras, count=count):
                result = self.query(function, extras=extras)
                require(result["record_count"] == count, "Date/hour/region filter count mismatch")
                if name.startswith("group-"): require(len(result["result"]) == (3 if name == "group-date" else 4), "Supported grouping lost valid groups")
                if name == "threshold-all": require(result["result"].get("满足") == count and result["result"].get("不满足") == 0, "Threshold result mismatch")
                return {"task_id": result["task_id"], "parameters": extras, "result": result["result"], "record_count": count}
            self.check("query:parameter:" + name, parameters, account="generator", ui="API_ONLY_FOR_HOUR_GROUP_THRESHOLD" if name != "region" else "CURRENT_UI")
        def early():
            result = self.query("count", dates=("2021-01-01", "2021-01-03"))
            require(result["result"] == 12, "Earliest requested history is missing")
            return {"task_id": result["task_id"], "period": ["2021-01-01", "2021-01-03"], "count": result["result"]}
        self.check("query:earliest-date-boundary", early, account="generator")
        def late():
            result = self.query("count", dates=("2026-09-28", "2026-09-30"))
            require(result["result"] == 12, "Latest requested history is missing")
            return {"task_id": result["task_id"], "period": ["2026-09-28", "2026-09-30"], "count": result["result"]}
        self.check("query:latest-date-boundary", late, account="generator")
        for name, extras in (("threshold-required", {}), ("group-field-invalid", {"group_by": "not_allowed"}), ("privacy-small-region", {"region": "北部片区"})):
            def invalid(name=name, extras=extras):
                result = self.query("threshold" if name == "threshold-required" else "group_by" if name == "group-field-invalid" else "count", extras=extras, dates=("2026-06-01", "2026-06-01") if name == "privacy-small-region" else ("2026-06-01", "2026-06-03"), failure=True)
                return {"_status": "EXPECTED_BLOCKED", **result}
            self.check("query:boundary:" + name, invalid, account="generator", ui="API_ONLY_INVALID_PARAMETER_PROBE")
        def date_limit():
            rules = self.call("/data/access-rules?owner_org_id=org-generator-t01", "regulator")
            rule = next(item for item in rules["items"] if item["resource_id"] == "generation" and item["function_code"] == "average" and item["mode"] == "AUTO_CALL" and item["status"] == "ACTIVE")
            require(rule["limits"]["max_duration_days"] == 31, "Expected the existing subject-owned 31-day AUTO_CALL rule")
            response = self.call("/trust-space/query/confirm", "regulator", {"provider_org_id": "org-generator-t01", "energy_domain": "electricity", "resource": "generation", "function": "average", "start_date": "2026-06-01", "end_date": "2026-07-02", "decimals": 2}, expected=(403,))
            return {"_status": "EXPECTED_BLOCKED", "date_span_days": 32, "rule_id": rule["rule_id"], "explicit_rule_max_days": 31, "response": response, "scope": "Subject AUTO_CALL rule, not an invented global limit on explicitly approved manual grants"}
        self.check("query:31-day-auto-rule-limit", date_limit, account="regulator")
        for field, function, original, tampered in (("hour", "average", 8, 9), ("threshold", "threshold", 1500, 1600), ("group_by", "group_by", "region", "organization")):
            def tamper(field=field, function=function, original=original, tampered=tampered):
                grant = self.query_grant
                condition = {"authorization_id": grant["request_id"], "provider_org_id": grant["provider"]["org_id"], "asset_id": grant["asset"]["asset_id"], "energy_domain": "electricity", "resource": "load", "function": function, "start_date": "2026-06-01", "end_date": "2026-06-03", "region": None, "decimals": 2, field: original}
                confirmation = self.call("/trust-space/query/confirm", "generator", condition)
                response = self.call("/trust-space/query/execute", "generator", {**condition, **{key: confirmation[key] for key in ("authorization_id", "provider_org_id", "asset_id") if confirmation.get(key) is not None}, field: tampered, "confirmation_token": confirmation["confirmation_token"]}, key=self.key("tampered-" + field), expected=(409,))
                return {"_status": "EXPECTED_BLOCKED", "field": field, "confirmed": original, "tampered": tampered, "response": response}
            self.check("query:confirmation-tamper:" + field, tamper, account="generator", ui="API_ONLY_INVALID_PARAMETER_PROBE")
        for name, changed in (("inverted-dates", {"start_date": "2026-06-03", "end_date": "2026-06-01"}), ("hour-out-of-range", {"hour": 24})):
            def malformed(name=name, changed=changed):
                grant = self.query_grant
                condition = {"authorization_id": grant["request_id"], "provider_org_id": grant["provider"]["org_id"], "energy_domain": "electricity", "resource": "load", "function": "sum", "start_date": "2026-06-01", "end_date": "2026-06-03", "decimals": 2, **changed}
                response = self.call("/trust-space/query/confirm", "generator", condition, expected=(400, 422))
                return {"_status": "EXPECTED_BLOCKED", "parameters": changed, "response": response}
            self.check("query:boundary:" + name, malformed, account="generator", ui="API_ONLY_INVALID_PARAMETER_PROBE")
        def comparison_scope():
            restricted = self.request(approve=True, scope={"max_uses": 1, "start_date": "2026-06-01", "end_date": "2026-06-03"})
            response = self.call("/trust-space/query/confirm", "generator", {"authorization_id": restricted["request_id"], "provider_org_id": restricted["provider"]["org_id"], "energy_domain": "electricity", "resource": "load", "function": "yoy", "start_date": "2026-06-01", "end_date": "2026-06-03", "decimals": 2}, expected=(403,))
            return {"_status": "EXPECTED_BLOCKED", "request_id": restricted["request_id"], "authorized_period": ["2026-06-01", "2026-06-03"], "comparison_period": ["2025-06-01", "2025-06-03"], "response": response}
        self.check("query:comparison-must-fit-original-authorization", comparison_scope, account="generator", ui="API_ONLY_NO_CURRENT_NATURAL_LANGUAGE_ENTRY")
        def semantics():
            current = self.query_results["average"]["result"]
            first = self.query("average", dates=("2026-06-01", "2026-06-01"))["result"]
            last = self.query("average", dates=("2026-06-03", "2026-06-03"))["result"]
            year = self.query("average", dates=("2025-06-01", "2025-06-03"))["result"]
            month = self.query("average", dates=("2026-05-01", "2026-05-03"))["result"]
            expected = {"growth_rate": round((last - first) / abs(first) * 100, 2), "yoy": round((current - year) / abs(year) * 100, 2), "mom": round((current - month) / abs(month) * 100, 2)}
            actual = {name: self.query_results[name]["result"] for name in expected}
            mismatches = {name: {"actual": actual[name], "expected_from_controlled_comparable_averages": expected[name]} for name in expected if not math.isclose(actual[name], expected[name], abs_tol=0.02)}
            return {"_status": "FAIL" if mismatches else "PASS", "comparison_periods": {"current": ["2026-06-01", "2026-06-03"], "year": ["2025-06-01", "2025-06-03"], "month": ["2026-05-01", "2026-05-03"]}, "mismatches": mismatches, "raw_records_used": False, "semantics": "Same-scope period averages for YoY/MoM; same-scope first/last-day averages for growth. Never compare different regions as period endpoints."}
        self.check("query:business-growth-yoy-mom-semantics", semantics, account="generator", ui="API_ONLY_NO_CURRENT_NATURAL_LANGUAGE_ENTRY")
        self.check("query:psi-independent-formula-boundary", lambda: {"_status": "SEMANTICS_UNVERIFIED", "http_properties_verified": "psi" in self.query_results, "separate_formula_test": {"path": "connector/tests/test_period_comparisons.py", "name": "test_psi_matches_an_independently_derived_ten_bin_distribution_formula", "independent_expected_value": "ln(5)/8", "execution_evidence": "Must be supplied by the separate connector test run; this HTTP script does not execute or invent it"}, "reason": "HTTP verifies finite nonnegative dimensionless output; aggregate-only responses do not disclose the individual distribution required for an independent full-bin recalculation. No raw-record reconstruction or synthetic PASS."}, account="generator", ui="API_ONLY_NO_CURRENT_NATURAL_LANGUAGE_ENTRY")

    def own_queries(self) -> None:
        specifications = (("generator", "electricity", "generation"), ("retailer", "electricity", "load"), ("coal", "coal", "production"), ("heat", "heat", "supply"), ("gas", "gas", "supply"), ("oil", "oil", "production"), ("exchange", "electricity", "price"))
        first_confirmation: dict[str, Any] = {}
        for account, domain, resource in specifications:
            def calculate_owned(account=account, domain=domain, resource=resource):
                owner = self.sessions[account]["user"]["org_id"]
                catalog = self.call(f"/trust-space/catalog?domain={domain}&page_size=100", account)
                asset = next(item for item in catalog["items"] if item["provider"]["org_id"] == owner and item["metadata"].get("resource_id") == resource)
                require(asset["actions"].get("can_compute_own") is True, "Owner's usable resource has no explicit computation capability")
                condition = {"provider_org_id": owner, "asset_id": asset["asset_id"], "energy_domain": domain, "resource": resource, "function": "average", "start_date": "2026-08-12", "end_date": "2026-08-14", "region": None, "decimals": 2}
                confirmation = self.call("/trust-space/query/confirm", account, condition)
                require(all(confirmation.get(field) for field in ("authorization_id", "provider_org_id", "asset_id")), "Owned confirmation omitted its bound identifiers")
                self.own(confirmation["authorization_id"])
                grant = self.call(f"/data/access-requests/{confirmation['authorization_id']}", account)
                require(grant["terms"].get("authorization_source") == "SELF_OWNED_QUERY" and grant["requested_scope"].get("max_uses") == 1, "Owner computation did not receive a one-use self-owned grant")
                expiry = datetime.fromisoformat(grant["expires_at"].replace("Z", "+00:00"))
                expiry = expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry
                require(0 < (expiry - datetime.now(timezone.utc)).total_seconds() <= 905, "Self-owned grant must expire within 15 minutes")
                body = {**condition, **{field: confirmation[field] for field in ("authorization_id", "provider_org_id", "asset_id")}, "confirmation_token": confirmation["confirmation_token"]}
                if account == "generator":
                    first_confirmation.update(account=account, body=body)
                key = self.key("own-query")
                task = self.call("/trust-space/query/execute", account, body, key=key)
                self.own(task["task_id"])
                deadline = time.monotonic() + 60
                while task["status"] not in {"SUCCEEDED", "FAILED"} and time.monotonic() < deadline:
                    task = self.call(f"/trust-space/query/tasks/{task['task_id']}", account)
                    if task["status"] not in {"SUCCEEDED", "FAILED"}:
                        time.sleep(0.15)
                require(task["status"] == "SUCCEEDED", f"Owned query failed: {task.get('failure_code')} {task.get('failure_summary')}")
                result = self.call(f"/trust-space/query/tasks/{task['task_id']}/result", account)
                require(result["record_count"] == 12 and result["raw_records_returned"] is False and result["privacy_verification"]["status"] == "VERIFIED", "Owned result lacks its expected private verified aggregation")
                require(result["asset_version_id"] == grant["asset"]["version_id"], "Owned query drifted from its immutable version")
                computation = self.call(f"/trust-space/computations/{result['job_id']}", account)
                participants = computation["external_execution"]["cross_domain_participants"]
                require(len(participants) == len(set(participants)), "Owner computation repeats the same subject in its participant projection")
                require(computation["job"]["privacy_guarantees"].get("api_raw_records_returned") is False, "Owned computation detail does not project its non-export API guarantee")
                replay = self.call("/trust-space/query/execute", account, body, key=key)
                require(replay["task_id"] == task["task_id"], "Owned replay created a second calculation")
                exhausted = self.call("/trust-space/query/execute", account, body, key=self.key("own-second-execution"), expected=(403,))
                current = self.call(f"/data/access-requests/{confirmation['authorization_id']}", account)
                require(current["usage_budget"]["remaining_uses"] == 0 and current["usage_budget"]["usable"] is False, "Self-owned calculation budget did not become exhausted")
                return {"task_id": task["task_id"], "job_id": result["job_id"], "authorization_id": confirmation["authorization_id"], "asset_id": confirmation["asset_id"], "domain": domain, "resource": resource, "record_count": 12, "unit": result["unit"], "result": result["result"], "self_owned_source": True, "one_use_consumed": True, "idempotent_replay": True, "second_execution_denied": exhausted["http_status"], "participant_projection_unique": True, "api_raw_records_returned": False}
            self.check("query:own-subject:" + account, calculate_owned, account=account)
        for field, replacement in (("asset_id", "asset-electricity-load"), ("provider_org_id", "org-retailer-t01")):
            def tamper_owned(field=field, replacement=replacement):
                require(first_confirmation, "No successful generator owned confirmation to probe")
                condition = {key: value for key, value in first_confirmation["body"].items() if key not in {"authorization_id", "confirmation_token"}}
                confirmation = self.call("/trust-space/query/confirm", "generator", condition)
                self.own(confirmation["authorization_id"])
                before = self.call(f"/data/access-requests/{confirmation['authorization_id']}", "generator")
                require(before["usage_budget"]["remaining_uses"] == 1 and before["usage_budget"]["usable"] is True, "Tamper probe needs an unused own confirmation, not an already exhausted grant")
                body = {**condition, **{key: confirmation[key] for key in ("authorization_id", "provider_org_id", "asset_id")}, "confirmation_token": confirmation["confirmation_token"], field: replacement}
                response = self.call("/trust-space/query/execute", "generator", body, key=self.key("owned-tamper-" + field), expected=(403, 409))
                after = self.call(f"/data/access-requests/{confirmation['authorization_id']}", "generator")
                require(after["usage_budget"]["remaining_uses"] == 1, "A rejected target mutation must not consume the original grant")
                return {"_status": "EXPECTED_BLOCKED", "tampered_field": field, "response": response, "unused_budget_preserved": True}
            self.check("query:own-confirmation-tamper:" + field, tamper_owned, account="generator", ui="API_ONLY_INVALID_PARAMETER_PROBE")

    def notifications(self) -> None:
        for account in self.sessions:
            if account == "admin":
                continue
            def inspect(account=account):
                catalog = self.call("/trust-space/catalog?page_size=100", account)
                candidates = [item for item in catalog["items"] if item.get("actions", {}).get("can_request_usage") and any(session["user"]["org_id"] == item["provider"]["org_id"] for session in self.sessions.values())]
                if candidates:
                    grant = self.request(approve=True, consumer=account, asset_id=candidates[0]["asset_id"])
                else:
                    # A domain with one provider can still exercise its real inbox:
                    # its matching exchange requests an owned resource for review.
                    own_org = self.sessions[account]["user"]["org_id"]
                    owned_asset = next(item for item in catalog["items"] if item["provider"]["org_id"] == own_org)
                    domain = owned_asset["domain"]
                    consumer = "exchange" if domain == "electricity" else "exchange_" + domain
                    grant = self.request(approve=True, consumer=consumer, asset_id=owned_asset["asset_id"])
                first = self.call("/trust-space/notifications?page=1&page_size=100", account)
                rows = list(first["items"])
                for page in range(2, min(10, math.ceil(first["total"] / 100)) + 1):
                    rows.extend(self.call(f"/trust-space/notifications?page={page}&page_size=100", account)["items"])
                ours = [item for item in rows if item.get("entity_id") in self.owned]
                if not ours:
                    return {"_status": "NOT_EXERCISED_NO_OWN_RUN_NOTIFICATION", "reason": "No own-run target notification for this role; other runs' notifications were not marked or mutated."}
                verified = []
                for item in ours:
                    entity_type, entity_id = item.get("entity_type", "").upper(), item["entity_id"]
                    routes = {"DATA_USAGE_REQUEST": "/data/access-requests/", "DATA_CONTRACT": "/trust-space/contracts/", "SETTLEMENT_TASK": "/trust-space/ttc/", "SETTLEMENT_RESULT": "/trust-space/results/", "PRIVACY_COMPUTE_JOB": "/trust-space/computations/"}
                    if entity_type in routes:
                        self.call(routes[entity_type] + quote(entity_id, safe=""), account)
                    elif entity_type == "AUDIT_REPORT" and account == "regulator":
                        reports = self.call("/audit/reports", account)
                        require(any(row["report_id"] == entity_id for row in reports), "Own report notification target is not readable")
                    else:
                        verified.append({"type": entity_type, "target_id": entity_id, "ui_jump": "SUMMARY_ONLY_NO_SAFE_CURRENT_ROUTE"})
                        continue
                    verified.append({"type": entity_type, "target_id": entity_id, "ui_jump": "TARGET_READABLE"})
                item = next((row for row in ours if not row.get("read_at")), ours[0])
                marked = self.call(f"/trust-space/notifications/{item['notification_id']}/read", account, {})
                require(marked.get("read_at"), "Single notification read was not persisted")
                return {"own_notifications": len(ours), "own_trigger_request_id": grant["request_id"], "single_read_notification_id": item["notification_id"], "targets": verified, "foreign_notifications_untouched": True}
            self.check("notification:single-read-and-own-targets:" + account, inspect, account=account)

    def run(self) -> int:
        self.setup()
        for area, action in (("accounts", self.accounts), ("authorization", self.authorizations), ("contract", self.contracts), ("settlement", self.settlements), ("assistant", self.assistants), ("electricity", self.electricity), ("queries", self.queries), ("own-queries", self.own_queries), ("notifications", self.notifications)):
            if area in self.areas:
                try:
                    action()
                except Exception as error:
                    self.check(f"{area}:setup", lambda error=error: (_ for _ in ()).throw(error))
        self.save()
        self.client.close()
        print(json.dumps({"evidence": str(self.output.relative_to(ROOT)), "run_id": self.run_id, "status_counts": dict(Counter(item["status"] for item in self.results))}, ensure_ascii=True), flush=True)
        return 1 if any(item["status"] == "FAIL" for item in self.results) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", help="Project-relative JSON evidence path; default runtime/deep-workflows-<timestamp>.json")
    parser.add_argument("--areas", default=",".join(sorted(AREAS)), help="Comma-separated subset for focused rechecks")
    arguments = parser.parse_args()
    areas = set(filter(None, arguments.areas.split(",")))
    require(areas <= AREAS and areas, "Unknown or empty --areas selection")
    output = (ROOT / arguments.output).resolve() if arguments.output else ROOT / "runtime" / ("deep-workflows-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json")
    return Acceptance(arguments.base_url, output, areas).run()


if __name__ == "__main__":
    sys.exit(main())
