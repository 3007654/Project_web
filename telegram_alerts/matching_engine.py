"""
Matching engine - connects the two demand feeds from earlier phases
(scraped tender awards, direct contractor requests) to subcontractor
profiles from Phase 2, by province + trade.

Pure logic, no network calls - fully unit-testable in isolation.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3

import config


def _stable_match_id(opportunity_type: str, opportunity_id, subcontractor_id) -> str:
    """Deterministic, not random - the same opportunity+subcontractor pair
    must produce the same match_id every time find_all_matches() is called,
    since the webhook re-derives matches fresh rather than persisting them
    (see webhook_app._find_match_by_id). A random UUID here would mean the
    Accept button's callback_data never matches on lookup."""
    raw = f"{opportunity_type}:{opportunity_id}:{subcontractor_id}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def load_subcontractors() -> list[dict]:
    if not os.path.exists(config.SUBCONTRACTORS_DB_PATH):
        return []
    conn = sqlite3.connect(config.SUBCONTRACTORS_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM subcontractor_profiles").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_matched_tenders() -> list[dict]:
    if not os.path.exists(config.MATCHED_TENDERS_JSON):
        return []
    with open(config.MATCHED_TENDERS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def load_direct_requests() -> list[dict]:
    if not os.path.exists(config.DIRECT_REQUESTS_JSON):
        return []
    with open(config.DIRECT_REQUESTS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _province_matches(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def _trade_matches_industries(trade: str, industries: list[str]) -> bool:
    trade_lower = (trade or "").strip().lower()
    return any(trade_lower == (i or "").strip().lower() for i in (industries or []))


def find_tender_matches(tenders: list[dict], subcontractors: list[dict]) -> list[dict]:
    """A tender can have multiple industry tags; match any subcontractor
    whose single trade appears among them, in the same province."""
    matches = []
    for tender in tenders:
        for sub in subcontractors:
            if _province_matches(tender.get("province"), sub.get("province")) and \
               _trade_matches_industries(sub.get("trade"), tender.get("industries")):
                matches.append({
                    "match_id": _stable_match_id("tender", tender.get("ocid"), sub.get("id")),
                    "opportunity_type": "tender",
                    "opportunity_id": tender.get("ocid"),
                    "opportunity_summary": tender,
                    "subcontractor_id": sub.get("id"),
                    "subcontractor_name": sub.get("company_name"),
                })
    return matches


def find_direct_request_matches(requests_: list[dict], subcontractors: list[dict]) -> list[dict]:
    """A direct request has exactly one industry (the contractor picked it
    from a dropdown), matched against the subcontractor's single trade."""
    matches = []
    for req in requests_:
        for sub in subcontractors:
            if _province_matches(req.get("province"), sub.get("province")) and \
               (req.get("industry") or "").strip().lower() == (sub.get("trade") or "").strip().lower():
                matches.append({
                    "match_id": _stable_match_id("direct_request", req.get("request_id"), sub.get("id")),
                    "opportunity_type": "direct_request",
                    "opportunity_id": req.get("request_id"),
                    "opportunity_summary": req,
                    "subcontractor_id": sub.get("id"),
                    "subcontractor_name": sub.get("company_name"),
                })
    return matches


def find_all_matches() -> list[dict]:
    subcontractors = load_subcontractors()
    tenders = load_matched_tenders()
    requests_ = load_direct_requests()
    return find_tender_matches(tenders, subcontractors) + find_direct_request_matches(requests_, subcontractors)
