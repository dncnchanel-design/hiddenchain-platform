"""Assistant and native report lists share the current-attempt audit boundary."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal, engine
from app.main import app
from app.models import AuditReport, Base, Organization, SettlementRule, SettlementTask, User
from app.security import create_access_token
from app.services.assistant_catalog import read_action, target_candidates
from app.services.rate_limit import limiter
from app.trust_models import TtcAttempt


@pytest.fixture(autouse=True)
def reset_test_database():
    limiter.reset()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for org_id in ("exchange", "foreign", "regulator", "ungranted", "no-audit", "admin"):
            db.add(Organization(org_id=org_id, org_name=org_id, org_type="EXCHANGE" if org_id in {"exchange", "foreign"} else "REGULATOR",
                                energy_domain="electricity"))
        db.flush()
        for account, role, permissions in (
            ("exchange", "EXCHANGE", ["VIEW_AUDIT"]),
            ("regulator", "REGULATOR", ["VIEW_AUDIT", "VIEW_AUDIT:TASK:rework"]),
            ("ungranted", "REGULATOR", ["VIEW_AUDIT"]),
            ("no-audit", "REGULATOR", ["VIEW_AUDIT:TASK:rework"]),
            ("admin", "ADMIN", ["VIEW_AUDIT", "VIEW_AUDIT:ALL"]),
        ):
            db.add(User(user_id=account, org_id=account, username=account, password_hash="unused",
                        display_name=account, role_code=role, permissions_json=permissions))
        db.add(SettlementRule(rule_id="rule", rule_name="rule", rule_version="1", formula_dsl="{}", rule_hash="a" * 64))
        db.flush()
        for task_id, creator, current in (("rework", "exchange", 2), ("foreign", "foreign", 1), ("unstarted", "exchange", 0)):
            db.add(SettlementTask(task_id=task_id, capsule_id=task_id, task_name=task_id, trade_batch_no=task_id,
                                  period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
                                  creator_org_id=creator, rule_id="rule", current_attempt=current))
        db.flush()
        for attempt_id, task_id, number in (("old", "rework", 1), ("current", "rework", 2), ("foreign", "foreign", 1)):
            db.add(TtcAttempt(attempt_id=attempt_id, task_id=task_id, capsule_id=task_id, attempt_no=number,
                              current_state="REWORK" if attempt_id == "old" else "RESULT_CONFIRM",
                              status="INTERRUPTED" if attempt_id == "old" else "COMPLETED", trace_id=attempt_id))
        db.flush()
        for report_id, task_id, attempt_id in (
            ("old-report", "rework", "old"), ("current-report", "rework", "current"),
            ("unbound-report", "rework", None), ("cross-bound-report", "rework", "foreign"),
            ("foreign-report", "foreign", "foreign"), ("unstarted-report", "unstarted", None),
        ):
            db.add(AuditReport(report_id=report_id, task_id=task_id, attempt_id=attempt_id,
                               template_code="AUDIT", report_title=report_id, report_content="private-report-body",
                               report_hash="b" * 64, risk_level="LOW"))
        db.commit()
    yield
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def http():
    client = TestClient(app)
    yield client
    client.close()


def _native(http, account):
    with SessionLocal() as db:
        user = db.get(User, account)
        token = create_access_token(user.user_id, user.role_code, user.org_id)
    return http.get("/api/audit/reports", headers={"Authorization": "Bearer " + token})


def _assert_matching_lists(db, http, account, expected):
    native = _native(http, account)
    assert native.status_code == 200, native.text
    assert {row["report_id"] for row in native.json()} == expected
    assistant = read_action(db, db.get(User, account), "LIST_AUDIT_REPORTS")
    assert assistant["status"] == "SUCCEEDED"
    assert assistant["total"] == len(expected)
    assert {row["report_id"] for row in assistant["items"]} == expected
    assert "private-report-body" not in str(assistant)


def test_rework_current_attempt_lists_and_candidates_exclude_old_unbound_and_cross_bound_reports(http):
    with SessionLocal() as db:
        _assert_matching_lists(db, http, "regulator", {"current-report"})
        actor = db.get(User, "regulator")
        candidates = target_candidates(db, actor, "EXPLAIN_AUDIT")
        assert {row["entity_id"] for row in candidates if row["entity_type"] == "audit_report"} == {"current-report"}
        assert db.scalar(select(func.count(AuditReport.report_id))) == 6  # Historical records stay intact.
        task = db.get(SettlementTask, "rework")
        task.current_attempt = 1
        db.commit()
        _assert_matching_lists(db, http, "regulator", {"old-report"})
        task.current_attempt = 2
        db.commit()
        _assert_matching_lists(db, http, "regulator", {"current-report"})


def test_report_lists_recheck_explicit_scope_global_grants_and_revoked_permission(http):
    with SessionLocal() as db:
        _assert_matching_lists(db, http, "ungranted", set())
        actor = db.get(User, "regulator")
        actor.permissions_json = ["VIEW_AUDIT", "VIEW_AUDIT:ALL"]
        db.commit()
        _assert_matching_lists(db, http, "regulator", {"current-report", "foreign-report"})
        actor.permissions_json = ["VIEW_AUDIT:ALL"]
        db.commit()
        assert _native(http, "regulator").status_code == 403
        assert read_action(db, actor, "LIST_AUDIT_REPORTS")["error_code"] == "AUDIT_SCOPE_DENIED"
        assert target_candidates(db, actor, "EXPLAIN_AUDIT") == []


@pytest.mark.parametrize("account", ["no-audit", "admin"])
def test_role_or_missing_audit_permission_cannot_expose_reports(http, account):
    assert _native(http, account).status_code == 403
    with SessionLocal() as db:
        output = read_action(db, db.get(User, account), "LIST_AUDIT_REPORTS")
        assert output["status"] == "BLOCKED" and "items" not in output
