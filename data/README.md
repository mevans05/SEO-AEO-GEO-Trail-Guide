# Data intake

Drop your GEO/SEO exports here. CSV, TSV, JSON and NDJSON are all accepted, and you do
not need to rename columns first — the normalizer maps common vendor headers onto one
schema and reports anything it could not place.

Five datasets are recognised:

| Dataset | Typical source | Carries |
|---|---|---|
| `citations` | Profound, Peec, Otterly, Semrush AI Toolkit, Ahrefs Brand Radar | Prompt-level AI answer results with cited sources |
| `backlinks` | Ahrefs, Semrush, Moz, Majestic | Referring domains, authority, anchors, targets |
| `authority` | Ahrefs, Semrush, Moz | DR/DA and traffic for you and competitors |
| `competitors` | Any of the above, plus AI visibility tools | Competitive metrics, optionally AI answer share |
| `content_gaps` | Ahrefs Content Gap, Semrush Keyword Gap | Topics, volume, difficulty, current ranks |

None of them is strictly required. The analysis adapts and states in §8 what the missing
data prevents it from claiming — but citation data is what makes this a GEO analysis
rather than a classic SEO audit, so it is the one worth chasing first.

Full schema, per-vendor export instructions and partial-data handling:
`.claude/skills/geo-seo-trail-guide/references/intake-schema.md`

## Running it

Invoke the skill and point it at this folder, or run the pipeline directly:

```bash
SKILL=.claude/skills/geo-seo-trail-guide
python3 $SKILL/scripts/normalize.py --data-dir ./data --out ./build/normalized.json \
    --brand-domain yourbrand.com --brand-name "Your Brand"
python3 $SKILL/scripts/analyze.py --in ./build/normalized.json --out ./build/analysis.json
python3 $SKILL/scripts/render_report.py --in ./build/analysis.json --out ./build/report-draft.md
```

The draft is a skeleton with the factual tables filled and `<!-- ANALYST: ... -->`
markers wherever judgment is required. Working those markers is the point of the skill.

## A note on what you put here

Exports often contain commercially sensitive competitive data. `build/` is gitignored;
this folder is not, so decide deliberately whether your exports should be committed.
