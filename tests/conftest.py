import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Run every test against a throwaway audit log / state file, and force
    mock mode for the Razorpay client and every LLM-backed feature
    regardless of what's in .env -- tests must be hermetic and never
    depend on real credentials being present (or absent), and must never
    attempt real network calls. This matters especially for
    USE_AI_RECOVERY_AGENT / USE_LLM_DIAGNOSIS: app.config reads .env at
    import time (before this fixture ever runs), so without this, a real
    .env with those flags on would make test_pipeline.py's full-batch
    tests fire real Anthropic API calls on every test run."""
    monkeypatch.chdir(tmp_path)

    from app.config import settings
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "", raising=False)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "", raising=False)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic", raising=False)
    monkeypatch.setattr(settings, "USE_LLM_DIAGNOSIS", False, raising=False)
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", False, raising=False)

    from app import db
    db.init_db()
    yield
