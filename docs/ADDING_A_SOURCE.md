# Adding a data source

The system is designed so that "we also have data from X" is a config change,
not a code change. There are three levels of effort; try them in order.

---

## Level 1 — an alias already covers it

Many tools export the same shape as one already supported. Try the existing
connector first:

| Your tool | Use type |
| --- | --- |
| Adobe Analytics, Matomo, Piwik | `ga4` |
| Salesforce, Pipedrive, any CRM funnel export | `hubspot` |
| Sitebulb, DeepCrawl, OnCrawl | `screaming_frog` |
| Substack, Mailchimp, ConvertKit | `beehiiv` |
| WordPress, Contentful, Sanity | `cms` |
| Ahrefs positions (with a column map) | `semrush` |

Run `trailguide sources` for the full alias list.

## Level 2 — map the columns

If the shape matches but the headers differ, remap them. No code:

```yaml
sources:
  - type: semrush
    name: ahrefs_positions
    path: data/ahrefs.csv
    options:
      column_map:
        keyword: "Keyword"
        position: "Current position"
        search_volume: "Volume"
        difficulty: "KD"
        url: "Current URL"
```

`column_map` maps `{canonical_field: your_column}`. Matching is already
case- and separator-insensitive, so you only need this when the names genuinely
differ.

## Level 3 — the generic connector

For an export that no connector understands, map it straight onto a canonical
collection:

```yaml
sources:
  - type: generic
    name: brand_tracker
    path: data/brand_study.csv
    options:
      target: surveys              # the canonical collection to fill
      column_map:
        period_start: "Wave start"
        respondents: "N"
        share_ai_assistant: "Used AI to research (%)"
        share_search_engine: "Used search (%)"
```

Valid `target` values: `keywords`, `pages`, `channels`, `funnel`, `citations`,
`crawl_issues`, `bot_hits`, `surveys`. Field types are coerced automatically, and
derived classifications (branded, intent) are filled in.

Omit `target` to park the data in `Dataset.extras` under `extras_key`, where a
custom analyzer can reach it:

```yaml
  - type: generic
    name: paid_search
    path: data/google_ads.csv
    options:
      extras_key: paid_search
```

Use `constants` to stamp values onto every row, and `json_path` to reach a nested
list inside a JSON document:

```yaml
    options:
      target: channels
      constants: {channel: paid_search}
      json_path: data.rows
```

## Level 4 — write a connector

Worth it when a source has real parsing logic (an API shape, nested JSON, a
format needing aggregation).

```python
# src/trailguide/connectors/my_tool.py
from ..core import coerce
from ..core.schemas import Dataset, KeywordMetric
from .base import Connector, register


@register
class MyToolConnector(Connector):
    """One line on what this reads."""

    name = "my_tool"
    aliases = ("mytool", "my-tool")
    description = "My Tool rank tracking export."
    produces = ("keywords",)

    def load(self) -> Dataset:
        dataset = Dataset()
        for file_path, row in self.rows():          # handles CSV/TSV/JSON/globs
            term = coerce.to_str(coerce.first_present(row, ("keyword", "term")))
            if not term:
                continue
            dataset.keywords.append(KeywordMetric(
                source=self.source_name,
                source_file=str(file_path),
                keyword=term,
                position=coerce.to_float(coerce.first_present(row, ("position", "rank"))),
                impressions=coerce.to_int(row.get("impressions"), 0) or 0,
            ))
        return dataset
```

Then add it to the imports in `connectors/__init__.py`. That is the whole
contract.

Rules worth following:

- **Translate only.** Judgement about what numbers *mean* belongs in analyzers.
- **Coerce everything** through `core.coerce` so one bad cell degrades to a null
  instead of killing the run.
- **Set `source` and `source_file`** so every figure traces back to its origin.
- **Accept aliases** for column names you have seen in the wild.

`self.rows()` handles CSV, TSV, JSON, JSONL, globs, directories, `skip_lines`
and `column_map` for you. Use `self.documents()` for whole JSON documents.

## Adding an analyzer

Same pattern. Subclass `Analyzer`, declare what you need, return opportunities:

```python
@register_analyzer
class MyAnalyzer(Analyzer):
    name = "my_analysis"
    surface = Surface.SEO
    description = "One line for `trailguide analyzers`."
    required_inputs = ("keywords",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        threshold = self.setting(context, "threshold", 100)
        lag, ramp = context.timing(self.name)
        ...
        projection = context.project(
            annual_sessions, self.surface, intent=..., lag_months=lag, ramp_months=ramp,
        )
        return [Opportunity(..., effort=context.effort(self.name, units=n))]
```

`context.project()` applies the correct Track 2 multiplier for your surface and
phases the value curve. `context.effort()` reads the configured effort profile.
Scoring, overlap deduplication and scheduling then happen centrally — you do not
rank your own output.

Two things to get right:

- **Set `demand_pool_override`** if your surface's default is wrong. Work that
  converts or amplifies existing traffic rather than claiming new demand should
  use `"none"` so it is exempt from overlap deduplication.
- **Pass `include_dark=False`** if your session estimate is already modeled from
  dark-pool logic, or you will count that pool twice.

Register it in `analysis/__init__.py`. It runs for every client automatically
unless `analysis.enabled` names an explicit allowlist.
