"""
Configuration for the eTenders pilot scraper.

Pilot scope, per the project brief: electrical / technical trades, Gauteng only.
Widen KEYWORDS and REGIONS in Phase 5 when expanding trade/region coverage.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# National Treasury OCDS sources (data.etenders.gov.za / ocds-api.etenders.gov.za)
OCDS_API_BASE = "https://ocds-api.etenders.gov.za"
OCDS_RELEASES_PATH = "/api/OCDSReleases"          # NEEDS LIVE CONFIRMATION - see NOTE in scraper.py
BULK_RELEASES_INDEX_URL = "https://data.etenders.gov.za/Home/ReleasesFiles"  # monthly bulk JSON/CSV/XLSX archive

# Pilot filters
REGIONS = ["gauteng"]

KEYWORDS = [
    "electrical", "electrician", "wiring", "wire", "cabling",
    "reticulation", "power installation", "lighting installation",
    "generator", "transformer", "switchgear", "substation",
    "instrumentation", "control systems", "technical installation",
    "hvac", "fire detection", "cctv installation", "solar pv",
]

# How far back to look on each scraper run (days). Kept short since this
# runs on a schedule (e.g. daily) rather than as a one-off historical pull.
LOOKBACK_DAYS = 3

# Where matched, filtered opportunities get written for the next stage
# (the matching/vetting engine and the WhatsApp/Telegram push in Phase 3).
OUTPUT_JSON = "matched_tenders.json"
OUTPUT_CSV = "matched_tenders.csv"

REQUEST_TIMEOUT_SECONDS = 30
REQUEST_HEADERS = {
    "User-Agent": "SubcontractorMatchingPilot/0.1 (Gauteng electrical pilot; contact via project owner)",
    "Accept": "application/json",
}

# Shared alert inputs and local state.
SUBCONTRACTORS_DB_PATH = str(PROJECT_ROOT / "subcontractor_db" / "subcontractors.db")
MATCHED_TENDERS_JSON = str(PROJECT_ROOT / "matched_tenders.json")
DIRECT_REQUESTS_JSON = str(PROJECT_ROOT / "request_form" / "direct_requests.json")
TELEGRAM_LINKS_FILE = str(Path(__file__).resolve().parent / "telegram_links.json")
SENT_ALERTS_FILE = str(Path(__file__).resolve().parent / "sent_alerts.json")

# The token is intentionally read from the environment and never committed.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_BASE = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if TELEGRAM_BOT_TOKEN
    else "https://api.telegram.org/bot"
)
