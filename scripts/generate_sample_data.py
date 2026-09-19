"""Generate the bundled sample dataset for Vantive, a fictional B2B SaaS client.

The data is synthetic but internally consistent: page-level traffic, keyword
positions, CRM funnel volumes and channel series all reconcile, and specific
pages are seeded with decay, cannibalization, indexation and Core Web Vitals
problems so every analyzer has something real to find.

Deterministic via a fixed seed, so the end-to-end test suite can assert on
exact outputs. Run from the repository root:

    python3 scripts/generate_sample_data.py
"""
import csv
import json
import math
import random
from pathlib import Path

random.seed(20260919)
OUT = Path("data/sample")
OUT.mkdir(parents=True, exist_ok=True)
DOMAIN = "https://vantive.io"
COMPETITORS = ["clearloop.com", "pipelinehq.com", "revsignal.io"]
MONTHS = [f"2025-{m:02d}" for m in range(10, 13)] + [f"2026-{m:02d}" for m in range(1, 10)]

def w(name, rows, fields):
    with (OUT / name).open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)
    print(f"  {name:38} {len(rows):>5} rows")

# ---------------------------------------------------------------- URL universe
BLOG = [
    ("revenue-forecasting-guide", "The Complete Guide to Revenue Forecasting", 2400, "2024-03-12", "2025-02-08"),
    ("sales-pipeline-metrics", "14 Sales Pipeline Metrics That Actually Predict Revenue", 1900, "2024-05-20", "2025-06-14"),
    ("crm-data-hygiene", "CRM Data Hygiene: A Practical Playbook", 1600, "2023-11-02", "2024-01-15"),
    ("revenue-intelligence-explained", "What Is Revenue Intelligence?", 2100, "2024-01-18", "2025-09-01"),
    ("forecast-accuracy-benchmarks", "Forecast Accuracy Benchmarks for B2B SaaS", 1400, "2024-08-09", "2025-08-22"),
    ("pipeline-coverage-ratio", "Pipeline Coverage Ratio: How Much Is Enough?", 1200, "2023-09-14", "2023-12-01"),
    ("sales-velocity-formula", "The Sales Velocity Formula, Explained", 1100, "2024-02-27", "2024-04-11"),
    ("deal-scoring-models", "Deal Scoring Models That Sales Teams Actually Use", 1750, "2024-06-30", "2025-05-19"),
    ("revops-tech-stack", "Building a RevOps Tech Stack in 2026", 2600, "2025-01-22", "2026-01-30"),
    ("churn-prediction-signals", "Early Churn Signals Hiding in Your CRM", 1500, "2024-10-05", "2025-03-27"),
    ("quota-attainment-analysis", "How to Analyze Quota Attainment", 980, "2023-07-19", "2023-10-03"),
    ("conversation-intelligence", "Conversation Intelligence: Buyer's Guide", 2200, "2024-11-14", "2025-11-02"),
    ("arr-vs-mrr", "ARR vs MRR: Which Should You Report?", 780, "2023-05-08", "2023-06-20"),
    ("sales-capacity-planning", "Sales Capacity Planning Without Guesswork", 1350, "2025-03-11", "2025-12-06"),
    ("attribution-models-b2b", "B2B Attribution Models Compared", 1850, "2024-04-16", "2025-07-09"),
]
COMPARE = [
    ("clearloop-alternative", "The Clearloop Alternative for RevOps Teams", 1100, "2024-09-03", "2025-10-15"),
    ("pipelinehq-vs-vantive", "PipelineHQ vs Vantive", 950, "2024-12-01", "2025-11-20"),
    ("revenue-intelligence-tools", "12 Revenue Intelligence Tools Compared", 2800, "2025-02-14", "2026-02-01"),
]
PRODUCT = [
    ("forecasting", "Revenue Forecasting Software", 900, "2024-01-10", "2026-01-12"),
    ("pipeline-analytics", "Pipeline Analytics", 850, "2024-01-10", "2025-10-30"),
    ("deal-intelligence", "Deal Intelligence", 800, "2024-01-10", "2025-04-18"),
]
OTHER = [
    ("pricing", "Pricing", 600, "2024-01-10", "2026-03-04"),
    ("demo", "Book a Demo", 300, "2024-01-10", "2025-12-11"),
    ("customers/northwind", "How Northwind cut forecast error by 41%", 1200, "2024-07-22", "2025-01-09"),
    ("customers/acme-logistics", "Acme Logistics: 3x pipeline visibility", 1150, "2025-04-02", "2025-08-14"),
    ("glossary/pipeline-coverage", "Pipeline Coverage (definition)", 420, "2024-02-05", "2024-02-05"),
    ("glossary/sales-velocity", "Sales Velocity (definition)", 390, "2024-02-05", "2024-02-05"),
    ("glossary/net-revenue-retention", "Net Revenue Retention (definition)", 410, "2024-02-05", "2024-02-05"),
]

