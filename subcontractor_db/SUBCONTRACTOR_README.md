# Phase 2 - Subcontractor Verification

Verified: all 13 tests pass, and the rendered pages were checked directly to
confirm the wording never claims a company "is legitimate" or "cannot commit
fraud" outside the disclaimer explaining that those are NOT what this badge
means.

## What this fixes

The badge no longer says "TRUSTED COMPANY". It says things like:
"CIPC: Verified - checked 5 September 2026 by Zipho"

That's a claim this platform can actually stand behind: a specific check,
against a specific source, on a specific date, by a named person. It is
NOT a claim that the company is legitimate or incapable of fraud - and the
UI says that explicitly, everywhere the badge appears.

## What this can't fix (and why)

No software can stop a person from ticking "verified" without actually
doing the check - that needs a live, authoritative API, and neither CIPC
nor CIDB offers one for free (see earlier research: CIPC requires a paid
login since 2024; CIDB's free portal isn't a documented API). What this
design DOES do instead: every check is permanently attributed to a named
person and a timestamp, and re-checks add new history rows rather than
silently overwriting the old one. A false "verified" entry is traceable,
not invisible.

## Setup in VS Code

1. Create a folder `subcontractor_verification`, with a `templates`
   subfolder inside it.
2. Put app.py, config.py, db.py, verification.py, test_app.py in the
   main folder.
3. Put base.html, index.html, add.html, profile.html in `templates/`.
4. `pip install flask`
5. Run: `python app.py`
6. Open http://127.0.0.1:5001 (port 5001, so it can run alongside the
   Phase 1 request form on port 5000 at the same time).

`subcontractors.db` is created automatically on first run.

To re-run the tests: `python -m unittest test_app.py -v`