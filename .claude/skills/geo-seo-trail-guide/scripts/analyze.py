#!/usr/bin/env python3
"""Score a normalized GEO/SEO payload into a ranked opportunity set.

The central move here is a join that neither an SEO tool nor a GEO tool makes
on its own: take the domains that answer engines actually cite for your prompt
set, and subtract the domains that already link to you. What is left is the
list of places where a single placement both earns a backlink and inserts you
into the retrieval corpus the engines are reading. Almost every recommendation
in the final document traces back to that join.

Everything in here is deterministic arithmetic. Judgment -- which pitch to
send, which award to enter, how to sequence a quarter -- belongs to the analyst
reading the output, not to this file.

Usage:
    python3 analyze.py --in ./build/normalized.json --out ./build/analysis.json
"""

import argparse
import json
import math
import os
import re
import statistics as stats
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# Tunable weights. Exposed here (rather than buried inline) because the right
# balance shifts by vertical: a regulated industry leans harder on authority,
# a fast-moving consumer category leans harder on foothold and freshness.
# --------------------------------------------------------------------------

TARGET_WEIGHTS = {
    "citation_frequency": 0.32,   # how often engines already pull from this domain
    "engine_breadth": 0.14,       # cited across many engines = durable, not a quirk
    "authority": 0.18,            # DR still governs link equity passed
    "attainability": 0.20,        # a target you cannot realistically land is worth 0
    "competitive_proof": 0.16,    # it covers your rivals, so it will cover you
}

WINNABILITY_WEIGHTS = {
    "foothold": 0.28,       # nudging position 8 to 3 beats building from nothing
    "authority_fit": 0.24,  # can a domain your size hold this ground at all
    "contest": 0.18,        # fewer incumbents = more room
    "format_fit": 0.16,     # list/comparison/definition shapes are what LLMs quote
    "ease": 0.14,           # inverse difficulty
}

# Query shapes that answer engines quote most readily, because each maps to a
# chunk an LLM can lift whole: a ranked list, a head-to-head, a definition.
FORMAT_PATTERNS = [
    (r"\b(best|top|leading)\b", 1.00, "ranked list"),
    (r"\b(vs\.?|versus|compared? to|comparison)\b", 0.95, "head-to-head comparison"),
    (r"\balternatives?\b", 0.95, "alternatives list"),
    (r"\b(what is|what are|define|definition|meaning of)\b", 0.85, "definition"),
    (r"\bhow (to|do|does|can)\b", 0.80, "how-to"),
    (r"\b(pricing|cost|price|how much)\b", 0.80, "pricing explainer"),
    (r"\b(template|checklist|example|examples|framework)\b", 0.75, "template/example"),
    (r"\b(guide|tutorial|walkthrough)\b", 0.65, "guide"),
    (r"\b(review|reviews|rating)\b", 0.65, "review"),
    (r"\b(statistics|stats|benchmark|report|trends|data)\b", 0.70, "data/benchmark"),
    (r"\bfor (small|enterprise|startups?|teams?|agencies)\b", 0.70, "segment fit"),
]

# Source archetypes drive routing: an outreach email works on a blog, but a
# review platform needs a customer-proof motion and a news desk needs a story.
SOURCE_ARCHETYPES = [
    (r"(g2|capterra|trustradius|trustpilot|getapp|softwareadvice|gartner|peerinsights|sourceforge|producthunt)",
     "review_platform", "Review platform"),
    (r"(wikipedia|wikidata|wikimedia)", "encyclopedia", "Encyclopedia / entity record"),
    (r"(reddit|quora|stackexchange|stackoverflow|news\.ycombinator|discourse)",
     "community", "Community / forum"),
    (r"(youtube|vimeo|tiktok)", "video", "Video platform"),
    (r"(linkedin|medium|substack)", "publishing", "Owned-adjacent publishing"),
    (r"(forbes|techcrunch|wired|reuters|bloomberg|wsj|nytimes|cnbc|businessinsider|guardian|ft\.com|axios|theverge|venturebeat|fastcompany|inc\.com|entrepreneur)",
     "tier1_news", "Tier-1 news / business press"),
    (r"(gov|\.gov$|\.gov\.|edu$|\.edu\.|ac\.uk)", "institutional", "Government / academic"),
    (r"(crunchbase|pitchbook|owler|zoominfo|clutch|goodfirms)", "database", "Company database"),
    (r"(award|webby|effie|shorty|anthem|stevie)", "awards", "Awards body"),
]


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def norm(value, lo, hi):
    """Scale into 0-1, tolerating a degenerate range."""
    if value is None:
        return None
    if hi is None or lo is None or hi <= lo:
        return 0.5
    return clamp((value - lo) / (hi - lo))


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def median_of(vals):
    vals = [v for v in vals if v is not None]
    return stats.median(vals) if vals else None


