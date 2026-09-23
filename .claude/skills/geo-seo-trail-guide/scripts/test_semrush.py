#!/usr/bin/env python3
"""Offline tests for the Semrush client.

Runs against recorded response shapes rather than the live API, because that
API bills per row returned -- a suite that called it for real would cost money
on every run and would fail in any environment without egress. What is verified
here is everything that is ours: URL construction, CSV parsing, error handling,
key redaction, cost arithmetic, and the local content-gap diff.

    python3 test_semrush.py
"""

import sys

import semrush_api as api
from fetch_semrush import build_content_gaps

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        FAILURES.append(name)


print("URL construction")
url, redacted = api.build_url("domain_overview", "SECRET123",
                              domain="example.com", database="us")
check("includes report type", "type=domain_ranks" in url)
check("includes key", "key=SECRET123" in url)
check("requests mapped columns", "export_columns=Dn%2CRk" in url or "Dn,Rk" in url)
check("key redacted for display", "SECRET123" not in redacted and "<KEY>" in redacted,
      f"-> {redacted}")

url, _ = api.build_url("referring_domains", "K", target="example.com",
                       target_type="root_domain", limit=250)
check("applies display_limit", "display_limit=250" in url)
check("applies sort", "display_sort=domain_ascore_desc" in url)
check("uses analytics base", url.startswith(api.BASE_ANALYTICS))

url, _ = api.build_url("backlinks_overview", "K", target="example.com",
                       target_type="root_domain", limit=500)
check("flat-cost report ignores limit", "display_limit" not in url)

try:
    api.build_url("domain_overview", "K", database="us")
    check("missing required param raises", False)
except api.SemrushError as e:
    check("missing required param raises", "domain" in str(e))

try:
    api.build_url("nonexistent_report", "K")
    check("unknown report raises", False)
except api.SemrushError:
    check("unknown report raises", True)

print("\nResponse parsing")
overview = "Dn;Rk;Or;Ot;Oc;Ad\r\nexample.com;1423;6200;28500;41200;180\r\n"
rows = api.parse_response(overview, "domain_overview")
check("parses one row", len(rows) == 1)
check("maps Dn -> Domain", rows[0].get("Domain") == "example.com")
check("maps Ot -> Organic Traffic", rows[0].get("Organic Traffic") == "28500")

refdoms = ("domain_ascore;domain;backlinks_num;country;first_seen;last_seen\r\n"
           "86;shrm.org;14;US;2024-01-02;2026-09-01\r\n"
           "74;hrdive.com;3;US;2025-03-11;2026-08-20\r\n")
rows = api.parse_response(refdoms, "referring_domains")
check("parses multiple rows", len(rows) == 2)
check("maps domain_ascore -> Domain Rating", rows[0].get("Domain Rating") == "86")
check("maps domain -> Referring Domain", rows[1].get("Referring Domain") == "hrdive.com")

# Column order changed upstream: parsing by header must still be correct.
shuffled = ("domain;last_seen;domain_ascore;backlinks_num;first_seen;country\r\n"
            "shrm.org;2026-09-01;86;14;2024-01-02;US\r\n")
rows = api.parse_response(shuffled, "referring_domains")
check("survives reordered columns", rows[0].get("Domain Rating") == "86"
      and rows[0].get("Referring Domain") == "shrm.org")

# Unrequested extra column should be ignored, not shift the mapping.
extra = ("domain;domain_ascore;backlinks_num;surprise_new_col\r\n"
         "shrm.org;86;14;whatever\r\n")
rows = api.parse_response(extra, "referring_domains")
check("ignores unknown extra column", rows[0].get("Domain Rating") == "86")

check("blank rows dropped",
      len(api.parse_response("Dn;Rk\r\nexample.com;5\r\n;\r\n", "domain_overview")) == 1)

print("\nError handling")
for body, label in [
    ("ERROR 50 :: NOTHING FOUND", "nothing found"),
    ("ERROR 40 :: API UNITS BALANCE IS ZERO", "zero units"),
    ("ERROR 120 :: WRONG KEY - ID PAIR", "bad key"),
]:
    try:
        api.parse_response(body, "domain_overview")
        check(f"raises on {label}", False)
    except api.SemrushError as e:
        check(f"raises on {label}", "API error" in str(e))

for body, label in [("", "empty body"), ("<html>502 Bad Gateway</html>", "html body")]:
    try:
        api.parse_response(body, "domain_overview")
        check(f"raises on {label}", False)
    except api.SemrushError:
        check(f"raises on {label}", True)

print("\nRetry behaviour")
import urllib.error


class FakeSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, n):
        self.calls.append(n)


def patched_urlopen(exc_seq, ok_body="Dn;Rk\r\nx.com;1\r\n"):
    state = {"i": 0}

    class Resp:
        def read(self):
            return ok_body.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        i = state["i"]
        state["i"] += 1
        if i < len(exc_seq):
            raise exc_seq[i]
        return Resp()
    return fake


