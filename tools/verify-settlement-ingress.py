"""Exercise fresh CSV -> connector -> demo settlement -> archive over HTTP.

Run against an isolated runtime/run-usability-stack.py instance. Only loopback
demo servers are accepted. All business writes use the supported HTTP APIs;
optional SQLite/Vault inspection is read-only. Never logs access tokens.
"""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import io
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS = "/api/trust-space/connectors"


def local_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password:
        raise ValueError("Verification requires an isolated loopback HTTP demo stack")
    return value.rstrip("/")


def project_path(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Evidence and runtime paths must stay inside the repository")
    return path


class DemoJourney:
    def __init__(self, base: str, out: Path):
        self.base, self.out = local_url(base), out
        self.client = httpx.Client(timeout=120, trust_env=False, follow_redirects=False)
        self.headers: dict[str, dict[str, str]] = {}
        self.run_id = uuid.uuid4().hex[:12]
        self.canary = "PRIVATE_CSV_ROW_" + self.run_id
        self.evidence: dict = {"run_id": self.run_id, "scope": "LOCAL_DEMO", "batches": []}
        health = self.call("GET", "/api/health")
        if health.get("environment") != "demo":
            raise ValueError("Refusing writes: API environment is not demo")
        for role in ("generator", "retailer", "exchange", "regulator"):
            # Public synthetic demo accounts only; never use production credentials.
            login = self.call("POST", "/api/auth/login", json={"username": role, "password": role + "123"})
            self.headers[role] = {"Authorization": "Bearer " + login["access_token"]}

    def call(self, method: str, path: str, role: str | None = None, expected: int = 200, **kwargs):
        headers = {**self.headers.get(role or "", {}), **kwargs.pop("headers", {})}
        response = self.client.request(method, self.base + path, headers=headers, **kwargs)
        if response.status_code != expected:
            # Do not include arbitrary response bodies or request headers in logs.
            raise AssertionError(f"{method} {path}: expected HTTP {expected}, got {response.status_code}")
        return response.json() if response.content else None

    def csv_file(self, role: str, batch: str, start: date, values: list[str]) -> tuple[Path, bytes]:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["record_date", "value", "unit", "region"])
        for offset, value in enumerate(values):
            writer.writerow([(start + timedelta(days=offset)).isoformat(), value, "MWh", self.canary])
        raw = stream.getvalue().encode("utf-8")
        path = self.out / f"{batch}-{role}.csv"
        path.write_bytes(raw)
        return path, raw

    def upload(self, role: str, batch: str, start: date, values: list[str]) -> dict:
        resource = "generation" if role == "generator" else "supply"
        asset_type = "GENERATION_DATA" if role == "generator" else "RETAIL_DATA"
        binding = {"schema_version": "connector-settlement-binding-v1", "trade_batch_no": batch,
                   "period_start": start.isoformat(), "period_end": (start + timedelta(days=len(values) - 1)).isoformat()}
        ticket = self.call("POST", CONNECTORS + "/tickets", role, expected=201,
                           json={"resource_id": resource, "settlement_binding": binding})
        assert ticket["ticket"]["claims"]["settlement_binding"] == binding
        path, raw = self.csv_file(role, batch, start, values)
        response = self.client.post(local_url(ticket["upload_url"]),
                                    data={"ticket": json.dumps(ticket["ticket"])}, files={"file": (path.name, raw, "text/csv")})
        assert response.status_code == 201, f"Connector ingestion failed with HTTP {response.status_code}"
        receipt = response.json()
        summary = receipt["settlement_summary"]
        assert Decimal(summary["energy_mwh"]) == sum(map(Decimal, values))
        assert summary["asset_type"] == asset_type and summary["record_count"] == len(values)
        assert summary["content_hash"] == receipt["content_hash"] and summary["raw_records_returned"] is False
        assert self.canary not in json.dumps(receipt)
        tampered = copy.deepcopy(receipt)
        tampered["settlement_summary"]["energy_mwh"] = "999"
        self.call("POST", CONNECTORS + "/receipts", role, expected=422, json=tampered)
        for mutation in ("integer_type", "batch_whitespace"):
            altered = copy.deepcopy(receipt)
            if mutation == "integer_type":
                altered["record_count"] = str(altered["record_count"])
            else:
                altered["settlement_summary"]["trade_batch_no"] += " "
            self.call("POST", CONNECTORS + "/receipts", role, expected=422, json=altered)
        other = "retailer" if role == "generator" else "generator"
        self.call("POST", CONNECTORS + "/receipts", other, expected=403, json=receipt)
        registered = self.call("POST", CONNECTORS + "/receipts", role, expected=201, json=receipt)
        settlement = registered["settlement"]
        assert settlement["status"] == "REGISTERED" and settlement["trade_batch_no"] == batch
        assert settlement["period_start"] == binding["period_start"] and settlement["period_end"] == binding["period_end"]
        replay = self.call("POST", CONNECTORS + "/receipts", role, json=receipt)
        recovered = self.call("GET", CONNECTORS + "/receipts/" + receipt["ticket_id"], role)
        assert replay["settlement"]["upload_id"] == recovered["settlement"]["upload_id"] == settlement["upload_id"]
        assert replay["idempotent_replay"] is True
        return {"role": role, "resource_id": resource, "energy_mwh": summary["energy_mwh"],
                "upload_id": settlement["upload_id"], "receipt_id": receipt["receipt_id"],
                "tamper_http": 422, "typed_payload_tamper_http": 422, "batch_text_tamper_http": 422,
                "cross_org_http": 403, "idempotency": "PASSED", "recovery": "PASSED"}

    def verify_rule_input_boundaries(self):
        before = self.call("GET", "/api/rules", "exchange")
        parameters = {"rule_name": "隔离演示数值边界拒绝验证", "contract_price": 420,
                      "deviation_threshold_mwh": 100, "deviation_penalty_rate": 150, "service_fee_rate": 3.2}
        for field in ("contract_price", "deviation_threshold_mwh", "deviation_penalty_rate", "service_fee_rate"):
            self.call("POST", "/api/rules", "exchange", expected=422, json={**parameters, field: "Infinity"})
        after = self.call("GET", "/api/rules", "exchange")
        assert {rule["rule_id"] for rule in before} == {rule["rule_id"] for rule in after}
        self.evidence["nonfinite_rule_parameters"] = "PASSED: all four parameters rejected; rule list remains readable and unchanged"
        self.save()

    def verify_receipt_order(self, runtime: Path | None):
        receipts = []
        for classification in ("L1", "L3"):
            ticket = self.call("POST", CONNECTORS + "/tickets", "generator", expected=201,
                               json={"resource_id": "generation", "classification": classification})
            path, raw = self.csv_file("generator", f"ORDER-{self.run_id}-{classification}", date(2026, 11, 1), ["1", "2", "3"])
            response = self.client.post(local_url(ticket["upload_url"]), data={"ticket": json.dumps(ticket["ticket"])},
                                        files={"file": (path.name, raw, "text/csv")})
            assert response.status_code == 201
            receipt = response.json()
            assert "settlement_summary" not in receipt
            receipts.append(receipt)
        older, newer = receipts
        assert older["version"] < newer["version"]
        latest = self.call("POST", CONNECTORS + "/receipts", "generator", expected=201, json=newer)
        late = self.call("POST", CONNECTORS + "/receipts", "generator", expected=201, json=older)
        assert latest["asset"]["asset_id"] == late["asset"]["asset_id"]
        catalog = self.call("GET", CONNECTORS + "/catalog", "generator")
        assert next(item for item in catalog["resources"] if item["resource_id"] == "generation")["current_version"] == newer["version"]
        if runtime:
            with sqlite3.connect((runtime / "platform.db").as_uri() + "?mode=ro", uri=True) as connection:
                record = connection.execute(
                    "SELECT a.sensitivity_level, v.version_no FROM data_assets a "
                    "JOIN data_asset_versions v ON v.version_id=a.current_version_id WHERE a.asset_id=?",
                    (latest["asset"]["asset_id"],),
                ).fetchone()
                assert record == ("L3", newer["version"])
        self.evidence["out_of_order_receipts"] = {"status": "PASSED", "older_version": older["version"],
            "current_version": newer["version"], "classification_checked_readonly": runtime is not None}
        self.save()

    def task_headers(self, role: str, task_id: str) -> dict[str, str]:
        response = self.client.get(self.base + "/api/settlement/tasks/" + task_id, headers=self.headers[role])
        assert response.status_code == 200
        return {"If-Match": response.headers["etag"]}

    def journey(self, index: int, generation: list[str], retail: list[str]):
        batch = f"INGRESS-{self.run_id}-{index}"
        start = date(2026, 10, index * 5 + 1)
        uploads = [self.upload("generator", batch, start, generation), self.upload("retailer", batch, start, retail)]
        catalog = self.call("GET", "/api/data/catalog", "exchange", params={"trade_batch_no": batch})
        for upload in uploads:
            entry = next(item for item in catalog["entries"] if item["owner_org_id"] == f"org-{upload['role']}-t01")
            assert entry["quality"]["period_start"] == start.isoformat()
            assert entry["quality"]["period_end"] == (start + timedelta(days=len(generation) - 1)).isoformat()
            assert entry["commitment_confirmed"] is True
        task_payload = {"task_name": f"新批次接入验收 {batch}", "trade_batch_no": batch,
                        "period_start": start.isoformat(), "period_end": (start + timedelta(days=len(generation) - 1)).isoformat(),
                        "rule_id": "rule-demo-business-v1", "participants": [
                            {"org_id": "org-generator-t01", "role_in_task": "GENERATOR"},
                            {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}],
                        "compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"}
        created = self.call("POST", "/api/settlement/tasks", "exchange", expected=201, json=task_payload)
        assert created["readiness"]["preflight_passed"] is True
        task_id = created["task_id"]
        run_body = {"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"}
        run = self.call("POST", f"/api/settlement/tasks/{task_id}/run", "exchange",
                        headers=self.task_headers("exchange", task_id), json=run_body)
        assert run["compute_job"]["status"] == "SUCCESS"
        rules = self.call("GET", "/api/rules", "exchange")
        params = next(rule["parameters_json"] for rule in rules if rule["rule_id"] == task_payload["rule_id"])
        gen, ret = sum(map(Decimal, generation)), sum(map(Decimal, retail))
        energy = min(gen, ret)
        deviation = abs(gen - ret)
        penalty = max(deviation - Decimal(str(params["deviation_threshold_mwh"])), Decimal(0)) * Decimal(str(params["deviation_penalty_rate"]))
        amount = energy * (Decimal(str(params["contract_price"])) - Decimal(str(params["service_fee_rate"]))) - penalty
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        computed = run["compute_job"]["result_json"]
        assert Decimal(str(computed["payable_amount_yuan"])) == amount
        assert Decimal(str(computed["deviation_penalty_yuan"])) == penalty.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        scoped = {item["org_id"]: item for item in run["results"] if item["result_scope"] == "ORG"}
        for role, direction in (("generator", "RECEIVABLE"), ("retailer", "PAYABLE")):
            result = scoped[f"org-{role}-t01"]
            assert Decimal(str(result["result_json"]["amount_yuan"])) == amount
            assert result["result_json"]["amount_direction"] == direction
            if role == "retailer":
                self.call("POST", f"/api/audit/reports/{run['report']['report_id']}/decision", "regulator",
                          json={"decision": "APPROVE", "opinion": "新批次接入 HTTP 验收复核"})
            confirmed = self.call("POST", f"/api/results/{result['result_id']}/confirm", role,
                                  headers=self.task_headers(role, task_id), json={"decision": "APPROVE", "opinion": "合成 CSV 独立金额核验通过"})
        assert confirmed["task"]["ttc"]["state"] == "ARCHIVED"
        assert confirmed["task"]["ttc"]["state_version"] == 13
        assert confirmed["formal_evidence"]["status"] == "PUBLISHED_DEMO"
        duplicate = self.call("POST", "/api/settlement/tasks", "exchange", expected=201,
                              json={**task_payload, "task_name": task_payload["task_name"] + " 重复阻断"})
        assert duplicate["readiness"]["preflight_passed"] is False
        duplicate_id = duplicate["task_id"]
        before = self.call("GET", f"/api/settlement/tasks/{duplicate_id}", "exchange")
        rejected = self.call("POST", f"/api/settlement/tasks/{duplicate_id}/run", "exchange", expected=409,
                             headers=self.task_headers("exchange", duplicate_id), json=run_body)
        assert rejected["detail"] == "该批次、期间及参与方已有结算任务，请勿重复结算"
        after = self.call("GET", f"/api/settlement/tasks/{duplicate_id}", "exchange")
        assert before["ttc"]["state"] == after["ttc"]["state"]
        assert before["ttc"]["state_version"] == after["ttc"]["state_version"]
        assert before["compute_summary"] == after["compute_summary"] is None
        assert before["result_count"] == after["result_count"] == 0
        self.evidence["batches"].append({"trade_batch_no": batch, "period_start": task_payload["period_start"],
            "period_end": task_payload["period_end"], "task_id": task_id, "uploads": uploads,
            "payable_amount_yuan": str(amount), "deviation_penalty_yuan": str(penalty),
            "state": "ARCHIVED", "state_version": 13, "duplicate_run_http": 409, "duplicate_state_unchanged": True})
        self.save()
        print(f"Batch {index}: ARCHIVED V13; independently verified amount {amount}; duplicate blocked", flush=True)

    def inspect_private_boundary(self, runtime: Path):
        with sqlite3.connect((runtime / "platform.db").as_uri() + "?mode=ro", uri=True) as connection:
            assert all(self.canary not in line for line in connection.iterdump())
        assert all(self.canary not in file.read_text(encoding="utf-8") for file in (runtime / "vault").rglob("*.json"))
        for role in ("generator", "retailer"):
            with sqlite3.connect((runtime / f"connector-{role}.db").as_uri() + "?mode=ro", uri=True) as connection:
                assert any(self.canary in line for line in connection.iterdump())
        self.evidence["raw_row_boundary"] = "PASSED: canary only in participant connectors, absent from platform DB and Vault"
        self.save()

    def save(self):
        (self.out / "http-evidence.json").write_text(json.dumps(self.evidence, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--out", required=True, type=project_path)
    parser.add_argument("--runtime", type=project_path, help="Optional isolated stack directory for read-only raw-row boundary check")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    runner = DemoJourney(args.base, args.out)
    try:
        runner.journey(1, ["10.1", "10.1", "10.1"], ["9.1", "9.1", "9.1"])
        runner.journey(2, ["100.123456", "100.2", "100.3"], ["50.123456", "50.2", "50.3"])
        runner.verify_rule_input_boundaries()
        runner.verify_receipt_order(args.runtime)
        if args.runtime:
            runner.inspect_private_boundary(args.runtime)
        print("Fresh-batch ingestion verification passed", flush=True)
    finally:
        runner.client.close()


if __name__ == "__main__":
    main()
