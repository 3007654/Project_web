"""
Verification score.

This score is a summary of what's on file (CIPC/CIDB checks, years active,
references) - useful for sorting and for a quick-glance badge. It is not,
and must not be presented as, a claim that a company is trustworthy or
incapable of fraud. Every profile page shows the underlying checks (source,
date, who checked) alongside the score so the score is never the only thing
a viewer sees.
"""


def compute_verification(cipc_verified: bool, cidb_verified: bool, cidb_grade,
                          years_active: int, reference_count: int) -> tuple[int, str]:
    score = 0

    if cipc_verified:
        score += 25

    if cidb_verified:
        score += 25
        score += min(cidb_grade or 0, 9) * 2  # up to +18

    score += min(years_active or 0, 7) * 3   # up to +21, caps at 7+ years
    score += min(reference_count or 0, 3) * 7  # up to +21, caps at 3+ references

    score = min(score, 100)

    # No CIPC or CIDB check on file at all -> stays Unverified regardless of
    # years/references. A re-check that comes back negative also keeps a
    # company out of Bronze+ even if it was verified before (see app.py:
    # the score always uses the *latest* record per check type).
    if not cipc_verified and not cidb_verified:
        tier = "Unverified"
    elif score >= 75:
        tier = "Gold"
    elif score >= 40:
        tier = "Silver"
    else:
        tier = "Bronze"

    return score, tier
