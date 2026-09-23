#!/usr/bin/env python3
"""Normalize heterogeneous GEO/SEO exports into one canonical JSON payload.

Every SEO and GEO vendor invents its own column names for the same five or six
ideas. Rather than force the user to reshape their exports, this script sniffs
each file's header row, decides which of the five datasets it belongs to, and
maps the columns onto canonical names. Anything it cannot place is reported
rather than silently dropped -- a quiet drop is how a strategy ends up built on
half the data.

Usage:
    python3 normalize.py --data-dir ./data --out ./build/normalized.json
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# Canonical schema
# --------------------------------------------------------------------------
# Each dataset maps canonical_field -> list of header aliases (lowercased,
# punctuation-stripped). Aliases are matched exactly first, then by substring,
# so "referring domain" catches "Referring Domain" and "referring_domains".

SCHEMAS = {
    "citations": {
        "_signals": ["prompt", "engine", "query", "answer", "citation", "mentioned", "llm", "ai platform"],
        "fields": {
            "prompt": ["prompt", "query", "question", "keyword", "search", "topic", "prompt text"],
            "engine": ["engine", "platform", "model", "ai engine", "llm", "source engine", "assistant"],
            "date": ["date", "run date", "checked", "timestamp", "observed", "week", "month"],
            "brand_mentioned": ["brand mentioned", "mentioned", "brand present", "is mentioned",
                                "brand appears", "presence", "visible", "included"],
            "brand_position": ["position", "rank", "brand position", "mention position", "order", "placement"],
            "cited_url": ["cited url", "url", "source url", "citation url", "link", "source link", "page"],
            "cited_domain": ["cited domain", "domain", "source domain", "source", "citation domain", "site"],
            "sentiment": ["sentiment", "tone", "polarity"],
            "competitors_mentioned": ["competitors mentioned", "competitor", "competitors",
                                      "other brands", "brands mentioned", "competing brands"],
            "share_of_voice": ["share of voice", "sov", "visibility", "visibility score", "answer share"],
        },
    },
    "backlinks": {
        "_signals": ["referring", "backlink", "anchor", "dofollow", "nofollow", "link type", "target url"],
        "fields": {
            "referring_domain": ["referring domain", "referring page domain", "source domain",
                                 "domain", "from domain", "linking domain", "site", "referring site"],
            "referring_url": ["referring page url", "referring url", "source url", "from url",
                              "page url", "link from", "referring page"],
            "target_url": ["target url", "to url", "destination", "link to", "landing page", "target page"],
            "domain_rating": ["domain rating", "dr", "domain authority", "da", "authority score",
                              "as", "domain score", "rating", "authority",
                              "page ascore", "domain ascore", "source ascore", "ascore"],
            "traffic": ["traffic", "domain traffic", "organic traffic", "monthly traffic", "visits"],
            "anchor": ["anchor", "anchor text", "link text"],
            "link_type": ["type", "link type", "follow", "dofollow", "rel", "nofollow"],
            "first_seen": ["first seen", "first indexed", "discovered", "date found", "seen"],
            "topical_relevance": ["relevance", "topical relevance", "topic", "category", "niche", "vertical"],
        },
    },
    "authority": {
        "_signals": ["domain rating", "domain authority", "authority score", "trust flow", "referring domains"],
        "fields": {
            "domain": ["domain", "site", "website", "url", "competitor", "brand", "company"],
            "is_client": ["is client", "client", "own", "is own", "self", "is brand", "brand flag"],
            "domain_rating": ["domain rating", "dr", "domain authority", "da", "authority score",
                              "as", "authority", "rating", "score", "domain ascore", "ascore"],
            "referring_domains": ["referring domains", "ref domains", "rd", "linking domains",
                                  "unique domains", "root domains"],
            "organic_traffic": ["organic traffic", "traffic", "monthly traffic", "sessions", "visits", "et"],
            "organic_keywords": ["organic keywords", "keywords", "ranking keywords", "kw", "total keywords"],
            "date": ["date", "as of", "snapshot", "month", "period"],
        },
    },
    "competitors": {
        "_signals": ["competitor", "rival", "share of voice", "competitor domain"],
        "fields": {
            "domain": ["domain", "competitor", "competitor domain", "site", "website", "brand", "company"],
            "is_client": ["is client", "client", "own", "is own", "self", "is brand", "brand flag"],
            "domain_rating": ["domain rating", "dr", "domain authority", "da", "authority score", "as", "authority"],
            "referring_domains": ["referring domains", "ref domains", "rd", "linking domains", "root domains"],
            "organic_traffic": ["organic traffic", "traffic", "monthly traffic", "visits"],
            "organic_keywords": ["organic keywords", "keywords", "ranking keywords", "kw"],
            "ai_answer_share": ["ai answer share", "answer share", "share of voice", "sov",
                                "ai visibility", "llm visibility", "ai share"],
            "notes": ["notes", "comment", "positioning", "segment"],
        },
    },
    "content_gaps": {
        "_signals": ["gap", "search volume", "difficulty", "kd", "your rank", "our rank", "intent"],
        "fields": {
            "topic": ["keyword", "topic", "query", "prompt", "term", "search term", "phrase"],
            "search_volume": ["search volume", "volume", "sv", "monthly searches", "msv", "searches"],
            "difficulty": ["difficulty", "kd", "keyword difficulty", "competition", "seo difficulty", "comp"],
            "our_rank": ["our rank", "your rank", "current rank", "position", "rank", "my rank", "client rank"],
            "best_competitor_rank": ["competitor rank", "best competitor rank", "top competitor",
                                     "competitor position", "rival rank"],
            "competitors_ranking": ["competitors ranking", "number of competitors", "competitor count",
                                    "competing domains", "competitors"],
            "intent": ["intent", "search intent", "stage", "funnel", "funnel stage",
                       "keyword intents", "keyword intent", "intents"],
            "cpc": ["cpc", "cost per click", "value", "commercial value"],
            "has_ai_overview": ["ai overview", "aio", "sge", "ai answer", "has ai overview",
                                "featured in ai", "serp features by keyword", "serp features"],
        },
    },
}

TRUTHY = {"true", "yes", "y", "1", "t", "mentioned", "present", "x", "included", "visible"}
FALSY = {"false", "no", "n", "0", "f", "absent", "not mentioned", "missing", ""}


def slug(s):
    """Normalize a header cell for matching: lowercase, strip punctuation."""
    return re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower()).strip()


def squash(s):
    return re.sub(r"\s+", " ", slug(s))


def parse_bool(v):
    s = str(v or "").strip().lower()
    if s in TRUTHY:
        return True
    if s in FALSY:
        return False
    return None


def parse_num(v):
    """Pull a number out of '1,234', '$4.50', '87%', 'DR 61', '1.2K', '3M'."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    mult = 1.0
    m = re.search(r"([-+]?[\d,]*\.?\d+)\s*([KMB])\b", s, re.I)
    if m:
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[m.group(2).lower()]
        s = m.group(1)
    else:
        m = re.search(r"[-+]?[\d,]*\.?\d+", s)
        if not m:
            return None
        s = m.group(0)
    try:
        return float(s.replace(",", "")) * mult
    except ValueError:
        return None