def archetype(domain):
    d = (domain or "").lower()
    for pattern, key, label in SOURCE_ARCHETYPES:
        if re.search(pattern, d):
            return key, label
    return "editorial", "Editorial / blog / trade"


def format_fit(text):
    """Best-matching answer shape for a query, with its score."""
    t = (text or "").lower()
    best, label = 0.35, "informational"   # floor: every query has some shape
    for pattern, score, name in FORMAT_PATTERNS:
        if re.search(pattern, t) and score > best:
            best, label = score, name
    return best, label


# --------------------------------------------------------------------------
# Visibility diagnostic
# --------------------------------------------------------------------------

def analyze_visibility(citations, brand_domain):
    """How visible is the brand across the tracked prompt set, per engine."""
    prompts = defaultdict(lambda: {"engines": set(), "mentioned_in": set(),
                                   "competitors": Counter(), "domains": set(),
                                   "sentiments": [], "positions": []})
    engines = set()

    for c in citations:
        p = c["prompt"] or "(unattributed citation)"
        rec = prompts[p]
        eng = c["engine"]
        engines.add(eng)
        rec["engines"].add(eng)
        if c["brand_mentioned"]:
            rec["mentioned_in"].add(eng)
            if c["brand_position"] is not None:
                rec["positions"].append(c["brand_position"])
        if c["cited_domain"]:
            rec["domains"].add(c["cited_domain"])
        for comp in c["competitors_mentioned"]:
            rec["competitors"][comp] += 1
        if c["sentiment"]:
            rec["sentiments"].append(c["sentiment"])

    total_prompts = len(prompts)
    engines = sorted(engines)

    per_engine = {}
    for eng in engines:
        seen = [p for p, r in prompts.items() if eng in r["engines"]]
        won = [p for p in seen if eng in prompts[p]["mentioned_in"]]
        cited_rows = [c for c in citations
                      if c["engine"] == eng and c["cited_domain"]]
        own_cites = [c for c in cited_rows if c["cited_domain"] == brand_domain]
        per_engine[eng] = {
            "prompts_tracked": len(seen),
            "prompts_with_brand": len(won),
            "answer_share_pct": pct(len(won), len(seen)),
            "citations_observed": len(cited_rows),
            "own_domain_citations": len(own_cites),
            "citation_share_pct": pct(len(own_cites), len(cited_rows)),
        }

    mentioned_any = [p for p, r in prompts.items() if r["mentioned_in"]]
    mentioned_all = [p for p, r in prompts.items()
                     if r["mentioned_in"] and r["mentioned_in"] >= r["engines"]]
    absent = [p for p, r in prompts.items() if not r["mentioned_in"]]

    sentiments = Counter(s for r in prompts.values() for s in r["sentiments"])
    rival = Counter()
    for r in prompts.values():
        for comp, n in r["competitors"].items():
            rival[comp] += n

    # Prompts where engines cite thin ground: few distinct sources and no
    # competitor named. Nobody owns the answer, so it is cheap to take.
    uncontested = []
    for p, r in prompts.items():
        if r["mentioned_in"]:
            continue
        if len(r["competitors"]) == 0 and len(r["domains"]) <= 3:
            uncontested.append({"prompt": p,
                                "distinct_sources": len(r["domains"]),
                                "engines": sorted(r["engines"])})

    return {
        "total_prompts_tracked": total_prompts,
        "engines_tracked": engines,
        "answer_share_pct": pct(len(mentioned_any), total_prompts),
        "full_coverage_pct": pct(len(mentioned_all), total_prompts),
        "prompts_absent": len(absent),
        "per_engine": per_engine,
        "sentiment_mix": dict(sentiments),
        "top_rival_brands": rival.most_common(12),
        "uncontested_prompts": sorted(uncontested,
                                      key=lambda x: x["distinct_sources"])[:25],
        "_prompt_index": {p: {"engines": sorted(r["engines"]),
                              "mentioned_in": sorted(r["mentioned_in"]),
                              "competitor_count": len(r["competitors"]),
                              "competitors": [c for c, _ in r["competitors"].most_common(6)],
                              "source_count": len(r["domains"]),
                              "avg_position": (round(sum(r["positions"]) / len(r["positions"]), 1)
                                               if r["positions"] else None)}
                          for p, r in prompts.items()},
    }


