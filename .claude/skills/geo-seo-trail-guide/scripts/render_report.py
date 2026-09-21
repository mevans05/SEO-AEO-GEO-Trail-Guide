#!/usr/bin/env python3
"""Render analysis.json into the deliverable's factual skeleton.

This writes every table that is pure arithmetic -- scorecard, source graph,
target tiers, roadmap horizons -- and leaves clearly marked slots where an
analyst has to supply judgment: the pitch angle for a given publication, the
campaign concept, the sequencing call. Splitting it this way keeps the numbers
reproducible and stops the writing phase from quietly re-deriving (and
mis-deriving) figures that were already computed.

Usage:
    python3 render_report.py --in ./build/analysis.json --out ./build/report-draft.md
"""

import argparse
import datetime as dt
import json
import os

SLOT = "<!-- ANALYST: {} -->"


NOT_MEASURED = "_not measured_"


def fmt(v, suffix="", dash="-"):
    if v is None or v == "":
        return dash
    if isinstance(v, float):
        return f"{v:,.1f}{suffix}" if v % 1 else f"{int(v):,}{suffix}"
    if isinstance(v, int):
        return f"{v:,}{suffix}"
    return f"{v}{suffix}"


def dr_cell(t):
    """Show an estimated DR as such, so a reader never mistakes a fallback for
    a measurement when deciding whether a target is worth pitching."""
    if t.get("domain_rating") is not None:
        return fmt(t["domain_rating"])
    est = t.get("domain_rating_used")
    return f"~{fmt(est)} est" if est is not None else "-"


def table(headers, rows):
    if not rows:
        return "_No qualifying rows in the supplied data._\n"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out) + "\n"


def bullets(items):
    return "\n".join(f"- {i}" for i in items) + "\n" if items else "_None._\n"


