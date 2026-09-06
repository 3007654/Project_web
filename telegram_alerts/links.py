"""
Links a subcontractor profile to a Telegram chat ID, so alerts know where
to send. A subcontractor links themselves by messaging the bot:
/start <their subcontractor ID> - see webhook_app.py for the handler.
"""

import json
import os

import config


def load_links() -> dict:
    if not os.path.exists(config.TELEGRAM_LINKS_FILE):
        return {}
    with open(config.TELEGRAM_LINKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_links(links: dict) -> None:
    with open(config.TELEGRAM_LINKS_FILE, "w", encoding="utf-8") as f:
        json.dump(links, f, indent=2)


def link_subcontractor(subcontractor_id: str, chat_id: str) -> None:
    links = load_links()
    links[str(subcontractor_id)] = chat_id
    save_links(links)


def get_chat_id(subcontractor_id: str) -> str | None:
    return load_links().get(str(subcontractor_id))
