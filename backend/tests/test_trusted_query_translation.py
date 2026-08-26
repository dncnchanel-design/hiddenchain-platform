from __future__ import annotations

from app.routers import trusted_query
from app.models import utc_now


def test_trusted_space_query_uses_manual_rules_when_deepseek_is_unavailable(client, auth_headers):
    response = client.post(
        "/api/trust-space/query/parse",
        headers=auth_headers["exchange"],
        json={"question": "查询2026年8月煤炭库存平均值"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "manual_rules"
    assert body["energy_domain"] == "coal"
    assert body["resource"] == "inventory"
    assert body["function"] == "average"
    assert body["requires_confirmation"] is True
    assert body["ready"] is True
    assert body["start_date"] == "2026-08-01"
    assert body["end_date"] == "2026-08-31"


def test_trusted_space_query_rejects_unknown_model_fields(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        trusted_query,
        "translate_trusted_space_query",
        lambda **_: {"payload": {"function": "drop_table"}},
    )
    response = client.post(
        "/api/trust-space/query/parse",
        headers=auth_headers["exchange"],
        json={"question": "查询煤炭库存"},
    )

    assert response.status_code == 422
    assert "翻译结果" in response.json()["detail"]


def test_trusted_space_query_gives_deepseek_the_reference_date(client, auth_headers, monkeypatch):
    captured: dict[str, object] = {}

    def translate(**kwargs):
        captured.update(kwargs)
        return {
            "payload": {
                "energy_domain": "oil",
                "resource": "inventory",
                "function": "trend",
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
                "region": None,
            },
            "provider": "deepseek",
            "model": "deepseek-test",
            "request_id": "req-test",
            "duration_ms": 12,
        }

    monkeypatch.setattr(trusted_query, "translate_trusted_space_query", translate)
    response = client.post(
        "/api/trust-space/query/parse",
        headers=auth_headers["exchange"],
        json={"question": "查询8月石油库存趋势"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "deepseek"
    assert response.json()["ready"] is True
    assert captured["context"]["today"] == utc_now().date().isoformat()
