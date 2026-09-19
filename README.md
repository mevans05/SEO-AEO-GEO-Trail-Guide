# SEO / AEO / GEO Trail Guide

A data-first opportunity analysis engine for search, answer engines and
generative engines. It takes the exports a growth analyst already pulls —
Semrush, Search Console, GA4, HubSpot, LinkedIn, Beehiiv, Webflow, PageSpeed,
Screaming Frog, Lighthouse — and produces a ranked, revenue-weighted portfolio
of work measured against an explicit revenue target.

The goal is to take the mechanical parts of the analysis off the analyst's desk:
the pivot tables, the CTR arithmetic, the striking-distance filters, the effort
guesses, the roadmap spreadsheet. What it hands back is a defensible starting
position with every number traced to its source, so the analyst's time goes to
strategy, client conversations and research instead of assembling the numbers.

Measurement follows the Zilker Trail Consulting two-track model:

```
Total attributed value = Track 1 (known attribution)
                       + Track 2 (modeled dark traffic)
```

Referrer-based analytics capture only part of search and LLM influence. The rest
is satisfied on the SERP, satisfied inside an assistant, or arrives later as
direct and branded search. Valuing only Track 1 systematically understates SEO
and AEO/GEO contribution — so every opportunity here is valued across both, with
the observed and modeled components reported separately.

---

## Quick start

No installation needed beyond PyYAML. The repository ships with a complete
sample dataset for a fictional B2B SaaS client, so this runs immediately:

```bash
pip install pyyaml

PYTHONPATH=src python3 -m trailguide.cli run \
  --config config/example_client.yml \
  --out ./out
```

Or install it properly:

```bash
pip install -e .
trailguide run --config config/example_client.yml --out ./out
```

You get:

| File | What it is |
| --- | --- |
| `opportunity-analysis.md` | The full written analysis, ready to edit and send |
| `analysis.json` | Complete machine-readable result for dashboards or diffs |
| `opportunities.csv` | The ranked register, sortable in a spreadsheet |
| `roadmap.csv` | The scheduled plan by quarter |
| `evidence.csv` | Every supporting datapoint, traced to its source file |
| `dark_traffic_estimators.csv` | The Track 2 audit trail |
| `jira-tickets.csv` | Jira import format, one row per scheduled item |
| `jira-tickets.md` | The same tickets, as the document appendix |
| `<client>-opportunity-analysis.docx` | The full analysis as Word — uploads to Drive as a Google Doc |
| `<client>-highlights.pptx` | The executive deck — uploads to Drive as Google Slides |

The last three need the optional extra: `pip install -e ".[deliverables]"`, then
`--format md,json,csv,jira,docx,pptx`.

Other commands:

```bash
trailguide validate --config config/example_client.yml   # check config and sources
trailguide sources                                       # list the 14 connectors
trailguide analyzers                                     # list the 14 analyzers
trailguide init --out config/new-client.yml              # scaffold a config
trailguide intake --client "Acme" --domain acme.com      # generate the data intake pack
trailguide collect --workbook intake/acme-intake.xlsx    # split a filled workbook into CSVs
```

## Starting an audit

`trailguide intake` generates the collection pack handed over at the start of an
audit: a workbook with one tab per export, header-only CSV stubs, a config wired
to them, and a brief explaining where each export comes from and what it
unlocks.

```bash
trailguide intake --client "Acme" --domain acme.com --brand-terms "acme" --out ./intake
# ... the client fills the workbook ...
trailguide collect --workbook ./intake/acme-intake.xlsx --out ./intake/data
trailguide validate --config ./intake/acme.yml
trailguide run --config ./intake/acme.yml --out ./out -f md,json,csv,jira,docx,pptx
```

The pack is generated from the connector registry rather than maintained by
hand, so it always asks for exactly the columns the code reads. Tabs are matched
back by their headers, so a renamed tab still lands in the right place and a
partially filled pack still runs — `validate` reports what loaded and what did
not.

## What it actually produces

From the bundled sample, abridged:

```
  Opportunities found     60
  Scheduled / deferred    45 / 15
  Dark traffic multiplier SEO 0.14x  GEO 6.60x
  Baseline attributed     5,762,370 USD (Track 1 + Track 2)
  Projected incremental   1,297,500 USD (832,174 - 1,762,826)
  Target                  1,400,000 USD -> 93% attainment
  Delivery cost           142,786 USD (143 person-days)
```

The report leads with a revenue bridge — current attributed revenue, incremental
by surface, projected total, target, gap — then the two-track measurement
baseline with every estimator shown and its assumptions stated, then a
capacity-constrained quarterly roadmap, then the full opportunity register with
evidence, actions, risks and success measures per item.

## How it works

```
exports ──> connectors ──> canonical dataset ──> Track 2 model
                                                      │
                                    analyzers ────────┤
                                        │             │
                                overlap dedup         │
                                        │             │
                                    scoring           │
                                        │             │
                              portfolio + roadmap <───┘
                                        │
                              report / json / csv
```

**Connectors** translate vendor exports into canonical records and do nothing
else. **Analyzers** read only canonical records and find and size opportunities;
they never rank their own output. **Ranking happens once, centrally**, so a
technical fix and a content programme compete on identical terms.

### The fourteen analyzers

