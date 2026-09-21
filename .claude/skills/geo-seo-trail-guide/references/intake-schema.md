# Intake schema and data sourcing

The normalizer accepts CSV, TSV, JSON, and NDJSON. It identifies each file from its
headers and filename, then maps columns onto the canonical names below. You do not need
to reshape exports by hand — but you do need to read the mapping report it prints,
because a column that fails to map is a conclusion that quietly goes missing.

## Contents

- [The five datasets](#the-five-datasets)
- [Where to get each export](#where-to-get-each-export)
- [Reading the mapping report](#reading-the-mapping-report)
- [When a field does not exist](#when-a-field-does-not-exist)
- [Adding a vendor](#adding-a-vendor)
- [Data hygiene](#data-hygiene)

## The five datasets

### 1. `citations` — AI answer-engine results

The most important file, and the one most brands do not have yet. One row per
(prompt × engine × cited source). If your tool exports one row per prompt with sources
in a list, explode it first.

| Canonical field | Required | Notes |
|---|---|---|
| `prompt` | yes | The question as asked. Keep the natural phrasing — prompt shape drives the format-fit score. |
| `engine` | yes | ChatGPT, Perplexity, Google AI Overviews, Claude, Gemini, Copilot. |
| `date` | no | Enables trend work across exports. |
| `brand_mentioned` | yes | Boolean-ish. Accepts Yes/No, TRUE/FALSE, 1/0. Inferred from `brand_position` if absent. |
| `brand_position` | no | Where in the answer the brand appears. |
| `cited_url` | strongly | The exact source URL. |
| `cited_domain` | strongly | Derived from `cited_url` when absent. **The central join needs this.** |
| `sentiment` | no | positive / neutral / negative. |
| `competitors_mentioned` | no | Semicolon- or comma-separated. Drives the displacement tier. |
| `share_of_voice` | no | If your tool computes one. |

### 2. `backlinks` — the brand's link profile

One row per link. Include competitor targets if you have a link-intersect export: the
script detects multiple target hosts and unlocks the competitive-displacement tier.

| Canonical field | Required | Notes |
|---|---|---|
| `referring_domain` | yes | Derived from `referring_url` when absent. |
| `referring_url` | no | The page carrying the link. |
| `target_url` | strongly | What it points at. **This is how competitor links are told from yours.** |
| `domain_rating` | strongly | DR, DA, or Authority Score — any 0–100 authority metric. |
| `traffic` | no | Referring domain's traffic. |
| `anchor` | no | Feeds the branded-anchor ratio. |
| `link_type` | no | Dofollow / nofollow / UGC / sponsored. |
| `first_seen` | no | Velocity analysis. |
| `topical_relevance` | no | Category or niche, if your tool assigns one. |

### 3. `authority` — the brand and its competitive set

One row per domain, including the brand's own. Mark the brand with `is_client`.

`domain`, `is_client`, `domain_rating`, `referring_domains`, `organic_traffic`,
`organic_keywords`, `date`.

### 4. `competitors` — competitive metrics, optionally with AI share

Overlaps with `authority`. Keep them separate when your AI-visibility tool reports
competitor answer share, since that column is what distinguishes the two files.

`domain`, `domain_rating`, `referring_domains`, `organic_traffic`, `organic_keywords`,
`ai_answer_share`, `notes`.

### 5. `content_gaps` — keyword and topic opportunities

`topic`, `search_volume`, `difficulty`, `our_rank`, `best_competitor_rank`,
`competitors_ranking`, `intent`, `cpc`, `has_ai_overview`.

`our_rank` accepts blank, `0`, or `101` for "not ranking" — all three are normalized to
unranked, so a 0 is never mistaken for a #1.

## Where to get each export

**Citations / AI visibility.** Profound, Peec AI, Otterly, Scrunch, Evertune,
Conductor, BrightEdge, Semrush AI Toolkit, Ahrefs Brand Radar. Export prompt-level
detail with sources, not just a summary score — a single visibility number cannot be
joined against anything.

No tool budget? Run 40–60 prompts by hand across three engines and log them in a
spreadsheet matching the schema above. Tedious, but a hand-built set of real prompts
beats a vendor's generic set, because you choose the prompts your buyers actually ask.

**Backlinks.** Ahrefs (Site Explorer → Backlinks → Export), Semrush (Backlink
Analytics), Moz Link Explorer, Majestic. For the competitive tier, use Ahrefs Link
Intersect or Semrush Backlink Gap with the brand and 3–5 rivals, which returns one file
with multiple target hosts.

**Authority and competitors.** Any of the above. Add AI answer share from the citation
tool if it reports it.

**Content gaps.** Ahrefs Content Gap, Semrush Keyword Gap, or your own ranking export
joined to a competitor set.

## Reading the mapping report

`normalize.py` prints a per-file summary. Three things to check:

**`UNCLASSIFIED`.** The file scored below the classification threshold. Usually a
heavily renamed export or a pivot table with a preamble. Open it, check the headers, and
either rename columns to something recognisable or add aliases (below). Do not proceed
with a file sitting unclassified.

**`missing:`.** A canonical field found no column. Judge each one:

- `sentiment`, `first_seen`, `cpc` missing — usually fine.
- `cited_domain` *and* `cited_url` missing — the central join is dead. Fix before continuing.
- `target_url` missing — competitor links cannot be told from yours. All links are assumed to be the brand's.
- `domain_rating` missing — attainability scoring falls back to a DR 45 default for every domain, which flattens the target ranking.

**`ignored:`.** Columns the mapper did not use. Skim for anything valuable you would
want scored — if it matters, add it as an alias.

## When a field does not exist

Prefer an honest gap to a fabricated value. The analysis handles `None` throughout and
the coverage warnings will surface it. Inventing a plausible-looking DR to fill a column
produces a ranked list that looks authoritative and is not.

The one exception worth making: if `cited_domain` is missing but `cited_url` is present,
that is handled automatically — the domain is parsed from the URL.

## Adding a vendor

Aliases live in `SCHEMAS` at the top of `scripts/normalize.py`. Add the new header,
lowercased and punctuation-free, to the relevant field's list:

```python
"domain_rating": ["domain rating", "dr", "domain authority", "da",
                  "authority score", "as", "trust flow"],   # <- added
```

Matching is exact-first, then substring, so a distinctive alias is safer than a short
one. Avoid two-letter aliases unless the vendor really uses them — `as` already risks
colliding, and a short alias can steal a column from a field that needed it more.

## Data hygiene

**Export everything on the same date.** A backlink file from March joined to citations
from September produces a citation gap that is partly just stale link data.

**Use one prompt set consistently.** Answer share is only comparable across periods if
the prompt set is stable. Adding twenty easy prompts will "improve" the number without
anything changing.

**Track at least three engines.** Single-engine data makes that engine's quirks look
like category truths. ChatGPT, Perplexity, and Google AI Overviews is the usual minimum.

**Fifty-plus prompts.** Below about 25, one result moves answer share by several points
and the horizon buckets get noisy. The analysis warns when the set is thin.

**Keep raw exports.** Store the originals alongside `build/` so any number in the
document can be traced back to a source row. Being able to answer "where did 26.7% come
from" in a meeting is most of this document's credibility.
