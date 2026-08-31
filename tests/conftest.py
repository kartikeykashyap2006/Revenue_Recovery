import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Run every test against a throwaway audit log / state file, and force
    mock mode for the Razorpay client regardless of what's in .env -- tests
    must be hermetic and never depend on real credentials being present
    (or absent), and must never attempt real network calls."""
    monkeypatch.chdir(tmp_path)

    from app.config import settings
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "", raising=False)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "", raising=False)

    from app import db
    db.init_db()
    yield
