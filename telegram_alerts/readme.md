# eTenders Scraper - Pilot (Phase 1)

Filters awarded National Treasury tenders down to electrical/technical trades in Gauteng.

## Setup
```
pip install requests
```

## Before running for real: one probe step

The live API's exact parameter names couldn't be verified from this build environment
(the API domain wasn't reachable here, and its Swagger docs render via JavaScript).
Run this once from a machine with normal internet access:

```
python3 scraper.py --probe
```

It prints the raw HTTP response from the Release API. Paste that output back
and `fetch_from_release_api()` in scraper.py can be corrected in minutes if the
parameter names differ from the OCDS-standard guess (`dateFrom`, `dateTo`,
`PageNumber`, `PageSize`).

## Normal run
```
python3 scraper.py
```
Writes `matched_tenders.json` and `matched_tenders.csv` - feed these into the
direct-request matching engine (Phase 2) and the WhatsApp/Telegram push (Phase 3).

## What's configurable
Edit `config.py` to widen `KEYWORDS` / `REGIONS` when the pilot expands past
electrical/Gauteng (Phase 5 in the roadmap).
