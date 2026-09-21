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
                              "as", "domain score", "rating", "authority"],
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
                              "as", "authority", "rating", "score"],
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
            "intent": ["intent", "search intent", "stage", "funnel", "funnel stage"],
            "cpc": ["cpc", "cost per click", "value", "commercial value"],
            "has_ai_overview": ["ai overview", "aio", "sge", "ai answer", "has ai overview", "featured in ai"],
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

    # Authority and competitors share most columns. The tell is whether the
    # file carries an AI-visibility column or a client flag.
    if scores.get("competitors", 0) and scores.get("authority", 0):
        if any("client" in h or "own" in h or "is brand" in h for h in hs):
            scores["authority"] += 4
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
            "domain_rating": parse_num(r.get("domain_rating")),
            "referring_domains": parse_num(r.get("referring_domains")),
            "organic_traffic": parse_num(r.get("organic_traffic")),
            "organic_keywords": parse_num(r.get("organic_keywords")),
            "ai_answer_share": parse_num(r.get("ai_answer_share")),
            "notes": str(r.get("notes") or "").strip() or None,
        })
    return out


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
            "has_ai_overview": parse_bool(r.get("has_ai_overview")),
        })
    return out


COERCERS = {
    "citations": coerce_citations,
    "backlinks": coerce_backlinks,
    "authority": coerce_authority,
    "competitors": coerce_competitors,
    "content_gaps": coerce_content_gaps,
}


def infer_brand_domain(datasets, explicit=None):
    """Work out which domain is the client's."""
    if explicit:
        return clean_domain(explicit)
    for row in datasets.get("authority", []):
        if row.get("is_client"):
            return row["domain"]
    # Fall back to the most common target-URL host in the backlink file: those
    # links all point at the client by definition.
    hosts = Counter()
    for row in datasets.get("backlinks", []):
        h = domain_of(row.get("target_url"))
        if h:
            hosts[h] += 1
    if hosts:
        return hosts.most_common(1)[0][0]
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

    for path in paths:
        rows, note = read_rows(path)
        rel = os.path.relpath(path, args.data_dir)
        if not rows:
            manifest.append({"file": rel, "dataset": None, "rows": 0, "note": f"{note}; no data rows"})
            continue
        headers = list(rows[0].keys())
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

    datasets = {name: COERCERS[name](rows) for name, rows in raw.items()}
    for name in SCHEMAS:
        datasets.setdefault(name, [])

    brand_domain = infer_brand_domain(datasets, args.brand_domain)

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
    if unmapped:
        print("\nWARNING: unclassified files (inspect headers, then map by hand):")
        for u in unmapped:
            print(f"  - {u}")


if __name__ == "__main__":
    main()
