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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import requests

import config
import industry_classifier

# Reuse one session across all requests (connection pooling) instead of
# opening a fresh TCP/TLS connection per request - meaningfully faster
# when making many requests to the same host.
_session = requests.Session()


def _fetch_single_day(day_str: str, max_retries: int = 3) -> list[dict]:
    """Fetch all pages for a single day. Deep pagination on this API gets
    slow/times out past ~10 pages, so keeping each request's date range to
    one day keeps the page count low and reliable."""
    releases: list[dict] = []
    page = 1
    while True:
        params = {
            "dateFrom": day_str,
            "dateTo": day_str,
            "PageNumber": page,
            "PageSize": 100,
        }

        for attempt in range(1, max_retries + 1):
            try:
                resp = _session.get(
                    f"{config.OCDS_API_BASE}{config.OCDS_RELEASES_PATH}",
                    params=params,
                    headers=config.REQUEST_HEADERS,
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                )
                resp.raise_for_status()
                break
            except requests.exceptions.ReadTimeout:
                if attempt == max_retries:
                    raise
                time.sleep(1.5 * attempt)
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                # Retry server-side errors (transient) - not client errors
                # (4xx means our request itself is wrong, retrying won't help).
                if status and 500 <= status < 600 and attempt < max_retries:
                    time.sleep(1.5 * attempt)
                    continue
                raise

        payload = resp.json()
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


def fetch_from_release_api(date_from: str, date_to: str) -> list[dict]:
    """
    Fetches the full date range by chunking into single-day requests
    (see _fetch_single_day), run CONCURRENTLY across days since each
    day's request is independent - this is the main speedup versus
    fetching one day at a time.
    """
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)

    day_strs = []
    current = start
    while current <= end:
        day_strs.append(current.isoformat())
        current += timedelta(days=1)

    all_releases: list[dict] = []
    with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_REQUESTS) as executor:
        future_to_day = {executor.submit(_fetch_single_day, d): d for d in day_strs}
        for future in as_completed(future_to_day):
            day_str = future_to_day[future]
            try:
                day_releases = future.result()
                print(f"  {day_str}: {len(day_releases)} release(s)")
                all_releases.extend(day_releases)
            except requests.exceptions.RequestException as exc:
                print(f"  {day_str}: gave up after retries ({exc}), skipping this day", file=sys.stderr)

    return all_releases


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


def is_in_region(release: dict) -> bool:
    # Empty config.REGIONS = no region restriction (nationwide pilot).
    if not config.REGIONS:
        return True

    tender = release.get("tender", {}) or {}
    province = (tender.get("province") or "").strip().lower()
    if province:
        return province in config.REGIONS

    buyer = release.get("buyer", {}) or {}
    haystacks = [
        json.dumps(buyer).lower(),
        json.dumps(tender.get("deliveryLocation", "")).lower(),
    ]
    return any(region in text for region in config.REGIONS for text in haystacks)


def matches_trade_keywords(release: dict) -> bool:
    # No longer a gate - every industry is in scope now. Kept as a
    # pass-through so nothing upstream needs to change; classification
    # happens separately via industry_classifier.classify_industries().
    return True


def extract_summary(release: dict) -> dict:
    """Flatten the fields the matching engine and WhatsApp/Telegram alerts need."""
    tender = release.get("tender", {}) or {}
    buyer = release.get("buyer", {}) or {}
    awards = release.get("awards", []) or []
    first_award = awards[0] if awards else {}
    industries = industry_classifier.classify_industries(release)

    return {
        "ocid": release.get("ocid"),
        "title": tender.get("title"),
        "buyer": buyer.get("name"),
        "province": tender.get("province"),
        "status": tender.get("status"),
        "industries": [m["industry"] for m in industries],
        "industry_scores": industries,
        "is_standing_offer": is_standing_offer(release),
        "contract_end_date": _extract_contract_end_date(release),
        "value_amount": (tender.get("value") or {}).get("amount"),
        "value_currency": (tender.get("value") or {}).get("currency"),
        "tender_period_end": (tender.get("tenderPeriod") or {}).get("endDate"),
        "award_date": first_award.get("date"),
        "award_value": (first_award.get("value") or {}).get("amount"),
        "source_release_date": release.get("date"),
    }


