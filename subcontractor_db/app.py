import os
import re
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, abort, session

import config
import db
import auth
import passport
from verification import compute_verification, compute_profile_status

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, config.DB_PATH)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_RE = re.compile(r"^https?://\S+$")

db.init_db(DB_PATH)


@app.context_processor
def inject_verifier_state():
    return {"verifier_name": auth.current_user_name(), "is_logged_in": bool(auth.current_user_id())}


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
    return conn.execute(
        "SELECT vr.*, vu.name AS verifier_name, vu.role AS verifier_role "
        "FROM verification_records vr "
        "JOIN verifier_users vu ON vu.id = vr.verified_by_user_id "
        "WHERE vr.subcontractor_id = ? AND vr.check_type = ? "
        "ORDER BY vr.checked_date DESC, vr.id DESC LIMIT 1",
        (subcontractor_id, check_type),
    ).fetchone()


def all_checks(conn, subcontractor_id):
    return conn.execute(
        "SELECT vr.*, vu.name AS verifier_name, vu.role AS verifier_role "
        "FROM verification_records vr "
        "JOIN verifier_users vu ON vu.id = vr.verified_by_user_id "
        "WHERE vr.subcontractor_id = ? "
        "ORDER BY vr.checked_date DESC, vr.id DESC",
        (subcontractor_id,),
    ).fetchall()


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
              f"Status recomputed: {status} (score {score}, tier {tier})")
    return score, tier, status


# ---------------------------------------------------------------------------
# Validation - profile submission (Phase 2B: no verification fields at all)
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
    availability_status = (form.get("availability_status") or "").strip()
    availability_date_raw = (form.get("availability_date") or "").strip()

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

    valid_statuses = [s[0] for s in config.AVAILABILITY_STATUSES]
    availability_date = None
    if availability_status not in valid_statuses:
        errors.append("Please select a valid availability status.")
    elif availability_status == "available_from":
        parsed = _parse_date(availability_date_raw)
        if not parsed:
            errors.append("Availability date is required when status is 'Available from a future date'.")
        elif parsed <= date.today():
            errors.append("Availability date must be in the future.")
        else:
            availability_date = parsed.isoformat()

    # --- skills / equipment: simple comma-separated lists ---
    skills_raw = (form.get("skills") or "").strip()
    skills = [s.strip() for s in skills_raw.split(",") if s.strip()][:config.MAX_SKILLS] if skills_raw else []

    equipment_raw = (form.get("equipment") or "").strip()
    equipment = [e.strip() for e in equipment_raw.split(",") if e.strip()][:config.MAX_EQUIPMENT] if equipment_raw else []

    # --- references, each optionally carrying evidence ---
    references = []
    for i in range(1, config.MAX_REFERENCES + 1):
        client = (form.get(f"ref{i}_client") or "").strip()
        comment = (form.get(f"ref{i}_comment") or "").strip()
        evidence_url = (form.get(f"ref{i}_evidence_url") or "").strip()
        project_value = (form.get(f"ref{i}_project_value") or "").strip()

        if client and not comment:
            errors.append(f"Reference {i} has a client name but no comment.")
            continue
        if comment and not client:
            errors.append(f"Reference {i} has a comment but no client name.")
            continue
        if not client and not comment:
            if evidence_url or project_value:
                errors.append(f"Reference {i} needs a client name and comment before adding evidence or a project value.")
            continue

        if evidence_url and not URL_RE.match(evidence_url):
            errors.append(f"Reference {i}'s evidence link must be a valid http(s) URL.")
            continue

        references.append({
            "client_name": client, "comment": comment,
            "evidence_url": evidence_url or None,
            "project_value": project_value or None,
        })

    data.update({
        "company_name": company_name, "contact_name": contact_name, "phone": phone,
        "email": email, "trade": trade, "province": province, "years_active": years_active,
        "availability_status": availability_status, "availability_date": availability_date,
        "skills": skills, "equipment": equipment, "references": references,
    })
    return data, errors