def url(slug, section=""):
    return f"{DOMAIN}/{section + '/' if section else ''}{slug}"

PAGES = []   # (url, template, words, published, updated)
for slug, title, words, pub, upd in BLOG:
    PAGES.append((url(slug, "blog"), "blog", title, words, pub, upd))
for slug, title, words, pub, upd in COMPARE:
    PAGES.append((url(slug, "compare"), "compare", title, words, pub, upd))
for slug, title, words, pub, upd in PRODUCT:
    PAGES.append((url(slug, "product"), "product", title, words, pub, upd))
for slug, title, words, pub, upd in OTHER:
    section = "" if slug in ("pricing", "demo") else ""
    PAGES.append((url(slug, section), slug.split("/")[0] if "/" in slug else slug, title, words, pub, upd))

# ------------------------------------------------------------- GSC query data
FEATURES = {
    "ai": "AI Overview, People also ask",
    "fs": "Featured Snippet, People also ask",
    "paa": "People also ask",
    "none": "",
    "sl": "Sitelinks",
}
# (keyword, page, position, impressions, ctr_factor, volume, kd, features, branded)
QUERIES = [
    ("revenue forecasting software", "/product/forecasting", 6.2, 14200, 0.55, 2400, 68, "ai", False),
    ("revenue forecasting tools", "/product/forecasting", 8.7, 9100, 0.5, 1600, 64, "ai", False),
    ("best revenue intelligence software", "/compare/revenue-intelligence-tools", 5.4, 11800, 0.6, 1900, 71, "ai", False),
    ("revenue intelligence platform", "/compare/revenue-intelligence-tools", 7.9, 8300, 0.5, 1300, 66, "paa", False),
    ("revenue intelligence", "/blog/revenue-intelligence-explained", 4.1, 21000, 0.45, 5400, 62, "ai", False),
    ("what is revenue intelligence", "/blog/revenue-intelligence-explained", 3.2, 16400, 0.4, 3600, 41, "fs", False),
    ("sales pipeline metrics", "/blog/sales-pipeline-metrics", 5.8, 18900, 0.5, 4400, 52, "fs", False),
    ("pipeline metrics to track", "/blog/sales-pipeline-metrics", 9.4, 7200, 0.45, 1100, 48, "paa", False),
    ("revenue forecasting guide", "/blog/revenue-forecasting-guide", 3.6, 12600, 0.7, 2900, 44, "paa", False),
    ("how to forecast revenue", "/blog/revenue-forecasting-guide", 7.1, 15300, 0.4, 3300, 55, "ai", False),
    ("forecast accuracy benchmark", "/blog/forecast-accuracy-benchmarks", 4.8, 5400, 0.6, 880, 39, "fs", False),
    ("pipeline coverage ratio", "/blog/pipeline-coverage-ratio", 6.9, 8800, 0.45, 1700, 36, "fs", False),
    ("pipeline coverage ratio", "/glossary/pipeline-coverage", 11.2, 3100, 0.3, 1700, 36, "fs", False),
    ("what is pipeline coverage", "/glossary/pipeline-coverage", 8.4, 4200, 0.4, 720, 31, "fs", False),
    ("sales velocity formula", "/blog/sales-velocity-formula", 5.1, 9600, 0.5, 2100, 34, "fs", False),
    ("sales velocity", "/blog/sales-velocity-formula", 7.7, 11400, 0.4, 3900, 42, "paa", False),
    ("sales velocity", "/glossary/sales-velocity", 13.8, 2900, 0.25, 3900, 42, "paa", False),
    ("deal scoring model", "/blog/deal-scoring-models", 6.4, 6700, 0.5, 990, 45, "paa", False),
    ("revops tech stack", "/blog/revops-tech-stack", 4.4, 10200, 0.6, 1800, 49, "paa", False),
    ("revops tools", "/blog/revops-tech-stack", 12.1, 6900, 0.3, 2600, 57, "ai", False),
    ("crm data hygiene", "/blog/crm-data-hygiene", 9.8, 4100, 0.35, 720, 29, "none", False),
    ("churn prediction signals", "/blog/churn-prediction-signals", 8.2, 5300, 0.4, 860, 47, "paa", False),
    ("conversation intelligence software", "/blog/conversation-intelligence", 10.6, 7800, 0.35, 2200, 69, "ai", False),
    ("b2b attribution models", "/blog/attribution-models-b2b", 7.3, 6100, 0.45, 1300, 53, "paa", False),
    ("sales capacity planning", "/blog/sales-capacity-planning", 11.9, 4600, 0.3, 1050, 44, "none", False),
    ("quota attainment analysis", "/blog/quota-attainment-analysis", 14.2, 2200, 0.25, 480, 33, "none", False),
    ("arr vs mrr", "/blog/arr-vs-mrr", 9.1, 8900, 0.4, 4100, 38, "fs", False),
    ("clearloop alternative", "/compare/clearloop-alternative", 4.9, 3400, 0.7, 590, 43, "sl", False),
    ("clearloop alternatives", "/compare/clearloop-alternative", 6.6, 2800, 0.55, 480, 45, "paa", False),
    ("pipelinehq vs vantive", "/compare/pipelinehq-vs-vantive", 2.8, 1900, 0.8, 320, 22, "none", False),
    ("pipeline analytics software", "/product/pipeline-analytics", 8.9, 6400, 0.4, 1150, 61, "ai", False),
    ("deal intelligence software", "/product/deal-intelligence", 10.2, 4900, 0.35, 830, 58, "ai", False),
    ("net revenue retention", "/glossary/net-revenue-retention", 6.1, 12800, 0.45, 5900, 51, "fs", False),
    ("vantive", "/", 1.1, 18600, 0.95, 4800, 12, "sl", True),
    ("vantive pricing", "/pricing", 1.3, 7400, 0.9, 1900, 14, "sl", True),
    ("vantive reviews", "/compare/revenue-intelligence-tools", 3.4, 3100, 0.6, 720, 19, "paa", True),
    ("vantive demo", "/demo", 1.2, 2600, 0.88, 590, 11, "sl", True),
    ("revenue forecasting software", "/blog/revenue-forecasting-guide", 12.8, 4300, 0.25, 2400, 68, "ai", False),
    ("best revenue intelligence software", "/blog/revenue-intelligence-explained", 14.6, 2900, 0.2, 1900, 71, "ai", False),
    ("revenue intelligence tools", "/compare/revenue-intelligence-tools", 6.8, 7600, 0.5, 1450, 65, "ai", False),
    ("revenue intelligence tools", "/blog/revops-tech-stack", 15.3, 2400, 0.2, 1450, 65, "ai", False),
]
rows = []
for kw, page, pos, imp, ctrf, vol, kd, feat, branded in QUERIES:
    from_curve = {1: .281, 2: .157, 3: .110, 4: .080, 5: .061, 6: .048, 7: .040, 8: .033,
                  9: .028, 10: .025}.get(int(pos), 0.015)
    if branded:
        from_curve *= 2.2
    clicks = max(0, int(imp * from_curve * ctrf))
    rows.append({"Query": kw, "Page": DOMAIN + page, "Clicks": clicks, "Impressions": imp,
                 "CTR": f"{clicks / imp * 100:.2f}%", "Position": f"{pos:.1f}"})
