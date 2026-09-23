#!/usr/bin/env python3
"""Semrush Analytics API client: report registry, request building, parsing.

Kept separate from the fetch CLI so the parsing and cost logic can be tested
against recorded fixtures without touching the network -- which matters here,
because the API bills per row returned and a test suite that calls it for real
costs money every run.

Two things about this API shape the design:

* Responses are semicolon-delimited CSV with a header row, and the column set
  is chosen per-request via `export_columns`. Parsing by header name rather
  than position means a column order change upstream cannot silently shift
  every value one field to the left.
* Errors come back as HTTP 200 with a plain-text body ("ERROR 50 :: NOTHING
  FOUND"), not as a status code. Anything that does not look like CSV has to be
  treated as a failure or the caller ends up parsing an error string into data.
"""

import csv
import io
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_MAIN = "https://api.semrush.com/"
BASE_ANALYTICS = "https://api.semrush.com/analytics/v1/"

API_KEY_ENV = "SEMRUSH_API_KEY"


class SemrushError(RuntimeError):
    """An API-level failure: bad key, no units, unknown report, empty result."""


# ---------------------------------------------------------------------------
# Report registry
# ---------------------------------------------------------------------------
# Declarative on purpose. Semrush revises column codes and unit prices, and a
# registry means a correction is a one-line edit here rather than a hunt
# through request-building code.
#
# `columns` maps the Semrush column code to the header our normalizer already
# recognises, so fetched files land in ./data looking like an ordinary export
# and the rest of the pipeline needs no changes at all.
#
# `unit_cost` is per returned line unless `flat_cost` is set. These prices are
# ESTIMATES for pre-flight budgeting -- verify against your own plan before
# trusting a large pull. Getting them slightly wrong costs you an inaccurate
# warning, not an inaccurate dataset.

REPORTS = {
    "domain_overview": {
        "base": BASE_MAIN,
        "type": "domain_ranks",
        "dataset": "authority",
        "unit_cost": 10,
        "columns": {
            "Dn": "Domain",
            "Rk": "Semrush Rank",
            "Or": "Organic Keywords",
            "Ot": "Organic Traffic",
            "Oc": "Organic Cost",
            "Ad": "Adwords Keywords",
        },
        "needs": ("domain", "database"),
    },
    "backlinks_overview": {
        "base": BASE_ANALYTICS,
        "type": "backlinks_overview",
        "dataset": "authority",
        "unit_cost": 40,
        "flat_cost": True,
        "columns": {
            "ascore": "Authority Score",
            "total": "Total Backlinks",
            "domains_num": "Referring Domains",
            "urls_num": "Referring URLs",
            "follows_num": "Follow Links",
            "nofollows_num": "Nofollow Links",
        },
        "needs": ("target", "target_type"),
    },
    "referring_domains": {
        "base": BASE_ANALYTICS,
        "type": "backlinks_refdomains",
        "dataset": "backlinks",
        "unit_cost": 40,
        "columns": {
            "domain": "Referring Domain",
            "domain_ascore": "Domain Rating",
            "backlinks_num": "Backlinks Count",
            "country": "Country",
            "first_seen": "First Seen",
            "last_seen": "Last Seen",
        },
        "needs": ("target", "target_type"),
        "sort": "domain_ascore_desc",
    },
    "backlinks": {
        "base": BASE_ANALYTICS,
        "type": "backlinks",
        "dataset": "backlinks",
        "unit_cost": 40,
        "columns": {
            "source_url": "Referring page URL",
            "source_title": "Referring page title",
            "target_url": "Target URL",
            "anchor": "Anchor",
            "nofollow": "Nofollow",
            "first_seen": "First seen",
            "last_seen": "Last seen",
        },
        "needs": ("target", "target_type"),
        "sort": "last_seen_desc",
    },
    "organic_keywords": {
        "base": BASE_MAIN,
        "type": "domain_organic",
        "dataset": "content_gaps",
        "unit_cost": 10,
        "columns": {
            "Ph": "Keyword",
            "Po": "Position",
            "Pp": "Previous Position",
            "Nq": "Search Volume",
            "Cp": "CPC",
            "Co": "Competition",
            "Nr": "Results",
            "Ur": "URL",
            "Tr": "Traffic Share",
        },
        "needs": ("domain", "database"),
        "sort": "tr_desc",
    },
    "keyword_difficulty": {
        # Opt-in via --with-difficulty. Priced well above the organic reports
        # and charged per keyword, so pulling it for a wide keyword set is the
        # easiest way to burn units by accident.
        "base": BASE_MAIN,
        "type": "phrase_kdi",
        "dataset": "content_gaps",
        "unit_cost": 50,
        "columns": {"Ph": "Keyword", "Kd": "Keyword Difficulty"},
        "needs": ("phrase", "database"),
    },
    "organic_competitors": {
        "base": BASE_MAIN,
        "type": "domain_organic_organic",
        "dataset": "competitors",
        "unit_cost": 40,
        "columns": {
            "Dn": "Domain",
            "Cr": "Competitor Relevance",
            "Np": "Common Keywords",
            "Or": "Organic Keywords",
            "Ot": "Organic Traffic",
            "Oc": "Organic Cost",
        },
        "needs": ("domain", "database"),
    },
}