def validate_recheck_form(form):
    errors = []
    check_type = (form.get("check_type") or "").strip()
    outcome = (form.get("outcome") or "").strip()
    source = (form.get("source") or "").strip()
    reference_number = (form.get("reference_number") or "").strip()
    grade_raw = (form.get("grade") or "").strip()
    checked_date_raw = (form.get("checked_date") or "").strip()
    notes = (form.get("notes") or "").strip()

    if check_type not in config.CHECK_TYPES:
        errors.append("Please select a valid check type.")
    if outcome not in ("verified", "not_verified", "needs_review"):
        errors.append("Please select a valid outcome.")
    if not source:
        errors.append("Source is required.")

    checked_date = _parse_date(checked_date_raw)
    if not checked_date:
        errors.append("Checked date is required.")
    elif checked_date > date.today():
        errors.append("Checked date can't be in the future.")

    grade = None
    if outcome == "verified":
        if not reference_number:
            errors.append("A reference number is required when the outcome is verified.")
        if check_type == "CIDB":
            if not grade_raw:
                errors.append("CIDB grade is required when the outcome is verified.")
            else:
                try:
                    grade = int(grade_raw)
                    if grade not in config.CIDB_GRADES:
                        errors.append("CIDB grade must be between 1 and 9.")
                except ValueError:
                    errors.append("CIDB grade must be a whole number.")
    else:
        if not notes:
            errors.append("Notes are required unless the outcome is a clean Verified.")

    if errors:
        return None, errors

    return {
        "check_type": check_type, "outcome": outcome, "source": source,
        "reference_number": reference_number or None, "grade": grade,
        "checked_date": checked_date.isoformat(), "notes": notes or None,
    }, errors


# ---------------------------------------------------------------------------
# Routes - public
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
        rows.append({"profile": p, "cipc": cipc, "cidb": cidb,
                      "availability": passport.availability_text(p)})
    conn.close()
    return render_template("index.html", rows=rows, disclaimer=config.VERIFICATION_DISCLAIMER)


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "GET":
        return render_template(
            "add.html", provinces=config.PROVINCES, trades=config.TRADES,
            availability_statuses=config.AVAILABILITY_STATUSES,
            errors=[], form={}, today=date.today().isoformat(),
        )

    data, errors = validate_profile_form(request.form)
    if errors:
        return render_template(
            "add.html", provinces=config.PROVINCES, trades=config.TRADES,
            availability_statuses=config.AVAILABILITY_STATUSES,
            errors=errors, form=request.form, today=date.today().isoformat(),
        ), 400

    conn = db.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO subcontractor_profiles "
        "(company_name, contact_name, phone, email, trade, province, years_active, "
        " availability_status, availability_date, tier, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'free', ?)",
        (data["company_name"], data["contact_name"], data["phone"], data["email"],
         data["trade"], data["province"], data["years_active"],
         data["availability_status"], data["availability_date"], db.now_iso()),
    )
    sub_id = cur.lastrowid

    avail_text = passport.availability_text({
        "availability_status": data["availability_status"],
        "availability_date": data["availability_date"],
    })
    log_event(conn, sub_id, "profile_created",
              f"Subcontractor profile created: {data['company_name']} (availability: {avail_text})")

    for ref in data["references"]:
        conn.execute(
            "INSERT INTO subcontractor_references "
            "(subcontractor_id, client_name, comment, evidence_url, project_value, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sub_id, ref["client_name"], ref["comment"], ref["evidence_url"], ref["project_value"],
             db.now_iso()),
        )
        log_event(conn, sub_id, "reference_added", f"Reference added: {ref['client_name']}")

    for skill in data["skills"]:
        conn.execute(
            "INSERT INTO subcontractor_skills (subcontractor_id, skill_name, created_at) VALUES (?, ?, ?)",
            (sub_id, skill, db.now_iso()),
        )
        log_event(conn, sub_id, "skill_added", f"Skill added: {skill}")

    for item in data["equipment"]:
        conn.execute(
            "INSERT INTO subcontractor_equipment (subcontractor_id, equipment_name, created_at) VALUES (?, ?, ?)",
            (sub_id, item, db.now_iso()),
        )
        log_event(conn, sub_id, "equipment_added", f"Equipment added: {item}")

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

    records = all_checks(conn, sub_id)
    references = conn.execute(
        "SELECT * FROM subcontractor_references WHERE subcontractor_id = ? ORDER BY id",
        (sub_id,),
    ).fetchall()
    skills = conn.execute(
        "SELECT * FROM subcontractor_skills WHERE subcontractor_id = ? ORDER BY id", (sub_id,),
    ).fetchall()
    equipment = conn.execute(
        "SELECT * FROM subcontractor_equipment WHERE subcontractor_id = ? ORDER BY id", (sub_id,),
    ).fetchall()
    events = conn.execute(
        "SELECT * FROM audit_events WHERE subcontractor_id = ? ORDER BY created_at, id", (sub_id,),
    ).fetchall()

    cipc = latest_check(conn, sub_id, "CIPC")
    cidb = latest_check(conn, sub_id, "CIDB")
    conn.close()

    explanations = []
    for rec in (cipc, cidb):
        if rec:
            sentence, label, css, days = passport.explain_check(rec)
            explanations.append({"sentence": sentence, "label": label, "css": css, "days": days,
                                  "check_type": rec["check_type"]})

    return render_template(
        "profile.html", p=p, records=records, references=references,
        skills=skills, equipment=equipment, events=events,
        check_types=config.CHECK_TYPES, grades=config.CIDB_GRADES,
        sources_by_check_type=config.SOURCES_BY_CHECK_TYPE,
        today=date.today().isoformat(), errors=[], form={},
        disclaimer=config.VERIFICATION_DISCLAIMER,
        is_logged_in=bool(auth.current_user_id()), verifier_name=auth.current_user_name(),
        availability=passport.availability_text(p), explanations=explanations,
    )


