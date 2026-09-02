"""The rate limiter exists because a 120-case batch came back 46% HTTP 429 --
nearly half the signals silently falling back to the deterministic default
instead of getting a real model opinion. These pin the behaviour that fixed
it, without touching the real API."""
import urllib.error

import pytest

import app.integrations.llm as llm


@pytest.fixture(autouse=True)
def reset_interval(monkeypatch):
    monkeypatch.setattr(llm, "_min_request_interval", 0.4, raising=False)
    monkeypatch.setattr(llm, "_last_request_at", 0.0, raising=False)
    # Keep the suite fast: the pacing logic is what's under test, not real waiting.
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)


def _http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("http://x", code, "err", headers, None)


def test_a_429_widens_the_interval_for_every_worker(monkeypatch):
    calls = {"n": 0}

    def _post(payload, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429)
        return {"ok": True}

    monkeypatch.setattr(llm, "_gemini_post", _post)
    before = llm.current_request_interval()

    assert llm._gemini_post_with_retry(b"{}") == {"ok": True}
    assert llm.current_request_interval() > before, (
        "a rate-limit response must slow the whole client down, not just retry"
    )


def test_sustained_success_narrows_the_interval_back_down(monkeypatch):
    monkeypatch.setattr(llm, "_gemini_post", lambda payload, timeout=30: {"ok": True})
    llm._widen_interval()
    widened = llm.current_request_interval()

    for _ in range(20):
        llm._gemini_post_with_retry(b"{}")

    assert llm.current_request_interval() < widened, (
        "a key that stops rate-limiting should regain speed rather than stay slow forever"
    )


def test_the_interval_never_falls_below_the_floor_or_exceeds_the_ceiling(monkeypatch):
    for _ in range(100):
        llm._widen_interval()
    assert llm.current_request_interval() <= llm._INTERVAL_CEILING

    for _ in range(1000):
        llm._narrow_interval()
    assert llm.current_request_interval() >= llm._INTERVAL_FLOOR


def test_retry_delay_prefers_the_servers_own_retry_after():
    # The server knows when its window reopens; our backoff curve is a guess.
    assert llm._retry_delay(_http_error(429, retry_after="7"), attempt=0) == 7.0


def test_retry_delay_falls_back_to_backoff_when_the_header_is_junk():
    delay = llm._retry_delay(_http_error(429, retry_after="not-a-number"), attempt=1)
    assert delay >= 3.0


def test_a_non_retryable_error_is_raised_immediately(monkeypatch):
    calls = {"n": 0}

    def _post(payload, timeout=30):
        calls["n"] += 1
        raise _http_error(401)

    monkeypatch.setattr(llm, "_gemini_post", _post)
    with pytest.raises(urllib.error.HTTPError):
        llm._gemini_post_with_retry(b"{}")
    assert calls["n"] == 1, "a bad key must fail fast, not burn the retry budget"


def test_persistent_rate_limiting_eventually_gives_up_rather_than_hanging(monkeypatch):
    calls = {"n": 0}

    def _post(payload, timeout=30):
        calls["n"] += 1
        raise _http_error(429)

    monkeypatch.setattr(llm, "_gemini_post", _post)
    with pytest.raises(urllib.error.HTTPError):
        llm._gemini_post_with_retry(b"{}")
    assert calls["n"] == llm._MAX_TRANSIENT_RETRIES + 1
