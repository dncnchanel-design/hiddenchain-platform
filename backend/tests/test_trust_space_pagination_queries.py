from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import event, select

from app.database import SessionLocal, engine
from app.models import AuditLog, AuditReport, PrivacyComputeJob, SettlementResult, User
from app.services import trust_space


@contextmanager
def _count_sql_statements():
    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)


def test_large_trust_space_lists_are_stable_and_query_bounded(client, auth_headers):
    same_time = datetime(2099, 1, 1, 0, 0, 0)
    with SessionLocal() as db:
        generator = db.scalar(select(User).where(User.username == "generator"))
        oil_user = db.scalar(select(User).where(User.username == "oil"))
        regulator = db.scalar(select(User).where(User.username == "regulator"))
        assert generator is not None and oil_user is not None and regulator is not None

        db.add_all(
            [
                PrivacyComputeJob(
                    job_id=f"job-page-{index:03d}",
                    task_id="task-ready-t01",
                    algorithm_code="PAGINATION_TEST",
                    input_hashes_json=[],
                    result_json={"index": index},
                    status="SUCCESS",
                    progress=100,
                    privacy_guarantees_json={"raw_data_exposed": False},
                    created_at=same_time,
                )
                for index in range(130)
            ]
        )
        db.add_all(
            [
                SettlementResult(
                    result_id=f"result-page-{index:03d}",
                    task_id="task-ready-t01",
                    org_id=generator.org_id,
                    result_scope="PAGINATION_TEST",
                    result_json={"index": index},
                    result_hash=f"result-hash-{index:03d}",
                    confirm_status="UNCONFIRMED",
                    created_at=same_time,
                )
                for index in range(130)
            ]
        )
        db.add_all(
            [
                AuditReport(
                    report_id=f"report-page-{index:03d}",
                    task_id="task-ready-t01",
                    template_code="PAGINATION_TEST",
                    report_title=f"report {index}",
                    report_content="bounded pagination fixture",
                    report_hash=f"report-hash-{index:03d}",
                    risk_level="LOW",
                    evidence_refs_json=[],
                    created_at=same_time,
                )
                for index in range(130)
            ]
        )
        db.add_all(
            [
                AuditLog(
                    log_id=f"log-page-{index:03d}",
                    occurred_at=same_time,
                    actor_user_id=generator.user_id,
                    actor_org_id=generator.org_id,
                    actor_name=generator.display_name,
                    action_code="PAGINATION_TEST",
                    target_type="SETTLEMENT_TASK",
                    target_id="task-ready-t01",
                    result="SUCCESS",
                    trace_id=f"trace-page-{index:03d}",
                    details_json={"index": index},
                )
                for index in range(130)
            ]
        )
        db.commit()

        with _count_sql_statements() as computation_sql:
            computation_page = trust_space.computation_list(
                db, generator, page=2, page_size=25
            )
        assert len(computation_sql) <= 3
        assert [item["job_id"] for item in computation_page["items"]] == [
            f"job-page-{index:03d}" for index in range(104, 79, -1)
        ]

        with _count_sql_statements() as result_sql:
            result_page = trust_space.result_list(db, generator, page=2, page_size=25)
        assert len(result_sql) <= 2
        assert [item["result_id"] for item in result_page["items"]] == [
            f"result-page-{index:03d}" for index in range(104, 79, -1)
        ]
        filtered_results = trust_space.result_list(
            db,
            generator,
            page=1,
            page_size=100,
            task_id="task-ready-t01",
        )
        assert filtered_results["total"] >= 130
        assert {item["task_id"] for item in filtered_results["items"]} == {
            "task-ready-t01"
        }
        denied_results = trust_space.result_list(
            db,
            oil_user,
            task_id="task-ready-t01",
        )
        assert denied_results["total"] == 0
        assert denied_results["items"] == []

        with _count_sql_statements() as audit_sql:
            audit_page = trust_space.audit_list(db, regulator, page=6, page_size=25)
        assert len(audit_sql) <= 4
        assert any("UNION ALL" in statement.upper() for statement in audit_sql)
        assert any(
            "LIMIT" in statement.upper() and "OFFSET" in statement.upper()
            for statement in audit_sql
        )
        assert [item["record_id"] for item in audit_page["items"]] == [
            *[f"report-page-{index:03d}" for index in range(4, -1, -1)],
            *[f"log-page-{index:03d}" for index in range(129, 109, -1)],
        ]

        repeated = trust_space.audit_list(db, regulator, page=6, page_size=25)
        assert [item["record_id"] for item in repeated["items"]] == [
            item["record_id"] for item in audit_page["items"]
        ]

    for path in ("computations", "results", "audit"):
        response = client.get(
            f"/api/trust-space/{path}?page_size=101",
            headers=auth_headers["regulator" if path == "audit" else "generator"],
        )
        assert response.status_code == 422

    filtered_response = client.get(
        "/api/trust-space/results?task_id=task-ready-t01&page_size=100",
        headers=auth_headers["generator"],
    )
    assert filtered_response.status_code == 200
    assert filtered_response.json()["total"] >= 130
    assert {item["task_id"] for item in filtered_response.json()["items"]} == {
        "task-ready-t01"
    }
    denied_response = client.get(
        "/api/trust-space/results?task_id=task-ready-t01",
        headers=auth_headers["oil"],
    )
    assert denied_response.status_code == 200
    assert denied_response.json()["total"] == 0
    assert denied_response.json()["items"] == []
