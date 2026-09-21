# SEO-AEO-GEO-Trail-Guide

An analysis engine that turns GEO/AEO and SEO data exports into an actionable authority
strategy document.

It ingests AI answer-engine citations, backlink profiles, domain authority and
competitor metrics, and content gap reports, then produces a single document covering
tactical link and citation outreach, PR process changes, marketing partnerships and
awards, and a content roadmap split into quick wins versus long-term authority building.

## The core idea

Most SEO audits rank link targets by Domain Rating. Most GEO reports list the prompts
where a brand is missing. Neither tells you where to actually go.

This engine joins the two:

> Take the domains answer engines actually cite for your prompt set. Subtract the domains
> that already link to you. What remains is the working list.

That remainder is higher-leverage than a DR-sorted list, because a placement on one of
those domains does two jobs at once — it earns a backlink, and it inserts the brand into
the text engines are demonstrably retrieving when someone asks about the category. A
DR 90 domain that has never surfaced in an answer for your prompts does only the first.

Every output section is a different route to that same target list, sorted by what kind
of domain it is: editorial sources go to outreach, news to PR, review platforms and
awards bodies to partnerships, and prompts where nobody is cited well become the content
roadmap.

## Usage

Built as a Claude Code skill. Drop exports in `data/` and ask:

```
Analyze the SEO and GEO data in ./data and build the strategy document
```

The skill triggers on requests about AI visibility, citation gaps, link targets,
outreach lists, PR strategy, or content prioritisation — including narrow slices like
"which keywords can we actually win".

To run the pipeline directly, or to see it work on the bundled sample dataset, see
[`data/README.md`](data/README.md).

## What it produces

A document in eight sections: executive summary and scorecard, competitive standing,
the citation-source graph, tiered outreach targets, PR process and campaigns,
partnerships and an awards calendar, a horizon-bucketed content roadmap, and a
methodology section carrying the data-coverage limitations.

Deterministic arithmetic — scores, medians, gaps, tiering — is computed once by the
analysis scripts and quoted from there, so no figure in the document is derived in
prose. The scripts leave marked slots wherever the work requires judgment rather than
calculation.

## Layout

```
.claude/skills/geo-seo-trail-guide/
  SKILL.md                      Workflow and writing standards
  scripts/
    normalize.py                Map vendor exports onto one schema
    analyze.py                  Visibility, source graph, tiering, winnability scoring
    render_report.py            Render the factual skeleton with analyst slots
  references/
    intake-schema.md            Canonical schema, per-vendor exports, partial data
    scoring-models.md           What each score means and when to retune it
    outreach-playbook.md        Tier-by-tier motions, pitch construction, sequencing
    pr-partnerships.md          PR process, campaigns, review platforms, awards
    content-roadmap.md          Winnability in practice, brief format, AEO pages
    deliverable-template.md     Section-by-section quality bar and checklist
  assets/sample-data/           Complete fictional five-file dataset for testing
data/                           Your exports go here
```

## Scope

Scores rank opportunities against each other within a single dataset. They are not
absolute measures and are not comparable across brands or across export dates. The
engine reports what its data cannot support rather than filling the gap — a section
without data behind it becomes an instrumentation recommendation, not generic best
practice.
