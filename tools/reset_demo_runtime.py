"""Safely reset only local demo runtime state and regenerate synthetic node data.

This script deliberately has no production mode.  It never touches source,
documentation, tests, or deployment configuration.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BACKEND_RUNTIME = BACKEND / "runtime"
LEGACY_RUNTIME = ROOT / "runtime"


def _safe_target(path: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(ROOT.resolve())
    return resolved


def _remove(path: Path) -> None:
    target = _safe_target(path)
    if target.is_dir():
        shutil.rmtree(target)
        print(f"removed directory: {target}")
    elif target.exists():
        target.unlink()
        print(f"removed file: {target}")


def _python_env(**updates: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({key: str(value) for key, value in updates.items()})
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(BACKEND), env.get("PYTHONPATH", "")]
    )
    return env


def _seed_backend() -> None:
    database_url = f"sqlite:///{(BACKEND_RUNTIME / 'hiddenchain.db').as_posix()}"
    code = (
        "from app.database import SessionLocal, ensure_runtime_schema; "
        "from app.demo_seed import seed_demo_catalog; "
        "ensure_runtime_schema(); "
        "db=SessionLocal(); seed_demo_catalog(db); db.close()"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=_python_env(
            APP_ENV="demo",
            DATABASE_URL=database_url,
            TEST_FIXTURE_SEED="false",
            DEMO_CATALOG_SEED="true",
            DEEPSEEK_ENABLED="false",
        ),
        check=True,
    )
    print(f"seeded backend demo database: {BACKEND_RUNTIME / 'hiddenchain.db'}")


def _seed_connector(*, domain: str, org_id: str, db_name: str) -> None:
    database_path = LEGACY_RUNTIME / db_name
    code = "from connector.app.main import _initialize; _initialize()"
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=_python_env(
            ENERGY_DOMAIN=domain,
            ORGANIZATION_ID=org_id,
            CONNECTOR_ID=f"node-{org_id}",
            CONNECTOR_NAME=f"{org_id}本地节点",
            CONNECTOR_DATABASE_PATH=str(database_path),
            CONNECTOR_SIGNING_PRIVATE_KEY=f"local-demo-reset-{org_id}",
            ALLOW_DEMO_KEY_REGISTRATION="true",
        ),
        check=True,
    )
    print(f"seeded local node database: {database_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="confirm deletion of the explicitly listed local demo runtime targets",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("refusing to reset runtime without --confirm")

    for target in (
        BACKEND_RUNTIME / "hiddenchain.db",
        BACKEND_RUNTIME / "vault",
        BACKEND_RUNTIME / "lineage" / "events.jsonl",
        LEGACY_RUNTIME / "hiddenchain.db",
        LEGACY_RUNTIME / "connector-electricity.db",
        LEGACY_RUNTIME / "connector-electricity-retailer.db",
        LEGACY_RUNTIME / "connector-electricity-exchange.db",
        LEGACY_RUNTIME / "connector-coal.db",
        LEGACY_RUNTIME / "connector-heat.db",
        LEGACY_RUNTIME / "connector-gas.db",
        LEGACY_RUNTIME / "connector-oil.db",
    ):
        _remove(target)

    (BACKEND_RUNTIME / "lineage").mkdir(parents=True, exist_ok=True)
    _seed_backend()
    for domain, org_id, db_name in (
        ("electricity", "org-generator-t01", "connector-electricity.db"),
        ("electricity", "org-retailer-t01", "connector-electricity-retailer.db"),
        ("electricity", "org-exchange-t01", "connector-electricity-exchange.db"),
        ("coal", "org-coal-t01", "connector-coal.db"),
        ("heat", "org-heat-t01", "connector-heat.db"),
        ("gas", "org-gas-t01", "connector-gas.db"),
        ("oil", "org-oil-t01", "connector-oil.db"),
    ):
        _seed_connector(domain=domain, org_id=org_id, db_name=db_name)
    print("demo runtime reset complete; all regenerated payloads are synthetic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
