#!/usr/bin/env python3
"""Pull Semrush data into ./data so the normal pipeline can run unchanged.

Writes ordinary CSVs with the headers normalize.py already recognises, which
keeps this an optional front-end rather than a second ingestion path: whether a
file arrived by API or by hand export, everything downstream is identical.

What it covers, and what it cannot:

    authority      yes   domain overview + Authority Score per domain
    competitors    yes   discovered organic competitors, or the ones you name
    backlinks      yes   referring domains and individual links
    content_gaps   yes   computed locally by diffing organic keyword sets
    citations      NO    Semrush exposes no public API for AI Visibility
                         Toolkit prompt/mention/citation data

That last line is the important one. Citations are what make this a GEO
analysis rather than a classic SEO audit, so a run without them produces a
partial document by design. The script says so on every run instead of leaving
you to notice a quiet gap in section 2.

Cost: this API bills per returned row. Always --dry-run first.

Usage:
    export SEMRUSH_API_KEY=...          # set in environment settings, not here
    python3 fetch_semrush.py --brand example.com --dry-run
    python3 fetch_semrush.py --brand example.com \\
        --competitors rival-a.com,rival-b.com --out-dir ./data
"""

import argparse
import csv
import os
import sys
from collections import defaultdict

import semrush_api as api


def write_csv(path, rows, headers=None):
    if not rows:
        return 0
    headers = headers or list(rows[0].keys())
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    return len(rows)


def fetch(report, key, dry_run, log, **params):
    """One report. In dry-run, print the redacted URL and return no rows."""
    limit = params.pop("limit", None)
    url, redacted = api.build_url(report, key or "DRYRUN", limit=limit, **params)
    if dry_run:
        log(f"    {redacted}")
        return []
    try:
        body = api.request(url)
        rows = api.parse_response(body, report)
        log(f"    {report}: {len(rows)} rows")
        return rows
    except api.SemrushError as e:
        # A failed report degrades that dataset; it should not abort a run that
        # may already have paid for several others.
        log(f"    {report}: FAILED - {e}")
        return []


def build_content_gaps(brand_kws, competitor_kws, difficulty=None):
    """Diff organic keyword sets into content-gap rows.

    Computed here rather than pulled from a gap endpoint because doing it
    locally yields exactly the columns the scoring model wants -- our rank,
    the best competitor rank, and how many rivals hold the term -- from data we
    have already paid for.
    """
    ours = {}
    for r in brand_kws:
        kw = (r.get("Keyword") or "").strip().lower()
        if kw:
            ours[kw] = r

    agg = defaultdict(lambda: {"row": None, "positions": [], "domains": set()})
    for domain, rows in competitor_kws.items():
        for r in rows:
            kw = (r.get("Keyword") or "").strip().lower()
            if not kw:
                continue
            rec = agg[kw]
            rec["row"] = rec["row"] or r
            rec["domains"].add(domain)
            try:
                rec["positions"].append(int(float(r.get("Position") or 0)))
            except (TypeError, ValueError):
                pass

    diff = difficulty or {}
    out = []
    for kw, rec in agg.items():
        src = ours.get(kw) or rec["row"] or {}
        our_row = ours.get(kw)
        positions = [p for p in rec["positions"] if p > 0]
        out.append({
            "Keyword": src.get("Keyword") or kw,
            "Search Volume": src.get("Search Volume", ""),
            "Keyword Difficulty": diff.get(kw, ""),
            "Our Rank": (our_row or {}).get("Position", ""),
            "Best Competitor Rank": min(positions) if positions else "",
            "Competitors Ranking": len(rec["domains"]),
            "Search Intent": "",
            "CPC": src.get("CPC", ""),
            "AI Overview": "",
        })

    # Keywords we rank for that no competitor does are not gaps, but they are
    # defensible ground the roadmap should still see.
    for kw, r in ours.items():
        if kw not in agg:
            out.append({
                "Keyword": r.get("Keyword") or kw,
                "Search Volume": r.get("Search Volume", ""),
                "Keyword Difficulty": diff.get(kw, ""),
                "Our Rank": r.get("Position", ""),
                "Best Competitor Rank": "", "Competitors Ranking": 0,
                "Search Intent": "", "CPC": r.get("CPC", ""), "AI Overview": "",
            })

    def vol(r):
        try:
            return -float(r["Search Volume"])
        except (TypeError, ValueError):
            return 0.0
    out.sort(key=vol)
    return out