def clean_domain(v):
    """Reduce a URL or messy domain string to a bare registrable host."""
    s = str(v or "").strip().lower()
    if not s:
        return None
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    s = s.split("/")[0].split("?")[0].split("#")[0].strip().strip(".")
    return s or None


def domain_of(url):
    return clean_domain(url)


# --------------------------------------------------------------------------
# Wide "gap" exports
# --------------------------------------------------------------------------
# Semrush's Keyword Gap and Backlink Gap reports come out pivoted: one column
# per domain, with the cell holding that domain's position or backlink count.
# They are the most valuable files a user can supply -- they carry the
# competitor comparison that unlocks the displacement and link-gap tiers -- and
# they are unreadable by a mapper that assumes one column per field. So they
# get detected and melted into long form before classification sees them.

# A header is treated as a domain column when it parses as a hostname. The TLD
# length floor keeps decimal-looking headers ("Traffic 1.5") out.
DOMAIN_COL_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)+$")

# Headers that look domain-ish but are ordinary metric columns.
NOT_A_DOMAIN = {"traffic", "results", "volume", "position", "competition", "keyword",
                "domain", "url", "cpc", "difficulty", "kd", "score", "ascore"}


def is_domain_column(header):
    h = str(header or "").strip().lower()
    h = re.sub(r"^https?://", "", h).replace("www.", "").split("/")[0]
    if not DOMAIN_COL_RE.match(h):
        return None
    if h.split(".")[0] in NOT_A_DOMAIN:
        return None
    if len(h.rsplit(".", 1)[-1]) < 2:
        return None
    return h


