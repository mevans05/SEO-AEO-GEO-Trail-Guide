---
name: geo-seo-trail-guide
description: Turns GEO/AEO and SEO data exports - AI answer-engine citations, backlink profiles, domain authority and competitor metrics, content gap reports - into an actionable authority strategy document covering link and citation outreach, PR process changes, marketing partnerships and awards, and a content roadmap split into quick wins versus long-term authority building. Use this whenever the user drops SEO or AI-visibility exports (Ahrefs, Semrush, Moz, Profound, Peec, Otterly, Conductor, BrightEdge) and wants analysis, prioritisation or a plan; whenever they ask why a brand is or is not being cited by ChatGPT, Perplexity, Claude, Gemini or AI Overviews; whenever they ask which links, publications, review sites, partnerships or awards to chase; and whenever they ask what content to build first for quick wins versus long-term authority. Use it even when the request sounds like a narrow slice ("rank these link targets", "which keywords can we actually win", "build an outreach list", "where are our citation gaps"), because those answers are only trustworthy on top of the full join this skill performs.
---

# GEO & SEO Trail Guide

## What this produces

One document. It answers four questions a brand's marketing leadership actually
argues about, in this order, because each depends on the one before it:

1. **Where do we stand** in answer engines and in classic search?
2. **Who do we need to reach** to change that, and in what order?
3. **What has to change in how we run PR and partnerships** for that to be repeatable?
4. **What do we build ourselves**, split into what pays off this quarter and what
   compounds over a year?

The document is for a reader who has to fund and staff the plan. That means every
recommendation carries a target, an owner slot, and a number it is supposed to move.

## The idea that makes this different from a generic audit

Most SEO audits rank link targets by Domain Rating. Most GEO reports list the prompts
where a brand is missing. Neither is very actionable alone, because neither tells you
*where to go*.

The useful move is a join between the two datasets:

> **Take the domains answer engines actually cite for the brand's prompt set. Subtract
> the domains that already link to the brand. What remains is the working list.**

That remainder matters more than a DR-sorted list because a placement on one of those
domains does two jobs at once. It earns a backlink, and it inserts the brand into the
text that engines are demonstrably retrieving when someone asks about the category.
A DR 90 domain that has never surfaced in an answer for your prompts does only the
first job.

This join is also what makes the four output sections cohere rather than read as four
unrelated decks. They are four routes to the same target list, sorted by what kind of
domain it is:

| Cited domain type | Section that handles it | Why that motion |
|---|---|---|
| Blogs, trade press, editorial | Tactical outreach (§3) | An email with an asset behind it works |
| News and business press | PR (§4) | Needs a story and a spokesperson, not a pitch for a link |
| Review platforms, directories, databases | Partnerships (§5) | Needs customer proof or a listing process, not outreach |
| Awards bodies, associations | Partnerships (§5) | Needs an entry, a deadline and a fee |
| Prompts where *nobody* is cited well | Content roadmap (§6) | Nothing to reach out to; go build the answer |

When you explain the plan, use that logic. A reader who understands *why* a target
landed in the PR section instead of the outreach section will run the plan correctly.

## Workflow

### Step 1 - Take stock of the data

Look at what is in the data directory (`./data` by default) before running anything.
Note which of the five datasets are present: citations, backlinks, authority,
competitors, content gaps. The document's credibility depends on being straight about
which sections rest on real data and which rest on an assumption, so establish that now
rather than discovering it while writing.

If the brand's own domain is not obvious from the files, ask. Getting it wrong inverts
the central join and every recommendation downstream, which is the one error in this
workflow that is not recoverable by editing later.

### Step 2 - Normalize

```bash
python3 scripts/normalize.py --data-dir ./data --out ./build/normalized.json \
    --brand-domain example.com --brand-name "Example"
```

Vendors all name the same column differently, so this maps them onto one schema. Read
its output rather than skimming past it. Two lines matter:

- **`UNCLASSIFIED` files.** The script could not tell what a file was. Open it, look at
  the headers, and either rename the columns or add the aliases to `SCHEMAS` in
  `scripts/normalize.py`. Never let a file drop silently.
- **`missing:` fields.** A canonical field that found no column. Some are harmless
  (`sentiment` is often absent). Others quietly change conclusions - if `cited_domain`
  is missing from the citation file, the central join has nothing to work with.

`references/intake-schema.md` has the full schema, the vendor-by-vendor export
instructions, and what to do when a needed field simply does not exist.

### Step 3 - Analyze

```bash
python3 scripts/analyze.py --in ./build/normalized.json --out ./build/analysis.json
```

This computes visibility by engine, the citation-source graph and its tiering, the
authority position, backlink profile health, and a winnability score for every topic.

It is deliberately the only place arithmetic happens. Percentages, medians, gaps and
scores are easy to get subtly wrong in prose and impossible for a reader to audit, so
they are computed once, saved, and quoted from there. When writing, quote
`analysis.json`; do not recompute a figure in your head.

Read the coverage warnings it prints. They constrain what the document may claim, and
they belong in §8 verbatim.