# --------------------------------------------------------------------------
# Citation source graph, and the join against the backlink profile
# --------------------------------------------------------------------------

def analyze_source_graph(citations, backlinks, brand_domain, brand_dr, dr_lookup):
    """Rank the domains engines cite, and flag which of them ignore you."""
    linked = {b["referring_domain"] for b in backlinks
              if b["referring_domain"] and
              (not b.get("target_url") or _host(b["target_url"]) in (None, brand_domain))}
    all_linking = {b["referring_domain"] for b in backlinks if b["referring_domain"]}

    # Competitor link intersect, when the export carries competitor targets.
    comp_links = defaultdict(set)
    for b in backlinks:
        host = _host(b.get("target_url"))
        if host and brand_domain and host != brand_domain:
            comp_links[b["referring_domain"]].add(host)

    src = defaultdict(lambda: {"prompts": set(), "engines": set(), "urls": Counter(),
                               "dr": None, "with_competitor": 0})
    all_prompts = set()
    for c in citations:
        if c["prompt"]:
            all_prompts.add(c["prompt"])
        d = c["cited_domain"]
        if not d or d == brand_domain:
            continue
        rec = src[d]
        if c["prompt"]:
            rec["prompts"].add(c["prompt"])
        rec["engines"].add(c["engine"])
        if c["cited_url"]:
            rec["urls"][c["cited_url"]] += 1
        if c["competitors_mentioned"]:
            rec["with_competitor"] += 1

    total_prompts = max(1, len(all_prompts))
    total_engines = max(1, len({c["engine"] for c in citations}))

    # Saturation point for citation frequency. A fixed fraction of the prompt
    # set collapses the top of the ranking whenever a category has many
    # frequently-cited domains, so anchor to the observed distribution instead:
    # the 90th percentile means roughly the top tenth of domains max out and
    # everything below stays separable, whatever the dataset's shape.
    observed = sorted(len(r["prompts"]) for r in src.values()) or [1]
    p90 = observed[min(len(observed) - 1, int(0.9 * len(observed)))]
    saturation = max(3.0, float(p90))

    # An unknown DR must not outrank a known one. Estimating from the median of
    # the domains we do have keeps a missing value neutral rather than making it
    # an advantage, which a flat low default would.
    known_drs = [dr_lookup[d] for d in src if d in dr_lookup]
    dr_fallback = stats.median(known_drs) if known_drs else 45.0

    graph = []
    for domain, rec in src.items():
        dr = dr_lookup.get(domain)
        dr_estimated = dr is None
        dr_used = dr if dr is not None else dr_fallback
        freq = clamp(len(rec["prompts"]) / saturation)
        breadth = clamp(len(rec["engines"]) / total_engines)
        auth = clamp(dr_used / 100.0)
        gap = dr_used - (brand_dr if brand_dr is not None else 30.0)
        attain = clamp(1.0 - (gap / 60.0)) if gap > 0 else 1.0
        proof = clamp(rec["with_competitor"] / max(1, len(rec["prompts"]))) \
            if rec["prompts"] else 0.0
        if domain in comp_links:
            proof = max(proof, clamp(len(comp_links[domain]) / 3.0))

        score = 100.0 * (
            TARGET_WEIGHTS["citation_frequency"] * freq +
            TARGET_WEIGHTS["engine_breadth"] * breadth +
            TARGET_WEIGHTS["authority"] * auth +
            TARGET_WEIGHTS["attainability"] * attain +
            TARGET_WEIGHTS["competitive_proof"] * proof
        )

        key, label = archetype(domain)
        has_link = domain in linked
        graph.append({
            "domain": domain,
            "prompts_cited": len(rec["prompts"]),
            "prompt_coverage_pct": pct(len(rec["prompts"]), total_prompts),
            "engines": sorted(rec["engines"]),
            "engine_count": len(rec["engines"]),
            "domain_rating": dr,
            "domain_rating_estimated": dr_estimated,
            "domain_rating_used": round(dr_used, 1),
            "links_to_us": has_link,
            "links_to_competitors": sorted(comp_links.get(domain, [])),
            "co_cited_with_competitor": rec["with_competitor"],
            "archetype": key,
            "archetype_label": label,
            "top_cited_url": rec["urls"].most_common(1)[0][0] if rec["urls"] else None,
            "target_score": round(score, 1),
            "components": {"citation_frequency": round(freq, 3),
                           "engine_breadth": round(breadth, 3),
                           "authority": round(auth, 3),
                           "attainability": round(attain, 3),
                           "competitive_proof": round(proof, 3)},
            "sample_prompts": sorted(rec["prompts"])[:4],
        })

    graph.sort(key=lambda x: -x["target_score"])

    # Tiering is about motion, not just score: each tier gets a different play.
    for row in graph:
        if not row["links_to_us"] and row["prompts_cited"] >= 2:
            row["tier"] = "T1"
            row["tier_label"] = "Citation gap - engines cite them, they ignore you"
        elif not row["links_to_us"] and row["links_to_competitors"]:
            row["tier"] = "T2"
            row["tier_label"] = "Competitive displacement - they cover rivals, not you"
        elif not row["links_to_us"]:
            row["tier"] = "T3"
            row["tier_label"] = "Authority build - in the graph, no relationship yet"
        else:
            row["tier"] = "HELD"
            row["tier_label"] = "Already linking - defend and deepen"

    # Pure link-gap targets: never cited in an AI answer, but they cover two or
    # more rivals. Classic SEO gap, still worth working after the T1 list.
    link_gap = []
    cited_domains = set(src)
    for domain, comps in comp_links.items():
        if domain in linked or domain in cited_domains or len(comps) < 2:
            continue
        dr = dr_lookup.get(domain)
        link_gap.append({"domain": domain, "domain_rating": dr,
                         "competitors_linked": sorted(comps),
                         "competitor_count": len(comps),
                         "archetype_label": archetype(domain)[1]})
    link_gap.sort(key=lambda x: (-x["competitor_count"], -(x["domain_rating"] or 0)))

    held = [g for g in graph if g["tier"] == "HELD"]
    return {
        "citation_saturation_point": saturation,
        "dr_fallback_used": round(dr_fallback, 1),
        "domains_missing_dr": sum(1 for g in graph if g["domain_rating_estimated"]),
        "total_cited_domains": len(graph),
        "cited_and_linking": len(held),
        "cited_not_linking": len(graph) - len(held),
        "citation_gap_capture_pct": pct(len(held), len(graph)),
        "targets": graph,
        "tier_counts": Counter(g["tier"] for g in graph),
        "archetype_mix": Counter(g["archetype_label"] for g in graph),
        "pure_link_gap": link_gap[:40],
        "referring_domains_total": len(all_linking),
    }


