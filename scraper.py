"""
eTenders scraper - Phase 1 of the Subcontractor Matching Platform pilot.

Pulls newly AWARDED tenders from National Treasury's OCDS data, filters
them to electrical/technical trades in Gauteng, and writes the matches
to JSON/CSV for the next stage (subcontractor matching + WhatsApp/Telegram push).

-----------------------------------------------------------------------------
NOTE ON THE LIVE API (read this before running against production):

National Treasury publishes this data two ways:

  1. Release API (ocds-api.etenders.gov.za) - a paginated, filterable JSON
     API. This is the right long-term source (near real-time), but its
     exact query-string contract (parameter names for date filtering and
     pagination, e.g. `dateFrom`/`dateTo` vs `PublishedFrom`/`PublishedTo`,
     and whether pagination is offset-, page-, or cursor-based) could not
     be confirmed from documentation alone - the Swagger UI at
     https://ocds-api.etenders.gov.za/swagger/index.html renders via
     JavaScript, so its schema isn't visible to a plain fetch, and the
     domain is not reachable from this build environment to test directly.

  2. Bulk monthly release files (data.etenders.gov.za/Home/ReleasesFiles) -
     JSON/CSV/XLSX archives, segmented by month, no auth or pagination
     needed. Slower to reflect new awards (updated periodically, not live)
     but zero guesswork.

This script tries the Release API first and falls back to the current
month's bulk JSON file if the API call fails or its shape doesn't match
what's expected. Before relying on this for the pilot:

  1. Run `python3 scraper.py --probe` once you have network access to
     ocds-api.etenders.gov.za. It prints the raw response from a first
     request so we can fix `fetch_from_release_api()` in five minutes if
     the parameter names differ from the OCDS-standard guess below.
  2. Everything downstream (filtering, output) is independent of which
     fetch path is used, since both are normalised to OCDS release dicts
     in `normalise_releases()`.
-----------------------------------------------------------------------------
"""

import csv
import json
import sys
from datetime import date, timedelta

import requests

import config


def fetch_from_release_api(date_from: str, date_to: str) -> list[dict]:
    """
    Try the near-real-time Release API. Returns a list of raw OCDS release
    dicts, or raises requests.RequestException / ValueError on failure so
    the caller can fall back to the bulk archive.
    """
    releases: list[dict] = []
    page = 1
    while True:
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "PageNumber": page,
            "PageSize": 100,
        }
        resp = requests.get(
            f"{config.OCDS_API_BASE}{config.OCDS_RELEASES_PATH}",
            params=params,
            headers=config.REQUEST_HEADERS,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()

        # OCDS release packages nest releases under "releases"; be defensive
        # since we haven't confirmed the exact response envelope.
        page_releases = payload.get("releases") if isinstance(payload, dict) else None
        if page_releases is None:
            raise ValueError(
                "Unexpected response shape from Release API - "
                "run with --probe and check the printed payload."
            )

        releases.extend(page_releases)

        has_next = bool(payload.get("links", {}).get("next"))
        if not has_next or not page_releases:
            break
        page += 1

    return releases


def fetch_from_bulk_archive(target_month: str) -> list[dict]:
    """
    Fallback: pull the bulk monthly JSON release package.
    target_month format: 'YYYY-MM'.

    The exact per-month file naming on data.etenders.gov.za should be
    confirmed against the index page (BULK_RELEASES_INDEX_URL) the first
    time this runs, since National Treasury's file-naming convention
    wasn't independently verifiable from this environment either.
    """
    index_resp = requests.get(
        config.BULK_RELEASES_INDEX_URL,
        headers=config.REQUEST_HEADERS,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    index_resp.raise_for_status()

    raise NotImplementedError(
        "Bulk archive parsing needs the real file-link pattern from "
        f"{config.BULK_RELEASES_INDEX_URL}. Inspect index_resp.text (saved "
        "to fetch_index_debug.html when run with --probe) and wire in the "
        "monthly file URL for target_month."
    )


def is_gauteng(release: dict) -> bool:
    buyer = release.get("buyer", {}) or {}
    tender = release.get("tender", {}) or {}
    haystacks = [
        json.dumps(buyer).lower(),
        json.dumps(tender.get("items", [])).lower(),
        json.dumps(tender.get("deliveryAddresses", [])).lower(),
    ]
    return any(region in text for region in config.REGIONS for text in haystacks)


def matches_trade_keywords(release: dict) -> bool:
    tender = release.get("tender", {}) or {}
    text = " ".join(
        filter(
            None,
            [
                tender.get("title", ""),
                tender.get("description", ""),
                " ".join(item.get("description", "") for item in tender.get("items", []) or []),
            ],
        )
    ).lower()
    return any(keyword in text for keyword in config.KEYWORDS)


def extract_summary(release: dict) -> dict:
    """Flatten the fields the matching engine and WhatsApp/Telegram alerts need."""
    tender = release.get("tender", {}) or {}
    buyer = release.get("buyer", {}) or {}
    awards = release.get("awards", []) or []
    first_award = awards[0] if awards else {}

    return {
        "ocid": release.get("ocid"),
        "title": tender.get("title"),
        "buyer": buyer.get("name"),
        "status": tender.get("status"),
        "value_amount": (tender.get("value") or {}).get("amount"),
        "value_currency": (tender.get("value") or {}).get("currency"),
        "tender_period_end": (tender.get("tenderPeriod") or {}).get("endDate"),
        "award_date": first_award.get("date"),
        "award_value": (first_award.get("value") or {}).get("amount"),
        "source_release_date": release.get("date"),
    }


def normalise_releases(raw_releases: list[dict]) -> list[dict]:
    matched = [
        r for r in raw_releases
        if r.get("tender", {}).get("status") == "complete"  # i.e. awarded
        and is_gauteng(r)
        and matches_trade_keywords(r)
    ]
    return [extract_summary(r) for r in matched]


def write_outputs(rows: list[dict]) -> None:
    with open(config.OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    if rows:
        with open(config.OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    print(f"Wrote {len(rows)} matched tender(s) to {config.OUTPUT_JSON} / {config.OUTPUT_CSV}")


def run(probe: bool = False) -> None:
    today = date.today()
    date_from = (today - timedelta(days=config.LOOKBACK_DAYS)).isoformat()
    date_to = today.isoformat()

    if probe:
        print(f"Probing Release API: {config.OCDS_API_BASE}{config.OCDS_RELEASES_PATH}")
        try:
            resp = requests.get(
                f"{config.OCDS_API_BASE}{config.OCDS_RELEASES_PATH}",
                params={"dateFrom": date_from, "dateTo": date_to, "PageNumber": 1, "PageSize": 5},
                headers=config.REQUEST_HEADERS,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            print("Status:", resp.status_code)
            print("Body (first 2000 chars):", resp.text[:2000])
        except requests.RequestException as exc:
            print("Request failed:", exc)
        return

    try:
        raw = fetch_from_release_api(date_from, date_to)
        print(f"Fetched {len(raw)} raw release(s) from the Release API.")
    except (requests.RequestException, ValueError) as exc:
        print(f"Release API failed ({exc}); falling back to bulk archive.", file=sys.stderr)
        raw = fetch_from_bulk_archive(today.strftime("%Y-%m"))

    matched = normalise_releases(raw)
    write_outputs(matched)


if __name__ == "__main__":
    run(probe="--probe" in sys.argv)
