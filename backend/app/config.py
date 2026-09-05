import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    # Which LLM backend app/integrations/llm.py calls. "anthropic" (default)
    # uses the Claude API and needs ANTHROPIC_API_KEY + billing set up.
    # "nvidia" calls NVIDIA's hosted NIM API instead (free via
    # build.nvidia.com, ~40 requests/minute on the free tier), running a
    # Nemotron reasoning model with its internal thinking pass explicitly
    # disabled -- reasoning tokens otherwise dominate wall-clock time for a
    # bounded few-way classification. Same prompts, same bounded JSON
    # schemas, same safe-fallback-on-failure behavior either way; only which
    # process answers the prompt changes.
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()
    NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
    NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    # The fastest the client will *try* to pace NVIDIA requests (requests/
    # minute): it sets the throttle's interval FLOOR (60 / rpm), the quickest
    # cadence it will ever use. This is an aspiration, not a fixed pace -- the
    # throttle still backs off above this interval whenever the shared NIM
    # worker pushes back (a 429 or a 503 "worker full"), then recovers toward
    # it. Set it high enough to exploit an uncongested worker: a real run
    # sustained ~44 RPM this way, and the 429/503 backpressure keeps a busy
    # worker from being hammered regardless of how high this is. 60 leaves
    # real headroom above the ~40 RPM the free tier averages; pacing to a
    # hard 40 measurably capped the good windows for no gain in the bad ones.
    NVIDIA_MAX_RPM = int(os.getenv("NVIDIA_MAX_RPM", "60"))
    USE_LIVE_RAZORPAY = os.getenv("USE_LIVE_RAZORPAY", "false").lower() == "true"
    USE_LLM_DIAGNOSIS = os.getenv("USE_LLM_DIAGNOSIS", "false").lower() == "true"
    # Distinct from USE_LLM_DIAGNOSIS: that one is a low-confidence root-
    # cause fallback. This one lets an LLM refine (never loosen) the
    # deterministic policy engine's proceed/hold/escalate decision for a
    # signal that already cleared every compliance guardrail -- see
    # app/engine/agent.py.
    USE_AI_RECOVERY_AGENT = os.getenv("USE_AI_RECOVERY_AGENT", "false").lower() == "true"
    # How many agent consultations may be in flight at once (see
    # app/engine/pipeline.py). Model calls dominate batch wall-clock time --
    # they were measured at ~5.4s each while the entire deterministic
    # pipeline runs 30 signals in 0.25s -- so these are issued in parallel.
    #
    # The NVIDIA request throttle (see app/integrations/llm.py), not this
    # number, governs throughput: request starts are spaced by the throttle
    # interval regardless of how many workers exist. Concurrency only needs
    # to be large enough to keep that cadence flowing while slow calls are
    # still outstanding (workers >= max_latency / interval; at the 60 RPM
    # floor -- 1s spacing -- and up to ~6s latency, 6 covers it). More workers
    # past that don't go faster and only worsen the 429/503 bursts when the
    # shared worker is busy, so 6 is the default. Override in .env only if a
    # higher tier genuinely needs deeper pipelining.
    AI_AGENT_MAX_CONCURRENCY = int(os.getenv("AI_AGENT_MAX_CONCURRENCY", "6"))

    # Stopping rules / compliance config
    MAX_CONTACT_ATTEMPTS = int(os.getenv("MAX_CONTACT_ATTEMPTS", "3"))
    COOLDOWN_HOURS_BETWEEN_ATTEMPTS = int(os.getenv("COOLDOWN_HOURS_BETWEEN_ATTEMPTS", "24"))
    QUIET_HOURS_START = int(os.getenv("QUIET_HOURS_START", "21"))  # 9 PM
    QUIET_HOURS_END = int(os.getenv("QUIET_HOURS_END", "9"))       # 9 AM
    HIGH_VALUE_ESCALATION_THRESHOLD = float(os.getenv("HIGH_VALUE_ESCALATION_THRESHOLD", "50000"))

    # Deployed frontend origin (e.g. https://recoup.vercel.app), added to the
    # CORS allow-list in app/main.py alongside the local Vite dev/preview
    # origins. Empty by default -- local dev never needs it.
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "")


settings = Settings()