def _host(url):
    if not url:
        return None
    s = re.sub(r"^https?://", "", str(url).strip().lower())
    s = re.sub(r"^www\.", "", s)
    return s.split("/")[0] or None


# --------------------------------------------------------------------------
# Authority position
# --------------------------------------------------------------------------

def analyze_authority(authority, competitors, visibility, brand_domain):
    rows = {r["domain"]: dict(r) for r in authority}
    for c in competitors:
        row = rows.setdefault(c["domain"], {"domain": c["domain"]})
        for k in ("domain_rating", "referring_domains", "organic_traffic",
                  "organic_keywords", "ai_answer_share"):
            if row.get(k) is None and c.get(k) is not None:
                row[k] = c[k]

    brand = rows.get(brand_domain, {})
    brand_dr = brand.get("domain_rating")
    rivals = [r for d, r in rows.items() if d != brand_domain]
    rival_drs = [r.get("domain_rating") for r in rivals if r.get("domain_rating") is not None]

    ranked = sorted(
        [r for r in rows.values() if r.get("domain_rating") is not None],
        key=lambda r: -r["domain_rating"])
    position = next((i + 1 for i, r in enumerate(ranked) if r["domain"] == brand_domain), None)

    leader = ranked[0] if ranked else None
    med = median_of(rival_drs)

    brand_rd = brand.get("referring_domains")
    rival_rds = [r.get("referring_domains") for r in rivals
                 if r.get("referring_domains") is not None]
    med_rd = median_of(rival_rds)

    return {
        "brand_domain": brand_domain,
        "brand_domain_rating": brand_dr,
        "brand_referring_domains": brand_rd,
        "brand_answer_share_pct": visibility.get("answer_share_pct"),
        "rank_by_dr": position,
        "field_size": len(ranked),
        "median_competitor_dr": med,
        "dr_gap_to_median": (round(brand_dr - med, 1)
                             if brand_dr is not None and med is not None else None),
        "dr_gap_to_leader": (round(brand_dr - leader["domain_rating"], 1)
                             if brand_dr is not None and leader else None),
        "leader": ({"domain": leader["domain"], "domain_rating": leader["domain_rating"]}
                   if leader else None),
        "median_competitor_referring_domains": med_rd,
        "referring_domain_gap_to_median": (round(brand_rd - med_rd)
                                           if brand_rd is not None and med_rd is not None else None),
        "table": sorted(rows.values(), key=lambda r: -(r.get("domain_rating") or 0)),
        "_dr_lookup": {d: r.get("domain_rating") for d, r in rows.items()
                       if r.get("domain_rating") is not None},
    }


