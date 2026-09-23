# Semrush connector

Pulls Semrush data straight into `./data` so the normal pipeline runs unchanged.
Whether a file arrived by API or by hand export, everything downstream is identical —
the connector is an optional front-end, not a second ingestion path.

## Contents

- [What it covers, and what it cannot](#what-it-covers-and-what-it-cannot)
- [Setup](#setup)
- [Cost control](#cost-control)
- [Usage](#usage)
- [What each dataset comes from](#what-each-dataset-comes-from)
- [Correcting an endpoint](#correcting-an-endpoint)
- [Testing](#testing)

## What it covers, and what it cannot

| Dataset | Via API? | Source |
|---|---|---|
| `authority` | yes | `domain_ranks` + `backlinks_overview` per domain |
| `competitors` | yes | `domain_organic_organic`, or the list you pass |
| `backlinks` | yes | `backlinks_refdomains` + `backlinks` |
| `content_gaps` | yes | computed locally by diffing `domain_organic` sets |
| **`citations`** | **no** | **not exposed by any public Semrush API** |

**The citation gap is the thing to understand before relying on this.** Semrush's AI
Visibility Toolkit holds exactly the prompt, mention and citation data this engine is
built around, but it is not in the public Analytics API catalog, and CSV export is not
available for the AI search module either. So a Semrush-only run produces a link-gap and
content audit, not the full GEO document: the central join in §2 — which cited domains
do not link to you — has nothing to join against.

The fetch script writes `data/CITATIONS-MISSING.md` on every run rather than letting
that gap go unnoticed, and §8 of the report states the limitation. Three ways to close
it, cheapest first:

1. **My Reports / Looker Studio.** Brand Performance, Visibility Overview and Prompt
   Tracking are wired into My Reports. If you can get a prompt-level table out that way,
   shape it to the `citations` schema in `intake-schema.md`.
2. **A vendor with an API.** Profound, Peec and Otterly expose prompt-level citation
   data. A second connector modelled on this one is a short job.
3. **By hand.** 40–60 prompts across three engines into a spreadsheet. Tedious, but you
   choose the prompts your buyers actually ask.

## Setup

**Two prerequisites, both outside the code.**

**1. The API key.** Request a **read-only** key. The connector only issues GETs; write
scopes cover the Projects API (projects, position-tracking campaigns, site audits), none
of which this touches. A leaked read-only key costs you API units; a write-capable one
can alter your account's configuration.

Store it in the environment's settings — the cloud environment menu in the session title
bar, then **Edit** — under API credentials, or as an environment variable named
`SEMRUSH_API_KEY`. A new session picks it up.

Never paste a key into the chat, a terminal, or a file in this repo. Anything pasted
into a conversation is in the transcript and should be rotated. `--api-key` exists on
the CLI for local one-offs, but it puts the key in your shell history, so prefer the
environment variable.

**2. Network access.** `api.semrush.com` must be permitted by the environment's network
policy. If it is not, every request fails with a proxy 403 and the client says so
explicitly rather than reporting a generic timeout. Change it in the same environment
settings, either by widening the access level or adding that host to the allowed
domains.

## Cost control

The Analytics API bills **per row returned**, not per request, which makes a wide
competitor pull expensive faster than people expect. Five competitors at 500 keywords
each is 2,500 billed rows before anything else.

**Always `--dry-run` first.** It prints every request it would make with the key
redacted, plus an upper-bound unit estimate, and calls nothing:

```bash
python3 scripts/fetch_semrush.py --brand example.com --dry-run
```

The estimate assumes every request returns its full limit, so real cost is usually
lower. Unit prices are configured in `REPORTS` in `scripts/semrush_api.py` and are
**estimates** — verify them against your own plan before a large pull.

The expensive flags, both off by default:

- `--competitor-backlinks` adds one referring-domain pull per competitor. Worth it: this
  is what unlocks the link-gap and competitive-displacement tiers in §3.
- `--with-difficulty` fetches keyword difficulty at a notably higher per-keyword price.
  Without it, `difficulty` is blank and winnability leans on foothold and format fit
  instead, which is a real but tolerable loss of precision.

## Usage

```bash
# 1. Preview cost, spend nothing
python3 scripts/fetch_semrush.py --brand example.com --dry-run

# 2. Fetch, letting Semrush discover competitors
python3 scripts/fetch_semrush.py --brand example.com --out-dir ./data

# 3. Or name them, and unlock the link-gap tiers
python3 scripts/fetch_semrush.py --brand example.com \
    --competitors rival-a.com,rival-b.com,rival-c.com \
    --competitor-backlinks --keyword-limit 1000 --out-dir ./data

# 4. Continue with the normal pipeline
python3 scripts/normalize.py --data-dir ./data --out ./build/normalized.json \
    --brand-domain example.com
```

Useful flags: `--database` (regional database, default `us`), `--max-competitors`,
`--keyword-limit`, `--backlink-limit`, `--refdomain-limit`.

## What each dataset comes from

**Authority.** `domain_ranks` for traffic and keyword counts, `backlinks_overview` for
Authority Score and referring-domain count, joined per domain. The brand is flagged
`Is Client=TRUE` so the normalizer identifies it without being told.

**Competitors.** `domain_organic_organic` returns organic competitors ranked by
relevance. Pass `--competitors` to override — worth doing when Semrush's notion of a
competitor differs from your commercial one, which is common.

**Backlinks.** `backlinks_refdomains` gives one row per referring domain with its
Authority Score; `backlinks` gives individual links with anchors and follow status. Both
are written to one file because the normalizer handles either shape. With
`--competitor-backlinks`, competitor referring domains are written with the competitor
as `Target URL`, which is what the analysis reads to detect link intersect.

**Content gaps.** Computed locally rather than pulled from a gap endpoint: organic
keyword sets are fetched per domain and diffed here. That yields exactly the columns the
scoring model wants — our rank, best competitor rank, and how many rivals hold the
term — from data already paid for. Keywords you rank for that no competitor does are
kept too, with `Competitors Ranking = 0`; they are not gaps, but they are defensible
ground the roadmap should see.

## Correcting an endpoint

Reports are declarative in `REPORTS` at the top of `scripts/semrush_api.py`. Each entry
holds the base URL, report type, requested `export_columns`, the mapping from Semrush
column codes to the headers our normalizer recognises, and the unit price.

Semrush revises column codes and prices periodically, and these definitions were written
without a live call to verify them — the API host was unreachable from the build
environment. **Expect to correct one or two on your first real run.** A correction is a
one-line edit in that dict; nothing else needs to change.

Responses are parsed by header name, not column position, so a reordered or added column
upstream cannot silently shift every value one field sideways. There are tests for both
cases.

## Testing

```bash
cd .claude/skills/geo-seo-trail-guide/scripts && python3 test_semrush.py
```

Runs fully offline against recorded response shapes — a suite that called the real API
would cost units on every run and fail wherever egress is restricted. It covers URL
construction, key redaction, CSV parsing (including reordered and unexpected columns),
Semrush's habit of returning errors as HTTP 200 with a plain-text body, retry and
backoff behaviour, cost arithmetic, and the local content-gap diff. It also asserts that
the headers this connector writes are ones `normalize.py` actually recognises, which is
the seam most likely to break quietly.

What it cannot verify is whether the endpoint definitions match today's live API. Only a
real call does that — start with `--dry-run`, then one small fetch.
