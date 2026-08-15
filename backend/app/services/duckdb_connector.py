from __future__ import annotations

import importlib.util
from typing import Any

from ..security import sha256_json


class DuckDBMetadataAdapter:
    """Run fixed, in-memory analytics over catalog metadata only.

    DuckDB is deliberately kept behind this adapter. The adapter accepts the
    already-sanitized catalog projection, never accepts SQL from a caller and
    never registers a Vault or business-data relation.
    """

    code = "DUCKDB_METADATA_ANALYTICS"
    version = "1.5.5"
    _QUERY = """
        SELECT asset_type,
               COUNT(*)::BIGINT AS product_count,
               COALESCE(SUM(record_count), 0)::BIGINT AS advertised_record_count,
               SUM(CASE WHEN sensitivity_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END)::BIGINT
                   AS sensitive_product_count
        FROM catalog_metadata
        GROUP BY asset_type
        ORDER BY asset_type
    """

    @classmethod
    def status(cls) -> dict[str, Any]:
        installed = importlib.util.find_spec("duckdb") is not None
        return {
            "code": cls.code,
            "version": cls.version,
            "installed": installed,
            "mode": "IN_MEMORY_METADATA_ONLY",
            "read_only_query": True,
            "raw_data_exposed": False,
        }

    @classmethod
    def summarize(cls, entries: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            import duckdb
        except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover - dependency is pinned
            raise RuntimeError("DUCKDB_NOT_INSTALLED") from exc

        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute(
                """
                CREATE TABLE catalog_metadata (
                    asset_type VARCHAR,
                    sensitivity_level VARCHAR,
                    record_count BIGINT,
                    validation_status VARCHAR
                )
                """
            )
            rows = [
                (
                    str(entry.get("asset_type") or "UNKNOWN"),
                    str(entry.get("sensitivity_level") or "UNKNOWN"),
                    int((entry.get("quality") or {}).get("record_count") or 0),
                    str((entry.get("quality") or {}).get("validation_status") or "UNKNOWN"),
                )
                for entry in entries
            ]
            if rows:
                connection.executemany(
                    "INSERT INTO catalog_metadata VALUES (?, ?, ?, ?)",
                    rows,
                )
            groups = [
                {
                    "asset_type": row[0],
                    "product_count": int(row[1]),
                    "advertised_record_count": int(row[2]),
                    "sensitive_product_count": int(row[3]),
                }
                for row in connection.execute(cls._QUERY).fetchall()
            ]
            return {
                **cls.status(),
                "resource_count": len(entries),
                "groups": groups,
                "query_hash": sha256_json({"query": cls._QUERY, "groups": groups}),
                "raw_data_exposed": False,
            }
        finally:
            connection.close()
