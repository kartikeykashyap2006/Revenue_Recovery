"""Core data models for the Revenue Recovery engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class SignalType(str, Enum):
    PAYMENT_FAILURE = "payment_failure"
    CHECKOUT_ABANDONMENT = "checkout_abandonment"
    SUBSCRIPTION_MANDATE_FAILURE = "subscription_mandate_failure"
    OVERDUE_RECEIVABLE = "overdue_receivable"


class RootCause(str, Enum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    CARD_EXPIRED = "card_expired"
    BANK_DECLINED_RISK = "bank_declined_risk"
    NETWORK_ERROR = "network_error"
    WRONG_OTP = "wrong_otp"
    EXCEEDED_LIMIT = "exceeded_limit"
    PRICE_HESITATION = "price_hesitation"
    PAYMENT_METHOD_UNAVAILABLE = "payment_method_unavailable"
    TECHNICAL_GLITCH = "technical_glitch"
    DISTRACTED_TIMEOUT = "distracted_timeout"
    MANDATE_EXPIRED = "mandate_expired"
    CASH_FLOW_DELAY = "cash_flow_delay"
    INVOICE_DISPUTE = "invoice_dispute"
    FORGOT = "forgot"
    UNKNOWN = "unknown"


class Channel(str, Enum):
    PAYMENT_LINK = "payment_link"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    NONE = "none"


class ActionStatus(str, Enum):
    SENT = "sent"
    RECOVERED = "recovered"
    FAILED = "failed"
    ESCALATED = "escalated"
    STOPPED = "stopped"
    SKIPPED = "skipped"
    # Outreach the agent judged premature right now and scheduled for later.
    # A deferred signal is persisted and re-enters a future batch, where it
    # goes through EVERY guardrail again from scratch -- deferral delays
    # contact, it never pre-authorises it.
    DEFERRED = "deferred"


@dataclass
class Signal:
    type: SignalType
    customer_id: str
    customer_name: str
    amount: float
    currency: str = "INR"
    language_pref: str = "en"  # "en" or "hi" -> bilingual (Hinglish) text channel
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class Diagnosis:
    signal_id: str
    root_cause: RootCause
    confidence: float
    reasoning: str


@dataclass
class Decision:
    signal_id: str
    playbook: str
    escalate: bool
    stop: bool
    stop_reason: Optional[str]
    plan: List[str] = field(default_factory=list)
    # Set only by the AI agent (app/engine/agent.py), and only within limits
    # the deterministic layer enforces: `channel_override` must be one of the
    # channels the assigned playbook actually supports, and `defer_hours` is
    # clamped to a non-negative maximum so the agent can postpone outreach
    # but never bring it forward.
    channel_override: Optional[str] = None
    defer_hours: int = 0


@dataclass
class ActionResult:
    signal_id: str
    playbook: str
    channel: Channel
    status: ActionStatus
    message_sent: Optional[str]
    amount_recovered: float
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class AgentRecommendation:
    """The AI recovery-decision agent's output for one signal that has
    already cleared every deterministic compliance guardrail. `action` is
    always one of a fixed, bounded set (see app/engine/agent.py) -- the
    agent proposes, the policy/execution layer disposes; it can never
    invent an action outside this set or bypass a compliance stop."""
    signal_id: str
    action: str  # "proceed" | "hold" | "escalate"
    confidence: float
    reasoning: str
    error: Optional[str] = None
    # How to recover, not just whether. Both are advisory and both are
    # validated/clamped by the deterministic layer before they can affect
    # anything -- see app/engine/agent.py.
    channel: Optional[str] = None   # must be a channel the playbook supports
    defer_hours: int = 0            # >= 0; postpone outreach by this many hours


@dataclass
class Trace:
    """Full audit trace for one signal moving through the pipeline."""
    signal: Signal
    diagnosis: Diagnosis
    decision: Decision
    action: ActionResult