w("gsc_queries.csv", rows, ["Query", "Page", "Clicks", "Impressions", "CTR", "Position"])

# ------------------------------------------------- GSC per-page monthly trend
DECAYING = {"/blog/crm-data-hygiene", "/blog/pipeline-coverage-ratio",
            "/blog/sales-velocity-formula", "/blog/quota-attainment-analysis",
            "/blog/arr-vs-mrr"}
page_base = {}
for u, template, title, words, pub, upd in PAGES:
    path = u.replace(DOMAIN, "") or "/"
    base = {"blog": 900, "compare": 700, "product": 500, "pricing": 1400,
            "demo": 400, "customers": 180, "glossary": 260}.get(template, 300)
    page_base[u] = base * random.uniform(0.55, 1.6)

rows = []
for u, template, title, words, pub, upd in PAGES:
    path = u.replace(DOMAIN, "")
    base = page_base[u]
    for i, month in enumerate(MONTHS):
        seasonal = 1.0 + 0.10 * math.sin(i / 12 * 2 * math.pi)
        if path in DECAYING:
            factor = 1.0 - 0.055 * i           # sustained slide
        else:
            factor = 1.0 + 0.012 * i           # mild growth
        clicks = max(5, int(base / 12 * seasonal * factor * random.uniform(0.9, 1.1)))
        rows.append({"Page": u, "Date": f"{month}-01", "Clicks": clicks,
                     "Impressions": int(clicks * random.uniform(11, 19)),
                     "Position": f"{random.uniform(4.0, 13.0):.1f}"})