def enrich_dr_lookup(dr_lookup, backlinks):
    """Backlink exports carry a domain rating for every referring domain.

    Those are the same domains that show up in the citation graph, so folding
    them in means attainability and authority score against real figures
    instead of collapsing to the DR 45 default. Authority-file values win on a
    conflict: they are the deliberate competitive set, not an incidental
    per-link reading.
    """
    seen = defaultdict(list)
    for b in backlinks:
        dom, dr = b.get("referring_domain"), b.get("domain_rating")
        if dom and dr is not None:
            seen[dom].append(dr)
    for dom, vals in seen.items():
        if dom not in dr_lookup:
            dr_lookup[dom] = stats.median(vals)
    return dr_lookup


# --------------------------------------------------------------------------
# Topic winnability
# --------------------------------------------------------------------------

def analyze_topics(content_gaps, visibility, authority, brand_domain):
    """Score every topic and prompt on how winnable it is, then bucket by horizon.

    Two sources feed one list: classic content-gap keyword rows, and prompts
    from the citation file where the brand is absent. They are scored on the
    same scale so a roadmap can sequence them together -- which is the point,
    since a single asset usually serves both a search query and a prompt.
    """
    brand_dr = authority.get("brand_domain_rating")
    med_dr = authority.get("median_competitor_dr")
    prompt_index = visibility.get("_prompt_index", {})

    volumes = [g["search_volume"] for g in content_gaps if g.get("search_volume")]
    vmax = max(volumes) if volumes else None
    vmin = min(volumes) if volumes else None
    cpcs = [g["cpc"] for g in content_gaps if g.get("cpc")]
    cmax = max(cpcs) if cpcs else None

    candidates = []

    for g in content_gaps:
        topic = g["topic"]
        rank = g.get("our_rank")
        if rank is None:
            foothold = 0.12
            foothold_note = "no ranking"
        elif rank <= 3:
            foothold = 0.55   # already won in search; the work is AEO formatting
            foothold_note = f"ranks #{int(rank)} - defend, optimise for citation"
        elif rank <= 10:
            foothold = 1.00
            foothold_note = f"ranks #{int(rank)} - striking distance"
        elif rank <= 20:
            foothold = 0.80
            foothold_note = f"ranks #{int(rank)} - page 2, upgrade the asset"
        elif rank <= 50:
            foothold = 0.45
            foothold_note = f"ranks #{int(rank)} - indexed but weak"
        else:
            foothold = 0.20
            foothold_note = f"ranks #{int(rank)} - effectively invisible"

        diff = g.get("difficulty")
        ease = clamp(1.0 - (diff / 100.0)) if diff is not None else 0.5

        # Sitewide DR sets a prior on whether a domain this size can hold the
        # ground. The slope is deliberately gentle: a challenger sitting 30-40 DR
        # below the category median is the normal case, not a disqualification.
        if brand_dr is not None and med_dr is not None:
            fit = clamp(0.5 + (brand_dr - med_dr) / 90.0, 0.10, 1.0)
        else:
            fit = 0.5
        if diff is not None and brand_dr is not None:
            # A keyword whose difficulty sits well above your DR is a build,
            # not a win, whatever the rest of the signals say.
            fit = clamp(fit * (1.0 - clamp((diff - brand_dr) / 80.0)), 0.10, 1.0)
        # An existing ranking is observed evidence, and it outranks both priors
        # above: if the page already sits at #4, the question of whether a domain
        # this size *could* rank there has been settled empirically.
        if rank is not None:
            if rank <= 10:
                fit = max(fit, 0.75)
            elif rank <= 20:
                fit = max(fit, 0.60)
            elif rank <= 50:
                fit = max(fit, 0.40)

        n_comp = g.get("competitors_ranking")
        contest = clamp(1.0 - ((n_comp - 1) / 8.0)) if n_comp else 0.5

        ff, fshape = format_fit(topic)

        vol_n = norm(g.get("search_volume"), vmin, vmax) if vmax else 0.4
        cpc_n = clamp((g.get("cpc") or 0) / cmax) if cmax else 0.0
        value = clamp(0.65 * (vol_n if vol_n is not None else 0.4) + 0.35 * cpc_n)

        candidates.append(_score_topic(
            topic=topic, source="content_gap",
            foothold=foothold, foothold_note=foothold_note, fit=fit,
            contest=contest, format_score=ff, format_shape=fshape, ease=ease,
            value=value,
            extra={"search_volume": g.get("search_volume"), "difficulty": diff,
                   "our_rank": rank, "intent": g.get("intent"),
                   "competitors_ranking": n_comp, "cpc": g.get("cpc"),
                   "has_ai_overview": g.get("has_ai_overview")}))

    gap_topics = {c["topic"].strip().lower() for c in candidates}

    for prompt, info in prompt_index.items():
        if prompt.strip().lower() in gap_topics or prompt.startswith("("):
            continue
        n_eng = len(info["engines"]) or 1
        n_won = len(info["mentioned_in"])
        if n_won == 0:
            foothold, note = 0.15, "absent from every engine"
        elif n_won < n_eng:
            foothold = 0.60 + 0.35 * (n_won / n_eng)
            note = f"cited in {n_won}/{n_eng} engines - extend the win"
        else:
            continue  # already held everywhere; not a gap

        ncomp = info["competitor_count"]
        contest = clamp(1.0 - ((ncomp - 1) / 8.0)) if ncomp else 0.85
        nsrc = info["source_count"]
        # Thin source sets mean the engines are scraping whatever they can find.
        thin = clamp(1.0 - (nsrc / 10.0))
        ff, fshape = format_fit(prompt)
        fit = (clamp(0.5 + (brand_dr - med_dr) / 90.0, 0.10, 1.0)
               if (brand_dr is not None and med_dr is not None) else 0.55)
        if n_won:
            # Already cited somewhere: the engines have accepted this domain as a
            # source for this question, so authority is demonstrably sufficient.
            fit = max(fit, 0.70)

        candidates.append(_score_topic(
            topic=prompt, source="ai_prompt",
            foothold=foothold, foothold_note=note, fit=fit,
            contest=max(contest, thin), format_score=ff, format_shape=fshape,
            ease=0.55 + 0.35 * thin, value=0.55 + 0.25 * thin,
            extra={"engines": info["engines"], "cited_in_engines": info["mentioned_in"],
                   "competitors_present": info["competitors"],
                   "distinct_sources": nsrc}))

    candidates.sort(key=lambda c: -c["priority"])
    for i, c in enumerate(candidates, 1):
        c["rank"] = i

    horizons = {"H1": [], "H2": [], "H3": []}
    for c in candidates:
        horizons[c["horizon"]].append(c)

    return {
        "total_candidates": len(candidates),
        "horizon_counts": {k: len(v) for k, v in horizons.items()},
        "topics": candidates,
        "horizons": horizons,
    }