| Surface | Analyzers |
| --- | --- |
| **SEO** | striking distance, content gap, cannibalization, content decay, indexation, internal linking |
| **AEO** | answer capture (featured snippets, People Also Ask, AI Overviews) |
| **GEO** | citation gap (share of model), retrieval readiness (AI crawler access) |
| **Technical** | Core Web Vitals, crawl health |
| **Conversion** | conversion rate gaps, measurement instrumentation |
| **Distribution** | owned-channel amplification |

### Design decisions worth knowing

**Prioritization is value per person-day, not value.** Ranking blends
confidence-adjusted in-horizon revenue, efficiency, speed to impact and evidence
quality. That is what stops one large slow programme crowding out several fast
ones that together deliver more.

**In-horizon, not run-rate.** Each opportunity has a lag before anything happens
and a ramp to full rate. Work that reaches full run rate in month 11 contributes
almost nothing to a 12-month target, and the ranking reflects that. Scheduling
re-phases each value curve by the time it waits for capacity.

**The same click is never sold twice.** A query can be in striking distance,
split across cannibalizing URLs, *and* have an unclaimed snippet. Each analysis
is right alone; summing them triple-counts. Opportunities sharing a demand pool
split contested value, and the adjustment is attached as visible evidence. On the
sample dataset this removes about $2.0M of double-counted run rate.

**Observed beats modeled, everywhere.** A page's own revenue per session beats
the site model (capped at 5× so one outlier cannot dominate). CRM stage rates
replace configured assumptions and every substitution is reported. Confidence
tiers — observed, derived, modeled, assumed — discount value accordingly.

**Gaps are reported, not filled with guesses.** An estimator without inputs
returns nothing and says why. A failing source degrades the run instead of
ending it. Measurement gaps become zero-revenue `enabling` work funded from
reserved capacity, because instrumentation does not create demand and pretending
otherwise would be dishonest.

**Implausible outputs are surfaced, not capped.** If the portfolio claims more
incremental organic traffic than the baseline plausibly supports, or more
generative influence than Track 2 says exists, the run says so and names the
settings to check.

## Configuring a client

One YAML file describes a client completely. Start from
`config/example_client.yml`, which is commented throughout, or run
`trailguide init`.

The two blocks to work through with the client, because they drive every number:

```yaml
economics:
  model: b2b                    # or ecommerce
  gross_margin: 0.82
  b2b:
    visit_to_lead: 0.018        # replaced by CRM data when available
    lead_to_mql: 0.40
    mql_to_sql: 0.35
    sql_to_win: 0.20
    average_contract_value: 21000
    sales_cycle_days: 60        # adds a revenue lag on top of the SEO lag
  intent_multipliers:           # a pricing query is not a glossary lookup
    transactional: 2.6
    informational: 0.35

capacity:
  reserved_for_enabling: 0.10   # held for measurement instrumentation
  per_quarter:                  # deliverable person-days by discipline
    seo: 18
    content: 22
    engineering: 8
```

Strategy can tilt a data-derived ranking, visibly:

```yaml
strategy:
  cluster_multipliers:
    forecasting: 1.35
    glossary: 0.6
```

Track 2 assumptions live in `dark_traffic:` and should be recalibrated quarterly
as survey and panel data accumulate.

## Adding your own data

Three levels, in order of effort:

1. **An alias already covers it.** Adobe and Matomo load through `ga4`,
   Salesforce through `hubspot`, Sitebulb through `screaming_frog`. Run
   `trailguide sources`.
2. **Map the columns.** `column_map` remaps headers with no code. Matching is
   already case- and separator-insensitive.
3. **Use the `generic` connector** to map any export onto a canonical collection,
   or park it in `extras` for a custom analyzer.

Writing a real connector is about 25 lines. See
[docs/ADDING_A_SOURCE.md](docs/ADDING_A_SOURCE.md).

## Documentation

- **[docs/HANDOFF.md](docs/HANDOFF.md)** — state of the work, decisions already
  made and why, known limitations and next steps. Read this first if you are
  picking the project up.
- **[docs/METHODOLOGY.md](docs/METHODOLOGY.md)** — how the POVs map to code, what
  each number claims, and what the system does *not* do
- **[docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md)** — what to export from each
  tool, which columns matter, and the priority order for onboarding
- **[docs/ADDING_A_SOURCE.md](docs/ADDING_A_SOURCE.md)** — extending connectors
  and analyzers

## Tests

```bash
cd tests && PYTHONPATH=../src:. python3 -m unittest discover -p 'test_*.py'
```

164 tests, with no runtime dependency beyond the standard library and PyYAML
(the document tests need the `deliverables` extra). They cover
the CTR and revenue arithmetic, every Track 2 estimator, connector normalization,
overlap deduplication, capacity scheduling, and an end-to-end run against the
sample dataset — including that the run is deterministic, so month-over-month
comparisons are signal rather than noise.

## Limitations

Read [the last section of METHODOLOGY.md](docs/METHODOLOGY.md#11-what-this-system-does-not-do)
before presenting output to a client. In short: Track 2 is modeled rather than
measured, the branded-lift estimator establishes correlation rather than
causation, third-party volume is an estimate, Core Web Vitals elasticities are
published benchmarks rather than client truth, and overlap deduplication sees
only the demand the exports show — richer keyword coverage sharpens it.

This system produces a defensible starting position from the data. Which
clusters matter strategically, what the brand can credibly claim, and what the
client will actually resource remain human calls.
