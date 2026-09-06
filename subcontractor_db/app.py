import os
import re
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, abort, session

import auth
import config
import db
from verification import compute_verification, compute_profile_status

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

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
        "SELECT vr.*, vu.name AS verifier_name, vu.role AS verifier_role "
        "FROM verification_records vr "
        "JOIN verifier_users vu ON vu.id = vr.verified_by_user_id "
        "WHERE vr.subcontractor_id = ? AND vr.check_type = ? "
        "ORDER BY vr.checked_date DESC, vr.id DESC LIMIT 1",
        (subcontractor_id, check_type),
    ).fetchone()
    return row


def recompute_and_store_status(conn, subcontractor_id):
    cipc = latest_check(conn, subcontractor_id, "CIPC")
    cidb = latest_check(conn, subcontractor_id, "CIDB")
    ref_count = conn.execute(
        "SELECT COUNT(*) AS n FROM subcontractor_references WHERE subcontractor_id = ?",
        (subcontractor_id,),
    ).fetchone()["n"]
    years_active = conn.execute(
        "SELECT years_active FROM subcontractor_profiles WHERE id = ?", (subcontractor_id,)
    ).fetchone()["years_active"]

    cipc_outcome = cipc["outcome"] if cipc else None
    cidb_outcome = cidb["outcome"] if cidb else None
    cidb_grade = cidb["grade"] if cidb else None

    score, tier = compute_verification(cipc_outcome, cidb_outcome, cidb_grade, years_active, ref_count)
    status = compute_profile_status(cipc_outcome, cidb_outcome)

    conn.execute(
        "UPDATE subcontractor_profiles SET verification_score = ?, verification_tier = ?, "
        "profile_status = ? WHERE id = ?",
        (score, tier, status, subcontractor_id),
    )
    log_event(conn, subcontractor_id, "status_computed",
              f"Status recomputed: {status} (score {score}, {tier})")
    return score, tier, status


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
    """Onboarding form now ONLY captures what the subcontractor themselves
    can honestly claim - company details and references. No verification
    fields exist here at all; that's the whole point of the rebuild."""
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
        "references": references,
    })
    return data, errors


def validate_verification_form(form):
    """The ONLY place a check can be recorded - and only reachable by a
    logged-in verifier (see the route below). verified_by_user_id comes
    from the session, never from the form, so it can't be spoofed."""
    errors = []
    check_type = (form.get("check_type") or "").strip()
    outcome = (form.get("outcome") or "").strip()
    source = (form.get("source") or "").strip()
    notes = (form.get("notes") or "").strip()
    checked_date_raw = (form.get("checked_date") or "").strip()
    grade_raw = (form.get("grade") or "").strip()
    reference_number = (form.get("reference_number") or "").strip()

    if check_type not in config.CHECK_TYPES:
        errors.append("Please select a valid check type.")
    if outcome not in ("verified", "not_verified", "needs_review"):
        errors.append("Please select an outcome: Verified, Not verified, or Needs review.")

    if not source:
        errors.append("Source is required - state exactly what was checked against.")

    checked_date = _parse_date(checked_date_raw)
    if not checked_date:
        errors.append("Checked date is required.")
    elif checked_date > date.today():
        errors.append("Checked date can't be in the future.")

    if outcome == "verified" and not reference_number:
        errors.append(
            "A reference number (CIPC registration number / CIDB CRS number) is required "
            "when the outcome is verified - this is what makes the check auditable later."
        )

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

    if outcome in ("not_verified", "needs_review") and not notes:
        errors.append(
            "Notes are required when the outcome isn't a clean verified match - "
            "record what didn't match or what needs a second look."
        )

    if errors:
        return None, errors

    return {
        "check_type": check_type,
        "outcome": outcome,
        "grade": grade,
        "reference_number": reference_number or None,
        "source": source,
        "notes": notes or None,
        "checked_date": checked_date.isoformat(),
    }, errors


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None, next=request.args.get("next", ""))

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    next_url = request.form.get("next") or url_for("index")

    conn = db.connect(DB_PATH)
    verifier = conn.execute(
        "SELECT * FROM verifier_users WHERE email = ? AND active = 1", (email,)
    ).fetchone()
    conn.close()

    if not verifier or not auth.verify_password(password, verifier["password_hash"]):
        return render_template("login.html", error="Incorrect email or password.", next=next_url), 401

    session["verifier_id"] = verifier["id"]
    session["verifier_name"] = verifier["name"]
    session["verifier_role"] = verifier["role"]
    return redirect(next_url)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    conn = db.connect(DB_PATH)
    profiles = conn.execute(
        "SELECT * FROM subcontractor_profiles ORDER BY "
        "CASE profile_status WHEN 'needs_review' THEN 0 WHEN 'pending' THEN 1 "
        "WHEN 'verified' THEN 2 ELSE 3 END, verification_score DESC, id ASC"
    ).fetchall()

    rows = []
    for p in profiles:
        cipc = latest_check(conn, p["id"], "CIPC")
        cidb = latest_check(conn, p["id"], "CIDB")
        rows.append({"profile": p, "cipc": cipc, "cidb": cidb})
    conn.close()
    return render_template(
        "index.html", rows=rows, disclaimer=config.VERIFICATION_DISCLAIMER,
        verifier_name=auth.current_user_name(),
    )


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "GET":
        return render_template(
            "add.html", provinces=config.PROVINCES, trades=config.TRADES,
            errors=[], form={}, verifier_name=auth.current_user_name(),
        )

    data, errors = validate_profile_form(request.form)
    if errors:
        return render_template(
            "add.html", provinces=config.PROVINCES, trades=config.TRADES,
            errors=errors, form=request.form, verifier_name=auth.current_user_name(),
        ), 400

    conn = db.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO subcontractor_profiles "
        "(company_name, contact_name, phone, email, trade, province, years_active, "
        "tier, profile_status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'free', 'pending', ?)",
        (data["company_name"], data["contact_name"], data["phone"], data["email"],
         data["trade"], data["province"], data["years_active"], db.now_iso()),
    )
    sub_id = cur.lastrowid
    log_event(conn, sub_id, "profile_created",
              f"Subcontractor profile submitted: {data['company_name']} - awaiting verification")

    for ref in data["references"]:
        conn.execute(
            "INSERT INTO subcontractor_references (subcontractor_id, client_name, comment, created_at) "
            "VALUES (?, ?, ?, ?)",
            (sub_id, ref["client_name"], ref["comment"], db.now_iso()),
        )
        log_event(conn, sub_id, "reference_added", f"Reference added: {ref['client_name']}")

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
        "SELECT vr.*, vu.name AS verifier_name, vu.role AS verifier_role "
        "FROM verification_records vr "
        "JOIN verifier_users vu ON vu.id = vr.verified_by_user_id "
        "WHERE vr.subcontractor_id = ? "
        "ORDER BY vr.checked_date DESC, vr.id DESC",
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
        "profile.html", p=p, records=records, references=references, events=events,
        check_types=config.CHECK_TYPES, grades=config.CIDB_GRADES,
        sources_by_check_type=config.SOURCES_BY_CHECK_TYPE,
        today=date.today().isoformat(), errors=[], form={},
        disclaimer=config.VERIFICATION_DISCLAIMER,
        verifier_name=auth.current_user_name(), is_logged_in=bool(auth.current_user_id()),
    )


