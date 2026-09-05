import os
import re
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, abort

import sub_config as config
import sub_db as db
from sub_verification import compute_verification

app = Flask(__name__)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, config.DB_PATH)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

db.init_db(DB_PATH)


# ---------------------------------------------------------------------------
# Small data-access helpers
# ---------------------------------------------------------------------------

def log_event(conn, subcontractor_id, event_type, description):
    conn.execute(
        "INSERT INTO audit_events (subcontractor_id, event_type, description, created_at) "
        "VALUES (?, ?, ?, ?)",
        (subcontractor_id, event_type, description, db.now_iso()),
    )


def latest_check(conn, subcontractor_id, check_type):
    row = conn.execute(
        "SELECT * FROM verification_records WHERE subcontractor_id = ? AND check_type = ? "
        "ORDER BY checked_date DESC, id DESC LIMIT 1",
        (subcontractor_id, check_type),
    ).fetchone()
    return row


def recompute_and_store_score(conn, subcontractor_id):
    cipc = latest_check(conn, subcontractor_id, "CIPC")
    cidb = latest_check(conn, subcontractor_id, "CIDB")
    ref_count = conn.execute(
        "SELECT COUNT(*) AS n FROM subcontractor_references WHERE subcontractor_id = ?",
        (subcontractor_id,),
    ).fetchone()["n"]
    years_active = conn.execute(
        "SELECT years_active FROM subcontractor_profiles WHERE id = ?", (subcontractor_id,)
    ).fetchone()["years_active"]

    cipc_verified = bool(cipc["verified"]) if cipc else False
    cidb_verified = bool(cidb["verified"]) if cidb else False
    cidb_grade = cidb["grade"] if cidb else None

    score, tier = compute_verification(cipc_verified, cidb_verified, cidb_grade, years_active, ref_count)

    conn.execute(
        "UPDATE subcontractor_profiles SET verification_score = ?, verification_tier = ? WHERE id = ?",
        (score, tier, subcontractor_id),
    )
    log_event(conn, subcontractor_id, "score_computed", f"Verification score computed: {score} ({tier})")
    return score, tier


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def validate_profile_form(form):
    errors = []
    data = {}

    company_name = (form.get("company_name") or "").strip()
    contact_name = (form.get("contact_name") or "").strip()
    phone = (form.get("phone") or "").strip()
    email = (form.get("email") or "").strip()
    trade = (form.get("trade") or "").strip()
    province = (form.get("province") or "").strip()
    years_active_raw = (form.get("years_active") or "").strip()

    if not company_name:
        errors.append("Company name is required.")
    if not contact_name:
        errors.append("Contact name is required.")

    digits = re.sub(r"[^\d]", "", phone)
    if not phone or len(digits) < 7:
        errors.append("A valid phone number is required.")

    if not email or not EMAIL_RE.match(email):
        errors.append("A valid email address is required.")

    if trade not in config.TRADES:
        errors.append("Please select a valid trade.")

    if province not in config.PROVINCES:
        errors.append("Please select a valid province.")

    years_active = None
    if not years_active_raw:
        errors.append("Years active is required.")
    else:
        try:
            years_active = int(years_active_raw)
            if years_active < 0 or years_active > 100:
                errors.append("Years active must be between 0 and 100.")
        except ValueError:
            errors.append("Years active must be a whole number.")

    cipc_checked, cipc_errors = _validate_check_fields(form, "cipc", "CIPC", require_grade=False)
    cidb_checked, cidb_errors = _validate_check_fields(form, "cidb", "CIDB", require_grade=True)
    errors += cipc_errors + cidb_errors

    references = []
    for i in (1, 2, 3):
        client = (form.get(f"ref{i}_client") or "").strip()
        comment = (form.get(f"ref{i}_comment") or "").strip()
        if client and not comment:
            errors.append(f"Reference {i} has a client name but no comment.")
        elif comment and not client:
            errors.append(f"Reference {i} has a comment but no client name.")
        elif client and comment:
            references.append({"client_name": client, "comment": comment})

    data.update({
        "company_name": company_name, "contact_name": contact_name, "phone": phone,
        "email": email, "trade": trade, "province": province, "years_active": years_active,
        "cipc": cipc_checked, "cidb": cidb_checked, "references": references,
    })
    return data, errors


