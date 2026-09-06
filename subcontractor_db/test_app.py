import os
import unittest
from datetime import datetime, timezone

import auth
import app as app_module
import db as db_module


class SubcontractorAppTests(unittest.TestCase):
    def setUp(self):
        self.db_path = "/tmp/test_subcontractors.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        app_module.DB_PATH = self.db_path
        db_module.init_db(self.db_path)

        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

        # Create one verifier account directly (bypassing create_verifier.py's
        # interactive prompts, which don't belong in an automated test).
        conn = self.get_conn()
        conn.execute(
            "INSERT INTO verifier_users (name, email, password_hash, role, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            ("Jane Verifier", "jane@platform.co.za", auth.hash_password("correct-horse-battery"),
             "VERIFIER", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        self.verifier_id = conn.execute(
            "SELECT id FROM verifier_users WHERE email = 'jane@platform.co.za'"
        ).fetchone()["id"]
        conn.close()

    def get_conn(self):
        return db_module.connect(self.db_path)

    def login(self):
        return self.client.post("/login", data={"email": "jane@platform.co.za", "password": "correct-horse-battery"})

    def valid_profile_payload(self, **overrides):
        payload = {
            "company_name": "Sparks Electrical CC",
            "contact_name": "Thabo Nkosi",
            "phone": "011 555 1234",
            "email": "thabo@sparkselectrical.co.za",
            "trade": "Electrical",
            "province": "Gauteng",
            "years_active": "6",
            "ref1_client": "Balwin Properties",
            "ref1_comment": "Rewired 3 show units on time.",
        }
        payload.update(overrides)
        return payload

    def valid_check_payload(self, **overrides):
        payload = {
            "check_type": "CIPC",
            "outcome": "verified",
            "source": "CIPC eServices portal (eservices.cipc.co.za)",
            "reference_number": "2019/123456/07",
            "checked_date": "2026-09-05",
        }
        payload.update(overrides)
        return payload

    # --- basic pages ---

    def test_index_loads_empty(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No subcontractors yet", resp.data)

    def test_add_form_loads_with_no_verification_fields(self):
        resp = self.client.get("/add")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Add Subcontractor", resp.data)
        self.assertNotIn(b"cipc_verified", resp.data)
        self.assertNotIn(b"cidb_verified", resp.data)

    # --- submission always starts pending, and can't self-verify ---

    def test_submission_starts_as_pending_with_no_checks(self):
        resp = self.client.post("/add", data=self.valid_profile_payload(), follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Verification Pending", resp.data)

        conn = self.get_conn()
        p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = 1").fetchone()
        self.assertEqual(p["profile_status"], "pending")
        self.assertEqual(p["verification_tier"], "Unverified")
        self.assertEqual(p["verification_score"], 0)

        records = conn.execute("SELECT * FROM verification_records WHERE subcontractor_id = 1").fetchall()
        self.assertEqual(len(records), 0)
        conn.close()

    def test_add_form_ignores_any_verification_fields_even_if_submitted(self):
        """Even if someone crafts a POST with old-style verification fields
        (e.g. replaying an old form), the submission endpoint has no code
        path that reads them - they're silently ignored, not honoured."""
        payload = self.valid_profile_payload(cipc_verified="on", cipc_checked_by="Anonymous")
        self.client.post("/add", data=payload)

        conn = self.get_conn()
        records = conn.execute("SELECT * FROM verification_records").fetchall()
        self.assertEqual(len(records), 0)
        conn.close()

    # --- verification requires login ---

    def test_recording_a_check_requires_login(self):
        self.client.post("/add", data=self.valid_profile_payload())
        resp = self.client.post("/subcontractor/1/verify", data=self.valid_check_payload(), follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

        conn = self.get_conn()
        records = conn.execute("SELECT * FROM verification_records").fetchall()
        self.assertEqual(len(records), 0)  # nothing was recorded
        conn.close()

    def test_wrong_password_rejected(self):
        resp = self.client.post("/login", data={"email": "jane@platform.co.za", "password": "wrong"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn(b"Incorrect email or password", resp.data)

    def test_login_then_record_check_succeeds(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        resp = self.client.post("/subcontractor/1/verify", data=self.valid_check_payload(), follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        conn = self.get_conn()
        records = conn.execute("SELECT * FROM verification_records WHERE subcontractor_id = 1").fetchall()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["verified_by_user_id"], self.verifier_id)
        self.assertEqual(records[0]["outcome"], "verified")
        self.assertEqual(records[0]["source"], "CIPC eServices portal (eservices.cipc.co.za)")
        conn.close()

    def test_verified_by_comes_from_session_not_form(self):
        """Even if a malicious form post tries to claim a different
        verifier, the recorded verified_by_user_id must come from the
        server-side session, not anything the client sent."""
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        payload = self.valid_check_payload()
        payload["verified_by_user_id"] = "9999"  # attempted spoof, should be ignored entirely
        self.client.post("/subcontractor/1/verify", data=payload)

        conn = self.get_conn()
        record = conn.execute("SELECT * FROM verification_records WHERE subcontractor_id = 1").fetchone()
        self.assertEqual(record["verified_by_user_id"], self.verifier_id)
        conn.close()

    def test_logout_then_verify_redirects_again(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        self.client.post("/logout")
        resp = self.client.post("/subcontractor/1/verify", data=self.valid_check_payload(), follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    # --- evidence requirements ---

    def test_reference_number_required_when_verified(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        payload = self.valid_check_payload(reference_number="")
        resp = self.client.post("/subcontractor/1/verify", data=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"reference number", resp.data)

    def test_source_always_required(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        payload = self.valid_check_payload(source="")
        resp = self.client.post("/subcontractor/1/verify", data=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Source is required", resp.data)

    def test_notes_required_for_not_verified_outcome(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        payload = self.valid_check_payload(outcome="not_verified", reference_number="", notes="")
        resp = self.client.post("/subcontractor/1/verify", data=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Notes are required", resp.data)

    def test_notes_required_for_needs_review_outcome(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        payload = self.valid_check_payload(outcome="needs_review", reference_number="", notes="")
        resp = self.client.post("/subcontractor/1/verify", data=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Notes are required", resp.data)

    def test_cidb_grade_required_when_verified(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        payload = self.valid_check_payload(
            check_type="CIDB", source="CIDB Register of Contractors (portal.cidb.org.za)",
            reference_number="10095915",
        )
        resp = self.client.post("/subcontractor/1/verify", data=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"CIDB grade is required", resp.data)

    def test_future_date_rejected(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        payload = self.valid_check_payload(checked_date="2099-01-01")
        resp = self.client.post("/subcontractor/1/verify", data=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"can&#39;t be in the future", resp.data)

    # --- status computation ---

    def test_profile_status_verified_after_one_positive_check(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        self.client.post("/subcontractor/1/verify", data=self.valid_check_payload())

        conn = self.get_conn()
        p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = 1").fetchone()
        self.assertEqual(p["profile_status"], "verified")
        conn.close()

    def test_profile_status_not_verified_when_only_negative_checks_exist(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        payload = self.valid_check_payload(outcome="not_verified", reference_number="", notes="Name mismatch on CIPC.")
        self.client.post("/subcontractor/1/verify", data=payload)

        conn = self.get_conn()
        p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = 1").fetchone()
        self.assertEqual(p["profile_status"], "not_verified")
        conn.close()

    def test_profile_status_needs_review_takes_priority(self):
        """Even if CIPC comes back cleanly verified, a CIDB check flagged
        needs_review should surface - not get hidden behind the good result."""
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        self.client.post("/subcontractor/1/verify", data=self.valid_check_payload())  # CIPC verified
        cidb_payload = self.valid_check_payload(
            check_type="CIDB", outcome="needs_review", reference_number="",
            source="CIDB Register of Contractors (portal.cidb.org.za)",
            notes="Company name is close but not exact - could be a different entity.",
        )
        self.client.post("/subcontractor/1/verify", data=cidb_payload)

        conn = self.get_conn()
        p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = 1").fetchone()
        self.assertEqual(p["profile_status"], "needs_review")
        conn.close()

    def test_lapse_preserves_history_and_updates_status(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        cidb_verified = self.valid_check_payload(
            check_type="CIDB", source="CIDB Register of Contractors (portal.cidb.org.za)",
            reference_number="10095915", grade="4",
        )
        self.client.post("/subcontractor/1/verify", data=cidb_verified)

        cidb_lapsed = self.valid_check_payload(
            check_type="CIDB", outcome="not_verified", reference_number="",
            source="CIDB Register of Contractors (portal.cidb.org.za)",
            checked_date="2026-09-06", notes="Registration has lapsed since last check.",
        )
        self.client.post("/subcontractor/1/verify", data=cidb_lapsed)

        conn = self.get_conn()
        records = conn.execute(
            "SELECT * FROM verification_records WHERE subcontractor_id = 1 AND check_type = 'CIDB' ORDER BY id"
        ).fetchall()
        self.assertEqual(len(records), 2)  # both kept, nothing overwritten
        self.assertEqual(records[0]["outcome"], "verified")
        self.assertEqual(records[1]["outcome"], "not_verified")

        p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = 1").fetchone()
        self.assertEqual(p["profile_status"], "not_verified")  # latest CIDB, only check on file
        conn.close()

    # --- profile page + audit trail ---

    def test_profile_page_shows_verifier_identity(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        self.client.post("/subcontractor/1/verify", data=self.valid_check_payload())

        resp = self.client.get("/subcontractor/1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Jane Verifier", resp.data)
        self.assertIn(b"VERIFIER", resp.data)

    def test_profile_404_for_missing_id(self):
        resp = self.client.get("/subcontractor/9999")
        self.assertEqual(resp.status_code, 404)

    def test_audit_trail_records_every_step(self):
        self.client.post("/add", data=self.valid_profile_payload())
        self.login()
        self.client.post("/subcontractor/1/verify", data=self.valid_check_payload())

        conn = self.get_conn()
        events = conn.execute(
            "SELECT event_type FROM audit_events WHERE subcontractor_id = 1 ORDER BY id"
        ).fetchall()
        types = [e["event_type"] for e in events]
        self.assertEqual(types, [
            "profile_created", "reference_added", "verification_recorded", "status_computed",
        ])
        conn.close()

    def test_logged_out_profile_page_shows_login_prompt_not_form(self):
        self.client.post("/add", data=self.valid_profile_payload())
        resp = self.client.get("/subcontractor/1")
        self.assertIn(b"Log in as a verifier", resp.data)
        self.assertNotIn(b"Record check", resp.data)


if __name__ == "__main__":
    unittest.main()