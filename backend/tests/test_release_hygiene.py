from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import RUNTIME_DIR, Settings, VAULT_DIR
from app.production import assert_production_runtime_clean


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_production_env_is_excluded_from_git_and_docker_context() -> None:
    gitignore = _read(".gitignore").splitlines()
    dockerignore = _read(".dockerignore").splitlines()

    assert ".env.production" in gitignore
    assert ".env.*" in gitignore
    assert "*.env" in gitignore
    assert ".agents/" in gitignore
    assert "AGENTS.md" in gitignore
    assert ".env.production" in dockerignore
    assert ".env.*" in dockerignore
    assert "*.env" in dockerignore
    assert "AGENTS.md" in dockerignore
    assert "backend/frontend_dist/" in gitignore
    assert "backend/*.db-*" in gitignore
    for database_pattern in (
        "*.db",
        "*.db-*",
        "*.sqlite",
        "*.sqlite-*",
        "*.sqlite3",
        "*.sqlite3-*",
    ):
        assert database_pattern in gitignore
    assert "backend/frontend_dist" in dockerignore
    for local_artifact in ("output", "outputs", "qa", "release", "tmp"):
        assert local_artifact in dockerignore


def test_backend_tests_use_a_session_vault_outside_shared_runtime_vault() -> None:
    """Fixture seeding must never append payloads to the shared demo Vault."""
    assert VAULT_DIR.resolve() != (RUNTIME_DIR / "vault").resolve()
    assert VAULT_DIR.resolve().is_relative_to(RUNTIME_DIR.resolve())
    assert VAULT_DIR.name == "vault"