def _score_topic(topic, source, foothold, foothold_note, fit, contest,
                 format_score, format_shape, ease, value, extra):
    w = WINNABILITY_WEIGHTS
    winnability = 100.0 * (
        w["foothold"] * foothold + w["authority_fit"] * fit +
        w["contest"] * contest + w["format_fit"] * format_score + w["ease"] * ease
    )
    # Value modulates rather than gates: a highly winnable low-volume topic is
    # still worth shipping, it just should not outrank a winnable big one.
    priority = winnability * (0.55 + 0.45 * value)

    if winnability >= 65:
        horizon, hl, window = "H1", "Quick win", "0-90 days"
    elif winnability >= 42:
        horizon, hl, window = "H2", "Build", "90-180 days"
    else:
        horizon, hl, window = "H3", "Authority build", "180-365+ days"

    row = {
        "topic": topic, "source": source,
        "winnability": round(winnability, 1),
        "priority": round(priority, 1),
        "horizon": horizon, "horizon_label": hl, "window": window,
        "answer_format": format_shape,
        "foothold_note": foothold_note,
        "components": {"foothold": round(foothold, 3), "authority_fit": round(fit, 3),
                       "contest": round(contest, 3), "format_fit": round(format_score, 3),
                       "ease": round(ease, 3), "value": round(value, 3)},
    }
    row.update({k: v for k, v in extra.items() if v is not None})
    return row


# --------------------------------------------------------------------------
# Backlink profile health
# --------------------------------------------------------------------------