def _validate_check_fields(form, prefix, label, require_grade):
    """Shared validation for the CIPC/CIDB blocks on the onboarding form.
    Returns (checked_dict_or_None, errors)."""
    errors = []
    ticked = form.get(f"{prefix}_verified") == "on"
    if not ticked:
        return None, errors

    checked_date_raw = (form.get(f"{prefix}_checked_date") or "").strip()
    checked_by = (form.get(f"{prefix}_checked_by") or "").strip()
    grade_raw = (form.get(f"{prefix}_grade") or "").strip()

    checked_date = _parse_date(checked_date_raw)
    if not checked_date:
        errors.append(f"{label} checked date is required when {label} verified is ticked.")
    elif checked_date > date.today():
        errors.append(f"{label} checked date can't be in the future.")

    if not checked_by:
        errors.append(f"{label} checked by (who did the check) is required when {label} verified is ticked.")

    grade = None
    if require_grade:
        if not grade_raw:
            errors.append(f"{label} grade is required when {label} verified is ticked.")
        else:
            try:
                grade = int(grade_raw)
                if grade not in config.CIDB_GRADES:
                    errors.append(f"{label} grade must be between 1 and 9.")
            except ValueError:
                errors.append(f"{label} grade must be a whole number.")

    if errors:
        return None, errors

    return {
        "verified": True, "grade": grade,
        "checked_date": checked_date.isoformat(), "checked_by": checked_by,
    }, errors


def validate_recheck_form(form):
    errors = []
    check_type = (form.get("check_type") or "").strip()
    outcome = (form.get("outcome") or "").strip()  # 'verified' or 'not_verified'
    checked_date_raw = (form.get("checked_date") or "").strip()
    checked_by = (form.get("checked_by") or "").strip()
    grade_raw = (form.get("grade") or "").strip()

    if check_type not in config.CHECK_TYPES:
        errors.append("Please select a valid check type.")
    if outcome not in ("verified", "not_verified"):
        errors.append("Please state whether the check came back verified or not.")
    if not checked_by:
        errors.append("Checked by (who did the check) is required.")

    checked_date = _parse_date(checked_date_raw)
    if not checked_date:
        errors.append("Checked date is required.")
    elif checked_date > date.today():
        errors.append("Checked date can't be in the future.")

    grade = None
    if check_type == "CIDB" and outcome == "verified":
        if not grade_raw:
            errors.append("CIDB grade is required when the outcome is verified.")
        else:
            try:
                grade = int(grade_raw)
                if grade not in config.CIDB_GRADES:
                    errors.append("CIDB grade must be between 1 and 9.")
            except ValueError:
                errors.append("CIDB grade must be a whole number.")

    if errors:
        return None, errors

    return {
        "check_type": check_type,
        "verified": outcome == "verified",
        "grade": grade,
        "checked_date": checked_date.isoformat(),
        "checked_by": checked_by,
    }, errors


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    conn = db.connect(DB_PATH)
    profiles = conn.execute(
        "SELECT * FROM subcontractor_profiles ORDER BY verification_score DESC, id ASC"
    ).fetchall()

    rows = []
    for p in profiles:
        cipc = latest_check(conn, p["id"], "CIPC")
        cidb = latest_check(conn, p["id"], "CIDB")
        rows.append({"profile": p, "cipc": cipc, "cidb": cidb})
    conn.close()
    return render_template("sub_index.html", rows=rows, disclaimer=config.VERIFICATION_DISCLAIMER)


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "GET":
        return render_template(
            "sub_add.html", provinces=config.PROVINCES, trades=config.TRADES,
            grades=config.CIDB_GRADES, errors=[], form={}, today=date.today().isoformat(),
        )

    data, errors = validate_profile_form(request.form)
    if errors:
        return render_template(
            "sub_add.html", provinces=config.PROVINCES, trades=config.TRADES,
            grades=config.CIDB_GRADES, errors=errors, form=request.form,
            today=date.today().isoformat(),
        ), 400

    conn = db.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO subcontractor_profiles "
        "(company_name, contact_name, phone, email, trade, province, years_active, tier, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'free', ?)",
        (data["company_name"], data["contact_name"], data["phone"], data["email"],
         data["trade"], data["province"], data["years_active"], db.now_iso()),
    )
    sub_id = cur.lastrowid
    log_event(conn, sub_id, "profile_created", f"Subcontractor profile created: {data['company_name']}")

    for check_type, checked in (("CIPC", data["cipc"]), ("CIDB", data["cidb"])):
        if checked:
            conn.execute(
                "INSERT INTO verification_records "
                "(subcontractor_id, check_type, verified, grade, checked_date, checked_by, created_at) "
                "VALUES (?, ?, 1, ?, ?, ?, ?)",
                (sub_id, check_type, checked["grade"], checked["checked_date"], checked["checked_by"],
                 db.now_iso()),
            )
            detail = f", grade {checked['grade']}" if checked["grade"] else ""
            log_event(conn, sub_id, "verification_recorded",
                      f"{check_type} check recorded as verified{detail} "
                      f"(checked {checked['checked_date']} by {checked['checked_by']})")

    for ref in data["references"]:
        conn.execute(
            "INSERT INTO subcontractor_references (subcontractor_id, client_name, comment, created_at) "
            "VALUES (?, ?, ?, ?)",
            (sub_id, ref["client_name"], ref["comment"], db.now_iso()),
        )
        log_event(conn, sub_id, "reference_added", f"Reference added: {ref['client_name']}")

    recompute_and_store_score(conn, sub_id)
    conn.commit()
    conn.close()

    return redirect(url_for("profile", sub_id=sub_id))


