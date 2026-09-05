"""
Industry classification for the eTenders scraper.

The pilot originally filtered to one trade (electrical) in one province.
Scope has since widened to every industry, nationwide - so this module no
longer decides IN/OUT. Every awarded tender passes through; this module's
job is to TAG each one with which industry/industries it belongs to, so
the downstream matching engine can route alerts to the right
subcontractors (a mining subcontractor shouldn't get plumbing alerts,
even though both now pass the region/award filters).

Two signals feed the score, same approach as before, generalised across
config.INDUSTRY_TAXONOMY instead of one hardcoded list:

  1. National Treasury's own structured category fields (tender.category,
     tender.mainProcurementCategory, tender.additionalProcurementCategories)
     - real classification data, not a guess.
  2. Fuzzy text similarity against title/description (difflib, stdlib -
     no extra dependency), so "electrician" still matches "electrical",
     plurals and minor typos don't cause a miss, etc.

FUZZY_MATCH_THRESHOLD is deliberately strict (0.85) - testing found looser
thresholds produced false positives (e.g. "general works" matching
"generator" at 0.75 similarity).
"""

from __future__ import annotations

import difflib

import config


def _fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _best_fuzzy_score(term: str, text: str) -> float:
    """
    Slide `term` over `text` word-by-word (as an n-gram window matching the
    term's word count) and return the best similarity ratio found.
    """
    words = text.split()
    term_word_count = max(1, len(term.split()))
    if not words:
        return 0.0

    best = 0.0
    for i in range(len(words) - term_word_count + 1):
        window = " ".join(words[i : i + term_word_count])
        best = max(best, _fuzzy_ratio(term, window))
    return best


def _score_against_terms(release: dict, terms: list[str]) -> tuple[float, list[str]]:
    tender = release.get("tender", {}) or {}
    reasons: list[str] = []
    score = 0.0

    category_fields = " ".join(
        filter(
            None,
            [
                tender.get("category", ""),
                tender.get("mainProcurementCategory", ""),
                " ".join(tender.get("additionalProcurementCategories", []) or []),
            ],
        )
    ).lower()

    for term in terms:
        term_lower = term.lower()
        if category_fields and term_lower in category_fields:
            score += 1.0
            reasons.append(f"category field contains '{term}'")
            break  # one structured hit per industry is enough signal

    free_text = " ".join(
        filter(None, [tender.get("title", ""), tender.get("description", "")])
    ).lower()

    if free_text:
        best_term = None
        best_score = 0.0
        for term in terms:
            s = _best_fuzzy_score(term.lower(), free_text)
            if s > best_score:
                best_score = s
                best_term = term

        if best_score >= config.FUZZY_MATCH_THRESHOLD:
            score += best_score
            reasons.append(f"text fuzzy-matches '{best_term}' (similarity {best_score:.2f})")

    return score, reasons


def classify_industries(release: dict) -> list[dict]:
    """
    Returns a list of {"industry": name, "score": float, "reasons": [...]},
    sorted by score descending, for every industry in the taxonomy that
    scores >= config.MIN_INDUSTRY_MATCH_SCORE.

    If nothing scores high enough, returns a single entry tagged with
    config.UNCATEGORISED_LABEL so the tender is still visible in output
    rather than silently dropped.
    """
    matches = []
    for industry, terms in config.INDUSTRY_TAXONOMY.items():
        score, reasons = _score_against_terms(release, terms)
        if score >= config.MIN_INDUSTRY_MATCH_SCORE:
            matches.append({"industry": industry, "score": round(score, 2), "reasons": reasons})

    if not matches:
        return [{"industry": config.UNCATEGORISED_LABEL, "score": 0.0, "reasons": []}]

    return sorted(matches, key=lambda m: m["score"], reverse=True)