def analyze_backlink_profile(backlinks, brand_domain):
    own = [b for b in backlinks
           if not b.get("target_url") or _host(b["target_url"]) in (None, brand_domain)]
    domains = {}
    for b in own:
        d = b["referring_domain"]
        cur = domains.setdefault(d, {"dr": b.get("domain_rating"), "dofollow": False,
                                     "links": 0, "anchors": Counter()})
        cur["links"] += 1
        if b.get("dofollow"):
            cur["dofollow"] = True
        if cur["dr"] is None:
            cur["dr"] = b.get("domain_rating")
        if b.get("anchor"):
            cur["anchors"][b["anchor"]] += 1

    drs = [v["dr"] for v in domains.values() if v["dr"] is not None]
    bands = Counter()
    for dr in drs:
        if dr >= 80:
            bands["DR 80+"] += 1
        elif dr >= 60:
            bands["DR 60-79"] += 1
        elif dr >= 40:
            bands["DR 40-59"] += 1
        elif dr >= 20:
            bands["DR 20-39"] += 1
        else:
            bands["DR 0-19"] += 1

    anchors = Counter()
    for v in domains.values():
        for a, n in v["anchors"].items():
            anchors[a] += n
    total_anchor = sum(anchors.values())
    branded = sum(n for a, n in anchors.items()
                  if brand_domain and brand_domain.split(".")[0] in a.lower())

    follow = sum(1 for v in domains.values() if v["dofollow"])
    return {
        "referring_domains": len(domains),
        "total_links": len(own),
        "dofollow_domains": follow,
        "dofollow_pct": pct(follow, len(domains)),
        "median_dr": median_of(drs),
        "dr_bands": dict(bands),
        "high_authority_domains": sum(1 for d in drs if d >= 60),
        "top_anchors": anchors.most_common(15),
        "branded_anchor_pct": pct(branded, total_anchor),
    }


# --------------------------------------------------------------------------

def build_scorecard(vis, src, auth, blp, topics, has_citations, has_backlinks):
    """A handful of numbers the reader should be able to recite from memory.

    A metric with no data behind it is reported as unmeasured, never as zero. A
    0% with an F next to it reads as a finding, and the reader will act on it;
    "no data" prompts them to go and get some, which is the honest next step.
    """
    def grade(v, bands):
        if v is None:
            return None
        for threshold, letter in bands:
            if v >= threshold:
                return letter
        return "F"

    answer_share = vis.get("answer_share_pct") if has_citations else None
    # Capture is only meaningful when both sides of the join are present:
    # without backlinks we cannot tell a domain that ignores us from one we
    # simply have no link record for.
    capture = (src.get("citation_gap_capture_pct")
               if (has_citations and has_backlinks) else None)
    return {
        "ai_answer_share_pct": answer_share,
        "ai_answer_share_grade": grade(answer_share, [(60, "A"), (40, "B"), (25, "C"), (10, "D")]),
        "citation_graph_capture_pct": capture,
        "citation_graph_capture_grade": grade(capture, [(50, "A"), (30, "B"), (15, "C"), (5, "D")]),
        "authority_rank": f"{auth.get('rank_by_dr')} of {auth.get('field_size')}"
                          if auth.get("rank_by_dr") else None,
        "dr_gap_to_median": auth.get("dr_gap_to_median"),
        "referring_domains": blp.get("referring_domains") if has_backlinks else None,
        "referring_domain_gap_to_median": auth.get("referring_domain_gap_to_median"),
        # T1 means "cited AND not linking to us". With no backlink data every
        # domain looks unlinked, so the count would be an artefact of the gap.
        "t1_targets_open": (src["tier_counts"].get("T1", 0)
                            if (has_citations and has_backlinks) else None),
        "quick_win_topics": topics["horizon_counts"].get("H1", 0),
        "prompts_absent": vis.get("prompts_absent") if has_citations else None,
    }


