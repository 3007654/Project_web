# Phase 2 — Subcontractor Verification (rebuilt)

Rebuilt from the original flat-file version to fix two things: what "Verified" is
allowed to claim, and the database shape underneath it. Tested end to end — 13/13
tests pass, plus a manual run against the live server (add a profile, re-check CIDB
as lapsed, watch the score and audit trail update).

## Why it changed

The original version's badge implied a company was trustworthy. That's not something
this platform (or any platform doing manual portal checks) can actually demonstrate.
What it *can* demonstrate is narrower and still useful: **this specific detail was
checked, against this source, on this date, by this person.** Every place that used to
say "Verified" now says that instead — see `config.VERIFICATION_DISCLAIMER`, shown on
both the list page and every profile.

This also means CIPC/CIDB checks are stored as a **history**, not a flag that gets
overwritten. If a subcontractor's CIDB grading lapses, that's a new row, not an edit —
the fact it was once verified doesn't disappear, and neither does the fact it later
wasn't.

## Schema

```
subcontractor_profiles
    |
    +-- verification_records   (one row per check: CIPC, CIDB, or a future check type;
    |                            never overwritten, so history is preserved)
    +-- subcontractor_references
    +-- audit_events           (a timestamped log: what happened, when, for whom)
```

This is intentionally just the subcontractor-side slice of the bigger picture discussed
(tenders / awarded contractors / requests / matches / contact_unlock come later). It's
shaped so those slot in later without a rewrite — `audit_events` already has a generic
`subcontractor_id` link and a free-text `event_type`, so a future `tender_id` or
`match_id` column is additive, not a redesign. Storage moved from flat JSON files to
SQLite (`subcontractors.db`, stdlib `sqlite3`, no new dependency) since a normalized,
queryable history is the point here, not just a shape another script can read.

`config.CHECK_TYPES` is deliberately just `["CIPC", "CIDB"]` for now but is meant to
grow — e.g. B-BBEE status or tax clearance, the way some competitor platforms already
track — without touching the schema.

## Verification score

Same weighting as before, now computed from the *latest* record per check type rather
than a stored flag:

- CIPC verified: +25
- CIDB verified: +25, plus +2 per CIDB grade (capped at +18)
- Years active: +3/year, capped at 7+ years (+21 max)
- Site references: +7 each, capped at 3 (+21 max)
- Capped at 100

Tiers: **Gold** (75+), **Silver** (40+), **Bronze** (below 40), or **Unverified** if
neither CIPC nor CIDB has ever been checked. If the *latest* CIDB check comes back
"not verified" (e.g. a lapsed registration), the profile drops out of Gold/Silver even
if an earlier check was positive — the score always reflects what's most recently on
file, and the audit trail keeps the full record of how it got there.

## What's new on the profile page

- **Verification history** — every check ever recorded for this subcontractor, not
  just the latest: check type, outcome, grade (CIDB only), date, and who checked it.
- **Record a check** — a small form to log a new check (e.g. a scheduled re-verification)
  without editing the profile. Outcome is a required Verified/Not Verified choice,
  because submitting this form means a check was actually performed — there's no way
  to silently leave a check type in limbo.
- **Audit trail** — every event for this profile in order: profile created, each check
  recorded, each reference added, each time the score was recomputed and to what.

## Setup in VS Code

1. Create a folder `subcontractor_db`, with a `templates` subfolder inside it.
2. Put `sub_app.py`, `sub_config.py`, `sub_db.py`, `sub_verification.py`, and `sub_test_app.py` in
   `subcontractor_db/`.
3. Put `sub_base.html`, `sub_index.html`, `sub_add.html`, and `sub_profile.html` in
   `subcontractor_db/templates/`.
4. In the terminal: `pip install flask`
5. Run: `python sub_app.py`
6. Open `http://127.0.0.1:5001` (port 5001, so it can run alongside the request form app).

`subcontractors.db` is created automatically on first run in the same folder.

To re-run the tests yourself: `python -m unittest sub_test_app.py -v`

## What's next

This is still just the "Subcontractor Verification" box from your diagram — CIPC,
CIDB, company details, trade, years, references → verification badge. The bigger
chain (tender → tender verification → awarded contractor verification → subcontractor
verification → match → both parties accept → contact unlocked → audit trail) is the
right direction, but per your own note: not built yet. The `audit_events` table here
is the piece that chain will lean on most, and it's already in place.
