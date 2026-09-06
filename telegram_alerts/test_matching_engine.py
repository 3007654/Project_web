import json
import os
import sqlite3
import tempfile
import unittest

import config
import matching_engine


class MatchingEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "subs.db")
        self.tenders_path = os.path.join(self.tmpdir, "tenders.json")
        self.requests_path = os.path.join(self.tmpdir, "requests.json")

        self._orig_db_path = config.SUBCONTRACTORS_DB_PATH
        self._orig_tenders_path = config.MATCHED_TENDERS_JSON
        self._orig_requests_path = config.DIRECT_REQUESTS_JSON
        config.SUBCONTRACTORS_DB_PATH = self.db_path
        config.MATCHED_TENDERS_JSON = self.tenders_path
        config.DIRECT_REQUESTS_JSON = self.requests_path

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE subcontractor_profiles (
                id INTEGER PRIMARY KEY, company_name TEXT, trade TEXT, province TEXT
            )
        """)
        conn.execute("INSERT INTO subcontractor_profiles VALUES (1, 'Sparks Electrical', 'Electrical', 'Gauteng')")
        conn.execute("INSERT INTO subcontractor_profiles VALUES (2, 'Rocky Mining Co', 'Mining & resources', 'Free State')")
        conn.commit()
        conn.close()

    def tearDown(self):
        config.SUBCONTRACTORS_DB_PATH = self._orig_db_path
        config.MATCHED_TENDERS_JSON = self._orig_tenders_path
        config.DIRECT_REQUESTS_JSON = self._orig_requests_path

    def test_load_subcontractors_from_sqlite(self):
        subs = matching_engine.load_subcontractors()
        self.assertEqual(len(subs), 2)
        self.assertEqual(subs[0]["company_name"], "Sparks Electrical")

    def test_tender_matches_on_province_and_industry_overlap(self):
        tenders = [{
            "ocid": "t1", "province": "Gauteng", "title": "Electrical works",
            "industries": ["Electrical", "Construction & civil"],
        }]
        subs = matching_engine.load_subcontractors()
        matches = matching_engine.find_tender_matches(tenders, subs)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["subcontractor_name"], "Sparks Electrical")

    def test_tender_no_match_wrong_province(self):
        tenders = [{"ocid": "t2", "province": "Western Cape", "industries": ["Electrical"]}]
        subs = matching_engine.load_subcontractors()
        matches = matching_engine.find_tender_matches(tenders, subs)
        self.assertEqual(len(matches), 0)

    def test_tender_no_match_wrong_industry(self):
        tenders = [{"ocid": "t3", "province": "Gauteng", "industries": ["Mining & resources"]}]
        subs = matching_engine.load_subcontractors()
        matches = matching_engine.find_tender_matches(tenders, subs)
        self.assertEqual(len(matches), 0)  # Rocky Mining is in Free State, not Gauteng

    def test_direct_request_matches_single_industry(self):
        reqs = [{"request_id": "r1", "province": "Free State", "industry": "Mining & resources"}]
        subs = matching_engine.load_subcontractors()
        matches = matching_engine.find_direct_request_matches(reqs, subs)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["subcontractor_name"], "Rocky Mining Co")

    def test_find_all_matches_combines_both_sources(self):
        with open(self.tenders_path, "w") as f:
            json.dump([{"ocid": "t1", "province": "Gauteng", "industries": ["Electrical"]}], f)
        with open(self.requests_path, "w") as f:
            json.dump([{"request_id": "r1", "province": "Free State", "industry": "Mining & resources"}], f)

        matches = matching_engine.find_all_matches()
        self.assertEqual(len(matches), 2)
        types = {m["opportunity_type"] for m in matches}
        self.assertEqual(types, {"tender", "direct_request"})

    def test_missing_files_return_empty_not_crash(self):
        # tenders.json / requests.json don't exist yet - should return [], not raise
        self.assertEqual(matching_engine.load_matched_tenders(), [])
        self.assertEqual(matching_engine.load_direct_requests(), [])


if __name__ == "__main__":
    unittest.main()
