# Deliverable structure and quality bar

`render_report.py` produces the skeleton. This says what each section has to achieve,
and what makes one fail. Use it as a checklist before delivering.

## Contents

- [Who is reading this](#who-is-reading-this)
- [Section by section](#section-by-section)
- [Failure modes](#failure-modes)
- [Pre-delivery checklist](#pre-delivery-checklist)

## Who is reading this

Three readers, and the document has to survive all three:

- **The person who funds it** reads §0 and §7 and nothing else. Those two sections must
  stand alone and must agree with each other.
- **The person who runs it** reads §§3–6 and works from the tables. Every row needs an
  owner, a date and a next action.
- **The sceptic** reads §8 first to decide whether to trust the rest. Do not bury the
  limitations; a document that states its own weaknesses is far harder to dismiss than
  one that appears seamless.

## Section by section

### §0 Executive summary

Five to seven sentences. Lead with the most consequential finding — usually the citation
gap from §2 — and name the one number that should change this quarter and what moves it.

Fails when: it restates the brief, opens with methodology, or hedges every claim. If the
reader cannot tell from §0 what the argument is, rewrite it.

**Scorecard.** Script-generated. Do not editorialise inside the table; interpret
underneath.

### §1 Where you stand

Script-generated tables plus interpretation. The tables are not the point; the mismatch
between them is.

The two readings worth looking for:

- **High DR, low answer share.** A retrieval and formatting problem, not an authority
  problem. The brand has earned authority the engines are not picking up — which is good
  news, because formatting is fast.
- **Low DR, decent answer share.** Visibility resting on borrowed authority, usually a
  handful of third-party pages. Fragile: if one roundup drops you, share falls with it.
  Diversify the source base before it happens.

Fails when: it narrates the tables back at the reader. Anyone can read a table. Say what
the combination means.

### §2 The citation-source graph

The pivot of the document. Everything downstream is a route into this list.

Must establish: how many domains engines cite, how many already link to you, and what
kind of sources the category runs on. The archetype mix dictates the motion — say which
one this brand faces, because a review-platform-dominated category and a news-dominated
one need different teams doing different work.

Fails when: it presents the table without the argument. The reader must finish this
section understanding *why* these domains matter more than a DR-sorted list.

### §3 Tactical outreach

The working list. Every row needs an angle, an owner and a date — the Angle column is
where the document earns its fee. "Guest post" is not an angle; it is the absence of one.

Must include: what asset exists or must be built before outreach starts, and the first
30 days concretely — volume per week, who sends, follow-up cadence.

See `outreach-playbook.md`.

Fails when: the angles are generic, or the plan assumes a linkable asset that does not
exist.

### §4 PR and earned media

Two parts, both required.

**Process changes.** How PR is run, not what campaigns to run. Grounded in this dataset.
Must name at least one thing that stops.

**Campaign concepts.** Two or three, each with a hook, the asset behind it, named target
publications from §2, a spokesperson, and a timeline.

See `pr-partnerships.md`.

Fails when: concepts are interchangeable with any brand in any category, or when it only
adds work and never subtracts.

### §5 Marketing partnerships

Review platforms, databases, entity records, communities, co-marketing, and the awards
calendar. Each play names the partner or platform, the motion, and the owner — and the
owner is frequently outside marketing, which is the point of separating this from §3.

The awards calendar needs programme, category, deadline, fee, owner, and the prompt a
win supports. **Verify every deadline and fee before publishing.** A calendar with stale
dates discredits the document.

See `pr-partnerships.md`.

Fails when: the review-platform work is assigned to marketing (it belongs to customer
success), or awards appear with no deadline, fee or owner.

### §6 Content roadmap

Horizon tables are script-generated. Add: the asset per topic, briefs for the top H1s,
the refresh-versus-new split, and the sequencing argument.

The sequencing argument is not optional. Someone will read §6 in isolation and want to
start at the H3 head term.

See `content-roadmap.md`.

Fails when: H1 is padded with things that are not quick wins, or briefs lack the 40–60
word direct answer — the single field that determines whether the page gets quoted.

### §7 90-day plan

Month by month: workstream, action drawn from §§3–6, owner, metric moved. Then baselines
from the scorecard, targets, and re-measurement cadence.

Constrain it to what the team can absorb. Forty actions is zero actions. If §§3–6
generated more work than the team can do, choosing is your job, not the reader's.

Fails when: it is a list of everything above rather than a sequenced subset, or targets
are set without baselines.

### §8 Methodology and coverage

Script-generated, with the coverage warnings verbatim. Add any weight retuning and the
caveat that scores are relative to this dataset.

Fails when: the warnings are softened. They are what makes the rest credible.

## Failure modes

**Generic recommendations.** The commonest failure. "Build high-quality backlinks",
"leverage PR", "create valuable content" — true, useless, and a signal the analyst did
not read the data. Every recommendation names a domain, a publication, a topic or a
programme.

**Unsequenced everything.** Listing all opportunities without ordering them hands the
prioritisation problem back to the reader, which was the job.

**Evidence and inference blurred.** The data shows absence from a prompt; *why* is a
hypothesis. Mark the difference. This is what lets a reader trust the parts that are
observed.

**Scores presented as measurements.** A target score of 72 is a rank position, not a
property of the domain. Keep raw scores out of §0.

**Ignoring the authority ceiling.** Recommending H3 content for month one. The data says
it cannot be won yet; overriding that with optimism costs a quarter.

**Silent data gaps.** A section written as though data existed when it did not. If
citations are missing, say the GEO findings are unsupported and make instrumentation the
first recommendation.

**No owners.** A plan with no names is a wish list. Every action gets an owner slot even
when you do not know the names — leave `_owner_` for the client to fill rather than
dropping the column.

**Padding.** If a section has no data behind it, write it as an instrumentation
recommendation instead of filling it with best practice. Readers can tell, and filler in
one section makes the whole document suspect.

## Pre-delivery checklist

```bash
grep -n "ANALYST:\|_TBD_" ./build/report-draft.md   # must return nothing
```

- [ ] Every `<!-- ANALYST: -->` marker replaced; no `_TBD_` cells remain
- [ ] §0 leads with a finding, names one number to move, and stands alone
- [ ] Every §3 row has an angle, an owner slot and a date
- [ ] §3 names the linkable asset, or schedules building it before outreach
- [ ] §4 names at least one thing to stop
- [ ] §4 campaigns could not be pasted into a competitor's deck unchanged
- [ ] §5 awards have verified deadlines, fees and owners
- [ ] §5 review-platform work is owned by customer success, not marketing
- [ ] §6 H1 topics are genuinely 90-day, and each top brief has its 40–60 word answer
- [ ] §6 states the refresh-versus-new split
- [ ] The sequencing argument (§§3–5 unlock §6 H3) appears explicitly
- [ ] §7 fits the team's actual capacity and has baselines
- [ ] §8 carries the coverage warnings unsoftened
- [ ] No score appears in §0 as though it were a measurement
- [ ] Crawler access (`GPTBot`, `ClaudeBot`, `PerplexityBot`, `Google-Extended`) checked —
      if blocked, it is the first line of §0
