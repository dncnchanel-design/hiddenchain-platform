"""The test runner must never erase an existing database supplied by its caller."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_existing_database_override_is_rejected_without_touching_file(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "existing.db"
    original = b"existing user database must remain intact"
    database.write_bytes(original)
    environment = {
        **os.environ,
        "HIDDENCHAIN_TEST_DB": str(database),
        "PYTHONPATH": str(backend),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import runpy; runpy.run_path('tests/conftest.py')"],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert database.exists(), "Importing the test fixtures deleted an existing database"
    assert database.read_bytes() == original
    assert result.returncode != 0
    assert "HIDDENCHAIN_TEST_DB" in result.stderr