def detect_wide_gap(headers):
    """Return (kind, {header: domain}) for a pivoted gap export, else None."""
    domain_cols = {}
    for h in headers:
        d = is_domain_column(h)
        if d:
            domain_cols[h] = d
    # One domain column is more likely a stray label than a pivot.
    if len(domain_cols) < 2:
        return None

    other = [squash(h) for h in headers if h not in domain_cols]
    blob = " | ".join(other)
    has_keyword = any(k in other for k in ("keyword", "topic", "phrase", "query", "term"))
    has_domain = any(k in other for k in ("domain", "referring domain", "source domain"))

    if has_keyword:
        return "keyword_gap", domain_cols
    if has_domain or "ascore" in blob or "authority" in blob:
        return "backlink_gap", domain_cols
    return None


def _rank(value):
    """Parse a position cell. Semrush uses blank, '-' or '0' for not ranking."""
    v = str(value or "").strip()
    if not v or v in ("-", "--", "0", "n/a", "na"):
        return None
    n = parse_num(v)
    if n is None or n <= 0 or n >= 101:
        return None
    return int(n)


def pick_brand_column(domain_cols, brand_domain):
    """Decide which pivoted column is the client's.

    An explicit --brand-domain wins. Failing that, Semrush puts the domain you
    ran the report for in the first column, which is a reliable-enough
    convention to use -- but the caller reports the assumption, because getting
    it wrong silently inverts every gap in the file.
    """
    if brand_domain:
        for header, dom in domain_cols.items():
            if dom == brand_domain:
                return header, False
    return (next(iter(domain_cols)), True) if domain_cols else (None, False)


def melt_keyword_gap(rows, domain_cols, brand_domain):
    """Pivoted keyword gap -> content_gap rows."""
    brand_col, guessed = pick_brand_column(domain_cols, brand_domain)
    out = []
    for r in rows:
        lowered = {squash(k): v for k, v in r.items() if k is not None}
        topic = ""
        for key in ("keyword", "topic", "phrase", "query", "term"):
            if lowered.get(key):
                topic = str(lowered[key]).strip()
                break
        if not topic:
            continue

        our = _rank(r.get(brand_col)) if brand_col else None
        rival_ranks = [_rank(r.get(h)) for h in domain_cols if h != brand_col]
        rival_ranks = [x for x in rival_ranks if x is not None]

        out.append({
            "topic": topic,
            "search_volume": lowered.get("search volume") or lowered.get("volume"),
            "difficulty": (lowered.get("keyword difficulty") or lowered.get("difficulty")
                           or lowered.get("kd")),
            "our_rank": our,
            "best_competitor_rank": min(rival_ranks) if rival_ranks else None,
            "competitors_ranking": len(rival_ranks),
            "intent": lowered.get("keyword intents") or lowered.get("intent"),
            "cpc": lowered.get("cpc"),
            "has_ai_overview": lowered.get("serp features by keyword"),
        })
    return out, brand_col, guessed


