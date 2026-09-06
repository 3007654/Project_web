"""
Configuration for the Subcontractor Verification app.
"""

PROVINCES = [
    "Gauteng",
    "Western Cape",
    "KwaZulu-Natal",
    "Eastern Cape",
    "Free State",
    "Limpopo",
    "Mpumalanga",
    "North West",
    "Northern Cape",
]

# Same trade/industry categories the Phase 1 scraper classifies tenders into,
# so a subcontractor's trade lines up with how opportunities are tagged.
TRADES = [
    "Electrical",
    "Mechanical & HVAC",
    "Construction & civil",
    "ICT & telecommunications",
    "Water & sanitation",
    "Security services",
    "Transport & logistics",
    "Health & medical",
    "Mining & resources",
    "Cleaning & facilities",
    "Agriculture",
    "Energy & renewables",
    "Professional & consulting services",
    "Supply of goods",
    "Other / uncategorised",
]

CIDB_GRADES = list(range(1, 10))

# Check types a verification_records row can carry. Open-ended on purpose -
# a future check (B-BBEE, tax clearance) is a new value here plus a new
# entry in SOURCES_BY_CHECK_TYPE, not a schema change.
CHECK_TYPES = ["CIPC", "CIDB"]

# The specific source a verifier must select for each check type - keeps
# "Verified" tied to a named, checkable source rather than a vague claim.
SOURCES_BY_CHECK_TYPE = {
    "CIPC": ["CIPC eServices portal (eservices.cipc.co.za)"],
    "CIDB": ["CIDB Register of Contractors (portal.cidb.org.za)"],
}

# (value, label) pairs for the availability field.
AVAILABILITY_STATUSES = [
    ("available", "Available now"),
    ("engaged", "Currently engaged"),
    ("available_from", "Available from a future date"),
]

MAX_SKILLS = 15
MAX_EQUIPMENT = 15
MAX_REFERENCES = 3

# How recent a check needs to be to count as "fresh" vs "aging" vs "stale",
# shown on the profile so a viewer isn't relying on a check from years ago
# without realising it.
FRESHNESS_FRESH_DAYS = 30
FRESHNESS_AGING_DAYS = 90

DB_PATH = "subcontractors.db"

# Only used to sign the session cookie for verifier logins - not protecting
# anything more sensitive than "who's logged in" at pilot scale. Change this
# to a real random value before this ever leaves your own machine.
SECRET_KEY = "dev-only-change-before-any-real-deployment"

# What "Verified" is allowed to mean everywhere in this app: a specific check
# against a specific source on a specific date, by a specific logged-in
# verifier - never a claim that the company is legitimate or incapable of
# fraud.
VERIFICATION_DISCLAIMER = (
    "\u201cVerified\u201d here means: an authorised verifier checked this against "
    "the named source, on the date shown, and logged what they found. It is a "
    "record of what was checked - not a guarantee that the company is "
    "legitimate or cannot commit fraud."
)