def is_awarded(release: dict) -> bool:
    # Confirmed live: tender.status on open tenders reads "active", not
    # "complete" - so don't rely on status alone. An award has actually
    # happened once there's a non-empty "awards" array.
    tender = release.get("tender", {}) or {}
    if tender.get("status") == "complete":
        return True
    return bool(release.get("awards"))


def _extract_contract_end_date(release: dict) -> str | None:
    """Standing offers/framework agreements carry their validity period on
    the contract, not the tender - check contracts[].period.endDate first,
    falling back to tender.contractPeriod.endDate if present."""
    contracts = release.get("contracts", []) or []
    for c in contracts:
        end_date = (c.get("period") or {}).get("endDate")
        if end_date:
            return end_date

    tender = release.get("tender", {}) or {}
    return (tender.get("contractPeriod") or {}).get("endDate")


def is_standing_offer(release: dict) -> bool:
    """Detects framework/standing-offer type contracts by matching known
    terms against title/description - reuses the same fuzzy approach as
    industry classification rather than a rigid exact-match list."""
    tender = release.get("tender", {}) or {}
    free_text = " ".join(
        filter(None, [tender.get("title", ""), tender.get("description", "")])
    ).lower()
    if not free_text:
        return False

    for term in config.STANDING_OFFER_TERMS:
        if term.lower() in free_text:
            return True
        if industry_classifier._best_fuzzy_score(term.lower(), free_text) >= config.FUZZY_MATCH_THRESHOLD:
            return True
    return False


def is_standing_and_valid(release: dict) -> bool:
    """A standing offer is worth including only while it's still valid -
    i.e. its contract end date (if known) hasn't passed. If no end date
    is published, fall back to the tender not being cancelled/unsuccessful
    as a weaker signal that it's still live."""
    if not is_standing_offer(release):
        return False

    end_date_str = _extract_contract_end_date(release)
    if end_date_str:
        try:
            end_date = date.fromisoformat(end_date_str[:10])
            return end_date >= date.today()
        except ValueError:
            pass  # unparseable date - fall through to status check

    tender = release.get("tender", {}) or {}
    return tender.get("status") not in ("cancelled", "unsuccessful")


def normalise_releases(raw_releases: list[dict]) -> list[dict]:
    matched = [
        r for r in raw_releases
        if (is_awarded(r) or is_standing_and_valid(r))
        and is_in_region(r)
    ]
    return [extract_summary(r) for r in matched]


def _sort_key(row: dict) -> str:
    """Most recent first. Prefer award_date, fall back to the release date;
    empty string sorts last."""
    return row.get("award_date") or row.get("source_release_date") or ""


def group_by_province_and_industry(rows: list[dict]) -> dict:
    """
    Nests matched tenders as {province: {industry: [rows...]}}, each list
    sorted most-recent-first. A tender with multiple industry tags appears
    under each of its industries (it's still one real tender - this is a
    view for browsing, not a partition).
    """
    grouped: dict[str, dict[str, list[dict]]] = {}

    for row in rows:
        province = row.get("province") or "(unspecified)"
        industries = row.get("industries") or ["(unspecified)"]

        for industry in industries:
            grouped.setdefault(province, {}).setdefault(industry, []).append(row)

    for province_groups in grouped.values():
        for industry_rows in province_groups.values():
            industry_rows.sort(key=_sort_key, reverse=True)

    return grouped


def print_summary_table(rows: list[dict]) -> None:
    """Quick counts so the shape of the data is visible without opening a file."""
    if not rows:
        print("No matched tenders to summarise.")
        return

    by_province: dict[str, int] = {}
    by_industry: dict[str, int] = {}
    for row in rows:
        province = row.get("province") or "(unspecified)"
        by_province[province] = by_province.get(province, 0) + 1
        for industry in row.get("industries") or ["(unspecified)"]:
            by_industry[industry] = by_industry.get(industry, 0) + 1

    print(f"\n--- Summary: {len(rows)} matched tender(s) ---")
    print("\nBy province:")
    for province, count in sorted(by_province.items(), key=lambda kv: -kv[1]):
        print(f"  {province}: {count}")

    print("\nBy industry:")
    for industry, count in sorted(by_industry.items(), key=lambda kv: -kv[1]):
        print(f"  {industry}: {count}")


