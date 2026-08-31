import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    USE_LIVE_RAZORPAY = os.getenv("USE_LIVE_RAZORPAY", "false").lower() == "true"
    USE_LLM_DIAGNOSIS = os.getenv("USE_LLM_DIAGNOSIS", "false").lower() == "true"

    # Stopping rules / compliance config
    MAX_CONTACT_ATTEMPTS = int(os.getenv("MAX_CONTACT_ATTEMPTS", "3"))
    COOLDOWN_HOURS_BETWEEN_ATTEMPTS = int(os.getenv("COOLDOWN_HOURS_BETWEEN_ATTEMPTS", "24"))
    QUIET_HOURS_START = int(os.getenv("QUIET_HOURS_START", "21"))  # 9 PM
    QUIET_HOURS_END = int(os.getenv("QUIET_HOURS_END", "9"))       # 9 AM
    HIGH_VALUE_ESCALATION_THRESHOLD = float(os.getenv("HIGH_VALUE_ESCALATION_THRESHOLD", "50000"))

    DB_PATH = os.getenv("DB_PATH", "audit_trail.db")


settings = Settings()
