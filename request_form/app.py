"""
Direct request form - Phase 1, part 2 of the Subcontractor Matching
Platform pilot.

Lets a main contractor submit a subcontractor request as soon as they
win or shortlist a project, rather than waiting for the scraper to pick
up the award. Per the brief, this is meant to be a stronger demand
signal than scraped tender data.

Run locally with:
    pip install flask
    python3 app.py
Then open http://127.0.0.1:5000 in a browser.

Submissions are appended to direct_requests.json / .csv in this folder -
same shape of file as the scraper's output, so both feeds can be merged
by the matching engine in Phase 2.
"""

import csv
import json
import os
import uuid
from datetime import datetime, date

from flask import Flask, render_template, request, redirect, url_for

import config

app = Flask(__name__)

REQUIRED_FIELDS = ["company_name", "contact_person", "contact_phone", "province", "industry", "description"]


def load_existing() -> list[dict]:
    if not os.path.exists(config.OUTPUT_JSON):
        return []
    with open(config.OUTPUT_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def save_all(rows: list[dict]) -> None:
    with open(config.OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    if rows:
        with open(config.OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def validate(form_data: dict) -> list[str]:
    """Server-side validation - never trust the browser alone. Returns a
    list of human-readable error messages (empty list = valid)."""
    errors = []
    for field in REQUIRED_FIELDS:
        if not form_data.get(field, "").strip():
            errors.append(f"'{field.replace('_', ' ').title()}' is required.")

    if form_data.get("province") and form_data["province"] not in config.PROVINCES:
        errors.append("Please select a valid province from the list.")

    if form_data.get("industry") and form_data["industry"] not in config.INDUSTRIES:
        errors.append("Please select a valid industry from the list.")

    needed_by = form_data.get("needed_by", "").strip()
    if needed_by:
        try:
            if date.fromisoformat(needed_by) < date.today():
                errors.append("'Needed by' date can't be in the past.")
        except ValueError:
            errors.append("'Needed by' date is not a valid date.")

    return errors


@app.route("/", methods=["GET"])
def show_form():
    return render_template(
        "index.html", provinces=config.PROVINCES, industries=config.INDUSTRIES, errors=[], form_data={}
    )


@app.route("/submit", methods=["POST"])
def submit():
    form_data = {
        "company_name": request.form.get("company_name", "").strip(),
        "contact_person": request.form.get("contact_person", "").strip(),
        "contact_phone": request.form.get("contact_phone", "").strip(),
        "contact_email": request.form.get("contact_email", "").strip(),
        "province": request.form.get("province", "").strip(),
        "industry": request.form.get("industry", "").strip(),
        "project_reference": request.form.get("project_reference", "").strip(),
        "description": request.form.get("description", "").strip(),
        "needed_by": request.form.get("needed_by", "").strip(),
    }

    errors = validate(form_data)
    if errors:
        return render_template(
            "index.html",
            provinces=config.PROVINCES,
            industries=config.INDUSTRIES,
            errors=errors,
            form_data=form_data,
        )

    record = {
        "request_id": str(uuid.uuid4()),
        "submitted_at": datetime.now().isoformat(timespec="seconds"),
        **form_data,
        "status": "open",  # open -> matched -> closed, for the matching engine to update
    }

    rows = load_existing()
    rows.append(record)
    save_all(rows)

    return redirect(url_for("thank_you", request_id=record["request_id"]))


@app.route("/thank-you")
def thank_you():
    request_id = request.args.get("request_id", "")
    return render_template("thank_you.html", request_id=request_id)


if __name__ == "__main__":
    app.run(debug=True)
