import os
import unittest

import sub_app as app_module
import sub_db as db_module


class SubcontractorAppTests(unittest.TestCase):
    def setUp(self):
        self.db_path = "/tmp/test_subcontractors.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        app_module.DB_PATH = self.db_path
        db_module.init_db(self.db_path)

        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def valid_payload(self, **overrides):
        payload = {
            "company_name": "Sparks Electrical CC",
            "contact_name": "Thabo Nkosi",
            "phone": "011 555 1234",
            "email": "thabo@sparkselectrical.co.za",
            "trade": "Electrical",
            "province": "Gauteng",
            "years_active": "6",
            "cipc_verified": "on",
            "cipc_checked_date": "2026-08-01",
            "cipc_checked_by": "Zipho",
            "cidb_verified": "on",
            "cidb_grade": "4",
            "cidb_checked_date": "2026-08-01",
            "cidb_checked_by": "Zipho",
            "ref1_client": "Balwin Properties",
            "ref1_comment": "Rewired 3 show units on time.",
        }
        payload.update(overrides)
        return payload

    def get_conn(self):
        return db_module.connect(self.db_path)

    # --- basic pages ---

    def test_index_loads_empty(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No subcontractors yet", resp.data)

    def test_add_form_loads(self):
        resp = self.client.get("/add")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Add Subcontractor", resp.data)

    # --- creation + scoring ---

    def test_valid_submission_saves_with_correct_score(self):
        resp = self.client.post("/add", data=self.valid_payload(), follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        conn = self.get_conn()
        p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = 1").fetchone()
        self.assertEqual(p["company_name"], "Sparks Electrical CC")

        records = conn.execute("SELECT * FROM verification_records WHERE subcontractor_id = 1").fetchall()
        self.assertEqual(len(records), 2)  # CIPC + CIDB
        cidb = [r for r in records if r["check_type"] == "CIDB"][0]
        self.assertEqual(cidb["grade"], 4)
        self.assertEqual(cidb["checked_by"], "Zipho")

        refs = conn.execute("SELECT * FROM subcontractor_references WHERE subcontractor_id = 1").fetchall()
        self.assertEqual(len(refs), 1)

        # score: 25 (CIPC) + 25 (CIDB) + 4*2=8 (grade) + 6*3=18 (years, <7) + 1*7=7 (refs) = 83
        self.assertEqual(p["verification_score"], 83)
        self.assertEqual(p["verification_tier"], "Gold")
        conn.close()

    def test_unchecked_subcontractor_gets_unverified_tier(self):
        payload = self.valid_payload(cipc_verified="", cidb_verified="",
                                      cipc_checked_date="", cidb_checked_date="",
                                      cipc_checked_by="", cidb_checked_by="", cidb_grade="")
        resp = self.client.post("/add", data=payload, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        conn = self.get_conn()
        p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = 1").fetchone()
        records = conn.execute("SELECT * FROM verification_records WHERE subcontractor_id = 1").fetchall()
        self.assertEqual(len(records), 0)  # nothing checked yet, no records at all
        # years=6 -> 18, refs=1 -> 7 => 25, but forced Unverified with no checks on file
        self.assertEqual(p["verification_score"], 25)
        self.assertEqual(p["verification_tier"], "Unverified")
        conn.close()

    # --- validation ---

    def test_server_side_validation_rejects_missing_required_fields(self):
        bad_payload = self.valid_payload(company_name="", email="not-an-email", trade="Nonsense Trade")
        resp = self.client.post("/add", data=bad_payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Company name is required", resp.data)
        self.assertIn(b"valid email", resp.data)
        self.assertIn(b"valid trade", resp.data)
        conn = self.get_conn()
        count = conn.execute("SELECT COUNT(*) AS n FROM subcontractor_profiles").fetchone()["n"]
        self.assertEqual(count, 0)
        conn.close()

    def test_checked_by_required_when_verified_ticked(self):
        payload = self.valid_payload(cipc_checked_by="")
        resp = self.client.post("/add", data=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"checked by", resp.data)

    def test_future_checked_date_rejected(self):
        payload = self.valid_payload(cidb_checked_date="2099-01-01")
        resp = self.client.post("/add", data=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"can&#39;t be in the future", resp.data)

    def test_lopsided_reference_rejected(self):
        payload = self.valid_payload(ref1_client="Some Client", ref1_comment="")
        resp = self.client.post("/add", data=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"has a client name but no comment", resp.data)

    # --- profile page + re-checks ---

    def test_profile_page_and_404(self):
        self.client.post("/add", data=self.valid_payload())
        resp = self.client.get("/subcontractor/1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Sparks Electrical CC", resp.data)
        self.assertIn(b"Balwin Properties", resp.data)
        self.assertIn(b"Subcontractor profile created", resp.data)  # audit trail visible

        resp2 = self.client.get("/subcontractor/9999")
        self.assertEqual(resp2.status_code, 404)

    def test_recheck_adds_history_row_and_updates_score(self):
        self.client.post("/add", data=self.valid_payload())

        # CIDB registration lapses on re-check - score should drop, and the
        # original verified row should still be there (history, not overwrite).
        resp = self.client.post("/subcontractor/1/verify", data={
            "check_type": "CIDB", "outcome": "not_verified",
            "checked_date": "2026-09-01", "checked_by": "Zipho",
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        conn = self.get_conn()
        records = conn.execute(
            "SELECT * FROM verification_records WHERE subcontractor_id = 1 AND check_type = 'CIDB' "
            "ORDER BY id"
        ).fetchall()
        self.assertEqual(len(records), 2)
        self.assertTrue(records[0]["verified"])
        self.assertFalse(records[1]["verified"])

        p = conn.execute("SELECT * FROM subcontractor_profiles WHERE id = 1").fetchone()
        # latest CIDB now not verified: 25 (CIPC) + 0 (CIDB) + 18 (years) + 7 (refs) = 50
        self.assertEqual(p["verification_score"], 50)
        self.assertEqual(p["verification_tier"], "Silver")
        conn.close()

    def test_recheck_requires_valid_fields(self):
        self.client.post("/add", data=self.valid_payload())
        resp = self.client.post("/subcontractor/1/verify", data={
            "check_type": "CIDB", "outcome": "verified",
            "checked_date": "2026-09-01", "checked_by": "Zipho",
            # missing grade, required when outcome is verified for CIDB
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"CIDB grade is required", resp.data)

    def test_audit_trail_records_every_step(self):
        self.client.post("/add", data=self.valid_payload())
        conn = self.get_conn()
        events = conn.execute(
            "SELECT event_type FROM audit_events WHERE subcontractor_id = 1 ORDER BY id"
        ).fetchall()
        types = [e["event_type"] for e in events]
        self.assertEqual(types, [
            "profile_created", "verification_recorded", "verification_recorded",
            "reference_added", "score_computed",
        ])
        conn.close()

    def test_id_increments_across_records(self):
        self.client.post("/add", data=self.valid_payload())
        self.client.post("/add", data=self.valid_payload(company_name="Voltage Works Pty Ltd"))
        conn = self.get_conn()
        names = [r["company_name"] for r in conn.execute(
            "SELECT company_name FROM subcontractor_profiles ORDER BY id"
        ).fetchall()]
        self.assertEqual(names, ["Sparks Electrical CC", "Voltage Works Pty Ltd"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