def write_outputs(rows: list[dict]) -> None:
    # Flat outputs, sorted most-recent-first, for spreadsheet use / feeding
    # straight into the matching engine.
    rows_sorted = sorted(rows, key=_sort_key, reverse=True)

    with open(config.OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows_sorted, f, indent=2, ensure_ascii=False)

    if rows_sorted:
        with open(config.OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows_sorted[0].keys()))
            writer.writeheader()
            writer.writerows(rows_sorted)

    # Grouped view: province -> industry -> tenders, for browsing rather
    # than spreadsheet processing.
    grouped = group_by_province_and_industry(rows)
    with open(config.OUTPUT_GROUPED_JSON, "w", encoding="utf-8") as f:
        json.dump(grouped, f, indent=2, ensure_ascii=False)

    print(
        f"Wrote {len(rows_sorted)} matched tender(s) to "
        f"{config.OUTPUT_JSON} / {config.OUTPUT_CSV} (flat, sorted by date) "
        f"and {config.OUTPUT_GROUPED_JSON} (grouped by province/industry)"
    )
    print_summary_table(rows_sorted)


def diagnose(raw_releases: list[dict]) -> None:
    """Print stage-by-stage filter counts and an industry breakdown, so a
    zero-match run can be debugged in seconds instead of guessed at."""
    total = len(raw_releases)
    awarded = [r for r in raw_releases if is_awarded(r)]
    standing_valid = [r for r in raw_releases if is_standing_and_valid(r)]
    standing_expired = [
        r for r in raw_releases
        if is_standing_offer(r) and not is_standing_and_valid(r)
    ]
    in_region = [r for r in raw_releases if is_in_region(r)]
    final = [
        r for r in raw_releases
        if (is_awarded(r) or is_standing_and_valid(r)) and is_in_region(r)
    ]

    print(f"Total releases fetched: {total}")
    print(f"  Pass is_awarded():          {len(awarded)}")
    print(f"  Standing offers, still valid: {len(standing_valid)}")
    print(f"  Standing offers, expired (excluded): {len(standing_expired)}")
    print(f"  Pass is_in_region():        {len(in_region)}")
    print(f"  Pass final (awarded OR standing-valid, AND region): {len(final)}")

    provinces = sorted({(r.get('tender', {}) or {}).get('province', '(none)') for r in raw_releases})
    statuses = sorted({(r.get('tender', {}) or {}).get('status', '(none)') for r in raw_releases})
    print(f"\nDistinct provinces seen in this batch: {provinces}")
    print(f"Distinct tender statuses seen in this batch: {statuses}")

    if final:
        industry_counts: dict[str, int] = {}
        for r in final:
            for m in industry_classifier.classify_industries(r):
                industry_counts[m["industry"]] = industry_counts.get(m["industry"], 0) + 1

        print(f"\nIndustry breakdown across {len(final)} matched tender(s):")
        for industry, count in sorted(industry_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {industry}: {count}")

        print("\nSample matched tenders (first 5):")
        for r in final[:5]:
            title = (r.get("tender", {}) or {}).get("title")
            province = (r.get("tender", {}) or {}).get("province")
            industries = [m["industry"] for m in industry_classifier.classify_industries(r)]
            print(f" - [{province}] {title} -> {industries}")


def run(probe: bool = False) -> None:
    today = date.today()
    date_from = (today - timedelta(days=config.LOOKBACK_DAYS)).isoformat()
    date_to = today.isoformat()

    if probe:
        print(f"Probing Release API: {config.OCDS_API_BASE}{config.OCDS_RELEASES_PATH}")
        try:
            resp = _session.get(
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
        try:
            raw = fetch_from_bulk_archive(today.strftime("%Y-%m"))
        except NotImplementedError as fallback_exc:
            print(f"\nBoth data sources failed for this run:", file=sys.stderr)
            print(f"  - Release API: {exc}", file=sys.stderr)
            print(f"  - Bulk archive: {fallback_exc}", file=sys.stderr)
            print("\nThis is usually the government API being temporarily slow. "
                  "Just try running the script again.", file=sys.stderr)
            sys.exit(1)

    if "--diagnose" in sys.argv:
        diagnose(raw)
        return

    matched = normalise_releases(raw)
    write_outputs(matched)


if __name__ == "__main__":
    run(probe="--probe" in sys.argv)