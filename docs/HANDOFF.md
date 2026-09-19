# Handoff

Context for picking this project up in a new session or a new environment.
Read this first; it records what exists, what was decided and why, and what is
deliberately left open.

---

## Current state

**Branch:** `claude/seo-aeo-priority-analyzer-3qtz9i`
**Status:** Complete and working. 169 tests pass, `ruff check` is clean, and the
bundled sample dataset runs end to end with no setup.
**Not done:** no pull request has been opened, and nothing has been merged to
`main`.

## Getting running

In Claude Code on the web, the SessionStart hook installs everything
automatically. Manually:

```bash
pip install -e ".[dev]"
export PYTHONPATH="$PWD/src:$PWD/tests"

python3 -m unittest discover -s tests -p 'test_*.py'   # 169 tests
ruff check .                                            # clean
trailguide run --config config/example_client.yml --out ./out
```

The Word, PowerPoint and workbook writers need the optional extra:

```bash
pip install -e ".[dev,deliverables]"

# Start an audit: generates the intake workbook, CSV stubs, config and brief.
trailguide intake --client "Acme" --domain acme.com --out ./intake

# Once the workbook comes back filled. --config also applies the client
# profile tab (brand terms, competitors, revenue target) to the config.
trailguide collect --workbook ./intake/acme-intake.xlsx --out ./intake/data \
                   --config ./intake/acme.yml
trailguide validate --config ./intake/acme.yml
trailguide run --config ./intake/acme.yml --out ./out -f md,json,csv,jira,docx,pptx
```

Upload the `.docx` and `.pptx` to Google Drive and they convert to a native
Google Doc and Google Slides file. That conversion is the whole delivery path -
there is no Google API dependency in the engine.

> The hook only applies to sessions that start on a branch containing it. Until
> this branch is merged to the repository's default branch, a session started on
> `main` will not pick it up.

## Where things live

| Path | What it holds |
| --- | --- |
| `src/trailguide/connectors/` | 14 source adapters. Translation only, no judgement. |
| `src/trailguide/core/` | Schemas, CTR curves, revenue model, classification, stats. |
| `src/trailguide/analysis/dark_traffic.py` | The Track 2 model — the heart of the system. |
| `src/trailguide/analysis/` | 14 analyzers across 6 surfaces. They find and size; they never rank. |
| `src/trailguide/prioritize/` | Scoring, overlap deduplication, capacity scheduling. |
| `src/trailguide/report/` | Markdown analysis, Jira tickets, Word/PowerPoint, JSON and CSV. |
| `src/trailguide/report/documents.py` | Word and PowerPoint writers, and the markdown-to-Word renderer. |
| `src/trailguide/report/jira.py` | Delivery tickets: Jira CSV import and the document appendix. |
| `src/trailguide/intake.py` | The audit intake pack: workbook, CSV stubs, config and brief. |
| `src/trailguide/pipeline.py` | The run sequence, start to finish. |
| `config/example_client.yml` | Fully commented demo config — the template for real clients. |
| `data/sample/` | 16 synthetic but internally consistent source files. |
| `scripts/generate_sample_data.py` | Regenerates `data/sample/` deterministically. |
| `docs/METHODOLOGY.md` | How the POVs map to code, and what the system does *not* do. |

## Decisions already made

These were worked through and validated. Reopen them only with a reason — several
were bugs caught by checking outputs against the data, not guesses.

**AEO uses the organic multiplier, not the LLM one.** Featured snippets, People
Also Ask and AI Overviews are won on the Google SERP and earn organic clicks.
Routing AEO through the LLM referral multiplier valued an organic click as an
assistant referral and inflated it roughly sevenfold.

**GEO is sized as a share of the modeled LLM pool, never grossed up.**
Generative opportunities estimate influence directly, which is already mostly
dark; applying the Track 2 multiplier on top counted that pool twice. A
plausibility guard in `pipeline.py` fails loudly if the parts ever exceed the
whole.

**Overlap deduplication exists because analyzers legitimately collide.** One
query can be in striking distance, split across cannibalizing URLs, *and* have an
unclaimed snippet. Summing all three sells the same clicks three times. On the
sample data this removes about $2.0M of double-counted annual run rate.

**Survey estimator uses the observed analytics conversion rate.** Analytics
"conversions" are usually leads; dividing them by a session-to-closed-won rate
mixes units and produced a 101x dark multiplier before it was caught.

