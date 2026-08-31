import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Run every test against a throwaway audit log / state file so tests
    never touch the real demo data in the project root."""
    monkeypatch.chdir(tmp_path)
    from app import db
    db.init_db()
    yield