w("gsc_pages_monthly.csv", rows, ["Page", "Date", "Clicks", "Impressions", "Position"])

# ------------------------------------------------------- Semrush positions
rows = []
seen = set()
for kw, page, pos, imp, ctrf, vol, kd, feat, branded in QUERIES:
    if kw in seen:
        continue
    seen.add(kw)
    rows.append({
        "Keyword": kw, "Position": f"{pos:.0f}", "Previous position": f"{pos + random.uniform(-2, 3):.0f}",
        "Search Volume": vol, "Keyword Difficulty": kd,
        "CPC": f"{random.uniform(4, 42):.2f}", "URL": DOMAIN + page,
        "Traffic": int(vol * 0.05), "Traffic (%)": "1.2",
        "Keyword Intents": ("Navigational" if branded else
                            "Transactional" if any(t in kw for t in ("software", "tools", "platform", "pricing", "demo"))
                            else "Commercial" if any(t in kw for t in ("best", "vs", "alternative", "compared"))
                            else "Informational"),
        "SERP Features by Keyword": FEATURES[feat],
        "Timestamp": "2026-09-01",
    })
w("semrush_positions.csv", rows, list(rows[0].keys()))

# ------------------------------------------------------------ Semrush gap
GAP = [
    ("sales forecasting best practices", 3200, 48, "Informational", "AI Overview, People also ask", None, 4, 7, 12),
    ("revenue operations software", 2600, 66, "Transactional", "AI Overview", None, 3, 5, 9),
    ("forecast category definitions", 1400, 28, "Informational", "Featured Snippet", None, 2, 6, None),
    ("sales forecast template", 8900, 35, "Informational", "Featured Snippet, People also ask", None, 5, 3, 11),
    ("weighted pipeline forecast", 1900, 41, "Informational", "People also ask", 34.0, 6, 9, None),
    ("revenue forecasting methods", 4100, 52, "Informational", "AI Overview, People also ask", None, 3, 8, 14),
    ("sales forecasting accuracy", 2200, 45, "Informational", "People also ask", 28.0, 7, 4, None),
    ("bottom up revenue forecast", 1250, 33, "Informational", "", None, 8, 12, None),
    ("revenue forecast model excel", 3400, 30, "Informational", "Featured Snippet", None, 9, 5, 16),
    ("saas revenue forecasting", 1800, 47, "Informational", "AI Overview", None, 4, 11, None),
    ("pipeline review meeting agenda", 1600, 24, "Informational", "People also ask", None, 2, 8, None),
    ("sales forecast vs pipeline", 1100, 31, "Informational", "Featured Snippet", None, 6, 3, 13),
    ("deal desk process", 2400, 38, "Informational", "", None, 5, 14, None),
    ("revenue leakage", 2900, 43, "Informational", "AI Overview, People also ask", None, 4, 6, 10),
    ("crm forecasting integration", 890, 55, "Commercial", "", None, 7, 9, None),
    ("best sales forecasting software", 5200, 72, "Commercial", "AI Overview, People also ask", None, 2, 4, 8),
    ("enterprise revenue intelligence", 720, 69, "Commercial", "AI Overview", None, 6, 3, None),
    ("revenue intelligence vs sales intelligence", 640, 34, "Informational", "People also ask", None, 3, 7, None),
]
rows = []
for kw, vol, kd, intent, feats, own, c1, c2, c3 in GAP:
    rows.append({
        "Keyword": kw, "Search Volume": vol, "Keyword Difficulty": kd,
        "CPC": f"{random.uniform(6, 48):.2f}", "Keyword Intents": intent,
        "SERP Features": feats,
        "vantive.io": own if own else "",
        "clearloop.com": c1 or "", "pipelinehq.com": c2 or "", "revsignal.io": c3 or "",
    })
