"""
Configuration for the Subcontractor Verification app (Phase 2, rebuilt).
"""

import os

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
# so a subcontractor's trade lines up with how opportunities are tagged
# (useful later when the matching engine joins tenders, awards, and profiles).
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

# CIDB contractor grading: 1 (lowest capacity) to 9 (highest).
CIDB_GRADES = list(range(1, 10))

# Check types a verification_records row can carry. CIPC and CIDB are the two
# the brief calls out; this list is deliberately open-ended so a future check
# (e.g. B-BBEE status, tax clearance) is just a new value here, not a schema
# change.
CHECK_TYPES = ["CIPC", "CIDB"]

SOURCES_BY_CHECK_TYPE = {
    "CIPC": ["CIPC eServices portal (eservices.cipc.co.za)"],
    "CIDB": ["CIDB Register of Contractors (portal.cidb.org.za)"],
}

DB_PATH = "subcontractors.db"

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

# What "Verified" is allowed to mean everywhere in this app: a specific check
# against a specific source on a specific date, recorded with who did it -
# never a claim that the company is legitimate or incapable of fraud.
VERIFICATION_DISCLAIMER = (
    "\u201cVerified\u201d here means: checked against the named source, on the date "
    "shown, by the person named. It is a record of what was checked - not a "
    "guarantee that the company is legitimate or cannot commit fraud."
)