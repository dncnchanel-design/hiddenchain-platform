from __future__ import annotations

ADMIN_ENDPOINT_SHAPES = {
    "/api/admin/overview": {
        "service_health",
        "counts",
        "security_boundary",
    },
    "/api/admin/system": {
        "organization_counts",
        "user_counts",
        "identity_counts",
        "node_counts",
        "technical_status",
        "security_boundary",
    },
    "/api/admin/agents": {
        "service_health",
        "identity_counts",
        "tool_counts",
        "permission_counts",
        "security_boundary",
    },
}

FORBIDDEN_ADMIN_PAYLOAD_KEYS = {
    "catalog",
    "applications",
    "requests",
    "tasks",
    "recent_tasks",
    "results",
    "audit_logs",
    "business_events",
    "agent_events",
    "instruction",
    "default_instruction",
    "prompt",
    "response",
    "details_json",
}


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value))
    return set()


def test_admin_safe_summaries_return_only_aggregate_dtos(client, auth_headers):
    for path, expected_keys in ADMIN_ENDPOINT_SHAPES.items():
        response = client.get(path, headers=auth_headers["admin"])

        assert response.status_code == 200, response.text
        payload = response.json()
        assert set(payload) == expected_keys
        assert not (_all_keys(payload) & FORBIDDEN_ADMIN_PAYLOAD_KEYS)
        assert not any(isinstance(value, list) for value in payload.values())


def test_admin_safe_summaries_reject_every_non_admin(client, auth_headers):
    headers = dict(auth_headers)
    for username in ("coal", "gas"):
        login = client.post(
            "/api/auth/login",
            json={"username": username, "password": f"{username}123"},
        )
        assert login.status_code == 200, login.text
        headers[username] = {"Authorization": f"Bearer {login.json()['access_token']}"}

    for actor in ("generator", "retailer", "coal", "heat", "gas", "oil", "exchange", "regulator"):
        for path in ADMIN_ENDPOINT_SHAPES:
            response = client.get(path, headers=headers[actor])

            assert response.status_code == 403


def test_admin_session_contains_only_management_routes(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers["admin"])

    assert response.status_code == 200, response.text
    assert {item["path"] for item in response.json()["menus"]} == {
        "/overview",
        "/system",
        "/agents",
        "/metrics",
        "/logs",
    }