w("semrush_keyword_gap.csv", rows, list(rows[0].keys()))

# ------------------------------------------------------ GA4 landing pages
rows = []
for u, template, title, words, pub, upd in PAGES:
    annual_clicks = page_base[u]
    sessions = int(annual_clicks * random.uniform(1.05, 1.35))
    base_cvr = {"pricing": 0.085, "demo": 0.22, "product": 0.048, "compare": 0.031,
                "customers": 0.036, "blog": 0.011, "glossary": 0.004}.get(template, 0.01)
    # a few deliberate under-performers within their template
    if u.endswith(("/blog/revops-tech-stack", "/blog/conversation-intelligence",
                   "/compare/revenue-intelligence-tools", "/product/deal-intelligence")):
        base_cvr *= 0.35
    conversions = round(sessions * base_cvr, 1)
    rows.append({
        "Landing page": u, "Sessions": sessions,
        "Engagement rate": f"{random.uniform(0.42, 0.78):.3f}",
        "Key events": conversions,     # lead events; B2B revenue lives in the CRM
        "Total revenue": 0,
    })
w("ga4_landing_pages.csv", rows, list(rows[0].keys()))

# --------------------------------------------------- GA4 channels by month
CH = ["Organic Search", "Direct", "Paid Search", "Referral", "Organic Social", "Email",
      "chatgpt.com / referral", "perplexity.ai / referral", "gemini.google.com / referral"]
rows = []
for i, month in enumerate(MONTHS):
    organic = int(13800 * (1 + 0.016 * i) * random.uniform(0.94, 1.06))
    # direct co-moves with organic (the dark-traffic signal) plus an email/social component
    email = int(1500 * random.uniform(0.7, 1.3))
    social = int(1100 * random.uniform(0.7, 1.3))
    direct = int(organic * 0.42 + email * 0.55 + social * 0.35 + random.gauss(0, 260))
    llm_total = int(210 * (1 + 0.13 * i) * random.uniform(0.85, 1.15))
    values = {
        "Organic Search": organic, "Direct": direct, "Paid Search": int(4200 * random.uniform(0.9, 1.1)),
        "Referral": int(1800 * random.uniform(0.85, 1.15)), "Organic Social": social, "Email": email,
        "chatgpt.com / referral": int(llm_total * 0.56),
        "perplexity.ai / referral": int(llm_total * 0.29),
        "gemini.google.com / referral": int(llm_total * 0.15),
    }
    cvr = {"Organic Search": 0.0165, "Direct": 0.026, "Paid Search": 0.021, "Referral": 0.019,
           "Organic Social": 0.008, "Email": 0.031}
    for channel, sessions in values.items():
        rate = cvr.get(channel, 0.034)      # LLM referrals convert well
        conversions = round(sessions * rate, 1)
        rows.append({
            "Session default channel group": channel, "Date": f"{month}-01",
            "Sessions": sessions, "Total users": int(sessions * 0.86),
            "Key events": conversions, "Total revenue": 0,
        })
