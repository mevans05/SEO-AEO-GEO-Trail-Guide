# Data contracts

What to export from each tool and which columns matter. Connectors are tolerant:
column names match case- and separator-insensitively (`Search Volume`,
`search_volume` and `SEARCH-VOLUME` all resolve), unknown columns are ignored,
and a malformed cell degrades to a null rather than failing the run.

Nothing here is mandatory. Every analyzer declares what it needs and skips with
a stated reason when it is missing, so you can start with two sources and add
more over time. More inputs mean more analyses and higher confidence, not a
different system.

---

## Priority order

If you are onboarding a client and want the fastest path to a useful run:

1. **Search Console** — unlocks striking distance, answer capture, the zero-click
   estimator, and cannibalization (with the query+page export).
2. **GA4 channels by month** — unlocks Track 1 revenue, the branded-lift
   estimator, and LLM referral tracking.
3. **Semrush positions + gap** — unlocks content gap and competitive context.
4. **Screaming Frog** — unlocks crawl health, indexation, internal linking.
5. **CRM funnel** — replaces assumed economics with observed ones.
6. **Citation panel, server logs, surveys** — unlock the GEO surface and the
   strongest Track 2 estimators.

---

## Google Search Console

**Export:** Performance report → Export → CSV. Take **Queries** and **Pages**.
For cannibalization you need queries *and* pages in one export (via the API or a
filtered UI export).

| Column | Aliases accepted | Notes |
| --- | --- | --- |
| `Query` | queries, search query, keyword | Omit for a page-level export |
| `Page` | landing page, url, address | |
| `Clicks` | url clicks, total clicks | |
| `Impressions` | total impressions | Denominator for the zero-click estimate |
| `Position` | average position, avg position | Fractional values are fine |
| `Date` | day, week, month | Needed for decay analysis |

> **Set `keyword_periods_per_year` to match your window.** A one-month export is
> 12 (the default). A twelve-month export is 1. Getting this wrong skews the
> zero-click estimator against every other one.

## Semrush

**Organic positions** — Organic Research → Positions → Export.

| Column | Notes |
| --- | --- |
| `Keyword`, `Position`, `Search Volume`, `Keyword Difficulty`, `CPC`, `URL` | |
| `Keyword Intents` | Preferred over keyword-text heuristics |
| `SERP Features by Keyword` | Normalized to the CTR model's feature keys |

**Keyword gap** — Keyword Gap → Export. One position column per domain.

```yaml
- type: semrush_gap
  path: data/keyword_gap.csv
  options:
    client_column: yourdomain.com          # which column is you
    competitor_columns: [rival-a.com, rival-b.com]
```

Blank, `0` or `-` means "not ranking" and is read as such.

## GA4 (or any analytics platform)

Two exports, both useful:

**Landing pages** — `Landing page`, `Sessions`, `Key events`, `Total revenue`,
`Engagement rate`.

**Channels by month** — `Session default channel group`, `Date`, `Sessions`,
`Key events`, `Total revenue`. **At least 6 months**, ideally 12 — the
branded-lift estimator needs the series.

Add a channel group matching LLM referrers (`chatgpt.com`, `perplexity.ai`,
`gemini.google.com`, `copilot.microsoft.com`, `claude.ai`) or they land in
`Referral` and Track 1 for the generative surface reads zero.

> **B2B:** leave `Total revenue` at 0 and let the CRM carry revenue. The engine
> falls back to the funnel model rather than reporting a zero baseline.

Adobe, Matomo and Piwik work through the same connector; use `column_map` if the
headers differ.

## CRM (HubSpot, Salesforce, Pipedrive)

Monthly, by original source: `Sessions`, `Contacts`, `MQLs`, `SQLs`, `Deals`,
`Closed Won`, `Closed won value`, `Avg deal size`, `Days to close`.

This is the highest-leverage optional input: it moves the economics from assumed
to observed. Make sure the source taxonomy matches your analytics channel
grouping.

## Screaming Frog

**Export:** `internal_all.csv` or `internal_html.csv`.

Needs `Address`, `Status Code`, `Indexability`, `Indexability Status`,
`Title 1`, `Meta Description 1`, `H1-1`, `Word Count`, `Crawl Depth`,
`Unique Inlinks`, `Response Time`.

Thresholds are per-source:

```yaml
options:
  thresholds:
    thin_content_words: 300
    max_crawl_depth: 4
    slow_response_ms: 1200
    min_inlinks: 1
```

## PageSpeed Insights / Lighthouse

Three shapes, all accepted: a raw Lighthouse JSON report, a PageSpeed Insights
API response (field data overrides lab data), or a flat CSV of
`URL, LCP, INP, CLS, TTFB, Performance`.

Point at a directory to load many reports at once. Prefer field data (CrUX)
where you have it.

## CMS (Webflow, WordPress, Contentful)

`Slug`/`URL`, `Name`/`Title`, `Collection`, `Published on`, `Updated on`,
`Author`, `Word count`.

`Updated on` is what makes decay analysis able to distinguish a stale page from
a page losing to a new competitor.

```yaml
options:
  base_url: https://yourdomain.com   # if slugs are relative
```

## LLM citation panel

The AEO/GEO leading indicator. **One row per prompt × engine × run.** Any tool or
a maintained spreadsheet works — the format is deliberately vendor-neutral.

| Column | Notes |
| --- | --- |
| `Prompt` | The exact prompt run |
| `Cluster` | Groups prompts into a reportable theme |
| `Engine` | ChatGPT, Perplexity, Gemini, Copilot… |
| `Date` | |
| `Brand cited` | yes/no |
| `Brand position` | 1 = named first; drives prominence weighting |
| `Sentiment` | positive/neutral/negative, or a numeric score |
| `Cited URLs` | Which of your pages were quoted |
| `Competitors cited` | Relative share matters more than absolute presence |
| `Monthly prompt volume` | **Required for sizing** — without it the citation estimator cannot run |

Practical guidance: 50–150 prompts across the buying journey, run monthly, with
the prompt set held **stable** so month-over-month movement is comparable.

## Server logs

Either an aggregated CSV (`URL`, `Bot`, `Hits`, `Date`) or raw
combined-format access logs (`.log`/`.txt`), which are parsed and aggregated.

Segment by user agent: Googlebot, Bingbot, GPTBot, OAI-SearchBot, ChatGPT-User,
PerplexityBot, ClaudeBot, Google-Extended. This is the only input that shows
retrieval directly rather than inferring it.

## Surveys

Either aggregated (`Period start`, `Respondents`, `Share search engine`,
`Share AI assistant`, `Share other`) or raw responses (`Period start`, `Answer`),
which are bucketed automatically.

Include an explicit **"an AI assistant (ChatGPT, Perplexity, Copilot)"** option.
Without it, AI-influenced discovery is invisible and the strongest GEO estimator
cannot run. Target 100+ responses per quarter.

## LinkedIn and newsletter

LinkedIn: `Date`, `Impressions`, `Clicks`, `Engagements`, `Followers`.
Beehiiv/Substack/Mailchimp: `Send date`, `Subject`, `Sends`, `Opens`, `Clicks`,
`Subscribers`.

Beyond their own traffic, these control a confound: a newsletter send drives
direct traffic that has nothing to do with search, and the branded-lift estimator
subtracts it before attributing anything to organic discovery.

## Anything else

Use the `generic` connector — see [ADDING_A_SOURCE.md](ADDING_A_SOURCE.md).
