"""
Thin wrapper around the Telegram Bot API. Kept deliberately simple (raw
HTTP via requests, no SDK dependency) so it's easy to mock in tests -
none of this module makes real network calls during testing.
"""

import requests

import config


def send_message(chat_id: str, text: str, accept_callback_data: str | None = None) -> dict:
    """
    Sends a message. If accept_callback_data is given, attaches a single
    inline "Accept" button whose tap will come back to the webhook as a
    callback_query with that data - used to gate contact release behind
    an explicit action, per the brief.
    """
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if accept_callback_data:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "Accept this match", "callback_data": accept_callback_data}]]
        }

    resp = requests.post(f"{config.TELEGRAM_API_BASE}/sendMessage", json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def answer_callback_query(callback_query_id: str, text: str = "") -> dict:
    """Acknowledges a button tap so Telegram stops showing a loading spinner
    on the user's client. Telegram requires this within a few seconds."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text

    resp = requests.post(f"{config.TELEGRAM_API_BASE}/answerCallbackQuery", json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def set_webhook(webhook_url: str) -> dict:
    """One-time setup call to tell Telegram where to POST updates.
    Run this once after deploying webhook_app.py somewhere with a public
    HTTPS URL (Telegram won't call a plain http:// or localhost address)."""
    resp = requests.post(
        f"{config.TELEGRAM_API_BASE}/setWebhook", json={"url": webhook_url}, timeout=15
    )
    resp.raise_for_status()
    return resp.json()