orig = api.urllib.request.urlopen
try:
    err500 = urllib.error.HTTPError("u", 500, "Server Error", {}, None)
    sleeper = FakeSleep()
    api.urllib.request.urlopen = patched_urlopen([err500, err500])
    body = api.request("https://x", retries=3, sleep=sleeper)
    check("retries 5xx then succeeds", body.startswith("Dn;Rk"))
    check("backs off exponentially", sleeper.calls == [2, 4], f"-> {sleeper.calls}")

    err403 = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
    sleeper = FakeSleep()
    api.urllib.request.urlopen = patched_urlopen([err403, err403, err403])
    try:
        api.request("https://x", retries=3, sleep=sleeper)
        check("does not retry 4xx", False)
    except api.SemrushError:
        check("does not retry 4xx", sleeper.calls == [], f"-> {sleeper.calls}")

    sleeper = FakeSleep()
    api.urllib.request.urlopen = patched_urlopen(
        [urllib.error.URLError("proxy CONNECT 403")] * 3)
    try:
        api.request("https://x", retries=3, sleep=sleeper)
        check("network error mentions the proxy", False)
    except api.SemrushError as e:
        check("network error mentions the proxy", "network policy" in str(e))
finally:
    api.urllib.request.urlopen = orig

print("\nCost estimation")
check("per-row scales with limit",
      api.estimate_units("referring_domains", 100) == 4000)
check("flat-cost ignores limit",
      api.estimate_units("backlinks_overview", 9999) == 40)
check("zero limit costs nothing", api.estimate_units("organic_keywords", 0) == 0)

print("\nKey resolution")
import os
os.environ.pop(api.API_KEY_ENV, None)
try:
    api.get_api_key()
    check("missing key raises", False)
except api.SemrushError as e:
    check("missing key raises", api.API_KEY_ENV in str(e))
os.environ[api.API_KEY_ENV] = "  envkey  "
check("reads and strips env key", api.get_api_key() == "envkey")
check("explicit arg wins", api.get_api_key("explicit") == "explicit")
os.environ.pop(api.API_KEY_ENV, None)

print("\nContent-gap diff")
brand = [{"Keyword": "hr software", "Position": "7", "Search Volume": "8100", "CPC": "12.4"},
         {"Keyword": "only ours", "Position": "3", "Search Volume": "200", "CPC": "1.0"}]
comps = {
    "rival-a.com": [{"Keyword": "hr software", "Position": "2", "Search Volume": "8100"},
                    {"Keyword": "payroll tools", "Position": "5", "Search Volume": "3300"}],
    "rival-b.com": [{"Keyword": "hr software", "Position": "4", "Search Volume": "8100"}],
}
gaps = build_content_gaps(brand, comps, {"payroll tools": "61"})
by_kw = {g["Keyword"].lower(): g for g in gaps}

check("contested keyword present", "hr software" in by_kw)
check("our rank carried", by_kw["hr software"]["Our Rank"] == "7")
check("best competitor rank is the minimum", by_kw["hr software"]["Best Competitor Rank"] == 2)
check("counts distinct rivals", by_kw["hr software"]["Competitors Ranking"] == 2)
check("keyword we do not rank for is a gap",
      by_kw["payroll tools"]["Our Rank"] == "")
check("difficulty merged when supplied",
      by_kw["payroll tools"]["Keyword Difficulty"] == "61")
check("uncontested own keyword retained",
      by_kw["only ours"]["Competitors Ranking"] == 0)
check("sorted by volume descending",
      [g["Keyword"].lower() for g in gaps][0] == "hr software")

print("\nHeaders match what normalize.py expects")
sys.path.insert(0, ".")
import normalize
gap_headers = {h.lower() for h in gaps[0]}
recognised = set()
for field, aliases in normalize.SCHEMAS["content_gaps"]["fields"].items():
    for h in gap_headers:
        if normalize.squash(h) in aliases:
            recognised.add(field)
check("content-gap headers map to canonical fields",
      {"topic", "search_volume", "our_rank", "difficulty"} <= recognised,
      f"-> mapped {sorted(recognised)}")

auth_headers = ["Domain", "Is Client", "Authority Score", "Referring Domains",
                "Organic Traffic", "Organic Keywords"]
rec = set()
for field, aliases in normalize.SCHEMAS["authority"]["fields"].items():
    for h in auth_headers:
        if normalize.squash(h) in aliases:
            rec.add(field)
check("authority headers map to canonical fields",
      {"domain", "is_client", "domain_rating", "referring_domains"} <= rec,
      f"-> mapped {sorted(rec)}")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
    sys.exit(1)
print("All tests passed.")
