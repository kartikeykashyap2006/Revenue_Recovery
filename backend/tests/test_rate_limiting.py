"""The rate limiter exists because a large batch running consultations
concurrently comes back with a burst of HTTP 429s -- signals silently
falling back to the deterministic default instead of getting a real model
opinion. These pin the behaviour that fixed it, against the NVIDIA request
path (the only HTTP-based provider with a throttle), without touching the
real API."""
import urllib.error

import pytest

import app.integrations.llm as llm


@pytest.fixture(autouse=True)
def reset_interval(monkeypatch):
    # Reset to the initial interval (which sits at/above the floor, so a
    # "narrow" step still has room to move down rather than being pinned).
    monkeypatch.setattr(llm, "_nvidia_min_request_interval", llm._NVIDIA_INITIAL_INTERVAL, raising=False)
    monkeypatch.setattr(llm, "_nvidia_last_request_at", 0.0, raising=False)
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

    monkeypatch.setattr(llm, "_nvidia_post", _post)
    before = llm.current_nvidia_request_interval()

    assert llm._nvidia_post_with_retry(b"{}") == {"ok": True}
    assert llm.current_nvidia_request_interval() > before, (
        "a rate-limit response must slow the whole client down, not just retry"
    )


def test_a_503_also_widens_the_interval(monkeypatch):
    """NVIDIA NIM signals a saturated (shared) inference worker with 503
    ResourceExhausted, not 429. Treating 503 as a plain retryable error --
    retrying straight back into the full worker without slowing down -- was
    measured costing whole minutes per batch, since every wasted attempt
    re-enters the throttle and burns another interval slot."""
    calls = {"n": 0}

    def _post(payload, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503)
        return {"ok": True}

    monkeypatch.setattr(llm, "_nvidia_post", _post)
    before = llm.current_nvidia_request_interval()

    assert llm._nvidia_post_with_retry(b"{}") == {"ok": True}
    assert llm.current_nvidia_request_interval() > before, (
        "a 503 means the upstream is out of capacity -- the client must back "
        "off, not just retry into the same saturated worker"
    )


def test_a_non_capacity_error_retries_without_widening(monkeypatch):
    """A 500 is a fault, not backpressure: worth a retry, but slowing every
    worker down for it would punish the whole batch for one bad response. The
    interval must not *widen* (the eventual success may narrow it, which is
    fine -- what's forbidden is treating a fault as a congestion signal)."""
    calls = {"n": 0}

    def _post(payload, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(500)
        return {"ok": True}

    monkeypatch.setattr(llm, "_nvidia_post", _post)
    before = llm.current_nvidia_request_interval()

    assert llm._nvidia_post_with_retry(b"{}") == {"ok": True}
    assert llm.current_nvidia_request_interval() <= before, "a 500 must not be read as backpressure"


def test_sustained_success_narrows_the_interval_back_down(monkeypatch):
    monkeypatch.setattr(llm, "_nvidia_post", lambda payload, timeout=30: {"ok": True})
    llm._nvidia_widen_interval()
    llm._nvidia_widen_interval()
    widened = llm.current_nvidia_request_interval()

    for _ in range(20):
        llm._nvidia_post_with_retry(b"{}")

    assert llm.current_nvidia_request_interval() < widened, (
        "a key that stops rate-limiting should regain speed rather than stay slow forever"
    )


def test_the_interval_never_falls_below_the_floor_or_exceeds_the_ceiling():
    for _ in range(100):
        llm._nvidia_widen_interval()
    assert llm.current_nvidia_request_interval() <= llm._NVIDIA_INTERVAL_CEILING

    for _ in range(1000):
        llm._nvidia_narrow_interval()
    assert llm.current_nvidia_request_interval() >= llm._NVIDIA_INTERVAL_FLOOR


def test_recovery_from_a_widened_interval_is_fast():
    # The interval starts near NVIDIA's documented ceiling rather than
    # feeling out an unknown one, so recovery from a widened interval should
    # take a handful of clean calls, not dozens.
    llm._nvidia_widen_interval()
    llm._nvidia_widen_interval()
    widened = llm.current_nvidia_request_interval()

    for _ in range(11):
        llm._nvidia_narrow_interval()

    assert llm.current_nvidia_request_interval() <= llm._NVIDIA_INTERVAL_FLOOR + 1e-9
    assert llm.current_nvidia_request_interval() < widened


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

    monkeypatch.setattr(llm, "_nvidia_post", _post)
    with pytest.raises(urllib.error.HTTPError):
        llm._nvidia_post_with_retry(b"{}")
    assert calls["n"] == 1, "a bad key must fail fast, not burn the retry budget"


def test_persistent_rate_limiting_eventually_gives_up_rather_than_hanging(monkeypatch):
    calls = {"n": 0}

    def _post(payload, timeout=30):
        calls["n"] += 1
        raise _http_error(429)

    monkeypatch.setattr(llm, "_nvidia_post", _post)
    with pytest.raises(urllib.error.HTTPError):
        llm._nvidia_post_with_retry(b"{}")
    assert calls["n"] == llm._MAX_TRANSIENT_RETRIES + 1


def test_floor_matches_the_configured_max_rate_and_start_is_no_faster():
    # The floor is the fastest cadence the throttle will use, derived from
    # NVIDIA_MAX_RPM (60 / rpm). The client starts at or slower than the floor
    # and discovers down toward it via success -- it never opens faster than
    # the configured max, and only ever widens above the floor on backpressure.
    from app.config import settings
    expected_floor = 60.0 / settings.NVIDIA_MAX_RPM
    assert llm._NVIDIA_INTERVAL_FLOOR == expected_floor
    assert llm._NVIDIA_INITIAL_INTERVAL >= llm._NVIDIA_INTERVAL_FLOOR
    assert llm._NVIDIA_INTERVAL_FLOOR <= llm._NVIDIA_INTERVAL_CEILING