w("ga4_channels_monthly.csv", rows, list(rows[0].keys()))

# -------------------------------------------------------------- HubSpot
rows = []
for month in MONTHS:
    sessions = int(14000 * random.uniform(0.92, 1.08))
    leads = round(sessions * 0.023, 1)
    mqls = round(leads * 0.46, 1)
    sqls = round(mqls * 0.41, 1)
    opps = round(sqls * 0.78, 1)
    won = round(sqls * 0.23, 1)
    for segment in ("Organic Search", "Direct", "Paid Search", "Email"):
        share = {"Organic Search": 0.46, "Direct": 0.27, "Paid Search": 0.18, "Email": 0.09}[segment]
        rows.append({
            "Original source": segment, "Date": f"{month}-01",
            "Sessions": int(sessions * share), "Contacts": round(leads * share, 1),
            "MQLs": round(mqls * share, 1), "SQLs": round(sqls * share, 1),
            "Deals": round(opps * share, 1), "Closed Won": round(won * share, 1),
            "Pipeline value": round(opps * share * 31000, 2),
            "Closed won value": round(won * share * 24000, 2),
            "Avg deal size": 24000, "Days to close": 75,
        })
w("hubspot_funnel.csv", rows, list(rows[0].keys()))

# ------------------------------------------------------------- LinkedIn
TOPICS = ["forecast accuracy benchmark", "pipeline coverage myth", "revops stack teardown",
          "deal scoring teardown", "churn signal breakdown", "quota planning", "attribution reality check"]
rows = []
for i, month in enumerate(MONTHS):
    for n in range(3):
        impressions = int(random.uniform(4200, 16000))
        clicks = int(impressions * random.uniform(0.006, 0.021))
        rows.append({
            "Date": f"{month}-{5 + n * 9:02d}", "Post title": f"{random.choice(TOPICS)} #{i}{n}",
            "Impressions": impressions, "Clicks": clicks,
            "Engagements": int(impressions * random.uniform(0.02, 0.06)),
            "Engagement rate": f"{random.uniform(2.0, 6.0):.2f}%",
            "Followers": 12400 + i * 180 + n * 20,
        })
w("linkedin_posts.csv", rows, list(rows[0].keys()))

# -------------------------------------------------------------- Beehiiv
rows = []
subs = 8600
for i, month in enumerate(MONTHS):
    for n in range(2):
        subs += random.randint(90, 240)
        sends = subs
        opens = int(sends * random.uniform(0.34, 0.47))
        clicks = int(opens * random.uniform(0.07, 0.15))
        rows.append({
            "Send date": f"{month}-{7 + n * 14:02d}",
            "Subject": f"Vantive Signal #{i * 2 + n + 41}",
            "Sends": sends, "Opens": opens, "Clicks": clicks,
            "Open rate": f"{opens / sends * 100:.1f}%", "Click rate": f"{clicks / sends * 100:.1f}%",
            "Subscribers": subs,
        })
w("beehiiv_sends.csv", rows, list(rows[0].keys()))

# --------------------------------------------------------------- Webflow CMS
rows = []
for u, template, title, words, pub, upd in PAGES:
    rows.append({
        "Slug": u.replace(DOMAIN + "/", ""), "Name": title, "Collection": template,
        "Published on": pub, "Updated on": upd,
        "Author": random.choice(["J. Okafor", "M. Reyes", "S. Lindqvist", "D. Osei"]),
        "Word count": words,
        "Schema": "Article" if template in ("blog", "compare") else "WebPage",
    })
w("webflow_cms.csv", rows, list(rows[0].keys()))