CITATION_NOTE = """\
# Citation data is NOT supplied by the Semrush connector

`fetch_semrush.py` pulled everything the Semrush Analytics API exposes, but AI
Visibility Toolkit data -- the prompts, mentions and citations that make this a
GEO analysis rather than a classic SEO audit -- is not among it. There is no
public Analytics API endpoint for it, and as of this writing CSV export is not
available for the AI search module either.

Without it the pipeline still runs, and section 8 of the report will state the
limitation. What you lose is the central join: which domains answer engines
cite for your prompts, and which of those do not link to you. That join is what
sections 2 through 5 are built on, so a run without citations is a link-gap and
content audit rather than the full document.

Three ways to close it, cheapest first:

1. **Semrush My Reports / Looker Studio.** Brand Performance, Visibility
   Overview and Prompt Tracking are wired into My Reports. If you can get a
   prompt-level table out that way, shape it to the `citations` schema in
   `references/intake-schema.md` and drop it in this folder.
2. **A vendor with an API.** Profound, Peec and Otterly all expose prompt-level
   citation data. A second connector modelled on this one would be a short job.
3. **By hand.** 40-60 prompts across three engines, logged to a spreadsheet
   matching the schema. Tedious, but you pick the prompts your buyers actually
   ask, which is usually better than a vendor's generic set.

Delete this file once citation data is in place.
"""


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brand", required=True, help="Your domain, e.g. example.com")
    ap.add_argument("--competitors", default="",
                    help="Comma-separated. Omit to auto-discover via Semrush.")
    ap.add_argument("--database", default="us", help="Regional database (default: us)")
    ap.add_argument("--out-dir", default="./data")
    ap.add_argument("--api-key", default=None,
                    help=f"Prefer the {api.API_KEY_ENV} environment variable.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the requests and a unit estimate. No key needed, no cost.")
    ap.add_argument("--max-competitors", type=int, default=5)
    # Defaults are deliberately modest. Backlink reports bill 40 units per row,
    # so generous limits multiplied across a competitor set can eat a monthly
    # allowance in a single command. Raise them once a small run has proved the
    # endpoints work against your plan.
    ap.add_argument("--keyword-limit", type=int, default=300,
                    help="Organic keywords per domain (default 300)")
    ap.add_argument("--backlink-limit", type=int, default=300)
    ap.add_argument("--refdomain-limit", type=int, default=200)
    ap.add_argument("--max-units", type=int, default=50000,
                    help="Abort if the estimate exceeds this many API units "
                         "(default 50000). Raise it deliberately, not reflexively.")
    ap.add_argument("--competitor-backlinks", action="store_true",
                    help="Also pull competitor referring domains, which unlocks the "
                         "link-gap and competitive-displacement tiers. Costs roughly "
                         "one more refdomain pull per competitor.")
    ap.add_argument("--with-difficulty", action="store_true",
                    help="Fetch keyword difficulty (extra units, charged per keyword).")
    args = ap.parse_args()

    brand = args.brand.strip().lower().replace("https://", "").replace("http://", "")
    brand = brand.replace("www.", "").split("/")[0]
    competitors = [c.strip().lower() for c in args.competitors.split(",") if c.strip()]

    key = None
    if not args.dry_run:
        try:
            key = api.get_api_key(args.api_key)
        except api.SemrushError as e:
            sys.exit(f"ERROR: {e}")

    def log(msg=""):
        print(msg, flush=True)

    log(f"Brand: {brand}   database: {args.database}")
    if args.dry_run:
        log("DRY RUN - printing requests and a cost estimate. Nothing is called.\n")

    # ---- planning / cost estimate -------------------------------------
    planned = [("domain_overview", 1), ("backlinks_overview", 1),
               ("organic_competitors", 1), ("referring_domains", args.refdomain_limit),
               ("backlinks", args.backlink_limit),
               ("organic_keywords", args.keyword_limit)]
    n_comp = len(competitors) or args.max_competitors
    planned += [("domain_overview", 1)] * n_comp
    planned += [("backlinks_overview", 1)] * n_comp
    planned += [("organic_keywords", args.keyword_limit)] * n_comp
    if args.competitor_backlinks:
        planned += [("referring_domains", args.refdomain_limit)] * n_comp
    if args.with_difficulty:
        planned += [("keyword_difficulty", args.keyword_limit)]

    total = sum(api.estimate_units(r, n) for r, n in planned)
    by_report = defaultdict(int)
    for r, n in planned:
        by_report[r] += api.estimate_units(r, n)

    log(f"Estimated cost: ~{total:,} API units across {len(planned)} requests "
        f"({n_comp} competitors).")
    for r, u in sorted(by_report.items(), key=lambda x: -x[1]):
        log(f"    {r:<22} ~{u:>9,} units")
    log("  Estimate assumes every request returns its full limit; actual cost is")
    log("  per row returned, so it is an upper bound. Verify unit prices against")
    log("  your plan - they are configured in semrush_api.py REPORTS.")

    if total > args.max_units:
        biggest = max(by_report, key=by_report.get)
        log("")
        log("=" * 70)
        log(f"REFUSING TO RUN: the estimate (~{total:,} units) exceeds the "
            f"--max-units budget of {args.max_units:,}.")
        log(f"The biggest line is '{biggest}' at ~{by_report[biggest]:,} units.")
        log("")
        log("This guard exists because the API bills per row returned, so a wide")
        log("pull can consume a monthly allowance in one command. Either lower the")
        log("limits (--refdomain-limit, --backlink-limit, --keyword-limit,")
        log("--max-competitors), drop --competitor-backlinks or --with-difficulty,")
        log("or raise --max-units deliberately once you have checked your balance.")
        log("=" * 70)
        sys.exit(2)
    log("")

    os.makedirs(args.out_dir, exist_ok=True)

    # ---- competitor discovery -----------------------------------------
    log("Competitors:")
    comp_rows = fetch("organic_competitors", key, args.dry_run, log,
                      domain=brand, database=args.database, limit=args.max_competitors)
    if not competitors:
        competitors = [r["Domain"].strip().lower() for r in comp_rows
                       if r.get("Domain") and r["Domain"].strip().lower() != brand]
        competitors = competitors[:args.max_competitors]
        if competitors:
            log(f"    discovered: {', '.join(competitors)}")
    domains = [brand] + competitors

    # ---- authority -----------------------------------------------------
    log("\nAuthority:")
    authority = []
    for d in domains:
        overview = fetch("domain_overview", key, args.dry_run, log,
                         domain=d, database=args.database)
        bl = fetch("backlinks_overview", key, args.dry_run, log,
                   target=d, target_type="root_domain")
        o = overview[0] if overview else {}
        b = bl[0] if bl else {}
        authority.append({
            "Domain": d,
            "Is Client": "TRUE" if d == brand else "FALSE",
            "Authority Score": b.get("Authority Score", ""),
            "Referring Domains": b.get("Referring Domains", ""),
            "Organic Traffic": o.get("Organic Traffic", ""),
            "Organic Keywords": o.get("Organic Keywords", ""),
            "Snapshot Date": "",
        })

    # ---- backlinks -----------------------------------------------------
    log("\nBacklinks:")
    backlinks = []
    refdoms = fetch("referring_domains", key, args.dry_run, log,
                    target=brand, target_type="root_domain", limit=args.refdomain_limit)
    for r in refdoms:
        backlinks.append({
            "Referring page URL": "", "Referring page title": "",
            "Referring Domain": r.get("Referring Domain", ""),
            "Domain rating": r.get("Domain Rating", ""),
            "Domain traffic": "", "Anchor": "", "Type": "",
            "Target URL": f"https://{brand}/",
            "First seen": r.get("First Seen", ""),
        })
    links = fetch("backlinks", key, args.dry_run, log,
                  target=brand, target_type="root_domain", limit=args.backlink_limit)
    for r in links:
        nf = (r.get("Nofollow") or "").strip().lower()
        backlinks.append({
            "Referring page URL": r.get("Referring page URL", ""),
            "Referring page title": r.get("Referring page title", ""),
            "Referring Domain": "", "Domain rating": "", "Domain traffic": "",
            "Anchor": r.get("Anchor", ""),
            "Type": "Nofollow" if nf in ("true", "1", "yes") else "Dofollow",
            "Target URL": r.get("Target URL", ""),
            "First seen": r.get("First seen", ""),
        })

    if args.competitor_backlinks:
        log("  competitor referring domains (unlocks the link-gap tiers):")
        for c in competitors:
            for r in fetch("referring_domains", key, args.dry_run, log,
                           target=c, target_type="root_domain",
                           limit=args.refdomain_limit):
                backlinks.append({
                    "Referring page URL": "", "Referring page title": "",
                    "Referring Domain": r.get("Referring Domain", ""),
                    "Domain rating": r.get("Domain Rating", ""),
                    "Domain traffic": "", "Anchor": "", "Type": "",
                    "Target URL": f"https://{c}/",
                    "First seen": r.get("First Seen", ""),
                })

    # ---- keywords and the computed gap ---------------------------------
    log("\nOrganic keywords:")
    brand_kws = fetch("organic_keywords", key, args.dry_run, log,
                      domain=brand, database=args.database, limit=args.keyword_limit)
    competitor_kws = {}
    for c in competitors:
        competitor_kws[c] = fetch("organic_keywords", key, args.dry_run, log,
                                  domain=c, database=args.database,
                                  limit=args.keyword_limit)

    difficulty = {}
    if args.with_difficulty and not args.dry_run:
        phrases = {(r.get("Keyword") or "").strip().lower()
                   for rows in list(competitor_kws.values()) + [brand_kws]
                   for r in rows if r.get("Keyword")}
        # phrase_kdi takes a semicolon-joined batch; chunk to keep URLs sane.
        batch = sorted(phrases)[:args.keyword_limit]
        for i in range(0, len(batch), 100):
            chunk = batch[i:i + 100]
            for r in fetch("keyword_difficulty", key, args.dry_run, log,
                           phrase=";".join(chunk), database=args.database):
                kw = (r.get("Keyword") or "").strip().lower()
                if kw:
                    difficulty[kw] = r.get("Keyword Difficulty", "")
    elif args.with_difficulty:
        log("    keyword_difficulty: skipped in dry run (needs the keyword set)")

    gaps = build_content_gaps(brand_kws, competitor_kws, difficulty)

    # ---- write ----------------------------------------------------------
    if args.dry_run:
        log("\nDry run complete. No files written, no units spent.")
        log("Re-run without --dry-run to fetch.")
        return

    log("\nWritten:")
    written = {
        "semrush_authority.csv": write_csv(
            os.path.join(args.out_dir, "semrush_authority.csv"), authority),
        "semrush_competitors.csv": write_csv(
            os.path.join(args.out_dir, "semrush_competitors.csv"),
            [{"Competitor Domain": r["Domain"], "Common Keywords": r.get("Common Keywords", ""),
              "Organic Keywords": r.get("Organic Keywords", ""),
              "Organic Traffic": r.get("Organic Traffic", ""),
              "Competitor Relevance": r.get("Competitor Relevance", "")}
             for r in comp_rows]),
        "semrush_backlinks.csv": write_csv(
            os.path.join(args.out_dir, "semrush_backlinks.csv"), backlinks),
        "semrush_content_gaps.csv": write_csv(
            os.path.join(args.out_dir, "semrush_content_gaps.csv"), gaps),
    }
    for name, n in written.items():
        log(f"    {name:<32} {n:>6} rows" if n else f"    {name:<32}      - (no rows)")

    note_path = os.path.join(args.out_dir, "CITATIONS-MISSING.md")
    with open(note_path, "w", encoding="utf-8") as fh:
        fh.write(CITATION_NOTE)

    log("\n" + "=" * 70)
    log("Citation data was NOT fetched: Semrush exposes no public API for AI")
    log("Visibility Toolkit prompts, mentions or citations. Without it the")
    log("central citation-gap join cannot run and the report degrades to a")
    log("link-gap and content audit.")
    log(f"See {note_path} for the three ways to close that gap.")
    log("=" * 70)
    log("\nNext: python3 normalize.py --data-dir %s --brand-domain %s"
        % (args.out_dir, brand))


if __name__ == "__main__":
    main()
