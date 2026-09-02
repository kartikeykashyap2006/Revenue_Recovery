"""Bilingual (English / Hinglish) message templates for the text-based
recovery channel. This is the implementation of the 'Hinglish voice
recovery' example direction as a WhatsApp/SMS-style bilingual text channel
rather than a live voice call -- see docs/architecture.md for why."""

from app.models import Signal


def payment_retry_message(signal: Signal, link: str) -> str:
    if signal.language_pref == "hi":
        return (
            f"Namaste {signal.customer_name}, aapka payment of Rs. {signal.amount:,.0f} "
            f"complete nahi ho paya. Yahan click karke dobara try karein: {link}"
        )
    return (
        f"Hi {signal.customer_name}, your payment of Rs. {signal.amount:,.0f} didn't go "
        f"through. Retry here: {link}"
    )


def checkout_reminder_message(signal: Signal, link: str) -> str:
    if signal.language_pref == "hi":
        return (
            f"Hi {signal.customer_name}, aapka cart abhi bhi ready hai! Order complete "
            f"karne ke liye yahan click karein: {link}"
        )
    return f"Hi {signal.customer_name}, your cart is still waiting! Complete your order here: {link}"


def mandate_retry_message(signal: Signal, link: str) -> str:
    if signal.language_pref == "hi":
        return (
            f"Namaste {signal.customer_name}, aapka subscription payment fail ho gaya. "
            f"Please yahan update karein: {link}"
        )
    return f"Hi {signal.customer_name}, your subscription payment failed. Please update here: {link}"


def receivable_reminder_message(signal: Signal, due_date: str) -> str:
    if signal.language_pref == "hi":
        return (
            f"Namaste {signal.customer_name}, aapka invoice of Rs. {signal.amount:,.0f} "
            f"(due {due_date}) abhi tak pending hai. Kripya jald payment karein."
        )
    return (
        f"Hi {signal.customer_name}, your invoice of Rs. {signal.amount:,.0f} "
        f"(due {due_date}) is still pending. Please arrange payment soon."
    )
