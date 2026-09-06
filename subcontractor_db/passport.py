"""
Helpers for the "Subcontractor Passport" section of the profile page:
turning raw verification_records rows into plain language a contractor
(not just a verifier) can read at a glance, plus a freshness signal so a
viewer isn't relying on a check from years ago without realising it.
"""

from datetime import date

import config

OUTCOME_TEXT = {
    "verified": "came back verified",
    "not_verified": "did not verify",
    "needs_review": "needs review",
}


def freshness(checked_date_str, today=None):
    """Returns (days_ago, label, css_class) for a checked_date string."""
    today = today or date.today()
    checked = date.fromisoformat(checked_date_str)
    days = (today - checked).days

    if days <= config.FRESHNESS_FRESH_DAYS:
        return days, "Fresh", "fresh"
    elif days <= config.FRESHNESS_AGING_DAYS:
        return days, "Aging", "aging"
    else:
        return days, "Stale", "stale"


def explain_check(record):
    """
    record: a sqlite3.Row (or dict-like) with check_type, outcome, source,
    checked_date, reference_number, grade, notes, verifier_name.

    Returns (sentence, freshness_label, freshness_css_class, days_ago).
    """
    days, label, css = freshness(record["checked_date"])
    outcome_text = OUTCOME_TEXT.get(record["outcome"], record["outcome"])

    parts = [
        f"{record['check_type']} {outcome_text} against {record['source']} "
        f"on {record['checked_date']} ({days} day{'s' if days != 1 else ''} ago), "
        f"logged by {record['verifier_name']}."
    ]
    if record["reference_number"]:
        parts.append(f"Reference #{record['reference_number']}.")
    if record["grade"]:
        parts.append(f"CIDB grade {record['grade']}.")
    if record["notes"]:
        parts.append(record["notes"])

    return " ".join(parts), label, css, days


def availability_text(profile):
    status = profile["availability_status"]
    if status == "available":
        return "Available now"
    if status == "engaged":
        return "Currently engaged"
    if status == "available_from":
        return f"Available from {profile['availability_date']}"
    return "Availability not set"