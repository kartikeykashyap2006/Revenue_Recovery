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
    # "gemini" calls Google's hosted Gemini API instead, running a Gemma
    # model -- free via a Google AI Studio key (aistudio.google.com/apikey),
    # no billing required to start. Same prompts, same bounded JSON
    # schemas, same safe-fallback-on-failure behavior either way; only
    # which process answers the prompt changes.
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-4-26b-a4b-it")
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
    # Kept modest by default: a free-tier key rate-limits well before a
    # laptop runs out of threads.
    AI_AGENT_MAX_CONCURRENCY = int(os.getenv("AI_AGENT_MAX_CONCURRENCY", "6"))

    # Stopping rules / compliance config
    MAX_CONTACT_ATTEMPTS = int(os.getenv("MAX_CONTACT_ATTEMPTS", "3"))
    COOLDOWN_HOURS_BETWEEN_ATTEMPTS = int(os.getenv("COOLDOWN_HOURS_BETWEEN_ATTEMPTS", "24"))
    QUIET_HOURS_START = int(os.getenv("QUIET_HOURS_START", "21"))  # 9 PM
    QUIET_HOURS_END = int(os.getenv("QUIET_HOURS_END", "9"))       # 9 AM
    HIGH_VALUE_ESCALATION_THRESHOLD = float(os.getenv("HIGH_VALUE_ESCALATION_THRESHOLD", "50000"))


settings = Settings()
