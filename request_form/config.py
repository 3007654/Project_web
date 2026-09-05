"""
Config for the direct-request form.

Industries here are kept in sync with etenders_scraper/config.py's
INDUSTRY_TAXONOMY keys - if you add an industry to one, add it to the
other too. They're separate files for now since this is a different
mini-app; Phase 2/5 can merge them into one shared config once the
subcontractor database ties everything together.
"""

PROVINCES = [
    "Gauteng", "Western Cape", "KwaZulu-Natal", "Eastern Cape",
    "Free State", "Limpopo", "Mpumalanga", "North West", "Northern Cape",
]

INDUSTRIES = [
    "Electrical",
    "Construction & civil",
    "Mining & resources",
    "Mechanical & HVAC",
    "ICT & telecommunications",
    "Security services",
    "Professional & consulting services",
    "Health & medical",
    "Transport & logistics",
    "Agriculture",
    "Cleaning & facilities",
    "Water & sanitation",
    "Energy & renewables",
    "Supply of goods",
    "Other",
]

OUTPUT_JSON = "direct_requests.json"
OUTPUT_CSV = "direct_requests.csv"
