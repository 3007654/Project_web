# Subcontractor Verification - Clean Rebuild

This replaces everything in your `subcontractor_db` folder. All 40 tests pass
(verified by actually running them), plus a full live-server walkthrough:
submit a profile (lands Pending) &rarr; view it logged out (login prompt, no
verification form) &rarr; log in as a verifier &rarr; record a check &rarr;
profile flips to Verified with a live freshness badge.

**A note on how this was built:** an earlier message in this thread described
a "Subcontractor Passport" version already built with 31 passing tests. That
description doesn't match anything actually in this folder or anything I have
a record of building - there was no `passport.py`, no skills/equipment
tables, no evidence fields anywhere in what was uploaded. What *was* real and
uploaded was the auth/verifier rebuild (login-gated checks, three-way
outcomes, evidence via reference numbers) - `auth.py`, `create_verifier.py`,
`db.py`, `verification.py`, `test_app.py`, and the templates. `app.py` and
`config.py` were never actually provided as content, only referenced by
filename. This rebuild takes that real uploaded material as the honest
starting point and adds the passport/capability/evidence/availability
features fresh on top of it - not "confirmed" from a prior claim, actually
written and tested here.

## What's in this version

**From the auth rebuild you uploaded (kept, not re-invented):**
- `verifier_users` table - real accounts, password-hashed, created only via
  `create_verifier.py` (terminal tool, no public sign-up).
- Recording a check requires login (`@auth.login_required` on `/verify`).
  `verified_by_user_id` always comes from the server-side session, never
  from anything the form claims.
- Three-way outcome: Verified / Not Verified / Needs Review. A `needs_review`
  result on any check type takes priority in the overall profile status.
- Every check requires a named `source`, and (if verified) a reference
  number; anything other than a clean Verified requires `notes`.
- A submission always starts `pending`, with zero verification records -
  there's no field anywhere on the submission form that can pre-verify it.

**New in this rebuild, per your last message:**
- **Capability data, structured** - `subcontractor_skills` and
  `subcontractor_equipment` are real tables (one row per skill/equipment
  item), not a paragraph of free text - a future matching engine can query
  "who has X skill" directly.
- **Evidence on references** - `subcontractor_references` now carries an
  optional `evidence_url` (validated as a real http/https link) and
  `project_value`. This is a link field, not a file upload - real file
  upload needs its own security work (file-type checks, size limits, path
  traversal protection) that deserves dedicated attention rather than being
  rushed in here.
- **Availability status** - Available now / Currently engaged / Available
  from a future date, with real validation: picking "available from"
  requires a date, and it must actually be in the future.
- **Verification freshness** - every check shows how many days old it is,
  color-coded Fresh (&le;30 days) / Aging (31-90) / Stale (90+), computed in
  `passport.py`.
- **"Why this status"** - a plain-language sentence per check type: what was
  checked, against what source, when, by whom, with the reference number and
  any notes - not just a badge color.
- **Subcontractor Passport card** - sits at the top of the profile page
  (public, no login needed to view): availability, skill/equipment/reference
  counts, and the freshness of the most recent check, at a glance.

## Files

```
subcontractor_db/
├── app.py                  Flask routes, validation, all wiring
├── config.py                provinces / trades / check sources / disclaimer
├── db.py                    SQLite schema (6 tables, see below)
├── auth.py                  password hashing + login_required decorator
├── passport.py              freshness calculation + plain-language explanations
├── verification.py          score/tier and profile-status computation
├── create_verifier.py       terminal tool to create verifier accounts
├── test_app.py               40 tests
└── templates/
    ├── base.html
    ├── index.html
    ├── add.html
    ├── profile.html
    └── login.html
```

## Schema

```
verifier_users

subcontractor_profiles
    ├── verification_records      (CIPC, CIDB, or a future check type;
    │                               never overwritten - history preserved)
    ├── subcontractor_references   (client, comment, evidence_url, project_value)
    ├── subcontractor_skills
    ├── subcontractor_equipment
    └── audit_events               (timestamped: what happened, for whom)
```

## Setup - this REPLACES your existing subcontractor_db folder

1. **Delete the entire current contents** of `subcontractor_db` - old mixed
   files (some from an earlier plain rebuild, some from the auth rebuild)
   are the source of the confusion here. Start clean.
2. Copy all the `.py` files above straight into `subcontractor_db/`, and the
   five `.html` files into `subcontractor_db/templates/`.
3. **Delete `subcontractors.db`** if one exists - the schema changed again
   (two new tables), it needs to be recreated.
4. `pip install flask` (no new dependency beyond Flask itself - password
   hashing uses werkzeug, already bundled with Flask).
5. **Create your first verifier account:**
   ```
   python create_verifier.py
   ```
   Follow the prompts. Create one account per person who'll actually be
   doing CIPC/CIDB checks.
6. Run: `python app.py`
7. Open `http://127.0.0.1:5001`

## Using it

- **Add Subcontractor** - company details, availability, skills, equipment,
  and up to 3 references (each optionally with an evidence link and a
  project value). No verification fields anywhere. Lands as
  **Verification Pending**.
- Click into the profile. Logged out, you'll see the Passport card, the
  "Why this status" section (empty until a check exists), capability,
  references, and audit trail - but a **login prompt** instead of a
  verification form.
- Click **Verifier login**, sign in with the account you created.
- The **Record a check** form now appears, tied to your name. Try leaving
  Notes blank on a "Not verified" outcome and watch it get rejected.
- After recording a check, refresh the profile: the status badge, score,
  and "Why this status" section all update, and the check shows up in
  Verification history with a Fresh/Aging/Stale freshness tag.

## Run the tests yourself
```
python -m unittest test_app.py -v
```