`references/scoring-models.md` explains what each score means, how the weights are set,
and when to retune them for a vertical.

### Step 4 - Render the skeleton

```bash
python3 scripts/render_report.py --in ./build/analysis.json --out ./build/report-draft.md
```

This writes every table that is pure arithmetic and leaves `<!-- ANALYST: ... -->`
markers and `_TBD_` cells wherever judgment is required. It prints how many slots
there are.

### Step 5 - Write the strategy

Fill every slot. This is the part that is actually worth the reader's time, and the
part the scripts cannot do: a script can rank `g2.com` as a T1 target, but only you can
say that the play there is a review-velocity campaign aimed at the "best HR software
for small business" prompt, resourced by the customer success team.

Work section by section, consulting the reference file for each:

| Section | Reference to read first |
|---|---|
| §3 Tactical outreach | `references/outreach-playbook.md` |
| §4 PR and earned media | `references/pr-partnerships.md` |
| §5 Partnerships and awards | `references/pr-partnerships.md` |
| §6 Content roadmap | `references/content-roadmap.md` |

Then check the result against `references/deliverable-template.md`, which sets the
quality bar for each section and lists the failure modes that make this kind of
document get ignored.

Confirm no `<!-- ANALYST:` markers or `_TBD_` cells survive:

```bash
grep -n "ANALYST:\|_TBD_" ./build/report-draft.md
```

### Step 6 - Deliver

Save the finished document. Ask the user where it should go if it is not obvious - a
markdown file in the repo, a published page, or a document connector are all
reasonable, and the right answer depends on who has to read it.

## Writing standards

These are what separate a document that gets acted on from one that gets skimmed.

**Name things.** "Pitch relevant industry publications" is not a recommendation.
"Pitch `hrdive.com` with the turnover-benchmark cut, because they cited three rivals on
that prompt and have no original data of their own" is. Every target, every asset,
every award has a name, and every action has an owner slot and a date.

**Distinguish evidence from inference.** The data shows the brand is absent from a
prompt; *why* it is absent is your hypothesis. Mark the difference. A reader who cannot
tell which is which will either over-trust the whole thing or dismiss it.

**Say what to stop.** A plan that only adds work will not be executed by a team that is
already fully committed. §4's process changes in particular should name at least one
thing that should stop or shrink.

**Respect the sequencing.** H3 topics are H3 *because* current authority cannot carry
them. If the roadmap tells the team to start there, the quarter is wasted. Make the
dependency explicit: these authority plays in §3-5 are what unlock the H3 content in §6.

**Keep the numbers honest.** Scores rank opportunities against each other inside one
dataset. They are not absolute, not comparable across brands, and not comparable across
export dates. Say so in §8 and do not let a score leak into the executive summary as if
it were a measurement.

**State the limits plainly.** If there is no backlink data, the central join did not
run, and the outreach list is ranked on citation frequency alone. That is still useful,
but the reader has to know. Put it in §8 and reference it wherever it bites.

## Handling partial data

Rarely does a brand have all five datasets. The document still gets written; what
changes is what it may claim.

| Missing | Effect | What to do |
|---|---|---|
| Citations | No GEO findings at all. The central join cannot run. | Say so up front. Run it as a classic link-gap and content audit, and make acquiring citation data the first recommendation. |
| Backlinks | Cannot tell which cited domains already link to you. | Tier on citation frequency and authority alone. Flag that T1/HELD split as unverified. |
| Authority / competitors | Winnability falls back to a neutral prior and reads optimistic. | Lean on foothold and format fit, which are still observed. Caveat the horizons. |
| Content gaps | Roadmap is built only from AI prompts. | Fine for a GEO-led brief; note that classic search demand is unrepresented. |
| Competitor backlinks | No link-gap or competitive-displacement tier. | Work T1 and T3 only. Recommend a link-intersect export next cycle. |

When a section has no data behind it, write it as an instrumentation recommendation
rather than padding it with generic best practice. A reader can tell the difference,
and generic filler is what makes the rest of the document suspect.

## Bundled resources

```
scripts/
  normalize.py       Map vendor exports onto one schema; reports what it could not place
  analyze.py         Visibility, source graph, tiering, authority, winnability scoring
  render_report.py   Render the factual skeleton with marked slots for judgment
references/
  intake-schema.md     Canonical schema, per-vendor export steps, partial-data handling
  scoring-models.md    What each score means, how weights are set, when to retune
  outreach-playbook.md Tier-by-tier outreach motions, pitch construction, sequencing
  pr-partnerships.md   PR SEO process, campaign patterns, review platforms, awards calendar
  content-roadmap.md   Winnability in practice, brief format, AEO page construction
  deliverable-template.md  Full section-by-section structure and quality bar
assets/sample-data/  A complete five-file fictional dataset for testing the pipeline
```

To see the whole pipeline work before pointing it at real data:

```bash
python3 scripts/normalize.py --data-dir assets/sample-data --out /tmp/n.json
python3 scripts/analyze.py --in /tmp/n.json --out /tmp/a.json
python3 scripts/render_report.py --in /tmp/a.json --out /tmp/draft.md
```
