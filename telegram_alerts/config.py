"""
Configuration for the eTenders pilot scraper.

Pilot scope, per the project brief: electrical / technical trades, Gauteng only.
Widen KEYWORDS and REGIONS in Phase 5 when expanding trade/region coverage.
"""

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