def melt_backlink_gap(rows, domain_cols, brand_domain):
    """Pivoted backlink gap -> backlink rows, one per (referring domain, target).

    Emitting a row per competitor target is what lets the analysis detect link
    intersect: the source graph reads target_url to tell a link to you from a
    link to a rival.
    """
    brand_col, guessed = pick_brand_column(domain_cols, brand_domain)
    out = []
    for r in rows:
        lowered = {squash(k): v for k, v in r.items() if k is not None}
        ref = None
        for key in ("domain", "referring domain", "source domain", "site"):
            if lowered.get(key):
                ref = clean_domain(lowered[key])
                break
        if not ref:
            continue
        dr = None
        for key in ("domain ascore", "ascore", "domain score", "authority score",
                    "domain rating", "dr", "as"):
            if lowered.get(key) not in (None, ""):
                dr = parse_num(lowered[key])
                break

        for header, target in domain_cols.items():
            count = parse_num(r.get(header))
            if not count or count <= 0:
                continue
            out.append({
                "referring_domain": ref,
                "referring_url": None,
                "target_url": f"https://{target}/",
                "domain_rating": dr,
                "traffic": None,
                "anchor": None,
                "link_type": None,
                "first_seen": None,
                "topical_relevance": None,
            })
    return out, brand_col, guessed


# --------------------------------------------------------------------------
# File reading
# --------------------------------------------------------------------------

