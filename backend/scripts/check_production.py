from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.is_file():
        raise RuntimeError(f"required file is missing: {relative_path}")
    return path.read_text(encoding="utf-8")


def require(text: str, pattern: str, message: str, findings: list[str]) -> None:
    if re.search(pattern, text, flags=re.MULTILINE) is None:
        findings.append(message)


def forbid(text: str, pattern: str, message: str, findings: list[str]) -> None:
    if re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE) is not None:
        findings.append(message)


def main() -> int:
    findings: list[str] = []
    compose = read("docker-compose.production.yml")
    config = read("backend/app/config.py")
    main_module = read("backend/app/main.py")
    schemas = read("backend/app/schemas.py")
    adapters = read("backend/app/services/adapters.py")
    production = read("backend/app/production.py")
    backend_dockerfile = read("backend/Dockerfile")

    require(compose, r"^\s*APP_ENV:\s*production\s*$", "production compose must set APP_ENV=production", findings)
    require(compose, r'^\s*TEST_FIXTURE_SEED:\s*["\']false["\']\s*$', "production compose must disable fixture seeding", findings)
    require(compose, r'^\s*TEST_COMPUTE_DELAY_MS:\s*["\']0["\']\s*$', "production compose must disable test compute delay", findings)
    require(compose, r"^\s*CORS_ORIGINS:\s*\$\{CORS_ORIGINS:\?", "production CORS origins must be explicitly supplied", findings)
    require(compose, r"^\s*OPA_LOCAL_FALLBACK:\s*\$\{OPA_LOCAL_FALLBACK:-false\}\s*$", "production compose must default OPA fallback to false", findings)
    forbid(compose, r"CORS_ORIGINS:.*(?:localhost|127\.0\.0\.1)", "production CORS must not default to a local origin", findings)

    require(config, r"def validate_runtime_settings", "runtime production validation is missing", findings)
    require(config, r"TEST_FIXTURE_SEED must be false", "fixture startup validation is missing", findings)
    require(config, r"OPA_LOCAL_FALLBACK must be false", "OPA fail-closed validation is missing", findings)
    require(main_module, r"validate_runtime_settings\(\)", "application startup must validate production settings", findings)
    require(main_module, r"assert_production_database_clean\(db, settings\)", "application startup must reject fixture databases", findings)
    require(production, r"NON_PRODUCTION_USERNAMES", "default account database guard is missing", findings)
    require(production, r"LOCAL_CONTROLLED_SETTLEMENT_V1", "compute record allowlist is missing", findings)
    require(production, r"LOCAL_EVIDENCE_LEDGER_V1", "evidence record allowlist is missing", findings)
    for module_path, forbidden_route in {
        "backend/app/routers/auth.py": "/test-users",
        "backend/app/routers/trade.py": "/settlement/import-and-run",
        "backend/app/routers/audit.py": "/anomalies/inject",
        "backend/app/routers/execution.py": "/example",
    }.items():
        forbid(read(module_path), rf'@router\.(?:get|post)\("{re.escape(forbidden_route)}"', f"production router still registers {forbidden_route}", findings)
    require(backend_dockerfile, r"FROM runtime AS production", "backend Dockerfile has no production target", findings)
    require(backend_dockerfile, r"rm -f /app/app/seed\.py /app/app/test_schemas\.py /app/app/routers/test_support\.py", "production image must remove fixture, test schema, and test route modules", findings)
    require(main_module, r'if settings\.app_env in \{"development", "test"\}:\s+from \.routers import test_support', "test account router is not environment-gated", findings)

    forbid(schemas, r'MPC_MOCK|SECRET_FLOW|SIMULATED_TEE', "production request schemas expose a simulated compute mode", findings)
    require(adapters, r'code = "LOCAL_CONTROLLED_SETTLEMENT_V1"', "controlled compute adapter is missing", findings)
    require(adapters, r'"implementation_status": "NOT_CONFIGURED"', "external privacy candidates must be marked not configured", findings)
    require(adapters, r'"cross_domain_non_export_verified": False', "cross-domain non-export must remain unverified", findings)
    require(adapters, r'"attestation_status": "NOT_PROVIDED"', "execution attestation must remain not provided", findings)
    workflow = read("backend/app/services/workflow.py")
    forbid(workflow, r'task\.status\s*=\s*"(?:AUTHORIZED|COMPUTING|EVIDENCED|FAILED)"', "settlement workflow contains a legacy task state", findings)

    frontend_root = ROOT / "frontend" / "src"
    if not frontend_root.is_dir():
        findings.append("frontend source directory is missing")
    else:
        frontend_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(frontend_root.rglob("*"))
            if path.is_file() and ".test." not in path.name
        )
        forbid(frontend_text, r"VITE_(?:DEMO|MOCK|ENV_LABEL)", "frontend contains a build-time demo/mock environment switch", findings)
        forbid(frontend_text, r"演示账号|默认账号|模拟计算", "frontend contains production-visible demo credentials or simulated compute copy", findings)
        require(frontend_text, r"ProductConfigProvider", "frontend white-label configuration provider is missing", findings)
        require(frontend_text, r"/public/config", "frontend does not load public runtime branding", findings)

    if findings:
        print("[production-guard] FAILED", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("[production-guard] PASS: production configuration and source boundaries are intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
