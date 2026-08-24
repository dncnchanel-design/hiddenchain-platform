from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import VAULT_DIR, settings
from ..security import sha256_json, sign_value


class LocalDomainVault:
    """Single-process simulation of isolated enterprise data domains.

    The business database only stores ``vault://`` references and commitments.
    Replacing this class with EDC-backed provider endpoints does not change the
    workflow contracts.
    """

    scheme = "vault://"

    @classmethod
    def write(cls, org_id: str, upload_id: str, payload: dict[str, Any]) -> tuple[str, str, str]:
        if settings.app_env == "production":
            raise RuntimeError("CENTRAL_RAW_VAULT_WRITE_BLOCKED")
        directory = VAULT_DIR / org_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{upload_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        data_hash = sha256_json(payload)
        commitment = sign_value({"org_id": org_id, "upload_id": upload_id, "hash": data_hash}, org_id)
        return f"{cls.scheme}{org_id}/{upload_id}", data_hash, commitment

    @classmethod
    def read(cls, data_ref: str) -> dict[str, Any]:
        if settings.app_env == "production":
            raise RuntimeError("CENTRAL_RAW_VAULT_READ_BLOCKED")
        if not data_ref.startswith(cls.scheme):
            raise ValueError("Unsupported data reference")
        relative = data_ref.removeprefix(cls.scheme)
        parts = Path(relative).parts
        if len(parts) != 2 or any(part in {".", ".."} for part in parts):
            raise ValueError("Invalid data reference")
        path = VAULT_DIR / parts[0] / f"{parts[1]}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @classmethod
    def delete(cls, data_ref: str) -> None:
        """Remove one newly-created local-domain object during transaction rollback."""
        if not data_ref.startswith(cls.scheme):
            return
        relative = data_ref.removeprefix(cls.scheme)
        parts = Path(relative).parts
        if len(parts) != 2 or any(part in {".", ".."} for part in parts):
            return
        path = VAULT_DIR / parts[0] / f"{parts[1]}.json"
        if path.is_file():
            path.unlink()