def read_rows(path):
    """Return (list_of_dict_rows, note). Handles CSV, TSV and JSON (incl. NDJSON
    and a top-level object wrapping the list under a data/results/rows key)."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        raw = fh.read()
    if not raw.strip():
        return [], "empty file"

    if ext in (".json", ".ndjson", ".jsonl"):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            rows = []
            for line in raw.splitlines():
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return [r for r in rows if isinstance(r, dict)], "ndjson"
        if isinstance(obj, list):
            return [r for r in obj if isinstance(r, dict)], "json array"
        if isinstance(obj, dict):
            for key in ("data", "results", "rows", "items", "records", "citations", "backlinks"):
                if isinstance(obj.get(key), list):
                    return [r for r in obj[key] if isinstance(r, dict)], f"json object[{key}]"
            return [obj], "json single object"
        return [], "unrecognized json"

    # Delimited text. Sniff the delimiter, and skip any preamble lines that
    # vendors like to put above the real header row.
    lines = raw.splitlines()
    start = 0
    delim = "\t" if ext in (".tsv", ".tab") else ","
    if delim == ",":
        try:
            delim = csv.Sniffer().sniff(raw[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
    for i, line in enumerate(lines[:10]):
        if line.count(delim) >= 1 and len(line.strip()) > 0:
            start = i
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])), delimiter=delim)
    rows = [r for r in reader if any((v or "").strip() for v in r.values())]
    return rows, f"delimited '{delim}'"


# --------------------------------------------------------------------------
# Classification and mapping
# --------------------------------------------------------------------------

def classify(headers, filename):
    """Guess which dataset a file holds, from its filename and header row.

    Filename is a strong hint because people name exports after what they are,
    but headers win ties -- a file called 'export(3).csv' still has to land
    somewhere sensible.
    """
    hs = [squash(h) for h in headers]
    blob = " | ".join(hs)
    fname = squash(filename)

    scores = {}
    for name, schema in SCHEMAS.items():
        score = 0
        for token in name.split("_") + [name.replace("_", "")]:
            if token and token[:6] in fname:
                score += 6
        for sig in schema["_signals"]:
            if sig in blob:
                score += 3
            if sig in fname:
                score += 2
        for field, aliases in schema["fields"].items():
            for h in hs:
                if h in aliases:
                    score += 2
                    break
        scores[name] = score

    # Authority and competitors share most columns. A client flag is decisive:
    # only an authority file marks which domain is yours, and that column is
    # how the brand gets identified downstream. It has to beat a filename hint
    # -- "Domain Overview - competitors.csv" is a perfectly ordinary name for
    # an authority export.
    if any(h in ("is client", "client", "is own", "own", "is brand", "brand flag")
           or h.startswith("is client") for h in hs):
        scores["authority"] = max(scores.values(), default=0) + 10
    elif scores.get("competitors", 0) and scores.get("authority", 0):
        if any("ai" in h or "answer share" in h or "sov" in h for h in hs):
            scores["competitors"] += 4

    best = max(scores, key=lambda k: scores[k])
    return (best, scores) if scores[best] >= 4 else (None, scores)


def map_row(row, fields):
    """Map one raw row onto canonical field names, keeping the leftovers."""
    lowered = {squash(k): v for k, v in row.items() if k is not None}
    out, used = {}, set()
    # Exact alias match first -- it is unambiguous, so it should claim the
    # column before any substring heuristic gets a chance to steal it.
    for field, aliases in fields.items():
        for alias in aliases:
            if alias in lowered and alias not in used:
                out[field] = lowered[alias]
                used.add(alias)
                break
    for field, aliases in fields.items():
        if field in out:
            continue
        for header, value in lowered.items():
            if header in used:
                continue
            if any(alias in header or header in alias for alias in aliases if len(alias) > 2):
                out[field] = value
                used.add(header)
                break
    extras = {k: v for k, v in lowered.items() if k not in used and str(v or "").strip()}
    if extras:
        out["_extra"] = extras
    return out


# --------------------------------------------------------------------------
# Per-dataset coercion
# --------------------------------------------------------------------------

def coerce_citations(rows):
    out = []
    for r in rows:
        cited_domain = clean_domain(r.get("cited_domain")) or domain_of(r.get("cited_url"))
        comps = r.get("competitors_mentioned")
        comp_list = []
        if comps:
            comp_list = [c.strip() for c in re.split(r"[;,|]", str(comps)) if c.strip()]
        mentioned = parse_bool(r.get("brand_mentioned"))
        pos = parse_num(r.get("brand_position"))
        if mentioned is None and pos is not None:
            mentioned = pos > 0
        out.append({
            "prompt": str(r.get("prompt") or "").strip(),
            "engine": str(r.get("engine") or "unspecified").strip().lower(),
            "date": str(r.get("date") or "").strip(),
            "brand_mentioned": mentioned,
            "brand_position": pos,
            "cited_url": str(r.get("cited_url") or "").strip() or None,
            "cited_domain": cited_domain,
            "sentiment": str(r.get("sentiment") or "").strip().lower() or None,
            "competitors_mentioned": comp_list,
            "share_of_voice": parse_num(r.get("share_of_voice")),
        })
    return [r for r in out if r["prompt"] or r["cited_domain"]]


def coerce_backlinks(rows):
    out = []
    for r in rows:
        dom = clean_domain(r.get("referring_domain")) or domain_of(r.get("referring_url"))
        if not dom:
            continue
        lt = str(r.get("link_type") or "").strip().lower()
        follow = None
        if "nofollow" in lt or "ugc" in lt or "sponsored" in lt:
            follow = False
        elif "dofollow" in lt or "follow" in lt:
            follow = True
        out.append({
            "referring_domain": dom,
            "referring_url": str(r.get("referring_url") or "").strip() or None,
            "target_url": str(r.get("target_url") or "").strip() or None,
            "domain_rating": parse_num(r.get("domain_rating")),
            "traffic": parse_num(r.get("traffic")),
            "anchor": str(r.get("anchor") or "").strip() or None,
            "dofollow": follow,
            "first_seen": str(r.get("first_seen") or "").strip() or None,
            "topical_relevance": str(r.get("topical_relevance") or "").strip() or None,
        })
    return out


def coerce_authority(rows):
    out = []
    for r in rows:
        dom = clean_domain(r.get("domain"))
        if not dom:
            continue
        out.append({
            "domain": dom,
            "is_client": parse_bool(r.get("is_client")),
            "domain_rating": parse_num(r.get("domain_rating")),
            "referring_domains": parse_num(r.get("referring_domains")),
            "organic_traffic": parse_num(r.get("organic_traffic")),
            "organic_keywords": parse_num(r.get("organic_keywords")),
            "date": str(r.get("date") or "").strip() or None,
        })
    return out


def coerce_competitors(rows):
    out = []
    for r in rows:
        dom = clean_domain(r.get("domain"))
        if not dom:
            continue
        out.append({
            "domain": dom,
            "is_client": parse_bool(r.get("is_client")),
            "domain_rating": parse_num(r.get("domain_rating")),
            "referring_domains": parse_num(r.get("referring_domains")),
            "organic_traffic": parse_num(r.get("organic_traffic")),
            "organic_keywords": parse_num(r.get("organic_keywords")),
            "ai_answer_share": parse_num(r.get("ai_answer_share")),
            "notes": str(r.get("notes") or "").strip() or None,
        })
    return out


def _ai_overview(value):
    """Interpret an AI-Overview signal that may be a flag or a feature list.

    Semrush ships a "SERP Features by Keyword" column holding names like
    "AI Overview, Featured snippet". Parsing that as a boolean yields None for
    every populated row, quietly losing the signal, so check for the feature by
    name first and only then fall back to boolean parsing.
    """
    s = str(value or "").strip().lower()
    if not s:
        return None
    if any(tok in s for tok in ("ai overview", "ai_overview", "aio", "sge", "ai mode")):
        return True
    b = parse_bool(s)
    if b is not None:
        return b
    # A non-empty feature list that names no AI feature is evidence of absence.
    return False if "," in s or len(s) > 3 else None


def coerce_content_gaps(rows):
    out = []
    for r in rows:
        topic = str(r.get("topic") or "").strip()
        if not topic:
            continue
        our = parse_num(r.get("our_rank"))
        # Exports use 0, blank or 101 for "not ranking". Treat them all as unranked
        # so the foothold logic below does not mistake a 0 for a #1 position.
        if our is not None and (our <= 0 or our >= 101):
            our = None
        out.append({
            "topic": topic,
            "search_volume": parse_num(r.get("search_volume")),
            "difficulty": parse_num(r.get("difficulty")),
            "our_rank": our,
            "best_competitor_rank": parse_num(r.get("best_competitor_rank")),
            "competitors_ranking": parse_num(r.get("competitors_ranking")),
            "intent": str(r.get("intent") or "").strip().lower() or None,
            "cpc": parse_num(r.get("cpc")),
            "has_ai_overview": _ai_overview(r.get("has_ai_overview")),
        })
    return out


def merge_content_gaps(rows):
    """Collapse duplicate topics across overlapping exports.

    Supplying both a Keyword Gap and an Organic Positions export is the normal
    case, and the same keyword appears in both with different columns filled --
    the gap file knows what rivals rank, the positions file knows the exact URL
    and difficulty. Left alone they become two roadmap rows for one piece of
    work, double-counted in the horizon totals.

    Merge field by field, preferring whichever row actually has a value. Where
    both do, the richer row wins on the assumption that the export carrying
    more populated columns is the more specific one.
    """
    groups = defaultdict(list)
    for r in rows:
        key = re.sub(r"\s+", " ", (r.get("topic") or "").strip().lower())
        if key:
            groups[key].append(r)

    merged = []
    for key, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        group.sort(key=lambda r: sum(1 for v in r.values() if v is not None), reverse=True)
        base = dict(group[0])
        for other in group[1:]:
            for field, value in other.items():
                if base.get(field) is None and value is not None:
                    base[field] = value
        # Rival counts come from the gap export; take the most informed view
        # rather than whichever row happened to be richest overall.
        counts = [r.get("competitors_ranking") for r in group
                  if r.get("competitors_ranking") is not None]
        if counts:
            base["competitors_ranking"] = max(counts)
        ranks = [r.get("best_competitor_rank") for r in group
                 if r.get("best_competitor_rank") is not None]
        if ranks:
            base["best_competitor_rank"] = min(ranks)
        ours = [r.get("our_rank") for r in group if r.get("our_rank") is not None]
        if ours:
            base["our_rank"] = min(ours)
        merged.append(base)
    return merged


COERCERS = {
    "citations": coerce_citations,
    "backlinks": coerce_backlinks,
    "authority": coerce_authority,
    "competitors": coerce_competitors,
    "content_gaps": coerce_content_gaps,
}


def infer_brand_domain(datasets, explicit=None, wide_brand=None):
    """Work out which domain is the client's, best evidence first.

    Order matters more than it looks. Identifying the wrong domain does not
    degrade the analysis, it inverts it: the citation gap, the link gap and
    every rank comparison come out backwards while still looking plausible.
    """
    if explicit:
        return clean_domain(explicit)

    # 1. An explicit client flag. Unambiguous.
    for key in ("authority", "competitors"):
        for row in datasets.get(key, []):
            if row.get("is_client"):
                return row["domain"]

    # 2. The brand column of a pivoted gap export. Semrush puts the domain the
    #    report was run for first, which is weak evidence on its own but far
    #    better than the frequency heuristic below -- a melted gap file gives
    #    every competitor target rows too, so counting targets picks whichever
    #    rival happens to have the most links.
    if wide_brand:
        return clean_domain(wide_brand)

    # 3. Most common backlink target host. Only trustworthy when the backlink
    #    data is a single-target export.
    hosts = Counter()
    for row in datasets.get("backlinks", []):
        h = domain_of(row.get("target_url"))
        if h:
            hosts[h] += 1
    if len(hosts) == 1:
        return hosts.most_common(1)[0][0]
    if hosts:
        top, n = hosts.most_common(1)[0]
        total = sum(hosts.values())
        # Require a clear majority; a near-tie means this heuristic is guessing.
        if n / total >= 0.6:
            return top
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="./data")
    ap.add_argument("--out", default="./build/normalized.json")
    ap.add_argument("--brand-domain", default=None,
                    help="Client domain. Inferred from the data when omitted.")
    ap.add_argument("--brand-name", default=None)
    args = ap.parse_args()

    if not os.path.isdir(args.data_dir):
        sys.exit(f"ERROR: data dir not found: {args.data_dir}")

    paths = []
    for root, _dirs, files in os.walk(args.data_dir):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in (".csv", ".tsv", ".tab", ".json", ".ndjson", ".jsonl"):
                paths.append(os.path.join(root, f))
    if not paths:
        sys.exit(f"ERROR: no CSV/TSV/JSON files under {args.data_dir}")

    raw = defaultdict(list)
    manifest, unmapped = [], []
    wide_brand = None

    for path in paths:
        rows, note = read_rows(path)
        rel = os.path.relpath(path, args.data_dir)
        if not rows:
            manifest.append({"file": rel, "dataset": None, "rows": 0, "note": f"{note}; no data rows"})
            continue
        headers = list(rows[0].keys())

        # Pivoted gap exports are melted before classification, since their
        # shape defeats the one-column-per-field mapper entirely.
        wide = detect_wide_gap(headers)
        if wide:
            kind, domain_cols = wide
            if kind == "keyword_gap":
                melted, brand_col, guessed = melt_keyword_gap(
                    rows, domain_cols, clean_domain(args.brand_domain))
                raw["content_gaps"].extend(melted)
                target_ds = "content_gaps"
            else:
                melted, brand_col, guessed = melt_backlink_gap(
                    rows, domain_cols, clean_domain(args.brand_domain))
                raw["backlinks"].extend(melted)
                target_ds = "backlinks"
            if brand_col and not wide_brand:
                wide_brand = domain_cols.get(brand_col)
            note_extra = (f"wide {kind}; brand column '{brand_col}'"
                          + (" (GUESSED - first column)" if guessed else ""))
            manifest.append({
                "file": rel, "dataset": target_ds, "rows": len(rows),
                "note": f"{note}; {note_extra}",
                "wide_format": kind,
                "brand_column": brand_col,
                "brand_column_guessed": guessed,
                "domain_columns": sorted(domain_cols.values()),
                "melted_rows": len(melted),
            })
            continue

        dataset, scores = classify(headers, rel)
        if dataset is None:
            manifest.append({"file": rel, "dataset": None, "rows": len(rows),
                             "note": f"{note}; could not classify", "scores": scores,
                             "headers": headers[:15]})
            unmapped.append(rel)
            continue
        fields = SCHEMAS[dataset]["fields"]
        mapped = [map_row(r, fields) for r in rows]
        matched = sorted({k for m in mapped for k in m if k != "_extra"})
        missing = [f for f in fields if f not in matched]
        leftover = sorted({k for m in mapped for k in m.get("_extra", {})})
        raw[dataset].extend(mapped)
        manifest.append({
            "file": rel, "dataset": dataset, "rows": len(rows), "note": note,
            "mapped_fields": matched, "unmapped_canonical_fields": missing,
            "ignored_columns": leftover[:20],
        })

    # Melted rows already carry canonical field names and parsed values, so the
    # coercers must tolerate seeing them a second time; both are idempotent for
    # already-clean input.
    datasets = {name: COERCERS[name](rows) for name, rows in raw.items()}
    before = len(datasets.get("content_gaps", []))
    if before:
        datasets["content_gaps"] = merge_content_gaps(datasets["content_gaps"])
    merged_away = before - len(datasets.get("content_gaps", []))
    for name in SCHEMAS:
        datasets.setdefault(name, [])

    brand_domain = infer_brand_domain(datasets, args.brand_domain, wide_brand)

    payload = {
        "brand_domain": brand_domain,
        "brand_name": args.brand_name,
        "counts": {k: len(v) for k, v in datasets.items()},
        "manifest": manifest,
        "unclassified_files": unmapped,
        "datasets": datasets,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print(f"Normalized -> {args.out}")
    print(f"Brand domain: {brand_domain or 'UNKNOWN (pass --brand-domain)'}")
    if merged_away:
        print(f"\nMerged {merged_away} duplicate topic rows appearing in more than "
              f"one export.")
    print("\nRow counts by dataset:")
    for k, v in payload["counts"].items():
        print(f"  {k:<15} {v:>6}")
    print("\nPer-file mapping:")
    for m in manifest:
        print(f"  {m['file']:<40} -> {m['dataset'] or 'UNCLASSIFIED':<14} ({m['rows']} rows)")
        if m.get("unmapped_canonical_fields"):
            print(f"      missing: {', '.join(m['unmapped_canonical_fields'])}")
        if m.get("ignored_columns"):
            print(f"      ignored: {', '.join(m['ignored_columns'])}")
        if m.get("wide_format"):
            print(f"      pivoted {m['wide_format']} -> {m['melted_rows']} rows; "
                  f"domains: {', '.join(m['domain_columns'])}")
            if m.get("brand_column_guessed"):
                print(f"      WARNING: assumed '{m['brand_column']}' is your domain "
                      f"(first column). Pass --brand-domain to be certain - getting "
                      f"this wrong inverts every gap in the file.")
    if unmapped:
        print("\nWARNING: unclassified files (inspect headers, then map by hand):")
        for u in unmapped:
            print(f"  - {u}")


if __name__ == "__main__":
    main()
