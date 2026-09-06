import unittest
from unittest.mock import patch, MagicMock

import telegram_bot


class TelegramBotTests(unittest.TestCase):
    @patch("telegram_bot.requests.post")
    def test_send_message_without_button(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        result = telegram_bot.send_message("12345", "hello")

        self.assertEqual(result, {"ok": True})
        called_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(called_json["chat_id"], "12345")
        self.assertEqual(called_json["text"], "hello")
        self.assertNotIn("reply_markup", called_json)

    @patch("telegram_bot.requests.post")
    def test_send_message_with_accept_button(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        telegram_bot.send_message("12345", "hello", accept_callback_data="match-abc-123")

        called_json = mock_post.call_args.kwargs["json"]
        button = called_json["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(button["callback_data"], "match-abc-123")
        self.assertEqual(button["text"], "Accept this match")

    @patch("telegram_bot.requests.post")
    def test_send_message_raises_on_http_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("boom")
        mock_post.return_value = mock_resp

        with self.assertRaises(Exception):
            telegram_bot.send_message("12345", "hello")

    @patch("telegram_bot.requests.post")
    def test_answer_callback_query(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        telegram_bot.answer_callback_query("cq-1", "Accepted!")

        called_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(called_json["callback_query_id"], "cq-1")
        self.assertEqual(called_json["text"], "Accepted!")


if __name__ == "__main__":
    unittest.main()
