#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings, validate_runtime_settings  # noqa: E402
from app.database import (  # noqa: E402
    SessionLocal,
    database_readiness,
    ensure_runtime_schema,
)
from app.production import assert_production_database_clean  # noqa: E402
from app.services.agent_provisioning import (  # noqa: E402
    AgentProvisioningError,
    load_production_agent_manifest,
    provision_production_agents,
)


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Provision production Agent identities and grants from an explicit JSON manifest."
        )
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to the read-only production Agent manifest.",
    )
    return parser.parse_args(argv)


def run(manifest_path: Path) -> dict[str, object]:
    if settings.app_env != "production":
        raise AgentProvisioningError("APP_ENV must be production")
    validate_runtime_settings(settings)
    manifest = load_production_agent_manifest(manifest_path)
    ensure_runtime_schema()
    with SessionLocal() as db:
        try:
            assert_production_database_clean(db, settings)
            agent_result = provision_production_agents(db, manifest)
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {
        "status": "READY",
        "database": database_readiness(),
        "agents": agent_result,
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _arguments(argv)
    try:
        result = run(arguments.manifest)
    except (AgentProvisioningError, RuntimeError) as exc:
        print(
            json.dumps(
                {"status": "FAILED", "error": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {"status": "FAILED", "error": "unexpected provisioning failure"},
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
