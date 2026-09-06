"""
Alert dispatch - Phase 3 of the brief: "push real time alerts directly
to WhatsApp Business API or Telegram channels."

Run this on a schedule (e.g. every 15 min via cron/Task Scheduler) after
the scraper and request form have run. It:
  1. Finds all current matches (matching_engine.find_all_matches())
  2. Skips any match already alerted for this exact opportunity+subcontractor
     pair (deduping against sent_alerts.json)
  3. Sends a Telegram alert (with an "Accept" button) to subcontractors
     who've linked their Telegram account
  4. Records what was sent, WITHOUT including private contact details -
     those only go out after an explicit Accept (see webhook_app.py)
"""

import json
import os

import config
import links
import matching_engine
import telegram_bot


def load_sent_alerts() -> dict:
    if not os.path.exists(config.SENT_ALERTS_FILE):
        return {}
    with open(config.SENT_ALERTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_sent_alerts(sent: dict) -> None:
    with open(config.SENT_ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(sent, f, indent=2, ensure_ascii=False)


def _dedupe_key(match: dict) -> str:
    return f"{match['opportunity_type']}:{match['opportunity_id']}:{match['subcontractor_id']}"


def format_alert_text(match: dict) -> str:
    """Deliberately excludes private contact info - that's the point of
    gating. Tenders never had private contact info to begin with (only a
    public buyer name); direct requests do, and it's withheld here."""
    summary = match["opportunity_summary"]
    if match["opportunity_type"] == "tender":
        return (
            f"<b>New tender award match</b>\n"
            f"{summary.get('title', '(no title)')}\n"
            f"Buyer: {summary.get('buyer', '(unknown)')}\n"
            f"Province: {summary.get('province', '(unknown)')}\n"
            f"Value: {summary.get('value_currency', '')} {summary.get('value_amount', 'undisclosed')}\n\n"
            f"Tap Accept to log your interest in this opportunity."
        )
    else:
        return (
            f"<b>New subcontractor request</b>\n"
            f"Industry: {summary.get('industry', '(unknown)')}\n"
            f"Province: {summary.get('province', '(unknown)')}\n"
            f"What they need: {summary.get('description', '(no description)')}\n"
            f"Needed by: {summary.get('needed_by') or 'not specified'}\n\n"
            f"Tap Accept to reveal the contractor's contact details."
        )


def dispatch_new_alerts() -> dict:
    """Returns a summary dict of what happened, for logging/printing."""
    sent = load_sent_alerts()
    matches = matching_engine.find_all_matches()

    stats = {"total_matches": len(matches), "already_sent": 0, "no_telegram_link": 0, "sent": 0}

    for match in matches:
        key = _dedupe_key(match)
        if key in sent:
            stats["already_sent"] += 1
            continue

        chat_id = links.get_chat_id(match["subcontractor_id"])
        if not chat_id:
            stats["no_telegram_link"] += 1
            continue

        text = format_alert_text(match)
        telegram_bot.send_message(chat_id, text, accept_callback_data=match["match_id"])

        sent[key] = {
            "match_id": match["match_id"],
            "opportunity_type": match["opportunity_type"],
            "opportunity_id": match["opportunity_id"],
            "subcontractor_id": match["subcontractor_id"],
            "status": "alerted",  # -> "accepted" -> "contact_released"
        }
        stats["sent"] += 1

    save_sent_alerts(sent)
    return stats


if __name__ == "__main__":
    result = dispatch_new_alerts()
    print(f"Total matches found: {result['total_matches']}")
    print(f"Already alerted (skipped): {result['already_sent']}")
    print(f"No Telegram link yet (skipped): {result['no_telegram_link']}")
    print(f"New alerts sent: {result['sent']}")