@app.route("/subcontractor/<int:sub_id>")
def profile(sub_id):
    conn = db.connect(DB_PATH)
    p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = ?", (sub_id,)).fetchone()
    if not p:
        conn.close()
        abort(404)

    records = conn.execute(
        "SELECT * FROM verification_records WHERE subcontractor_id = ? "
        "ORDER BY checked_date DESC, id DESC",
        (sub_id,),
    ).fetchall()
    references = conn.execute(
        "SELECT * FROM subcontractor_references WHERE subcontractor_id = ? ORDER BY id",
        (sub_id,),
    ).fetchall()
    events = conn.execute(
        "SELECT * FROM audit_events WHERE subcontractor_id = ? ORDER BY created_at, id",
        (sub_id,),
    ).fetchall()
    conn.close()

    return render_template(
        "sub_profile.html", p=p, records=records, references=references, events=events,
        check_types=config.CHECK_TYPES, grades=config.CIDB_GRADES,
        today=date.today().isoformat(), errors=[], form={},
        disclaimer=config.VERIFICATION_DISCLAIMER,
    )


@app.route("/subcontractor/<int:sub_id>/verify", methods=["POST"])
def record_check(sub_id):
    conn = db.connect(DB_PATH)
    p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = ?", (sub_id,)).fetchone()
    if not p:
        conn.close()
        abort(404)

    checked, errors = validate_recheck_form(request.form)
    if errors:
        records = conn.execute(
            "SELECT * FROM verification_records WHERE subcontractor_id = ? "
            "ORDER BY checked_date DESC, id DESC", (sub_id,),
        ).fetchall()
        references = conn.execute(
            "SELECT * FROM subcontractor_references WHERE subcontractor_id = ? ORDER BY id", (sub_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM audit_events WHERE subcontractor_id = ? ORDER BY created_at, id", (sub_id,),
        ).fetchall()
        conn.close()
        return render_template(
            "sub_profile.html", p=p, records=records, references=references, events=events,
            check_types=config.CHECK_TYPES, grades=config.CIDB_GRADES,
            today=date.today().isoformat(), errors=errors, form=request.form,
            disclaimer=config.VERIFICATION_DISCLAIMER,
        ), 400

    conn.execute(
        "INSERT INTO verification_records "
        "(subcontractor_id, check_type, verified, grade, checked_date, checked_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sub_id, checked["check_type"], 1 if checked["verified"] else 0, checked["grade"],
         checked["checked_date"], checked["checked_by"], db.now_iso()),
    )
    outcome_text = "verified" if checked["verified"] else "not verified"
    detail = f", grade {checked['grade']}" if checked["grade"] else ""
    log_event(conn, sub_id, "verification_recorded",
              f"{checked['check_type']} check recorded as {outcome_text}{detail} "
              f"(checked {checked['checked_date']} by {checked['checked_by']})")

    recompute_and_store_score(conn, sub_id)
    conn.commit()
    conn.close()

    return redirect(url_for("profile", sub_id=sub_id))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
