# Methodology

How the two points of view translate into code, and what each number is actually
claiming. If you are going to defend an output in front of a client, read this
first.

---

## 1. The measurement gap

Both POVs open on the same problem: referrer-based analytics capture only part of
search and LLM influence. Demand goes missing because it is

- satisfied on the SERP (featured snippets, Knowledge Panels, AI Overviews),
- satisfied inside an assistant and never reaches the site,
- redirected as direct traffic when someone types the URL later,
- miscategorised as branded search after an unbranded discovery,
- stripped of its referrer by privacy settings, ITP or HTTPS-to-HTTP transitions.

A strategy built only on referrer data understates SEO and AEO/GEO contribution,
and so understates ROI. Every projection in this system is therefore computed
across two tracks.

## 2. The two-track model

```
Total attributed value = Track 1 (known attribution)
                       + Track 2 (modeled dark traffic)
```

| | Track 1 | Track 2 |
| --- | --- | --- |
| Definition | Visits and revenue with a traceable referrer | Modeled visits and revenue from zero-click visibility, LLM influence and unassigned sessions |
| Sources | GA4, Search Console, server logs, CRM | GSC impressions, citation panel, branded/direct lift, surveys, third-party benchmarks |
| Confidence | High — directly observed | Directional — a modeled range, refined over time |
| Cadence | Continuous | Monthly refresh, quarterly recalibration |

Implemented in `analysis/dark_traffic.py`. Track 1 comes from the channel series
built out of analytics records; Track 2 is the blended estimator output.

The two tracks stay separate all the way into the report (`ValueProjection`
carries `known_revenue` and `dark_revenue` as distinct fields) so a client can
accept the observed number and interrogate the modeled one independently.

## 3. Triangulating Track 2

Both POVs insist on converging methods rather than a single model. Five
estimator families run against whatever inputs exist. Each returns its own
number, confidence and stated assumptions.

### Dark organic (SEO and AEO)

| Method | What it measures | Confidence | Function |
| --- | --- | --- | --- |
| `zero_click_ctr_gap` | Clicks the SERP withheld: expected CTR at the observed position minus the CTR actually earned | 0.60 | `estimate_zero_click` |
| `branded_direct_lift` | Direct traffic that co-moves with non-branded organic, after removing email and social | 0.55 × r² | `estimate_branded_lift` |
| `third_party_benchmark` | Published dark-organic baselines | 0.35 | `estimate_benchmark` |
| `survey_calibration` | Self-reported search discovery versus attributed organic | 0.60 × sample factor | `estimate_survey_seo` |

### Dark LLM influence (GEO)

| Method | What it measures | Confidence | Function |
| --- | --- | --- | --- |
| `survey_calibration` | Customers crediting an AI assistant, net of observed LLM referrals | 0.60 × sample factor | `estimate_survey_ai` |
| `citation_share` | Prominence-weighted prompt exposure across engines | 0.45 | `estimate_citation_share` |
| `third_party_benchmark` | Total LLM influence as a multiple of observed referrals | 0.35 | `estimate_benchmark` |
| `crawler_retrieval` | AI crawler retrieval volume from server logs | 0.30 | `estimate_crawler_retrieval` |

### Blending

- **Point estimate** — confidence-weighted mean across available estimators.
- **Range** — the spread between the lowest and highest estimator. When methods
  disagree the range widens; it does not harden into a false consensus.
- **Confidence** — weighted mean, plus up to a 0.20 bonus when independent
  methods converge. Agreement is itself evidence.
- **Unavailable methods** are listed with the reason, never silently skipped.
  An estimator with no inputs contributes nothing rather than a guess.

### Two corrections worth knowing about

**Units.** The survey estimator converts conversions back into sessions using
the *observed* analytics conversion rate, not the funnel model's
session-to-closed-won rate. An analytics "conversion" is usually a lead;
dividing leads by a closed-won rate mixes units and inflates the estimate by
orders of magnitude.

**Annualization.** The zero-click estimator annualizes via
`keyword_periods_per_year` (default 12, i.e. a one-month Search Console
window). If your keyword export covers a different window, change it — the other
estimators are already annual, and mixing bases silently skews the blend.

## 4. Which surface gets which multiplier

This distinction matters and is easy to get wrong.

