"""Run the planned regression on disposable MySQL tables, preserving app data.

Run from backend: .venv/Scripts/python.exe scripts/test_agent_isolated.py
Uses test tables only. With no DROP grant, rows are deleted after the run.
"""

from pathlib import Path
import sys
import os
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from app.database import Base, SessionLocal, engine
from app import models  # Register all tables before applying the test-only prefix.
from app.auth import seed_users
from app.services import seed_candidates, seed_datasets


def main() -> int:
    prefix = os.environ.get("AGENT_TEST_TABLE_PREFIX") or f"m7test_{uuid4().hex[:8]}_"
    if not prefix.startswith("m7test_") or not prefix.replace("_", "").isalnum():
        raise ValueError("Invalid isolated table prefix")
    tables = list(Base.metadata.tables.values())
    originals = [(table, table.name) for table in tables]
    for table, name in originals:
        table.name = prefix + name
    try:
        Base.metadata.create_all(engine)
        assert all(table.name.startswith(prefix) for table in tables)
        with engine.begin() as connection:
            for table in reversed(tables):
                connection.execute(table.delete())
        with SessionLocal() as db:
            seed_datasets(db)
            seed_candidates(db)
            seed_users(db)
        print("Regression uses disposable tables:", prefix, flush=True)
        tests = sys.argv[1:] or ["tests/test_agent.py", "tests/test_m4.py", "tests/test_m5.py", "tests/test_pipeline.py", "tests/test_features.py", "tests/test_enterprise_portal.py", "tests/test_api.py"]
        return pytest.main([*tests, "-q", "--tb=short", "--basetemp=.pytest_tmp_agent_regression"])
    finally:
        # This metadata contains only this invocation's prefixed table names.
        if not all(table.name.startswith(prefix) for table in tables):
            raise RuntimeError("Refusing cleanup: unexpected table names")
        with engine.begin() as connection:
            for table in reversed(tables):
                connection.execute(table.delete())
        try:
            Base.metadata.drop_all(engine)
            assert not any(name.startswith(prefix) for name in inspect(engine).get_table_names())
            print("Disposable MySQL tables removed", flush=True)
        except OperationalError as error:
            if error.orig.args[0] != 1142:
                raise
            remaining = [name for name in inspect(engine).get_table_names() if name.startswith(prefix)]
            print(f"DROP grant unavailable: {len(remaining)} empty test tables remain ({prefix})", flush=True)
        for table, name in originals:
            table.name = name


if __name__ == "__main__":
    raise SystemExit(main())
