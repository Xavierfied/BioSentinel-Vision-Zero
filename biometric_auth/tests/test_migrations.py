"""Alembic migrations build exactly the schema the models describe."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _alembic(tmp_path, *args):
    url = f"sqlite+aiosqlite:///{tmp_path}/migrate.db"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={url}", *args],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_upgrade_matches_models_and_downgrades(tmp_path):
    up = _alembic(tmp_path, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    check = _alembic(tmp_path, "check")
    assert check.returncode == 0, check.stderr + check.stdout
    down = _alembic(tmp_path, "downgrade", "base")
    assert down.returncode == 0, down.stderr