# ---------------------------------------------------------- Screaming Frog
NOINDEX = {"/glossary/net-revenue-retention", "/customers/acme-logistics"}
ORPHANS = {"/blog/quota-attainment-analysis", "/glossary/sales-velocity", "/blog/arr-vs-mrr"}
BROKEN = ["/blog/old-forecasting-post", "/resources/2023-benchmark-report", "/blog/legacy-revops-guide"]
rows = []
for u, template, title, words, pub, upd in PAGES:
    path = u.replace(DOMAIN, "")
    inlinks = 1 if path in ORPHANS else random.randint(4, 46)
    rows.append({
        "Address": u, "Content Type": "text/html; charset=UTF-8", "Status Code": 200, "Status": "OK",
        "Indexability": "Non-Indexable" if path in NOINDEX else "Indexable",
        "Indexability Status": "noindex" if path in NOINDEX else "",
        "Title 1": title, "Meta Description 1": f"{title} - Vantive." if words > 500 else "",
        "H1-1": title, "Word Count": words, "Crawl Depth": random.randint(1, 5),
        "Unique Inlinks": inlinks, "Response Time": f"{random.uniform(0.18, 1.9):.3f}",
        "Canonical Link Element 1": u, "Last Modified": upd,
    })
for path in BROKEN:
    rows.append({
        "Address": DOMAIN + path, "Content Type": "text/html; charset=UTF-8", "Status Code": 404,
        "Status": "Not Found", "Indexability": "Non-Indexable", "Indexability Status": "Client Error",
        "Title 1": "", "Meta Description 1": "", "H1-1": "", "Word Count": 0, "Crawl Depth": 3,
        "Unique Inlinks": random.randint(2, 9), "Response Time": "0.210",
        "Canonical Link Element 1": "", "Last Modified": "",
    })
for path in ["/blog/glossary-stub-a", "/blog/glossary-stub-b"]:
    rows.append({
        "Address": DOMAIN + path, "Content Type": "text/html; charset=UTF-8", "Status Code": 200,
        "Status": "OK", "Indexability": "Indexable", "Indexability Status": "",
        "Title 1": "Stub", "Meta Description 1": "", "H1-1": "Stub", "Word Count": 120,
        "Crawl Depth": 6, "Unique Inlinks": 2, "Response Time": "1.850",
        "Canonical Link Element 1": DOMAIN + path, "Last Modified": "2023-04-01",
    })
w("screaming_frog_internal_html.csv", rows, list(rows[0].keys()))

# ------------------------------------------------------------- PageSpeed
SLOW = {"blog", "compare"}
rows = []
for u, template, title, words, pub, upd in PAGES:
    slow = template in SLOW
    rows.append({
        "URL": u, "Device": "mobile",
        "LCP": int(random.uniform(3100, 4700)) if slow else int(random.uniform(1700, 2450)),
        "INP": int(random.uniform(210, 390)) if slow else int(random.uniform(90, 185)),
        "CLS": f"{random.uniform(0.12, 0.28):.3f}" if slow else f"{random.uniform(0.01, 0.08):.3f}",
        "TTFB": int(random.uniform(380, 900)),
        "Performance": random.randint(31, 58) if slow else random.randint(72, 94),
        "SEO": random.randint(83, 100), "Accessibility": random.randint(74, 96),
    })
w("pagespeed_mobile.csv", rows, list(rows[0].keys()))

# a single Lighthouse JSON report, to exercise the JSON path too
lh = {
    "requestedUrl": DOMAIN + "/product/forecasting",
    "finalUrl": DOMAIN + "/product/forecasting",
    "configSettings": {"formFactor": "mobile"},
    "categories": {"performance": {"score": 0.44}, "seo": {"score": 0.92},
                   "accessibility": {"score": 0.81}},
    "audits": {
        "largest-contentful-paint": {"numericValue": 3980.4},
        "interaction-to-next-paint": {"numericValue": 268.0},
        "cumulative-layout-shift": {"numericValue": 0.19},
        "server-response-time": {"numericValue": 640.0},
    },
}
(OUT / "lighthouse_product_forecasting.json").write_text(json.dumps(lh, indent=2))
print(f"  {'lighthouse_product_forecasting.json':38} {1:>5} report")

