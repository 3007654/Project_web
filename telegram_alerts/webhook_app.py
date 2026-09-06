"""
Webhook receiver for Telegram updates - Phase 3, the "gated contact"
half of the brief: "Full contact details are released only once both
sides accept a match through the platform."

Handles two kinds of incoming Telegram updates:
  1. A message "/start <subcontractor_id>" - links that Telegram chat to
     the subcontractor's profile (see links.py).
  2. A callback_query (an "Accept" button tap) - looks up the match,
     marks it accepted, and sends the real contact details ONLY NOW,
     in a follow-up message. Direct requests have real contact info to
     release; tenders only ever had a public buyer name (see
     alert_dispatch.format_alert_text) so "accepting" a tender just logs
     interest rather than unlocking anything new - still useful for the
     brief's "keeps every introduction logged and billable" goal.

Run alongside the other Flask apps on a separate port. Telegram needs a
public HTTPS URL to send updates to (see telegram_bot.set_webhook) -
during local development, a tool like ngrok can expose localhost publicly
for testing.
"""

from flask import Flask, request, jsonify

import alert_dispatch
import links
import matching_engine
import telegram_bot

app = Flask(__name__)


def _find_match_by_id(match_id: str) -> dict | None:
    """Re-derives the live match list and finds one by ID. At pilot scale
    this is cheap enough to just recompute rather than persist full match
    objects separately from sent_alerts.json."""
    for match in matching_engine.find_all_matches():
        if match["match_id"] == match_id:
            return match
    return None


def _format_contact_release(match: dict) -> str:
    summary = match["opportunity_summary"]
    if match["opportunity_type"] == "direct_request":
        return (
            f"<b>Contact details released</b>\n"
            f"Company: {summary.get('company_name')}\n"
            f"Contact: {summary.get('contact_person')}\n"
            f"Phone: {summary.get('contact_phone')}\n"
            f"Email: {summary.get('contact_email') or 'not provided'}\n\n"
            f"This introduction has been logged."
        )
    else:
        return (
            f"<b>Interest logged</b>\n"
            f"Buyer: {summary.get('buyer')}\n"
            f"Reference: {match['opportunity_id']}\n\n"
            f"Tenders are public record - there's no private contact to release, "
            f"but your interest is now logged for follow-up."
        )


@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(force=True, silent=True) or {}

    if "message" in update:
        text = (update["message"].get("text") or "").strip()
        chat_id = update["message"]["chat"]["id"]

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                subcontractor_id = parts[1].strip()
                links.link_subcontractor(subcontractor_id, chat_id)
                telegram_bot.send_message(
                    chat_id,
                    "You're linked! You'll now receive alerts for matching opportunities.",
                )
            else:
                telegram_bot.send_message(
                    chat_id,
                    "To link your account, send /start followed by your subcontractor ID "
                    "(shown on your profile page).",
                )
        return jsonify({"ok": True})

    if "callback_query" in update:
        cq = update["callback_query"]
        callback_query_id = cq["id"]
        match_id = cq.get("data", "")
        chat_id = cq["message"]["chat"]["id"]

        sent = alert_dispatch.load_sent_alerts()
        record = next((v for v in sent.values() if v["match_id"] == match_id), None)

        if not record:
            telegram_bot.answer_callback_query(callback_query_id, "This match is no longer available.")
            return jsonify({"ok": True})

        if record["status"] != "alerted":
            telegram_bot.answer_callback_query(callback_query_id, "You've already responded to this one.")
            return jsonify({"ok": True})

        match = _find_match_by_id(match_id)
        if not match:
            telegram_bot.answer_callback_query(callback_query_id, "This opportunity is no longer active.")
            return jsonify({"ok": True})

        record["status"] = "accepted"
        sent = alert_dispatch.load_sent_alerts()
        for key, v in sent.items():
            if v["match_id"] == match_id:
                sent[key]["status"] = "accepted"
        alert_dispatch.save_sent_alerts(sent)

        telegram_bot.answer_callback_query(callback_query_id, "Accepted!")
        telegram_bot.send_message(chat_id, _format_contact_release(match))

        for key, v in sent.items():
            if v["match_id"] == match_id:
                sent[key]["status"] = "contact_released"
        alert_dispatch.save_sent_alerts(sent)

        return jsonify({"ok": True})

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5002)