| Surface | Multiplier | Why |
| --- | --- | --- |
| SEO | organic | Ranking work earns organic clicks; its dark traffic is zero-click and unassigned demand |
| **AEO** | **organic** | Snippets, PAA and AI Overviews are won *on the Google SERP* and earn organic clicks. Applying the LLM referral multiplier here would value an organic click as an assistant referral |
| GEO | none applied | Generative opportunities are sized *directly as shares of the modeled LLM-influenced pool*, so grossing them up again would count that pool twice |
| TECHNICAL, CONVERSION, DISTRIBUTION | none | These convert or amplify existing demand rather than creating new demand |

The consequence: generative opportunities can never claim more influence than
Track 2 says exists. The plausibility guard in `pipeline.py` enforces it.

## 5. Sessions to revenue

`core/economics.py` translates sessions into money, and nothing else does.

- **Ecommerce**: sessions → conversions → revenue, via conversion rate and AOV.
- **B2B**: sessions → leads → MQL → SQL → closed won, via stage rates and ACV.
  The sales cycle adds a revenue lag on top of the SEO lag, so a Q1 ranking win
  lands as Q2 or Q3 revenue.

Three rules keep this honest:

1. **Observed beats modeled.** A page with measured revenue per session uses it,
   capped at 5× the site model so one freak-converting URL cannot dominate.
2. **Intent is priced.** Transactional and informational traffic are not worth
   the same per session; `intent_multipliers` and `template_multipliers` price
   the difference.
3. **The CRM wins.** When a funnel export is supplied, observed stage rates and
   deal values replace the configured assumptions, and every substitution is
   reported. Ratios are only adopted when volume supports them and the result is
   plausible, so a sparse export cannot quietly wreck the model.

## 6. Overlap: not selling the same click twice

Several analyzers can legitimately find the same keyword. A query might be in
striking distance, split across two cannibalizing URLs, *and* have an unclaimed
featured snippet. Each analysis is right in isolation; summing all three sells
the same clicks three times.

`prioritize/overlap.py` resolves this. Opportunities competing for the same
**demand pool** share the value of any entity they both claim:

- `search` — SEO and AEO opportunities, plus crawl-health recovery
- `generative` — GEO opportunities
- *no pool* — conversion, performance and distribution work, which claims no
  additional demand and keeps its full value

The split is equal per claimant. A value-weighted split would be more precise
but needs a per-entity value breakdown the analyzers do not produce; an equal
split is conservative and easy to explain, which matters more in a number a
client will challenge. Every adjustment is attached to the opportunity as
evidence, so the discount is visible rather than silent.

Analyzers claim demand at two levels - some name keywords, others name URLs -
so before contention is counted, a page-level claim is expanded into the
keywords that page is observed to rank for, drawn from the keyword records
themselves. A decaying page and a striking-distance keyword on that page are the
same clicks, and without the expansion both billed for them in full. The
expansion is impression-weighted, so contesting one minor query on a page that
ranks for fifty barely moves the page-level projection while contesting its head
term takes a real bite.

A keyword export never shows everything a page ranks for: Search Console hides
anonymized long-tail queries, and a rank tracker only covers terms someone chose
to track. A page-level claim is therefore only partly exposed to keyword-level
contention. `PAGE_DEMAND_VISIBILITY` (default 0.5, set per client via
`analysis.settings.overlap.page_demand_visibility`) is the share assumed visible;
the remainder is long tail that no keyword-level opportunity is claiming.

That share is a stated assumption rather than a derived one, deliberately.
Deriving it would mean comparing keyword impressions against page impressions,
and the two are not on a comparable basis - keyword records mix a one-month
Search Console window with monthly rank-tracker volume, while page records
accumulate across every period in the export. On the sample data that comparison
lands between 1.6x and 31x, which is a units mismatch rather than a measurement.
Naming the assumption is honest; deriving it from mismatched units would repeat
exactly the class of bug this system has been bitten by twice.

## 7. Prioritization

Ranking happens once, centrally, so a technical fix and a content program are
compared on identical terms. Four normalized components, weighted in config:

| Component | Default | What it rewards |
| --- | --- | --- |
| `value` | 0.35 | Confidence-adjusted revenue realized inside the horizon |
| `efficiency` | 0.35 | That value per person-day |
| `speed` | 0.15 | How soon value starts landing |
| `confidence` | 0.15 | Observed evidence over modeled assumption |

Efficiency is what stops one large slow programme crowding out several fast ones
that together deliver more. Speed matters because a 12-month target cannot be
hit by work that ramps in month 11.