@app.route("/subcontractor/<int:sub_id>/verify", methods=["POST"])
@auth.login_required
def record_check(sub_id):
    conn = db.connect(DB_PATH)
    p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = ?", (sub_id,)).fetchone()
    if not p:
        conn.close()
        abort(404)

    checked, errors = validate_verification_form(request.form)
    if errors:
        records = conn.execute(
            "SELECT vr.*, vu.name AS verifier_name, vu.role AS verifier_role "
            "FROM verification_records vr JOIN verifier_users vu ON vu.id = vr.verified_by_user_id "
            "WHERE vr.subcontractor_id = ? ORDER BY vr.checked_date DESC, vr.id DESC", (sub_id,),
        ).fetchall()
        references = conn.execute(
            "SELECT * FROM subcontractor_references WHERE subcontractor_id = ? ORDER BY id", (sub_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM audit_events WHERE subcontractor_id = ? ORDER BY created_at, id", (sub_id,),
        ).fetchall()
        conn.close()
        return render_template(
            "profile.html", p=p, records=records, references=references, events=events,
            check_types=config.CHECK_TYPES, grades=config.CIDB_GRADES,
            sources_by_check_type=config.SOURCES_BY_CHECK_TYPE,
            today=date.today().isoformat(), errors=errors, form=request.form,
            disclaimer=config.VERIFICATION_DISCLAIMER,
            verifier_name=auth.current_user_name(), is_logged_in=True,
        ), 400

    verifier_id = auth.current_user_id()

    conn.execute(
        "INSERT INTO verification_records "
        "(subcontractor_id, check_type, outcome, reference_number, grade, source, notes, "
        "checked_date, verified_by_user_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sub_id, checked["check_type"], checked["outcome"], checked["reference_number"],
         checked["grade"], checked["source"], checked["notes"], checked["checked_date"],
         verifier_id, db.now_iso()),
    )
    detail = f", grade {checked['grade']}" if checked["grade"] else ""
    ref_detail = f", ref# {checked['reference_number']}" if checked["reference_number"] else ""
    log_event(conn, sub_id, "verification_recorded",
              f"{checked['check_type']} check recorded as {checked['outcome']}{detail}{ref_detail}, "
              f"source: {checked['source']} "
              f"(checked {checked['checked_date']} by {auth.current_user_name()})")

    recompute_and_store_status(conn, sub_id)
    conn.commit()
    conn.close()

    return redirect(url_for("profile", sub_id=sub_id))


if __name__ == "__main__":
    app.run(debug=True, port=5001)