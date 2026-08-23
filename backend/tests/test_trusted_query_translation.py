from __future__ import annotations

from app.routers import trusted_query


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
    assert body["ready"] is False
    assert body["start_date"] is None


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
