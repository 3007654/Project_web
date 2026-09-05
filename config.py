"""
Configuration for the eTenders pilot scraper.

Pilot scope, per the project brief: electrical / technical trades, Gauteng only.
Widen KEYWORDS and REGIONS in Phase 5 when expanding trade/region coverage.
"""

# National Treasury OCDS sources (data.etenders.gov.za / ocds-api.etenders.gov.za)
OCDS_API_BASE = "https://ocds-api.etenders.gov.za"
OCDS_RELEASES_PATH = "/api/OCDSReleases"          # NEEDS LIVE CONFIRMATION - see NOTE in scraper.py
BULK_RELEASES_INDEX_URL = "https://data.etenders.gov.za/Home/ReleasesFiles"  # monthly bulk JSON/CSV/XLSX archive

# Region filter. Empty list = no region restriction (match tenders from
# any province) - the pilot was widened from Gauteng-only to nationwide.
# To scope back down later, just add province names here, e.g. ["gauteng"].
REGIONS: list[str] = []

# Industry taxonomy for the classifier (see industry_classifier.py).
# Each industry maps to a list of search terms used for both structured
# category matching and fuzzy text matching - not a pass/fail gate, since
# every awarded tender is now kept regardless of industry. This exists so
# each matched tender is TAGGED with its industry/industries, letting the
# downstream matching engine route alerts to the right subcontractors
# (a mining subcontractor shouldn't get electrical-only alerts, etc).
#
# Add or edit industries/terms freely - no code changes needed elsewhere.
INDUSTRY_TAXONOMY = {
    "Electrical": [
        "electrical", "electrician", "wiring", "cabling", "reticulation",
        "power installation", "lighting installation", "generator",
        "transformer", "switchgear", "substation", "solar pv",
    ],
    "Construction & civil": [
        "construction", "civil works", "building", "renovation",
        "roads", "bridge", "paving", "earthworks", "concrete",
        "structural", "roofing", "fencing",
    ],
    "Mining & resources": [
        "mining", "mineral", "quarry", "excavation", "drilling",
        "ore", "coal", "shaft", "mine rehabilitation",
    ],
    "Mechanical & HVAC": [
        "mechanical", "hvac", "ventilation", "air conditioning",
        "boiler", "pump", "pipework", "refrigeration",
    ],
    "ICT & telecommunications": [
        "ict", "information technology", "software", "network",
        "telecommunications", "server", "data centre", "cctv installation",
        "fibre", "cabling infrastructure",
    ],
    "Security services": [
        "security services", "guarding", "access control",
        "surveillance", "alarm systems",
    ],
    "Professional & consulting services": [
        "consulting", "professional services", "engineering design",
        "project management", "advisory", "feasibility study",
        "land surveying",
    ],
    "Health & medical": [
        "medical", "healthcare", "hospital", "clinic", "pharmaceutical",
        "ambulance", "health services",
    ],
    "Transport & logistics": [
        "transport", "logistics", "fleet", "freight", "haulage",
        "vehicle supply",
    ],
    "Agriculture": [
        "agriculture", "farming", "irrigation", "livestock", "agri-processing",
    ],
    "Cleaning & facilities": [
        "cleaning services", "facilities management", "waste removal",
        "landscaping", "hygiene services",
    ],
    "Water & sanitation": [
        "water reticulation", "sanitation", "sewer", "wastewater",
        "borehole", "water treatment",
    ],
    "Energy & renewables": [
        "renewable energy", "solar farm", "wind energy", "energy efficiency",
    ],
    "Supply of goods": [
        "supply and delivery", "procurement of goods", "equipment supply",
        "stationery", "furniture supply",
    ],
}

# How similar free text needs to be to a search term to count as a fuzzy
# match (0.0-1.0). Tested against real near-misses: 0.6 was too loose (it
# let "general works" match "generator" at 0.75 similarity - a false
# positive). 0.85 still catches genuine variants ("electrician" vs
# "electrical" family, plurals, minor typos) while rejecting unrelated
# words that just happen to share letters.
FUZZY_MATCH_THRESHOLD = 0.85

# Minimum score (see industry_classifier.score_industry_match) for an
# industry to be attached as a tag to a release. A structured-category hit
# alone (score 1.0) or a strong fuzzy text match both clear this on their
# own.
MIN_INDUSTRY_MATCH_SCORE = 0.85

# Label used when a release doesn't score against any industry in the
# taxonomy above (still kept in output, just untagged/needs a human look).
UNCATEGORISED_LABEL = "Other / uncategorised"

# How far back to look on each scraper run (days). Set to 90 (~3 months)
# to catch standing offers/framework agreements that are still valid, not
# just tenders awarded in the last few days - see is_standing_and_valid()
# in scraper.py. Fetching is chunked by day and run concurrently (see
# MAX_CONCURRENT_REQUESTS below), so a larger window costs more total
# requests but not more wall-clock time per request.
LOOKBACK_DAYS = 90

# Terms that indicate a "standing offer" / framework-type contract rather
# than a once-off award. These contracts stay valid (callable) for months
# after being set up, so they need a different "is this still useful"
# check than a plain award date - see is_standing_and_valid().
STANDING_OFFER_TERMS = [
    "standing offer", "framework agreement", "panel of service providers",
    "panel of suppliers", "period contract", "term contract",
    "call-off contract", "transversal contract", "supplier database",
]

# Where matched, filtered opportunities get written for the next stage
# (the matching/vetting engine and the WhatsApp/Telegram push in Phase 3).
OUTPUT_JSON = "matched_tenders.json"
OUTPUT_CSV = "matched_tenders.csv"

REQUEST_TIMEOUT_SECONDS = 60

# How many days to fetch in parallel. Higher = faster, but too high risks
# tripping rate limits on a public government API. 6 is a reasonable
# balance; drop it if you start seeing repeated timeouts.
MAX_CONCURRENT_REQUESTS = 6
REQUEST_HEADERS = {
    "User-Agent": "SubcontractorMatchingPilot/0.1 (Gauteng electrical pilot; contact via project owner)",
    "Accept": "application/json",
}