def test_internal_agent_metadata_and_env_suffix_files_are_git_ignored() -> None:
    if shutil.which("git") is None or not (PROJECT_ROOT / ".git").exists():
        pytest.skip("Git worktree is unavailable")

    expected_ignored_paths = {
        "AGENTS.md",
        ".agents/session.json",
        "secrets.env",
        "frontend/secrets.env",
    }
    ignored = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            *sorted(expected_ignored_paths),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ignored.returncode == 0, ignored.stderr
    assert set(ignored.stdout.splitlines()) == expected_ignored_paths

    tracked = subprocess.run(
        ["git", "ls-files", "--", "AGENTS.md", ".agents"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.returncode == 0, tracked.stderr
    assert tracked.stdout.strip() == ""


def test_development_env_example_uses_current_environment_switches() -> None:
    example = _read(".env.example")

    for name in (
        "APP_ENV",
        "TEST_FIXTURE_SEED",
        "DEMO_CATALOG_SEED",
        "DEMO_BUSINESS_SEED",
        "TEST_COMPUTE_DELAY_MS",
    ):
        assert re.search(rf"^{name}=", example, flags=re.MULTILINE)
    assert "DEMO_SEED=" not in example
    assert "MOCK_DELAY_MS=" not in example


def test_production_compose_requires_subject_connector_identity() -> None:
    compose = _read("docker-compose.production.yml")

    for name in (
        "SUBJECT_NODE_ENDPOINTS_JSON",
        "SUBJECT_NODE_BROWSER_ENDPOINTS_JSON",
        "SUBJECT_NODE_IDS_JSON",
        "SUBJECT_NODE_PUBLIC_KEYS_JSON",
        "PLATFORM_SIGNING_PRIVATE_KEY",
    ):
        assert re.search(rf"^\s*{name}:\s*\$\{{{name}:\?", compose, flags=re.MULTILINE)
    assert 'DEMO_CATALOG_SEED: "false"' in compose
    assert 'DEMO_BUSINESS_SEED: "false"' in compose
    for name in (
        "SUBJECT_NODE_PUBLIC_KEY_RINGS_JSON",
        "DID_WALLET_BINDINGS_JSON",
        "BRAND_THEME_ID",
        "BRAND_PRIMARY",
    ):
        assert re.search(rf"^\s*{name}:", compose, flags=re.MULTILINE)
    assert "${CLOUDFLARE_TUNNEL_TOKEN:-}" in compose
    assert "${PUBLIC_DOMAIN:-}" in compose
    assert "${CLOUDFLARE_TUNNEL_TOKEN:?" not in compose
    assert "${PUBLIC_DOMAIN:?" not in compose


@pytest.mark.parametrize(
    ("profile", "tunnel_token", "public_domain"),
    (
        (None, "", "power.example.com"),
        (None, "test-tunnel-token", ""),
        ("direct-domain", "", "power.example.com"),
        ("cloudflare", "test-tunnel-token", ""),
    ),
)
def test_compose_does_not_require_inactive_profile_settings(
    profile: str | None,
    tunnel_token: str,
    public_domain: str,
) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose CLI is unavailable")
    if subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        check=False,
    ).returncode:
        pytest.skip("Docker Compose plugin is unavailable")

    command = [
        "docker",
        "compose",
        "--env-file",
        "production.env.example",
        "-f",
        "docker-compose.production.yml",
    ]
    if profile:
        command.extend(("--profile", profile))
    command.extend(("config", "--quiet"))
    environment = os.environ.copy()
    environment.update(
        {
            "CLOUDFLARE_TUNNEL_TOKEN": tunnel_token,
            "PUBLIC_DOMAIN": public_domain,
        }
    )

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_windows_installer_requires_only_the_selected_profile_setting() -> None:
    installer = _read("install-windows.ps1")

    assert re.search(
        r'if \(\$Profile -eq "DirectDomain"\) \{\s*Require-ProfileSetting '
        r'\$envFile "PUBLIC_DOMAIN"',
        installer,
    )
    assert re.search(
        r'elseif \(\$Profile -eq "Cloudflare"\) \{\s*Require-ProfileSetting '
        r'\$envFile "CLOUDFLARE_TUNNEL_TOKEN"',
        installer,
    )


def test_render_subject_endpoints_match_deployed_subdomains_and_main_branch() -> None:
    render = _read("render.yaml")

    assert '"org-retailer-t01":"https://hiddenchain-electricity-retailer.onrender.com"' in render
    assert '"org-exchange-t01":"https://hiddenchain-electricity-exchange.onrender.com"' in render
    assert "https://hiddenchain-electricity-retailer-connector.onrender.com" not in render
    assert "https://hiddenchain-electricity-exchange-connector.onrender.com" not in render
    assert render.count("branch: main") == 8
    assert render.count("autoDeployTrigger: checksPass") == 8
    assert "SUBJECT_NODE_BROWSER_ENDPOINTS_JSON" in render
    assert "SUBJECT_NODE_IDS_JSON" in render
    for org_id in (
        "org-generator-t01",
        "org-retailer-t01",
        "org-exchange-t01",
        "org-coal-t01",
        "org-heat-t01",
        "org-gas-t01",
        "org-oil-t01",
    ):
        assert f"value: local-node-{org_id}" in render
    assert render.count("key: CONNECTOR_CORS_ORIGINS") == 7
    assert render.count("key: CONNECTOR_SEED_SYNTHETIC_DATA") == 7


def test_local_compose_exposes_browser_direct_connector_endpoints() -> None:
    compose = _read("docker-compose.yml")

    assert "SUBJECT_NODE_BROWSER_ENDPOINTS_JSON" in compose
    assert '"127.0.0.1:5173:8080"' in compose
    assert '"5173:80"' not in compose
    for port in range(8101, 8108):
        assert f'"127.0.0.1:{port}:8000"' in compose
    for org_id in (
        "org-generator-t01",
        "org-retailer-t01",
        "org-exchange-t01",
        "org-coal-t01",
        "org-heat-t01",
        "org-gas-t01",
        "org-oil-t01",
    ):
        assert f"CONNECTOR_ID: local-node-{org_id}" in compose
    assert compose.count('CONNECTOR_SEED_SYNTHETIC_DATA: "true"') == 7


def test_frontend_runtime_contract_pins_tooling_and_static_cache_policy() -> None:
    package = json.loads(_read("frontend/package.json"))
    nginx = _read("frontend/nginx.conf")
    application = _read("backend/app/main.py")

    assert package["packageManager"] == "pnpm@11.19.0"
    assert "listen 8080;" in nginx
    assert "gzip on;" in nginx
    assert 'Cache-Control "public, max-age=31536000, immutable"' in nginx
    assert 'Cache-Control "no-cache, must-revalidate"' in nginx
    assert "app.add_middleware(GZipMiddleware, minimum_size=1024)" in application
    assert 'path.startswith("/assets/")' in application
    assert '"public, max-age=31536000, immutable"' in application
    assert '"no-cache, must-revalidate"' in application
    assert "requested.is_relative_to(frontend_root)" in application


def test_windows_package_includes_its_declared_entry_documents() -> None:
    packager = _read("tools/package-windows.ps1")

    for name in ("JUDGE_DEPLOYMENT.md", "JUDGE_DEPLOYMENT.tex", "SOURCE_CODE_GUIDE.md"):
        assert f'"{name}"' in packager
    assert "\\.(?:db|sqlite|sqlite3)(?:-.+)?$" in packager
    assert '".pem", ".key", ".p12", ".pfx", ".ppk", ".jks", ".keystore", ".der"' in packager
    assert '"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"' in packager
    assert '"frontend_dist"' in packager
    assert "^\\.env(?:\\..+)?$" in packager
    assert "\\.env$" in packager
    assert '"render.yaml"' in packager
    assert '"frontend\\.dockerignore"' in packager
    assert '".github\\workflows"' in packager
    assert '".yml", ".yaml"' in packager
    assert '"PRODUCTION_AGENT_PROVISIONING.example.json"' in packager


def test_release_docs_declare_packaged_ci_workflows() -> None:
    manifest = _read("RELEASE_MANIFEST.md")
    guide = _read("SOURCE_CODE_GUIDE.md")

    assert "`.github/workflows/`" in manifest
    assert "`.github/workflows/`" in guide


def test_release_manifest_declares_production_agent_provisioning_example() -> None:
    manifest = _read("RELEASE_MANIFEST.md")

    assert "`docs/PRODUCTION_AGENT_PROVISIONING.example.json`" in manifest
    assert "示例" in manifest


def test_production_guard_files_exist_in_both_backend_build_contexts() -> None:
    for dockerfile_name in ("Dockerfile", "backend/Dockerfile"):
        dockerfile = _read(dockerfile_name)
        for required_file in (".gitignore", ".dockerignore", "render.yaml"):
            assert f"COPY {required_file} {required_file}" in dockerfile

    frontend_dockerignore = _read("frontend/.dockerignore").splitlines()
    for forbidden_context_item in (
        ".env",
        ".env.*",
        "*.env",
        "node_modules",
        "dist",
        "coverage",
        "*.pem",
        "*.key",
    ):
        assert forbidden_context_item in frontend_dockerignore


def test_production_runtime_guard_rejects_existing_central_vault(tmp_path: Path) -> None:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    (vault_dir / "payload.json").write_text("do-not-read", encoding="utf-8")

    with pytest.raises(RuntimeError, match="central vault"):
        assert_production_runtime_clean(Settings(app_env="production"), vault_dir=vault_dir)


def test_production_runtime_guard_allows_empty_or_nonproduction_vault(tmp_path: Path) -> None:
    empty_vault = tmp_path / "empty"
    empty_vault.mkdir()
    assert_production_runtime_clean(Settings(app_env="production"), vault_dir=empty_vault)

    development_vault = tmp_path / "development"
    development_vault.mkdir()
    (development_vault / "payload.json").write_text("fixture", encoding="utf-8")
    assert_production_runtime_clean(Settings(app_env="development"), vault_dir=development_vault)