def coverage_warnings(payload, vis, src, auth):
    """Name what is missing. A recommendation built on absent data is a guess,
    and the reader deserves to know which is which."""
    warn = []
    counts = payload.get("counts", {})
    has_citations = bool(counts.get("citations"))
    if not has_citations:
        warn.append("No citation data: every GEO/AEO finding is unsupported. "
                    "Export prompt-level results from your AI visibility tool. "
                    "Answer share, citation-graph capture and the outreach tiers are "
                    "reported as unmeasured rather than zero.")
    if not counts.get("backlinks"):
        warn.append("No backlink data: the citation-gap join cannot run, so outreach "
                    "targets are ranked on citation frequency alone.")
    if not counts.get("authority") and not counts.get("competitors"):
        warn.append("No authority or competitor data: winnability falls back to a "
                    "neutral authority assumption and will read optimistic.")
    if not counts.get("content_gaps"):
        warn.append("No content-gap data: the roadmap is built only from AI prompts, "
                    "so classic search demand is unrepresented.")
    if not payload.get("brand_domain"):
        warn.append("Brand domain could not be inferred: pass --brand-domain to "
                    "normalize.py or the citation-gap join will be wrong.")
    if auth.get("brand_domain_rating") is None:
        warn.append("No domain rating for the brand: attainability scores use a "
                    "default of DR 30.")
    # The remaining checks describe the shape of the citation set. With no
    # citations at all they would just restate the warning above in three
    # different ways, which buries the one message that matters.
    if not has_citations:
        return warn
    if vis.get("total_prompts_tracked", 0) and vis["total_prompts_tracked"] < 25:
        warn.append(f"Only {vis['total_prompts_tracked']} prompts tracked. Answer-share "
                    "percentages on a set this small move several points on one result; "
                    "treat them as directional and widen the set to 50+.")
    if len(vis.get("engines_tracked", [])) < 2:
        warn.append("Single engine tracked. Engine-specific quirks will look like "
                    "category truths; add at least ChatGPT, Perplexity and AI Overviews.")
    if src.get("total_cited_domains", 0) < 10:
        warn.append("Fewer than 10 distinct cited domains observed; the source graph "
                    "is too thin to tier reliably.")
    return warn


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="./build/normalized.json")
    ap.add_argument("--out", default="./build/analysis.json")
    args = ap.parse_args()

    with open(args.inp, encoding="utf-8") as fh:
        payload = json.load(fh)

    ds = payload["datasets"]
    brand_domain = payload.get("brand_domain")

    vis = analyze_visibility(ds["citations"], brand_domain)
    auth = analyze_authority(ds["authority"], ds["competitors"], vis, brand_domain)
    dr_lookup = enrich_dr_lookup(auth["_dr_lookup"], ds["backlinks"])
    src = analyze_source_graph(ds["citations"], ds["backlinks"], brand_domain,
                               auth.get("brand_domain_rating"), dr_lookup)
    blp = analyze_backlink_profile(ds["backlinks"], brand_domain)
    topics = analyze_topics(ds["content_gaps"], vis, auth, brand_domain)

    out = {
        "brand_domain": brand_domain,
        "brand_name": payload.get("brand_name"),
        "scorecard": build_scorecard(vis, src, auth, blp, topics,
                                     has_citations=bool(ds["citations"]),
                                     has_backlinks=bool(ds["backlinks"])),
        "visibility": {k: v for k, v in vis.items() if not k.startswith("_")},
        "authority": {k: v for k, v in auth.items() if not k.startswith("_")},
        "source_graph": {**src, "tier_counts": dict(src["tier_counts"]),
                         "archetype_mix": dict(src["archetype_mix"])},
        "backlink_profile": blp,
        "topics": topics,
        "data_coverage": {"counts": payload.get("counts"),
                          "manifest": payload.get("manifest"),
                          "warnings": coverage_warnings(payload, vis, src, auth)},
        "methodology": {"target_weights": TARGET_WEIGHTS,
                        "winnability_weights": WINNABILITY_WEIGHTS,
                        "horizon_thresholds": {"H1": ">=65", "H2": "42-64", "H3": "<42"}},
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)

    sc = out["scorecard"]

    def show(v, suffix="", grade=None):
        if v is None:
            return "not measured (no data)"
        return f"{v}{suffix}" + (f"  (grade {grade})" if grade else "")

    print(f"Analysis -> {args.out}\n")
    print(f"Brand: {brand_domain}")
    print(f"AI answer share:        {show(sc['ai_answer_share_pct'], '%', sc['ai_answer_share_grade'])}")
    print(f"Citation graph capture: {show(sc['citation_graph_capture_pct'], '%', sc['citation_graph_capture_grade'])}")
    print(f"Authority rank:         {show(sc['authority_rank'])}  (DR gap to median: {sc['dr_gap_to_median']})")
    print(f"T1 outreach targets:    {show(sc['t1_targets_open'])}")
    print(f"H1 quick-win topics:    {show(sc['quick_win_topics'])}")
    print(f"Prompts with no brand:  {show(sc['prompts_absent'])}")
    if out["data_coverage"]["warnings"]:
        print("\nCoverage warnings:")
        for w in out["data_coverage"]["warnings"]:
            print(f"  ! {w}")


if __name__ == "__main__":
    main()