# ---------------------------------------------------------- LLM citations
PROMPTS = [
    ("best revenue intelligence software", "revenue intelligence", 4800, "evaluation"),
    ("revenue intelligence platform comparison", "revenue intelligence", 1900, "evaluation"),
    ("what is revenue intelligence", "revenue intelligence", 3600, "awareness"),
    ("how do I improve forecast accuracy", "forecasting", 2900, "consideration"),
    ("best sales forecasting software", "forecasting", 5200, "evaluation"),
    ("how to build a revenue forecast", "forecasting", 3300, "awareness"),
    ("what pipeline coverage ratio should I target", "pipeline analytics", 1700, "consideration"),
    ("how to measure sales velocity", "pipeline analytics", 2100, "awareness"),
    ("tools for pipeline analytics", "pipeline analytics", 1150, "evaluation"),
    ("clearloop alternatives", "competitive", 590, "evaluation"),
    ("vantive vs clearloop", "competitive", 320, "evaluation"),
    ("is vantive good for revops", "competitive", 210, "evaluation"),
    ("what should be in a revops tech stack", "revops", 1800, "awareness"),
    ("how do I reduce revenue leakage", "revops", 2900, "consideration"),
]
ENGINES = ["ChatGPT", "Perplexity", "Gemini", "Copilot"]
CITE_RATE = {"revenue intelligence": 0.42, "forecasting": 0.22, "pipeline analytics": 0.55,
             "competitive": 0.71, "revops": 0.12}
rows = []
for month in MONTHS[-6:]:
    for prompt, cluster, volume, stage in PROMPTS:
        for engine in ENGINES:
            engine_bias = {"ChatGPT": 1.0, "Perplexity": 1.35, "Gemini": 0.7, "Copilot": 0.85}[engine]
            cited = random.random() < min(0.95, CITE_RATE[cluster] * engine_bias)
            competitors = random.sample(COMPETITORS, k=random.randint(1, 3))
            rows.append({
                "Date": f"{month}-15", "Prompt": prompt, "Cluster": cluster, "Engine": engine,
                "Brand cited": "yes" if cited else "no",
                "Brand position": random.randint(1, 4) if cited else "",
                "Sentiment": random.choice(["positive", "positive", "neutral"]) if cited else "",
                "Cited URLs": (f"{DOMAIN}/blog/revenue-intelligence-explained" if cited else ""),
                "Competitors cited": ", ".join(competitors),
                "Monthly prompt volume": volume, "Buying stage": stage,
            })
w("llm_citations.csv", rows, list(rows[0].keys()))

# ----------------------------------------------------------- Server logs
BOTS = ["Googlebot", "Bingbot", "GPTBot", "PerplexityBot", "ClaudeBot", "Google-Extended", "OAI-SearchBot"]
AI_COVERED = {p[0] for p in PAGES[:18]}     # AI crawlers have not reached the rest
rows = []
for month in MONTHS[-6:]:
    for u, template, title, words, pub, upd in PAGES:
        for bot in BOTS:
            is_ai = bot in ("GPTBot", "PerplexityBot", "ClaudeBot", "Google-Extended", "OAI-SearchBot")
            if is_ai and u not in AI_COVERED:
                continue
            hits = random.randint(4, 60) if not is_ai else random.randint(1, 14)
            rows.append({"URL": u, "Bot": bot, "Hits": hits, "Date": f"{month}-01"})
w("server_logs_crawlers.csv", rows, list(rows[0].keys()))

# --------------------------------------------------------------- Survey
rows = []
for quarter, (period, n) in enumerate([("2025-10-01", 118), ("2026-01-01", 143), ("2026-04-01", 137), ("2026-07-01", 156)]):
    rows.append({
        "Period start": period, "Respondents": n,
        "Share search engine": f"{random.uniform(0.46, 0.53):.3f}",
        "Share AI assistant": f"{random.uniform(0.12, 0.20):.3f}",
        "Share other": f"{random.uniform(0.30, 0.40):.3f}",
        "Converted only": "true",
    })
w("discovery_survey.csv", rows, list(rows[0].keys()))
print("\nSample dataset written to data/sample/")