**Zero-click estimator annualizes explicitly** via `keyword_periods_per_year`.
The other estimators are annual; mixing bases silently skewed the blend.

**Striking-distance targets are difficulty-banded and movement-capped.** The
original rule pushed a KD-41 term at position 3.2 toward position 1.2. A keyword
already inside its realistic band now yields zero gain, which is the honest
answer.

**Portfolio revenue is confidence-adjusted and in-horizon**, not run rate, so the
total is directly comparable to a target rather than a best case. Scheduling
re-phases each value curve by the time it waits for capacity.

**Measurement gaps carry zero revenue.** Instrumentation does not create demand.
They are tagged `enabling` and funded from reserved capacity instead.

**Overlap dedup resolves keywords to their landing pages.** A page-level claim
is expanded into the keywords that page ranks for, so a decaying page and a
striking-distance keyword on it contest each other instead of both billing for
the same clicks. On the sample data this moved removal from about $2.0M to
$2.9M of annual run rate, and target attainment from 124% to 93% - the earlier
figure was inflated by cross-level double counting.

**The share of a page's demand that keywords represent is a stated assumption,
not a derived one.** `PAGE_DEMAND_VISIBILITY` defaults to 0.5. Deriving it from
keyword impressions over page impressions was tried and rejected: the two are
not on a comparable basis, and the ratio lands between 1.6x and 31x on the
sample data. That is a units mismatch, not a measurement.

**The intake template is generated from the connectors.** Every connector
declares the exports it reads as `IntakeSheet` objects, and `trailguide intake`
builds the workbook from the registry. A column cannot drift out of the template
without the connector changing too, and a test fails if a connector declares no
intake at all.

**Documents render the markdown report rather than restating it.** One
narrative, many formats. Duplicating the wording in a Word writer would have
drifted from the markdown the first time either changed.

**Column matching is separator- and case-insensitive.** A literal-match bug in
`coerce.first_present` silently disabled citation volume, brand position and
survey shares across every connector. Fixed at that one layer rather than by
enumerating spellings per connector.

## Known limitations

Stated in full at the end of `docs/METHODOLOGY.md`. The ones most likely to bite:

1. **Overlap dedup only sees what the exports show.** Cross-level matching is
   closed, but a page whose keywords are absent from the export still contests
   other claims at page level only. Richer keyword coverage sharpens it.
2. **`keyword_periods_per_year` must match the export window** (default 12, i.e.
   one month of Search Console). Wrong value skews the zero-click estimator.
3. **Default CTR curves and CWV elasticities are published benchmarks**, not
   client truth. Calibrate per client once first-party data justifies it.
4. **The branded-lift estimator establishes correlation, not causation.**
   Geo-holdout and pre/post testing remain the way to prove causation.
5. **The sample dataset is synthetic.** It exercises every code path and every
   analyzer, but its numbers are not a benchmark for any real client.

## Reasonable next steps

Roughly in order of value:

- Run it against one real client's exports and compare the output to what an
  analyst produced by hand. That is the only real validation.
- Calibrate `dark_traffic` defaults and CTR curves once real first-party data
  exists, then recalibrate quarterly as the POV prescribes.
- Add a run-over-run diff so month-to-month movement in opportunities and
  estimators is visible directly. Opportunity IDs are already deterministic to
  support this.
- Open a PR and merge to `main` so the SessionStart hook applies to all sessions.
- Validate `PAGE_DEMAND_VISIBILITY` against a client where full keyword coverage
  exists, and calibrate it rather than leaving it at the 0.5 default.
- Consider a `sheets` connector reading a Google Sheet directly, so a filled
  intake workbook never has to be downloaded at all.

## Environment notes

- Runtime needs only **Python 3.10+ and PyYAML**. Everything else is standard
  library, deliberately, so the engine runs anywhere without a dependency dance.
- `ruff` and `pytest` are dev-only extras.
- The two source POV PDFs were session uploads and are **not in the repository**.
  Their substance is captured in `docs/METHODOLOGY.md`, which maps each claim to
  its implementation. Re-attach the PDFs if a new session needs the originals.
- Reading PDFs in a fresh container may need `pip install --ignore-installed
  cryptography` before `pypdf` will import, because the system `cryptography`
  package can be missing its `_cffi_backend`. This affects PDF reading only, not
  the engine.
