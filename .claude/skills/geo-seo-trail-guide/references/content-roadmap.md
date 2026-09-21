# Content roadmap

Section 6 of the deliverable. The analysis hands you a ranked, horizon-bucketed topic
list; this is how to turn it into briefs a writer can execute and a plan a director can
fund.

## Contents

- [Reading the horizons](#reading-the-horizons)
- [The sequencing argument](#the-sequencing-argument)
- [Choosing the asset](#choosing-the-asset)
- [The brief format](#the-brief-format)
- [Writing pages engines quote](#writing-pages-engines-quote)
- [Uncontested prompts](#uncontested-prompts)
- [Refresh over net-new](#refresh-over-net-new)
- [Measurement](#measurement)

## Reading the horizons

**H1, 0–90 days.** Winnability ≥ 65. Almost always one of three situations: the brand
ranks 4–20 and needs a better asset, it is cited in some engines but not others, or the
topic is thinly contested. These move the scorecard inside a quarter, which matters
beyond the traffic — an early, visible win is what buys the programme room to run the
slower work.

**H2, 90–180 days.** Winnability 42–64. Winnable with a genuine asset and usually some
link support. These are where most of the durable traffic ends up.

**H3, 180–365+ days.** Winnability < 42. Head terms and high-competition commercial
queries the brand cannot hold yet. Real targets, wrong quarter.

Do not pad H1 by lowering the bar. A roadmap whose "quick wins" take nine months
destroys trust in the rest of the document.

## The sequencing argument

Make this explicit, because it is the part most likely to be overridden by someone who
skips to §6 and sees the head term they have wanted for two years:

> H3 topics are H3 **because current authority cannot carry them**. The outreach, PR and
> partnership work in §§3–5 is what raises the ceiling. Attempting H3 content in month
> one produces a good page that ranks nowhere and cites nobody, and burns a quarter of
> writer capacity finding that out.

A useful framing for the reader: §§3–5 raise the ceiling, §6 fills the room underneath
it. Re-run the analysis after a quarter of authority work and topics migrate from H3 to
H2 on their own — that migration is a good metric to promise, and a good reason to
re-export data on a schedule.

## Choosing the asset

Match the asset to the query's shape, which the analysis records as `answer_format`.
The shape determines what an engine can lift.

| Format | Asset | What makes it citable |
|---|---|---|
| Ranked list ("best X") | Curated comparison with explicit criteria | A real table with named criteria. Self-serving lists that rank you first are discounted by readers and engines both. |
| Head-to-head ("X vs Y") | Comparison page | Honest treatment of where the competitor wins. One-sided pages do not get cited. |
| Alternatives | Alternatives page including yourself, ranked honestly | Same discipline. |
| Definition ("what is X") | Reference page | A 40–60 word definition in the first paragraph, before any context. |
| How-to | Step-by-step guide | Numbered steps, each independently parseable. |
| Pricing | Pricing explainer with real numbers | Actual figures. "Contact us" is unciteable. |
| Template / checklist | Downloadable plus full inline version | The inline version is what gets retrieved; a gated PDF is invisible. |
| Data / benchmark | Original research | Your own numbers. This is the asset class that earns links *and* citations. |

Two of these carry a counter-intuitive discipline worth stating in the document.
Comparison and alternatives pages **must** be honest about where competitors win: engines
synthesise across many sources, so a page contradicting the consensus reads as an
outlier and gets discounted. A page that concedes the competitor's genuine advantage and
explains who should choose which is the one that gets quoted. Similarly, gating an asset
removes it from the corpus entirely — publish the full version inline and offer the
download as convenience, not as a toll.

## The brief format

For each H1 topic and the top H2s, one brief. Keep it to this — longer briefs do not
produce better pages:

```
Topic:            [from the roadmap table]
Horizon / rank:   H1 #3  (winnability 78, priority 66)
Current position: [foothold_note from the analysis]
Answer format:    [answer_format from the analysis]
Target prompts:   [the AI prompts and search queries this must satisfy]

Direct answer (40-60 words, opens the page):
  [Write it here. This exact text is what gets lifted into an AI answer.
   If it cannot be written in 60 words, the topic is too broad - split it.]

Structure:
  H1: [question-shaped]
  H2: [sub-question] -> [what answers it]
  H2: [sub-question] -> [what answers it]
  Table: [what it compares, which columns]

Evidence required:  [original data, customer examples, expert quote, sources to cite]
Internal links:     [from which existing pages, with what anchor]
Schema:             [Article / FAQPage / Product]
Distribution:       [which §3 targets this asset supports]
Owner / due:        [name, date]
Success metric:     [rank target, or citation in named engines, by date]
```

The **direct answer** is the highest-leverage field. Write it yourself rather than
leaving it to the writer, because it is the specific text that determines whether this
page becomes the quoted answer. The 60-word constraint is also a useful scope test: a
topic that cannot be answered that concisely is two topics.

The **distribution** field is what stops §6 from drifting away from §3. Every major
asset should have an outreach purpose, and every T1 target should have an asset behind
it. If an H1 brief supports no target and no target needs it, question whether it earns
a slot this quarter.

## Writing pages engines quote

Retrieval works on chunks, not pages. A page is a set of independently retrievable
passages, and it should be built that way.

**Answer first.** The direct answer in the opening paragraph, before context, history or
positioning. A page that buries its answer under 600 words of preamble supplies no clean
chunk to lift.

**Question-shaped headings.** Match how people actually ask. Each H2 should be
answerable in the two or three paragraphs beneath it without reference to the rest of
the page.

**Self-contained passages.** Avoid "as mentioned above". A retrieved chunk arrives
without its neighbours.

**Tables for anything comparative.** Highly extractable and disproportionately quoted.

**Specifics over adjectives.** "Deploys in 3 days" is quotable; "fast deployment" is
not. Numbers, dates, named entities and concrete claims are what survive synthesis.

**Cite your sources.** Pages that cite credible sources are treated as more reliable,
and the outbound links cost nothing.

**Real authorship.** A named author with credentials, `Person` schema, and a consistent
presence across the site.

**Visible freshness.** Accurate last-updated dates, with actual updates behind them.

## Uncontested prompts

The analysis surfaces prompts where no competitor is named and few sources are cited —
the engines are answering from thin ground. These are the cheapest wins available and
are easy to overlook because their search volume is often unremarkable.

Treat them as a distinct workstream. A single well-formatted page can take the answer
outright, and low competition means it holds. When one appears with meaningful
commercial intent, it should outrank higher-volume H1 topics in the sequence.

## Refresh over net-new

Most roadmaps over-weight new pages. The data usually argues otherwise: a topic at rank
7 with an existing page is a refresh, and a refresh ships in days rather than weeks.

Check `foothold_note` before commissioning anything. "Ranks #7 — striking distance"
means upgrade the page that exists: add the direct answer up top, add the comparison
table, update stale figures, strengthen internal links, add schema. Expect to spend
about 20% of the effort of a new page for a larger share of the movement.

State the split explicitly in §6 — "eight refreshes, four new pages" is a resourcing
answer a content director can act on, where "twelve topics" is not.

## Measurement

| Metric | Cadence | Note |
|---|---|---|
| Rank for target topics | Monthly | Leading indicator |
| Citation in named engines | Monthly | Re-export citations with a stable prompt set |
| Answer share overall | Monthly | The headline scorecard number |
| H3 → H2 migration | Quarterly | Proof the §§3–5 authority work is landing |
| Assisted conversions | Quarterly | Ties the programme to revenue |

Set expectations on lag in the document. A refreshed page can move search rank in weeks,
but appearing in AI answers depends on each engine's re-crawl and index cycle, which
commonly runs four to twelve weeks behind — and varies by engine. Teams that do not know
this conclude the programme failed in month two, which is exactly when the earliest work
is about to land.