# Reports that would satisfy the citations dataset. Empty, deliberately: as of
# this writing Semrush exposes no public Analytics API endpoint for AI
# Visibility Toolkit prompt, mention or citation data. Left here as the place
# to add one, and as the reason fetch_semrush.py says so out loud rather than
# producing a silently citation-free run.
CITATION_REPORTS = {}


def build_url(report_name, api_key, limit=None, offset=None, **params):
    """Build a request URL. Returns (url, redacted_url_for_display)."""
    if report_name not in REPORTS:
        raise SemrushError(f"unknown report '{report_name}'")
    spec = REPORTS[report_name]

    missing = [p for p in spec["needs"] if not params.get(p)]
    if missing:
        raise SemrushError(f"{report_name} requires: {', '.join(missing)}")

    query = {"type": spec["type"], "key": api_key,
             "export_columns": ",".join(spec["columns"])}
    query.update({k: v for k, v in params.items() if v is not None})
    if limit and not spec.get("flat_cost"):
        query["display_limit"] = int(limit)
    if offset:
        query["display_offset"] = int(offset)
    if spec.get("sort") and not spec.get("flat_cost"):
        query["display_sort"] = spec["sort"]

    url = spec["base"] + "?" + urllib.parse.urlencode(query)
    redacted = url.replace(urllib.parse.quote(str(api_key), safe=""), "<KEY>") \
        if api_key else url
    return url, redacted


def estimate_units(report_name, limit):
    """Pre-flight cost estimate. Semrush bills per returned line, so a wide
    competitor pull gets expensive faster than people expect."""
    spec = REPORTS[report_name]
    if spec.get("flat_cost"):
        return spec["unit_cost"]
    return spec["unit_cost"] * int(limit or 0)


def parse_response(body, report_name):
    """Parse a semicolon-CSV response into rows keyed by our canonical headers.

    Raises on anything that is not CSV, because this API reports failure in the
    body with a 200 status and an unparsed error string would otherwise flow
    downstream as though it were data.
    """
    text = (body or "").strip()
    if not text:
        raise SemrushError(f"{report_name}: empty response")

    if text.upper().startswith("ERROR"):
        # Shape: "ERROR 50 :: NOTHING FOUND"
        m = re.match(r"ERROR\s+(\d+)\s*::\s*(.+)", text, re.I)
        code, msg = (m.group(1), m.group(2).strip()) if m else ("?", text[:200])
        raise SemrushError(f"{report_name}: API error {code}: {msg}")

    if ";" not in text.splitlines()[0]:
        raise SemrushError(
            f"{report_name}: response is not semicolon-CSV (got: {text[:120]!r})")

    spec = REPORTS[report_name]
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows = []
    for raw in reader:
        row = {}
        for code, header in spec["columns"].items():
            if code in raw:
                row[header] = (raw[code] or "").strip()
        if any(v for v in row.values()):
            rows.append(row)
    return rows


def request(url, timeout=60, retries=3, sleep=time.sleep):
    """GET with backoff on transient failures.

    429 and 5xx are retried; 4xx other than 429 are not, since a bad key or a
    malformed report will fail identically on every attempt and retrying only
    delays a clear error message.
    """
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "geo-seo-trail-guide/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 or e.code >= 500:
                if attempt < retries - 1:
                    sleep(2 ** (attempt + 1))
                    continue
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            raise SemrushError(f"HTTP {e.code}: {e.reason}. {detail}".strip()) from e
        except urllib.error.URLError as e:
            last = e
            if attempt < retries - 1:
                sleep(2 ** (attempt + 1))
                continue
            raise SemrushError(
                f"network error: {e.reason}. If this is a proxy 403, the host "
                f"api.semrush.com is not permitted by this environment's "
                f"network policy.") from e
    raise SemrushError(f"request failed after {retries} attempts: {last}")


def get_api_key(explicit=None):
    """Resolve the key from the argument or the environment.

    Never accept a key on the command line in a way that would land it in shell
    history, and never print it: the redacted URL is what gets logged.
    """
    key = explicit or os.environ.get(API_KEY_ENV)
    if not key:
        raise SemrushError(
            f"No API key. Set {API_KEY_ENV} in the environment's settings "
            f"(do not paste it into a terminal or a file).")
    return key.strip()