# ---------------------------------------------------------------------------
# Routes - verification (login required)
# ---------------------------------------------------------------------------

@app.route("/subcontractor/<int:sub_id>/verify", methods=["POST"])
@auth.login_required
def record_check(sub_id):
    conn = db.connect(DB_PATH)
    p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = ?", (sub_id,)).fetchone()
    if not p:
        conn.close()
        abort(404)

    checked, errors = validate_recheck_form(request.form)
    if errors:
        records = all_checks(conn, sub_id)
        references = conn.execute(
            "SELECT * FROM subcontractor_references WHERE subcontractor_id = ? ORDER BY id", (sub_id,),
        ).fetchall()
        skills = conn.execute(
            "SELECT * FROM subcontractor_skills WHERE subcontractor_id = ? ORDER BY id", (sub_id,),
        ).fetchall()
        equipment = conn.execute(
            "SELECT * FROM subcontractor_equipment WHERE subcontractor_id = ? ORDER BY id", (sub_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM audit_events WHERE subcontractor_id = ? ORDER BY created_at, id", (sub_id,),
        ).fetchall()
        cipc = latest_check(conn, sub_id, "CIPC")
        cidb = latest_check(conn, sub_id, "CIDB")
        conn.close()

        explanations = []
        for rec in (cipc, cidb):
            if rec:
                sentence, label, css, days = passport.explain_check(rec)
                explanations.append({"sentence": sentence, "label": label, "css": css, "days": days,
                                      "check_type": rec["check_type"]})

        return render_template(
            "profile.html", p=p, records=records, references=references,
            skills=skills, equipment=equipment, events=events,
            check_types=config.CHECK_TYPES, grades=config.CIDB_GRADES,
            sources_by_check_type=config.SOURCES_BY_CHECK_TYPE,
            today=date.today().isoformat(), errors=errors, form=request.form,
            disclaimer=config.VERIFICATION_DISCLAIMER,
            is_logged_in=True, verifier_name=auth.current_user_name(),
            availability=passport.availability_text(p), explanations=explanations,
        ), 400

    conn.execute(
        "INSERT INTO verification_records "
        "(subcontractor_id, check_type, outcome, reference_number, grade, source, notes, "
        " checked_date, verified_by_user_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sub_id, checked["check_type"], checked["outcome"], checked["reference_number"],
         checked["grade"], checked["source"], checked["notes"], checked["checked_date"],
         auth.current_user_id(), db.now_iso()),
    )
    log_event(conn, sub_id, "verification_recorded",
              f"{checked['check_type']} recorded as {checked['outcome']} against {checked['source']} "
              f"(checked {checked['checked_date']} by {auth.current_user_name()})")

    recompute_and_store_status(conn, sub_id)
    conn.commit()
    conn.close()

    return redirect(url_for("profile", sub_id=sub_id))


# ---------------------------------------------------------------------------
# Routes - login/logout
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or request.form.get("next") or url_for("index")

    if request.method == "GET":
        return render_template("login.html", error=None, next=next_url)

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    conn = db.connect(DB_PATH)
    user = conn.execute(
        "SELECT * FROM verifier_users WHERE email = ? AND active = 1", (email,)
    ).fetchone()
    conn.close()

    if not user or not auth.verify_password(password, user["password_hash"]):
        return render_template("login.html", error="Incorrect email or password.", next=next_url), 401

    session["verifier_id"] = user["id"]
    session["verifier_name"] = user["name"]
    session["verifier_role"] = user["role"]
    return redirect(next_url)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)