**Value is always in-horizon, never run-rate.** Each opportunity has a
`lag_months` before anything happens and a `ramp_months` climb to full rate.
A programme that reaches full run rate in month 11 contributes almost nothing to
a 12-month goal, and the ranking reflects that.

## 8. Portfolio and the revenue bridge

A ranked list is not a plan. `prioritize/portfolio.py` schedules greedily by
score under per-discipline, per-quarter capacity.

- Work scheduled later realizes less inside the horizon; each item's value curve
  is re-phased by the months it waits for capacity.
- Portfolio revenue is **confidence-adjusted**, so the total is directly
  comparable to a target rather than being a best case.
- **Enabling work** (measurement instrumentation) is funded first, from a
  reserved share of capacity. It carries zero projected revenue — instrumentation
  does not create demand, and attaching revenue to it would be dishonest — but
  deferring it means every later quarter is planned on weaker evidence.
- When the portfolio misses the target, `gap_analysis()` states whether the
  deferred backlog could close it and exactly how many person-days per
  discipline that would take. That turns "we are short" into a costed ask.

## 9. What comes out

The analysis is only useful if it reaches the people who act on it, in the form
they work in.

| Output | What it is for |
| --- | --- |
| `opportunity-analysis.md` | The written analysis. One narrative, and the source every other document renders. |
| `*-opportunity-analysis.docx` | The same analysis as Word, tickets appended. Uploads to Drive as a native Google Doc. |
| `*-highlights.pptx` | The executive deck. Uploads to Drive as native Google Slides. |
| `jira-tickets.csv` | Jira's import format, one row per scheduled item. |
| `jira-tickets.md` | The same tickets as the document appendix. |
| `analysis.json` | The full machine-readable result, for dashboards and run-over-run diffs. |
| `opportunities.csv`, `roadmap.csv`, `evidence.csv` | The register, the schedule and the supporting datapoints. |

The document renders the markdown rather than restating it: one narrative, many
formats. A second copy of the wording would drift from the first the moment
either changed.

Tickets carry the case, not just the instruction - what to do, why it is worth
doing, what "done" means, and how the result will be measured. Acceptance
criteria lead with the measurement, because a ticket closed without it cannot be
shown to have worked. Enabling work says plainly that it carries no projected
revenue, for the same reason the portfolio does: instrumentation does not create
demand.

## 10. Baseline → intervention → lift → ROI

The POVs' five-step loop maps onto the tooling directly:

1. **Baseline** — run against current exports; `dark_traffic` gives the
   Track 1 + Track 2 starting position.
2. **Intervention** — deliver the roadmap.
3. **Re-measure** — monthly citation and rank tracking, quarterly revenue
   reconciliation. Re-run with fresh exports.
4. **Isolate lift** — compare runs across both tracks. Opportunity IDs are
   deterministic, so an item can be tracked month over month as its score moves.
5. **Project ROI** — incremental revenue against programme cost, with ranges
   given Track 2's modeled nature.

Recalibrate `dark_traffic` settings quarterly as survey and panel data
accumulate. **Treat movement in the estimators as the signal, not the point
estimate alone.**

## 11. What this system does not do

Stated plainly, because knowing the edges is what makes the rest usable.

- **Overlap is resolved at keyword level, using observed data only.** A page
  whose keywords are absent from the export contests other claims only at page
  level, and a keyword with no landing page in the export is matched by name
  alone. Richer keyword coverage sharpens the deduplication.
- **It does not replace judgement.** It produces a defensible starting position
  from the data. Which clusters matter strategically, what the brand can
  credibly claim, and what the client will actually resource are human calls.
  `strategy.cluster_multipliers` exists so that judgement is applied visibly.
- **It does not prove causation.** The branded-lift estimator measures
  correlation and scales by r². Geo-holdout and pre/post testing, as both POVs
  describe, remain the way to establish causation.
- **Track 2 is modeled, not measured.** It is triangulated and reported with its
  spread, but it is an estimate. Present it as one.
- **Third-party volume is an estimate.** Content-gap projections assume the site
  can reach the target position; they are discounted by difficulty but remain
  the least certain opportunity class.
- **Elasticities are benchmarks, not client truth.** Core Web Vitals conversion
  uplift comes from published studies. Validate with a real test before treating
  it as a commitment.
