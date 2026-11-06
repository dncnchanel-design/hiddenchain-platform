from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.routers import trade


def test_parallel_participant_confirmations_preserve_version_and_finalization(client, auth_headers, monkeypatch):
    """Stale confirmations must retry, rather than losing the aggregate update."""
    task_id = "task-history-t01"
    url = f"/api/settlement/tasks/{task_id}"
    results = client.get(f"/api/settlement/results?task_id={task_id}", headers=auth_headers["exchange"]).json()
    result_ids = {item["org_id"]: item["result_id"] for item in results if item["result_scope"] == "ORG"}
    report = next(item for item in client.get("/api/audit/reports", headers=auth_headers["regulator"]).json() if item["task_id"] == task_id)
    approval = client.post(f"/api/audit/reports/{report['report_id']}/decision", headers=auth_headers["regulator"], json={"decision": "APPROVE", "opinion": "同意审计"})
    assert approval.status_code == 200, approval.text
    current = client.get(url, headers=auth_headers["exchange"])
    etag = current.headers["etag"]
    gate = Barrier(2, timeout=20)
    original_assert = trade._assert_if_match

    def synchronized_check(task, expected):
        original_assert(task, expected)
        if task.task_id == task_id:
            gate.wait()

    monkeypatch.setattr(trade, "_assert_if_match", synchronized_check)

    def confirm(role):
        result_id = result_ids[f"org-{role}-t01"]
        response = client.post(f"/api/results/{result_id}/confirm", headers={**auth_headers[role], "If-Match": etag}, json={"decision": "APPROVE", "opinion": "同意结算"})
        return role, response

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(confirm, ("generator", "retailer")))
    monkeypatch.setattr(trade, "_assert_if_match", original_assert)
    state = client.get(url, headers=auth_headers["exchange"])
    assert sorted(response.status_code for _, response in responses) == [200, 412], {
        "responses": [(role, response.status_code) for role, response in responses],
        "task_status": state.json()["status"],
        "ttc_state": state.json()["ttc"]["state"],
    }
    losing_role = next(role for role, response in responses if response.status_code == 412)
    retried = client.post(f"/api/results/{result_ids[f'org-{losing_role}-t01']}/confirm", headers={**auth_headers[losing_role], "If-Match": state.headers["etag"]}, json={"decision": "APPROVE", "opinion": "同意结算"})
    assert retried.status_code == 200, retried.text
    assert retried.json()["task"]["ttc"]["state"] == "ARCHIVED"
    assert retried.json()["formal_evidence"]["status"] == "PUBLISHED_DEMO"
