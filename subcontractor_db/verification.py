"""
Verification scoring and status - Phase 2 rebuild.

Two separate things are computed here, deliberately kept apart:

  1. verification_score / verification_tier (Gold/Silver/Bronze/Unverified)
     - a rough, sortable summary of what's on file. Useful for browsing,
     not a claim of trustworthiness.

  2. profile_status (pending/verified/not_verified/needs_review) - the
     actual workflow state: has an authorised verifier looked at this
     subcontractor at all, and if so, what did they find?

This score is a summary of what's on file (checks, years active,
references) - useful for sorting and for a quick-glance badge. It is not,
and must not be presented as, a claim that a company is trustworthy or
incapable of fraud. Every profile page shows the underlying checks (source,
date, who checked) alongside the score so the score is never the only thing
a viewer sees.
"""

VALID_OUTCOMES = ("verified", "not_verified", "needs_review")


def compute_verification(cipc_outcome: str | None, cidb_outcome: str | None, cidb_grade,
                          years_active: int, reference_count: int) -> tuple[int, str]:
    """Only a 'verified' outcome contributes points - 'not_verified' and
    'needs_review' both count as zero for scoring purposes, though they're
    very different things (see compute_profile_status, which distinguishes
    them for the actual workflow status)."""
    score = 0

    if cipc_outcome == "verified":
        score += 25

    if cidb_outcome == "verified":
        score += 25
        score += min(cidb_grade or 0, 9) * 2  # up to +18

    score += min(years_active or 0, 7) * 3   # up to +21, caps at 7+ years
    score += min(reference_count or 0, 3) * 7  # up to +21, caps at 3+ references

    score = min(score, 100)

    if cipc_outcome != "verified" and cidb_outcome != "verified":
        tier = "Unverified"
    elif score >= 75:
        tier = "Gold"
    elif score >= 40:
        tier = "Silver"
    else:
        tier = "Bronze"

    return score, tier


def compute_profile_status(cipc_outcome: str | None, cidb_outcome: str | None) -> str:
    """
    - No checks recorded at all yet -> 'pending'
    - Either latest check is 'needs_review' -> 'needs_review' (this takes
      priority - an ambiguous result should surface, not get buried under
      a positive result from the other check type)
    - At least one check exists and none are verified -> 'not_verified'
    - At least one check is 'verified', none need review -> 'verified'
    """
    outcomes = [o for o in (cipc_outcome, cidb_outcome) if o is not None]

    if not outcomes:
        return "pending"
    if "needs_review" in outcomes:
        return "needs_review"
    if "verified" in outcomes:
        return "verified"
    return "not_verified"