import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import config
import alert_dispatch
import links


class AlertDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "subs.db")
        self.tenders_path = os.path.join(self.tmpdir, "tenders.json")
        self.requests_path = os.path.join(self.tmpdir, "requests.json")
        self.links_path = os.path.join(self.tmpdir, "links.json")
        self.sent_path = os.path.join(self.tmpdir, "sent.json")

        self._orig = {
            "db": config.SUBCONTRACTORS_DB_PATH, "tenders": config.MATCHED_TENDERS_JSON,
            "requests": config.DIRECT_REQUESTS_JSON, "links": config.TELEGRAM_LINKS_FILE,
            "sent": config.SENT_ALERTS_FILE,
        }
        config.SUBCONTRACTORS_DB_PATH = self.db_path
        config.MATCHED_TENDERS_JSON = self.tenders_path
        config.DIRECT_REQUESTS_JSON = self.requests_path
        config.TELEGRAM_LINKS_FILE = self.links_path
        config.SENT_ALERTS_FILE = self.sent_path

        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE subcontractor_profiles (id INTEGER PRIMARY KEY, company_name TEXT, trade TEXT, province TEXT)")
        conn.execute("INSERT INTO subcontractor_profiles VALUES (1, 'Sparks Electrical', 'Electrical', 'Gauteng')")
        conn.commit()
        conn.close()

        with open(self.tenders_path, "w") as f:
            json.dump([{"ocid": "t1", "province": "Gauteng", "industries": ["Electrical"], "title": "Rewiring job", "buyer": "City of Joburg"}], f)
        with open(self.requests_path, "w") as f:
            json.dump([], f)

    def tearDown(self):
        config.SUBCONTRACTORS_DB_PATH = self._orig["db"]
        config.MATCHED_TENDERS_JSON = self._orig["tenders"]
        config.DIRECT_REQUESTS_JSON = self._orig["requests"]
        config.TELEGRAM_LINKS_FILE = self._orig["links"]
        config.SENT_ALERTS_FILE = self._orig["sent"]

    @patch("alert_dispatch.telegram_bot.send_message")
    def test_no_alert_sent_without_telegram_link(self, mock_send):
        result = alert_dispatch.dispatch_new_alerts()
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["no_telegram_link"], 1)
        mock_send.assert_not_called()

    @patch("alert_dispatch.telegram_bot.send_message")
    def test_alert_sent_once_linked(self, mock_send):
        links.link_subcontractor("1", "chat-999")
        result = alert_dispatch.dispatch_new_alerts()
        self.assertEqual(result["sent"], 1)
        mock_send.assert_called_once()
        chat_id_arg = mock_send.call_args.args[0]
        self.assertEqual(chat_id_arg, "chat-999")

    @patch("alert_dispatch.telegram_bot.send_message")
    def test_alert_never_sent_twice_for_same_match(self, mock_send):
        links.link_subcontractor("1", "chat-999")
        alert_dispatch.dispatch_new_alerts()
        result2 = alert_dispatch.dispatch_new_alerts()  # run again, nothing new
        self.assertEqual(result2["sent"], 0)
        self.assertEqual(result2["already_sent"], 1)
        self.assertEqual(mock_send.call_count, 1)  # still just once total

    def test_alert_text_never_contains_private_contact_for_direct_request(self):
        match = {
            "opportunity_type": "direct_request",
            "opportunity_summary": {
                "industry": "Electrical", "province": "Gauteng",
                "description": "Need rewiring", "needed_by": "2026-12-01",
                "contact_phone": "0821234567", "contact_email": "secret@example.com",
                "company_name": "ABC Construction",
            },
        }
        text = alert_dispatch.format_alert_text(match)
        self.assertNotIn("0821234567", text)
        self.assertNotIn("secret@example.com", text)
        self.assertNotIn("ABC Construction", text)


if __name__ == "__main__":
    unittest.main()
