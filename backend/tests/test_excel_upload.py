from __future__ import annotations

from pathlib import Path


SAMPLE_XLSX = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "public"
    / "sample-data"
    / "hiddenchain-excel-batch-data.xlsx"
)
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sample_file() -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("hiddenchain-sample.xlsx", SAMPLE_XLSX.read_bytes(), XLSX_MIME)}


def test_excel_validation_covers_ten_sheets_and_one_thousand_rows(client, auth_headers):
    response = client.post(
        "/api/data/uploads/excel/validate",
        headers=auth_headers["admin"],
        files=_sample_file(),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is True
    assert payload["sheet_count"] == 10
    assert payload["row_count"] == 1000
    assert [item["row_count"] for item in payload["sheets"]] == [100] * 10
    assert payload["errors"] == []


def test_excel_import_is_atomic_and_idempotent(client, auth_headers):
    first = client.post(
        "/api/data/uploads/excel/import",
        headers=auth_headers["admin"],
        files=_sample_file(),
    )
    assert first.status_code == 200, first.text
    assert first.json()["imported_count"] == 1000
    assert first.json()["idempotent_replay"] is False

    replay = client.post(
        "/api/data/uploads/excel/import",
        headers=auth_headers["admin"],
        files=_sample_file(),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["imported_count"] == 0
    assert replay.json()["idempotent_replay"] is True

    records = client.get("/api/data/uploads", headers=auth_headers["admin"])
    assert records.status_code == 200
    imported = [item for item in records.json() if item.get("summary_json", {}).get("excel_import")]
    assert len(imported) == 1000
    assert all(item["raw_payload_exposed"] is False for item in imported)


def test_excel_import_keeps_role_boundary_and_writes_nothing_on_validation_error(client, auth_headers):
    before = client.get("/api/data/uploads", headers=auth_headers["generator"])
    assert before.status_code == 200
    before_count = len(before.json())

    validation = client.post(
        "/api/data/uploads/excel/validate",
        headers=auth_headers["generator"],
        files=_sample_file(),
    )
    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert validation.json()["errors"]

    rejected = client.post(
        "/api/data/uploads/excel/import",
        headers=auth_headers["generator"],
        files=_sample_file(),
    )
    assert rejected.status_code == 422

    after = client.get("/api/data/uploads", headers=auth_headers["generator"])
    assert after.status_code == 200
    assert len(after.json()) == before_count
