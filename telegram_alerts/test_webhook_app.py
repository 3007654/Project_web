import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import config
import webhook_app
import alert_dispatch
import links


class WebhookTests(unittest.TestCase):
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
            json.dump([], f)
        with open(self.requests_path, "w") as f:
            json.dump([{
                "request_id": "r1", "province": "Gauteng", "industry": "Electrical",
                "description": "Need rewiring", "needed_by": "2026-12-01",
                "company_name": "ABC Construction", "contact_person": "Jane Doe",
                "contact_phone": "0821234567", "contact_email": "jane@abc.co.za",
            }], f)

        webhook_app.app.config["TESTING"] = True
        self.client = webhook_app.app.test_client()

    def tearDown(self):
        config.SUBCONTRACTORS_DB_PATH = self._orig["db"]
        config.MATCHED_TENDERS_JSON = self._orig["tenders"]
        config.DIRECT_REQUESTS_JSON = self._orig["requests"]
        config.TELEGRAM_LINKS_FILE = self._orig["links"]
        config.SENT_ALERTS_FILE = self._orig["sent"]

    @patch("webhook_app.telegram_bot.send_message")
    def test_start_command_links_subcontractor(self, mock_send):
        resp = self.client.post("/telegram/webhook", json={
            "message": {"text": "/start 1", "chat": {"id": 555}}
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(links.get_chat_id("1"), 555)
        mock_send.assert_called_once()
        self.assertIn("linked", mock_send.call_args.args[1].lower())

    @patch("webhook_app.telegram_bot.send_message")
    def test_start_without_id_asks_for_it(self, mock_send):
        resp = self.client.post("/telegram/webhook", json={
            "message": {"text": "/start", "chat": {"id": 555}}
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(links.get_chat_id("1"))
        self.assertIn("subcontractor ID", mock_send.call_args.args[1])

    @patch("webhook_app.telegram_bot.answer_callback_query")
    @patch("webhook_app.telegram_bot.send_message")
    def test_full_accept_flow_releases_contact_only_after_tap(self, mock_send, mock_answer):
        links.link_subcontractor("1", 555)
        alert_dispatch.dispatch_new_alerts()  # sends the initial (gated) alert

        # Check the FIRST message sent (the alert) does NOT contain contact info
        first_alert_text = mock_send.call_args.args[1]
        self.assertNotIn("0821234567", first_alert_text)
        self.assertNotIn("jane@abc.co.za", first_alert_text)

        sent = alert_dispatch.load_sent_alerts()
        match_id = list(sent.values())[0]["match_id"]
        self.assertEqual(list(sent.values())[0]["status"], "alerted")

        # Now simulate the Accept button tap
        resp = self.client.post("/telegram/webhook", json={
            "callback_query": {
                "id": "cq-1", "data": match_id,
                "message": {"chat": {"id": 555}},
            }
        })
        self.assertEqual(resp.status_code, 200)

        # NOW the contact details should have gone out, in a SEPARATE message
        self.assertEqual(mock_send.call_count, 2)
        second_message_text = mock_send.call_args.args[1]
        self.assertIn("0821234567", second_message_text)
        self.assertIn("jane@abc.co.za", second_message_text)

        sent_after = alert_dispatch.load_sent_alerts()
        self.assertEqual(list(sent_after.values())[0]["status"], "contact_released")

    @patch("webhook_app.telegram_bot.answer_callback_query")
    @patch("webhook_app.telegram_bot.send_message")
    def test_double_accept_does_not_resend_contact(self, mock_send, mock_answer):
        links.link_subcontractor("1", 555)
        alert_dispatch.dispatch_new_alerts()
        sent = alert_dispatch.load_sent_alerts()
        match_id = list(sent.values())[0]["match_id"]

        payload = {"callback_query": {"id": "cq-1", "data": match_id, "message": {"chat": {"id": 555}}}}
        self.client.post("/telegram/webhook", json=payload)
        call_count_after_first_accept = mock_send.call_count

        # Tap Accept again
        self.client.post("/telegram/webhook", json=payload)
        self.assertEqual(mock_send.call_count, call_count_after_first_accept)  # no new message sent
        mock_answer.assert_called_with("cq-1", "You've already responded to this one.")


if __name__ == "__main__":
    unittest.main()