def render(a):
    b = []
    w = b.append
    brand = a.get("brand_name") or a.get("brand_domain") or "the brand"
    domain = a.get("brand_domain") or "unknown-domain"
    today = dt.date.today().isoformat()
    sc = a["scorecard"]
    vis = a["visibility"]
    src = a["source_graph"]
    auth = a["authority"]
    blp = a["backlink_profile"]
    topics = a["topics"]

    w(f"# GEO & SEO Authority Trail Guide - {brand}\n")
    w(f"**Domain:** {domain}  |  **Prepared:** {today}  |  "
      f"**Prompt set:** {fmt(vis.get('total_prompts_tracked'))} prompts across "
      f"{len(vis.get('engines_tracked', []))} engines\n")

    # ---------------------------------------------------------------- 0
    w("\n## 0. Executive summary\n")
    w(SLOT.format(
        "Write 5-7 sentences. Lead with the single most consequential finding from "
        "the scorecard and section 2, not with a restatement of the brief. Name the "
        "one number that should change this quarter and what moves it. Do not "
        "recompute figures here - cite the ones below.") + "\n")

    w("\n### Scorecard\n")

    def metric(value, suffix="", grade=None, read="", absent=""):
        """Render one scorecard row, keeping 'no data' distinct from 'zero'.

        A 0% next to an F grade reads as a finding and gets acted on; an
        unmeasured metric needs to prompt the opposite response, which is to go
        and instrument it."""
        if value is None:
            return [NOT_MEASURED, absent or "No data supplied for this metric"]
        label = f"Grade {grade} - {read}" if grade else read
        return [fmt(value, suffix), label]

    w(table(["Metric", "Value", "Read"], [
        ["AI answer share", *metric(
            sc["ai_answer_share_pct"], "%", sc["ai_answer_share_grade"],
            "share of tracked prompts naming the brand",
            "No citation data supplied - see section 8")],
        ["Citation-graph capture", *metric(
            sc["citation_graph_capture_pct"], "%", sc["citation_graph_capture_grade"],
            "cited sources that already link to you",
            "Needs both citation and backlink data to compute")],
        ["Authority rank", *metric(
            sc["authority_rank"], "", None,
            f"DR gap to competitor median: {fmt(sc['dr_gap_to_median'])}",
            "No authority or competitor data supplied")],
        ["Referring domains", *metric(
            sc["referring_domains"], "", None,
            f"Gap to competitor median: {fmt(sc['referring_domain_gap_to_median'])}",
            "No backlink data supplied")],
        ["Open T1 targets", *metric(
            sc["t1_targets_open"], "", None,
            "Cited by engines, no link to you - the working list",
            "Needs both citation and backlink data: the tier is defined by the "
            "absence of a link, so it cannot be verified without your link profile")],
        ["Quick-win topics", *metric(
            sc["quick_win_topics"], "", None,
            "Winnability >= 65, 0-90 day horizon",
            "No topics could be scored")],
        ["Prompts with no mention", *metric(
            sc["prompts_absent"], "", None,
            "Where the brand is invisible today",
            "No citation data supplied")],
    ]))

    # ---------------------------------------------------------------- 1
    w("\n## 1. Where you stand\n")
    w("### Answer-engine visibility\n")
    w(table(["Engine", "Prompts tracked", "Prompts naming brand", "Answer share",
             "Citations seen", "Own-domain citations", "Citation share"],
            [[e, fmt(d["prompts_tracked"]), fmt(d["prompts_with_brand"]),
              fmt(d["answer_share_pct"], "%"), fmt(d["citations_observed"]),
              fmt(d["own_domain_citations"]), fmt(d["citation_share_pct"], "%")]
             for e, d in sorted(vis.get("per_engine", {}).items())]))

    if vis.get("total_prompts_tracked"):
        w(f"\nBrand appears in at least one engine on **{fmt(vis.get('answer_share_pct'), '%')}** "
          f"of tracked prompts, and in every engine on **{fmt(vis.get('full_coverage_pct'), '%')}**. "
          f"The spread between those two numbers is engine-specific work, not a category "
          f"problem.\n")
    else:
        w("\n_No citation data was supplied, so answer-engine visibility is unmeasured. "
          "Instrumenting it is the first recommendation in this document - without it, "
          "every GEO claim below would be conjecture._\n")

    if vis.get("sentiment_mix"):
        w("\n**Sentiment of brand mentions:** " +
          ", ".join(f"{k} ({v})" for k, v in sorted(vis["sentiment_mix"].items(),
                                                    key=lambda x: -x[1])) + "\n")

    if vis.get("top_rival_brands"):
        w("\n**Brands the engines name most often in your prompt set:**\n")
        w(table(["Brand", "Mentions"],
                [[n, fmt(c)] for n, c in vis["top_rival_brands"][:10]]))

    w("\n### Authority position\n")
    w(table(["Domain", "DR", "Referring domains", "Organic traffic", "Keywords", "AI answer share"],
            [[("**" + r["domain"] + "** (you)") if r["domain"] == domain else r["domain"],
              fmt(r.get("domain_rating")), fmt(r.get("referring_domains")),
              fmt(r.get("organic_traffic")), fmt(r.get("organic_keywords")),
              fmt(r.get("ai_answer_share"), "%")]
             for r in auth.get("table", [])[:15]]))

    w("\n### Backlink profile\n")
    w(table(["Measure", "Value"], [
        ["Referring domains", fmt(blp.get("referring_domains"))],
        ["Total links", fmt(blp.get("total_links"))],
        ["Dofollow domains", f"{fmt(blp.get('dofollow_domains'))} ({fmt(blp.get('dofollow_pct'), '%')})"],
        ["Median referring DR", fmt(blp.get("median_dr"))],
        ["DR 60+ domains", fmt(blp.get("high_authority_domains"))],
        ["Branded anchor share", fmt(blp.get("branded_anchor_pct"), "%")],
    ]))
    if blp.get("dr_bands"):
        w("\n**Authority distribution:** " +
          ", ".join(f"{k}: {v}" for k, v in sorted(blp["dr_bands"].items(), reverse=True)) + "\n")

    w("\n" + SLOT.format(
        "Two or three sentences interpreting the three tables together. The useful "
        "reading is usually the mismatch: strong DR but low answer share means a "
        "retrieval/formatting problem, not an authority problem; the reverse means "
        "you are being cited on borrowed authority and it will not hold.") + "\n")

    # ---------------------------------------------------------------- 2
    w("\n## 2. The citation-source graph\n")
    if not src.get("total_cited_domains"):
        w("_No citation data was supplied, so the source graph - the join this document "
          "is built on - could not be computed. Sections 3 to 5 below fall back to the "
          "backlink and competitor data alone, and section 6 is driven by search demand "
          "rather than by prompts._\n")
    elif sc.get("citation_graph_capture_pct") is None:
        w(f"Answer engines pulled from **{fmt(src.get('total_cited_domains'))}** distinct "
          f"third-party domains across this prompt set. Without backlink data we cannot "
          f"tell which of them already link to you, so the capture rate is unmeasured and "
          f"the tiers below rank on citation evidence alone.\n")
    else:
        w(f"Answer engines pulled from **{fmt(src.get('total_cited_domains'))}** distinct "
          f"third-party domains across this prompt set. "
          f"**{fmt(src.get('cited_and_linking'))}** of them already link to you "
          f"({fmt(src.get('citation_gap_capture_pct'), '%')} capture); "
          f"**{fmt(src.get('cited_not_linking'))}** do not.\n")
    w("\nThat second number is the core of this document. Each of those domains is a "
      "place where one placement does two jobs at once: it earns a link, and it puts "
      "you inside the text the engines are already reading when someone asks about "
      "your category.\n")

    if src.get("archetype_mix"):
        w("\n**What kind of sources the engines trust here:**\n")
        total = sum(src["archetype_mix"].values()) or 1
        w(table(["Source type", "Domains", "Share"],
                [[k, fmt(v), f"{round(100*v/total)}%"]
                 for k, v in sorted(src["archetype_mix"].items(), key=lambda x: -x[1])]))
        w("\n" + SLOT.format(
            "One or two sentences. The mix dictates the motion: review-platform-heavy "
            "means a customer-proof programme, news-heavy means a PR programme, "
            "community-heavy means presence work. Say which this is.") + "\n")

    w("\n### Top cited domains\n")
    w(table(["#", "Domain", "Type", "Prompts", "Engines", "DR", "Links to you?", "Score"],
            [[i, t["domain"], t["archetype_label"], fmt(t["prompts_cited"]),
              fmt(t["engine_count"]), dr_cell(t),
              "yes" if t["links_to_us"] else "**no**", fmt(t["target_score"])]
             for i, t in enumerate(src.get("targets", [])[:25], 1)]))

    # ---------------------------------------------------------------- 3
    w("\n## 3. Tactical outreach plan\n")
    w("Targets are tiered by the motion they need, not only by score. Work T1 to "
      "exhaustion before starting T3: a domain the engines already quote is worth "
      "several times a cold high-DR domain that has never appeared in an answer.\n")
    if src.get("total_cited_domains") and sc.get("citation_graph_capture_pct") is None:
        w("\n**Caveat.** No backlink data was supplied, so every domain below appears "
          "unlinked and the tiers are unverified - some of these almost certainly link "
          "to you already. Check each against your own link profile before pitching; a "
          "cold pitch to an existing partner damages the relationship.\n")

    tiers = [
        ("T1", "Citation gap - highest leverage",
         "Engines cite them for your prompts and they do not link to you. Every "
         "placement here is a link plus a retrieval-corpus insertion."),
        ("T2", "Competitive displacement",
         "They cover your rivals and not you. The relationship is proven reachable "
         "for a brand at your level; you simply are not in the piece yet."),
        ("T3", "Authority build",
         "In the graph, no relationship. Slower, warmer, usually a PR or partnership "
         "motion rather than an outreach email."),
    ]
    for tier, label, why in tiers:
        rows = [t for t in src.get("targets", []) if t.get("tier") == tier]
        w(f"\n### {tier}: {label} ({len(rows)} domains)\n")
        w(f"{why}\n\n")
        w(table(["Domain", "Type", "Prompts cited", "DR", "Covers rivals",
                 "Score", "Angle", "Owner", "Target date"],
                [[t["domain"], t["archetype_label"], fmt(t["prompts_cited"]),
                  dr_cell(t),
                  ", ".join(t["links_to_competitors"][:3]) or "-",
                  fmt(t["target_score"]), "_TBD_", "_TBD_", "_TBD_"]
                 for t in rows[:20]]))
        if rows:
            w("\n" + SLOT.format(
                f"Fill the Angle column for each {tier} row: the specific reason this "
                "outlet would want the piece, tied to the prompt that surfaced them and "
                "to something you can actually supply (data, a customer, an expert). "
                "Generic 'guest post' entries are worse than blank - they get ignored "
                "and they burn the relationship. Assign an owner and a date.") + "\n")

    if src.get("pure_link_gap"):
        w("\n### Link gap (SEO-only, no AI citation observed)\n")
        w("These never appeared in an answer but link to two or more rivals. Work them "
          "after T1-T2; they build authority without moving answer share directly.\n\n")
        w(table(["Domain", "Type", "DR", "Rivals linked"],
                [[g["domain"], g["archetype_label"], fmt(g["domain_rating"]),
                  ", ".join(g["competitors_linked"][:4])]
                 for g in src["pure_link_gap"][:15]]))

    w("\n### Outreach sequencing\n")
    w(SLOT.format(
        "Lay out the first 30 days concretely: how many targets per week, who sends, "
        "what the follow-up cadence is, and what asset each tier needs before "
        "outreach starts. An outreach plan without a linkable asset behind it fails "
        "on reply rate, so name the asset.") + "\n")

    # ---------------------------------------------------------------- 4
    w("\n## 4. PR and earned media\n")
    news = [t for t in src.get("targets", [])
            if t.get("archetype") in ("tier1_news", "editorial") and not t["links_to_us"]]
    w(f"{len(news)} news or editorial domains in the citation graph have no link to you.\n\n")
    w(table(["Publication", "Prompts cited", "DR", "Engines"],
            [[t["domain"], fmt(t["prompts_cited"]), dr_cell(t),
              ", ".join(t["engines"][:3])] for t in news[:15]]))
    w("\n### Process changes\n")
    w(SLOT.format(
        "Recommend changes to how PR is run, not just campaigns to run. Ground each "
        "one in this dataset. See references/pr-partnerships.md for the standard "
        "levers - reactive commentary, proprietary data studies, expert bylines, "
        "entity consistency, release discipline - and pick the two or three that this "
        "brand's gaps actually call for. Say what stops, not only what starts.") + "\n")
    w("\n### Campaign concepts\n")
    w(SLOT.format(
        "Two or three concrete campaigns with a hook, the data or asset behind them, "
        "the target publications drawn from the table above, and a rough timeline. A "
        "concept that could run for any brand in any category is not a concept.") + "\n")

    # ---------------------------------------------------------------- 5
    w("\n## 5. Marketing partnerships\n")
    for key, heading, note in [
        ("review_platform", "Review platforms",
         "Heavily quoted by answer engines for commercial and comparison prompts. "
         "Movement here needs a customer-proof motion, not outreach."),
        ("database", "Databases and directories",
         "Structured, frequently crawled, and cheap to correct. Low glamour, fast payback."),
        ("encyclopedia", "Entity records",
         "Governs whether engines treat the brand as a known entity at all."),
        ("community", "Communities",
         "Disclosure rules matter; participate as a named expert, never astroturf."),
    ]:
        rows = [t for t in src.get("targets", []) if t.get("archetype") == key]
        if not rows:
            continue
        w(f"\n### {heading}\n{note}\n\n")
        w(table(["Domain", "Prompts cited", "Present?", "DR"],
                [[t["domain"], fmt(t["prompts_cited"]),
                  "yes" if t["links_to_us"] else "**no**", dr_cell(t)]
                 for t in rows[:10]]))

    w("\n### Partnership and co-marketing plays\n")
    w(SLOT.format(
        "Name specific partners or partner types and what each side gets. Cover "
        "listicle inclusion, integration/marketplace pages, joint research, and "
        "association membership where relevant. See references/pr-partnerships.md.") + "\n")

    w("\n### Awards programme\n")
    w(SLOT.format(
        "Build a dated entry calendar from references/pr-partnerships.md, filtered to "
        "this brand's category and stage. Note entry fee, deadline, and which prompt "
        "or topic a win would help. Awards earn a high-DR dofollow link and feed the "
        "'award-winning X' and 'best X' prompt classes, which is why they belong in a "
        "GEO plan rather than only a brand plan.") + "\n")

    # ---------------------------------------------------------------- 6
    w("\n## 6. Content roadmap\n")
    w(f"{fmt(topics.get('total_candidates'))} candidate topics scored on winnability "
      "(foothold, authority fit, contest, answer-format fit, difficulty) and ordered "
      "by priority, which weights winnability by commercial value.\n")

    hz = [("H1", "Horizon 1 - quick wins (0-90 days)",
           "Winnability >= 65. You have a foothold, the field is thin, or the format "
           "is one engines quote readily. Ship these first and the scorecard moves "
           "inside a quarter."),
          ("H2", "Horizon 2 - build (90-180 days)",
           "Winnable with a real asset behind it, usually needing links or depth."),
          ("H3", "Horizon 3 - authority build (180-365+ days)",
           "Out of reach at current authority. Sequenced after sections 3-5 raise the "
           "ceiling; starting here wastes a quarter.")]
    for key, heading, why in hz:
        rows = topics.get("horizons", {}).get(key, [])
        w(f"\n### {heading} - {len(rows)} topics\n{why}\n\n")
        w(table(["#", "Topic", "Source", "Win", "Priority", "Answer format",
                 "Current position", "Asset"],
                [[t["rank"], t["topic"],
                  "AI prompt" if t["source"] == "ai_prompt" else "Search gap",
                  fmt(t["winnability"]), fmt(t["priority"]), t["answer_format"],
                  t["foothold_note"], "_TBD_"]
                 for t in rows[:20]]))
        if rows:
            w("\n" + SLOT.format(
                f"For the top {min(8, len(rows))} {key} rows, fill the Asset column with the "
                "specific page or update to produce, and add a one-line brief below: the "
                "direct answer the page must state in its first 60 words, the format "
                "(table, ranked list, definition block), and the internal links it needs. "
                "The 40-60 word direct answer is what gets lifted into an AI response, so "
                "it is the part to get right.") + "\n")

    if vis.get("uncontested_prompts"):
        w("\n### Uncontested prompts\n")
        w("No competitor named, few sources cited. The engines are answering from thin "
          "ground, so a single well-formatted page can take the answer outright.\n\n")
        w(table(["Prompt", "Distinct sources", "Engines"],
                [[u["prompt"], fmt(u["distinct_sources"]), ", ".join(u["engines"])]
                 for u in vis["uncontested_prompts"][:15]]))

    # ---------------------------------------------------------------- 7
    w("\n## 7. 90-day plan and measurement\n")
    w(SLOT.format(
        "A month-by-month table: workstream, specific action drawn from sections 3-6, "
        "owner, and the metric it moves. Keep it to what this team can actually "
        "absorb - a plan with forty actions is a plan with none. Then set baselines "
        "and targets from the scorecard, and state the re-measurement cadence "
        "(monthly for answer share, quarterly for authority).") + "\n")

    # ---------------------------------------------------------------- 8
    w("\n## 8. Methodology and data coverage\n")
    cov = a.get("data_coverage", {})
    w("\n**Rows ingested:**\n\n")
    w(table(["Dataset", "Rows"],
            [[k, fmt(v)] for k, v in (cov.get("counts") or {}).items()]))
    w("\n**Files processed:**\n\n")
    w(table(["File", "Mapped to", "Rows"],
            [[m["file"], m.get("dataset") or "UNCLASSIFIED", fmt(m.get("rows"))]
             for m in (cov.get("manifest") or [])]))
    if cov.get("warnings"):
        w("\n**Coverage limitations.** These bound what the document can claim:\n\n")
        w(bullets(cov["warnings"]))
    meth = a.get("methodology", {})
    w("\n**Scoring weights.** Target score: " +
      ", ".join(f"{k} {v}" for k, v in meth.get("target_weights", {}).items()) + ".\n")
    w("\nWinnability: " +
      ", ".join(f"{k} {v}" for k, v in meth.get("winnability_weights", {}).items()) + ".\n")
    w("\nHorizon thresholds: " +
      ", ".join(f"{k} {v}" for k, v in meth.get("horizon_thresholds", {}).items()) + ".\n")
    if src.get("domains_missing_dr"):
        w(f"\n**Estimated authority.** {src['domains_missing_dr']} of "
          f"{src.get('total_cited_domains')} cited domains had no domain rating in the "
          f"supplied data. Those are scored at the median of the domains that did "
          f"(DR {fmt(src.get('dr_fallback_used'))}) and shown as `~N est` in the tables "
          f"above. The median is used rather than a low default so that a missing value "
          f"stays neutral instead of pushing a domain up or down the ranking. Supplying "
          f"authority figures for them would sharpen the order.\n")
    w(f"\n**Citation frequency scale.** A domain cited on "
      f"{fmt(src.get('citation_saturation_point'))} or more prompts scores the maximum "
      f"on that component; the point is set at the 90th percentile of what was observed "
      f"here, so it adapts to this dataset rather than to a fixed threshold.\n")
    w("\nScores rank opportunities against each other within this dataset. They are "
      "not absolute measures and are not comparable across brands or across export "
      "dates.\n")

    return "\n".join(b)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="./build/analysis.json")
    ap.add_argument("--out", default="./build/report-draft.md")
    args = ap.parse_args()

    with open(args.inp, encoding="utf-8") as fh:
        analysis = json.load(fh)
    md = render(analysis)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(md)

    slots = md.count("<!-- ANALYST:")
    print(f"Draft -> {args.out}")
    print(f"{len(md.splitlines())} lines, {slots} analyst slots to fill.")
    print("Replace every <!-- ANALYST: ... --> marker and every _TBD_ cell before delivery.")


if __name__ == "__main__":
    main()
