# Scoring models

Two composite scores drive the document: **target score** ranks outreach destinations,
**winnability** ranks topics. Both live in `scripts/analyze.py`, both expose their
weights at the top of the file, and both emit their components so any row can be
explained.

Read this before defending a ranking to a client, and before retuning weights for a
vertical.

## Contents

- [What these scores are and are not](#what-these-scores-are-and-are-not)
- [Target score](#target-score)
- [Tiering](#tiering)
- [Winnability](#winnability)
- [Horizons](#horizons)
- [Retuning by vertical](#retuning-by-vertical)
- [Explaining a score](#explaining-a-score)

## What these scores are and are not

They rank opportunities **against each other within one dataset**. That is all.

A target score of 72 does not mean anything in isolation. It is not comparable to a 72
computed for another brand, in another category, or from an export taken a month later
with a different prompt set. The scores exist to answer "what do we do first," which is
a question about ordering, not about absolute merit.

Say this in §8 of the document, and do not let a raw score appear in the executive
summary as though it were a measurement. "22 domains cite us in the answer layer and do
not link to us" is a finding. "Average target score 61.4" is noise.

## Target score

Ranks each cited domain as an outreach destination, 0–100.

| Component | Weight | What it measures | Why it is weighted this way |
|---|---|---|---|
| `citation_frequency` | 0.32 | Prompts this domain is cited on, over a saturation point of 15% of the prompt set | The strongest available evidence that engines treat this domain as a source for your category. It carries the most weight because it is the thing a DR-sorted list cannot see. |
| `engine_breadth` | 0.14 | Distinct engines citing it, over engines tracked | A domain cited by four engines is a fixture. One cited by a single engine may be that engine's quirk. |
| `authority` | 0.18 | DR / 100 | Still governs the link equity a placement passes. Deliberately below citation frequency: a cited DR 55 trade title beats an uncited DR 90 general title. |
| `attainability` | 0.20 | Falls linearly as the target's DR exceeds yours, reaching 0 at +60 | Ranks unreachable targets down. A list topped by destinations you will never land is worse than useless — it burns the team's quarter. |
| `competitive_proof` | 0.16 | Covers rivals via citation or link | Proof the door opens for a brand at your level. Converts "they might cover us" into "they cover companies like us." |

### Two details that matter when reading the ranking

**The frequency scale adapts to the dataset.** `citation_frequency` saturates at the
90th percentile of observed prompt counts, not at a fixed fraction of the prompt set. A
fixed threshold collapses the top of the ranking in any category with many
frequently-cited domains — six domains tie at the maximum and the ordering becomes
arbitrary exactly where it matters most. Anchoring to the observed distribution means
roughly the top tenth max out and everything beneath stays separable.

**A missing DR is filled with the median, not a low default.** Roughly half of cited
domains typically have no authority figure in the supplied data, because they appear in
the citation export but not the backlink export. Scoring them at a flat low value
buries real opportunities; scoring them at a flat mid value like 45 is worse, because
it hands them near-maximum attainability and floats unknown domains *above* known ones.
The median of the domains that do have a figure keeps the unknown neutral. These show as
`~N est` in the tables and are disclosed in §8 — never let an estimate read as a
measurement.

Note the intended consequence for very high DR targets: a DR 94 national title cited on
two-thirds of the prompt set will still rank below a DR 58 trade title cited just as
often, because attainability discounts it. That is correct. The trade title is where the
placement actually happens this quarter.

## Tiering

Tiers are assigned by **motion required**, not by score, because two domains with the
same score can need completely different work. Work them in order.

**T1 — Citation gap.** Cited on 2+ prompts, no link to you. The highest-leverage list
in the document: a placement earns a link *and* inserts you into text the engines are
already retrieving. Exhaust T1 before starting T3.

**T2 — Competitive displacement.** No link to you, but they cover rivals. The
relationship is proven reachable at your level; you are simply not in the piece. Often
the fastest conversions, because the format already exists and you are asking to be
added to it.

**T3 — Authority build.** In the citation graph, no relationship. Slower and warmer,
usually PR or partnership rather than an outreach email.

**HELD — Already linking.** Defend and deepen. Refresh the placement, update stale
figures, and check that what they say about you is still accurate — an outdated claim in
a frequently-cited source propagates into answers for a long time.

**Pure link gap.** Never observed in an answer, but links to 2+ rivals. Classic SEO
opportunity; builds authority without moving answer share directly. Work after T1–T2.

## Winnability

Ranks topics 0–100 on how realistically the brand can own the answer.

| Component | Weight | What it measures |
|---|---|---|
| `foothold` | 0.28 | Existing rank, or partial citation across engines |
| `authority_fit` | 0.24 | Whether a domain this size can hold the ground |
| `contest` | 0.18 | Inverse of how many rivals hold it |
| `format_fit` | 0.16 | Whether the query shape is one engines quote |
| `ease` | 0.14 | Inverse keyword difficulty |

**Foothold** is weighted highest because moving position 8 to position 3 is a different
order of work than building from nothing, and the data tells you which you are facing.
Note that ranking 1–3 scores *lower* (0.55) than ranking 4–10 (1.00): you have already
won that search result, so the remaining upside is AEO formatting, not ranking work.

**Authority fit** starts from the sitewide DR gap to the competitor median, on a gentle
slope — a challenger 30–40 DR below the category median is the normal case, not a
disqualification — then gets adjusted down where keyword difficulty exceeds the brand's
DR.

Critically, **an observed ranking overrides both priors**. If a page already sits at #4,
the question of whether a domain this size *could* rank there has been settled
empirically, so fit is floored at 0.75. The same applies to prompts already cited in at
least one engine: the engines have accepted the domain as a source for that question.
Without this override the component collapses to zero for every challenger brand and
contributes nothing but a flat penalty.

**Format fit** scores the query's shape. Ranked lists ("best X"), head-to-head
comparisons, and alternatives pages score highest; open-ended informational queries
score lowest. This is not a proxy for search intent — it measures how liftable an answer
is. An LLM synthesising a response reaches for a clean ranked list or a definition it
can quote whole.

**Priority** then modulates winnability by commercial value:
`priority = winnability × (0.55 + 0.45 × value)`. Value never zeroes a topic, because a
highly winnable low-volume topic is still worth shipping — it just should not outrank a
winnable high-volume one.

## Horizons

| Horizon | Winnability | Window | Meaning |
|---|---|---|---|
| H1 | ≥ 65 | 0–90 days | Foothold exists, field is thin, or format is easily quoted. Ship first. |
| H2 | 42–64 | 90–180 days | Winnable with a real asset behind it. |
| H3 | < 42 | 180–365+ days | Out of reach at current authority. |

The dependency is the point: **H3 topics are H3 because authority cannot carry them
yet.** The outreach, PR, and partnership work in §§3–5 is what raises that ceiling. A
roadmap that sends the team at H3 head terms in month one wastes the quarter. Make the
sequencing explicit in the document.

## Retuning by vertical

The defaults suit a mid-market B2B brand challenging larger incumbents. Edit the weight
dictionaries at the top of `analyze.py` and say in §8 that you did.

**Regulated industries** (health, finance, legal). Engines lean hard on institutional
and high-trust sources. Raise `authority` to ~0.25, cut `attainability` to ~0.13.
Expect fewer H1 topics and do not fight it.

**Fast-moving consumer categories.** Freshness and community sources dominate. Raise
`citation_frequency` to ~0.38, cut `authority` to ~0.12.

**Enterprise / considered purchase.** Analyst and review platforms carry the category.
Raise `competitive_proof` to ~0.22 — if they cover your rivals and not you, that is the
whole problem.

**Local or regional.** Directories and local press matter more than DR. Cut `authority`
to ~0.10, raise `attainability` to ~0.28.

**Very low authority** (DR < 20). Attainability will suppress nearly everything good.
Either raise it to ~0.30 and accept a conservative list, or work `pure_link_gap` and T2
first and treat T1 as a twelve-month goal.

## Explaining a score

Every scored row carries a `components` object, so any ranking can be decomposed rather
than asserted. In the document, explain rankings in prose rather than printing
component values — the reader wants the reasoning, not the arithmetic:

> `hrdive.com` ranks third not because of its DR 74, which is unremarkable here, but
> because four engines cited it across six of our prompts while it links to three
> competitors and not to us. It is reachable, it is trusted by the engines, and it
> already covers companies our size.

That is the same information as `citation_frequency 0.85, competitive_proof 1.0`, in a
form a CMO can act on.
