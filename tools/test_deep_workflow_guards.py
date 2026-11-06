"""Acceptance reports must distinguish exact demo blocking from other failures."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("deep_workflow_guards", Path(__file__).with_name("verify-deep-workflows.py"))
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


def evidence():
    before = {
        "task_id": "own-probe", "trade_batch_no": "DEMO-2026-08-E2E",
        "period_start": "2026-08-01", "period_end": "2026-08-31", "state_version": 1,
        "participants": [{"org_id": "org-generator-t01", "role_in_task": "GENERATOR"}, {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}],
    }
    seed = {**deepcopy(before), "task_id": "task-demo-business-e2e", "compute_summary": {"status": "SUCCESS"}}
    response = {"http_status": 409, "detail": "该批次、期间及参与方已有结算任务，请勿重复结算"}
    return before, deepcopy(before), seed, response


def test_exact_seeded_duplicate_is_a_valid_expected_block():
    workflow.validate_seeded_settlement_conflict(*evidence())


@pytest.mark.parametrize("condition", ["unrelated_conflict", "wrong_status", "different_seed", "same_task", "new_batch", "different_period", "different_party", "not_executed", "mutated_task"])
def test_unrelated_failures_and_changed_tasks_cannot_be_marked_expected(condition):
    before, after, seed, response = evidence()
    if condition == "unrelated_conflict":
        response["detail"] = "任务状态已经变化"
    elif condition == "wrong_status":
        response["http_status"] = 403
    elif condition == "different_seed":
        seed["task_id"] = "another-task"
    elif condition == "same_task":
        before["task_id"] = seed["task_id"]
    elif condition == "new_batch":
        before["trade_batch_no"] = seed["trade_batch_no"] = "NEW-BATCH"
    elif condition == "different_period":
        before["period_end"] = "2026-08-30"
    elif condition == "different_party":
        before["participants"][0]["org_id"] = "different-generator"
    elif condition == "not_executed":
        seed["compute_summary"]["status"] = "FAILED"
    else:
        after["state_version"] += 1
    with pytest.raises(workflow.CheckFailure):
        workflow.validate_seeded_settlement_conflict(before, after, seed, response)
