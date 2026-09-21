#!/usr/bin/env python3
"""Generate the bundled sample dataset.

Fictional brand (cascadehr.com) in a fictional category. Header names are
deliberately drawn from different vendors' real export conventions so the
normalizer's column mapping gets exercised rather than flattered.
"""
import csv, random, os
random.seed(1971)

BRAND = "cascadehr.com"
COMPETITORS = ["bamboohr.example", "rippling.example", "gustohq.example",
               "hibob.example", "personio.example"]

ENGINES = ["ChatGPT", "Perplexity", "Google AI Overviews", "Claude", "Gemini"]

PROMPTS = [
    ("best HR software for small business", "commercial", 8100, 71, 6),
    ("BambooHR alternatives", "commercial", 2400, 58, 4),
    ("how to run payroll for the first time", "informational", 3600, 34, 3),
    ("what is an HRIS", "informational", 5400, 29, 5),
    ("HR software pricing comparison", "commercial", 1900, 62, 5),
    ("employee onboarding checklist template", "informational", 4400, 31, 4),
    ("best applicant tracking systems 2026", "commercial", 6600, 74, 7),
    ("PEO vs HRIS", "informational", 880, 38, 2),
    ("how to calculate PTO accrual", "informational", 2900, 24, 3),
    ("remote employee compliance requirements", "informational", 1300, 45, 3),
    ("HR software for 50 employees", "commercial", 720, 49, 4),
    ("open enrollment best practices", "informational", 1600, 33, 3),
    ("what is a 401k safe harbor plan", "informational", 3300, 41, 5),
    ("performance review templates", "informational", 7200, 36, 6),
    ("cheapest payroll software", "commercial", 1100, 55, 4),
    ("HRIS implementation timeline", "informational", 390, 22, 1),
    ("how to write an employee handbook", "informational", 2700, 39, 4),
    ("best HR software for startups", "commercial", 1800, 64, 5),
    ("employee turnover rate benchmarks", "informational", 1450, 28, 2),
    ("Gusto vs Rippling", "commercial", 2200, 51, 3),
    ("multi-state payroll tax rules", "informational", 610, 47, 2),
    ("HR analytics dashboard examples", "informational", 480, 26, 1),
    ("what is quiet hiring", "informational", 320, 18, 1),
    ("compensation benchmarking tools", "commercial", 890, 53, 4),
    ("how to reduce time to hire", "informational", 540, 30, 2),
    ("SOC 2 requirements for HR data", "informational", 410, 44, 2),
    ("best benefits administration software", "commercial", 1250, 60, 5),
    ("employee engagement survey questions", "informational", 5900, 35, 6),
    ("I-9 compliance checklist", "informational", 2100, 32, 3),
    ("HR software integrations with QuickBooks", "commercial", 330, 27, 2),
]

# Cited sources, with their real-world archetype and a rough authority.
SOURCES = [
    ("g2.com", 92, "review"), ("capterra.com", 90, "review"),
    ("trustradius.com", 78, "review"), ("softwareadvice.com", 81, "review"),
    ("shrm.org", 86, "trade"), ("hrdive.com", 74, "trade"),
    ("forbes.com", 94, "news"), ("businessinsider.com", 92, "news"),
    ("inc.com", 89, "news"), ("techcrunch.com", 93, "news"),
    ("fastcompany.com", 91, "news"), ("nerdwallet.com", 88, "news"),
    ("reddit.com", 95, "community"), ("quora.com", 87, "community"),
    ("wikipedia.org", 97, "encyclopedia"),
    ("thebalancemoney.com", 80, "editorial"), ("hrtechnologist.example", 61, "trade"),
    ("peoplemanagingpeople.example", 52, "editorial"),
    ("selectsoftwarereviews.example", 58, "review"),
    ("hrexecutive.example", 67, "trade"), ("workology.example", 55, "editorial"),
    ("tlnt.example", 59, "trade"), ("hrmorning.example", 57, "trade"),
    ("crunchbase.com", 91, "database"), ("clutch.co", 82, "database"),
    ("gartner.com", 93, "review"), ("paycheckcity.example", 63, "editorial"),
    ("irs.gov", 96, "institutional"), ("dol.gov", 95, "institutional"),
    ("smallbiztrends.example", 66, "editorial"), ("cascadehr.com", 44, "own"),
]
SRC_DR = {d: dr for d, dr, _ in SOURCES}

os.makedirs(".", exist_ok=True)

# ---- citations (Profound / Peec style export) --------------------------
with open("citations_ai_visibility.csv", "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    wr.writerow(["Prompt", "AI Platform", "Run Date", "Brand Mentioned",
                 "Brand Position", "Citation URL", "Source Domain",
                 "Sentiment", "Competing Brands Mentioned"])
    for prompt, intent, vol, kd, ncomp in PROMPTS:
        # Harder commercial prompts get broad engine coverage; niche ones less.
        engines = random.sample(ENGINES, k=random.choice([3, 4, 5, 5]))
        # Brand wins more on low-difficulty informational prompts.
        win_base = 0.62 if (intent == "informational" and kd < 35) else 0.16
        for eng in engines:
            mentioned = random.random() < win_base
            pos = random.randint(1, 5) if mentioned else ""
            comps = random.sample(COMPETITORS, k=min(ncomp, len(COMPETITORS)))
            if mentioned and random.random() < 0.4:
                comps = comps[:max(1, len(comps) - 2)]
            pool = [s for s in SOURCES if s[0] != BRAND]
            if intent == "commercial":
                pool = [s for s in pool if s[2] in ("review", "news", "trade", "editorial", "database")]
            n_cites = random.randint(2, 6) if kd > 40 else random.randint(1, 3)
            cited = random.sample(pool, k=min(n_cites, len(pool)))
            if mentioned and random.random() < 0.45:
                cited.append(("cascadehr.com", 44, "own"))
            for dom, dr, _kind in cited:
                slug = prompt.replace(" ", "-").lower()[:40]
                wr.writerow([prompt, eng, "2026-09-0%d" % random.randint(1, 9),
                             "Yes" if mentioned else "No", pos,
                             f"https://{dom}/{slug}", dom,
                             random.choice(["positive", "positive", "neutral", "neutral", "negative"])
                             if mentioned else "",
                             "; ".join(comps)])

# ---- backlinks (Ahrefs style) ------------------------------------------
LINKING = [("shrm.org", 86), ("hrdive.com", 74), ("thebalancemoney.com", 80),
           ("workology.example", 55), ("hrmorning.example", 57),
           ("smallbiztrends.example", 66), ("capterra.com", 90),
           ("paycheckcity.example", 63), ("startupsavant.example", 41),
           ("austinchamber.example", 48), ("hrtechfeed.example", 33),
           ("saasgenius.example", 38), ("techbullion.example", 44),
           ("medium.com", 95), ("linkedin.com", 98)]
EXTRA = [(f"hrblog{i}.example", random.randint(12, 48)) for i in range(1, 34)]

with open("backlinks_ahrefs_export.csv", "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    wr.writerow(["Referring page URL", "Referring page title", "Domain rating",
                 "Domain traffic", "Anchor", "Type", "Target URL", "First seen"])
    for dom, dr in LINKING + EXTRA:
        for _ in range(random.randint(1, 3)):
            anchor = random.choice(["Cascade HR", "Cascade HR", "cascadehr.com",
                                    "HR software", "this HR platform", "read more",
                                    "best HR software for small business"])
            wr.writerow([f"https://{dom}/post-{random.randint(100,999)}",
                         f"Article on {dom}", dr, random.randint(500, 900000), anchor,
                         random.choice(["Dofollow", "Dofollow", "Dofollow", "Nofollow"]),
                         f"https://{BRAND}/{random.choice(['', 'pricing', 'blog/hr-guide', 'features'])}",
                         f"2025-0{random.randint(1,9)}-1{random.randint(0,9)}"])
    # Competitor link intersect rows, so the pure link-gap analysis has fuel.
    for dom, dr in [("forbes.com", 94), ("inc.com", 89), ("nerdwallet.com", 88),
                    ("selectsoftwareReviews.example", 58), ("tlnt.example", 59),
                    ("hrexecutive.example", 67), ("g2.com", 92),
                    ("peoplemanagingpeople.example", 52), ("fitsmallbiz.example", 72),
                    ("businessnewsdaily.example", 76)]:
        for comp in random.sample(COMPETITORS, k=random.randint(2, 4)):
            wr.writerow([f"https://{dom}/review-{random.randint(10,99)}",
                         f"Review on {dom}", dr, random.randint(10000, 900000),
                         comp.split(".")[0], "Dofollow", f"https://{comp}/", "2025-06-01"])

# ---- authority (Semrush style) -----------------------------------------
with open("domain_authority_semrush.csv", "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    wr.writerow(["Domain", "Is Client", "Authority Score", "Referring Domains",
                 "Organic Traffic", "Organic Keywords", "Snapshot Date"])
    wr.writerow([BRAND, "TRUE", 44, 412, 28500, 6200, "2026-09-01"])
    for dom, dr, rd, tr, kw in [
        ("bamboohr.example", 81, 14200, 890000, 121000),
        ("rippling.example", 78, 9800, 640000, 88000),
        ("gustohq.example", 79, 11500, 720000, 96000),
        ("hibob.example", 68, 5400, 310000, 47000),
        ("personio.example", 71, 6900, 402000, 58000),
    ]:
        wr.writerow([dom, "FALSE", dr, rd, tr, kw, "2026-09-01"])

# ---- competitors (with AI share) ---------------------------------------
with open("competitor_metrics.json", "w", encoding="utf-8") as fh:
    import json
    json.dump({"results": [
        {"competitor_domain": "bamboohr.example", "domain_rating": 81,
         "referring_domains": 14200, "organic_traffic": 890000,
         "ai_answer_share": 61.4, "notes": "Category leader, heavy review-site presence"},
        {"competitor_domain": "rippling.example", "domain_rating": 78,
         "referring_domains": 9800, "organic_traffic": 640000,
         "ai_answer_share": 48.2, "notes": "Strong paid + PR motion"},
        {"competitor_domain": "gustohq.example", "domain_rating": 79,
         "referring_domains": 11500, "organic_traffic": 720000,
         "ai_answer_share": 52.7, "notes": "Owns payroll informational queries"},
        {"competitor_domain": "hibob.example", "domain_rating": 68,
         "referring_domains": 5400, "organic_traffic": 310000,
         "ai_answer_share": 24.1, "notes": "EMEA-weighted"},
        {"competitor_domain": "personio.example", "domain_rating": 71,
         "referring_domains": 6900, "organic_traffic": 402000,
         "ai_answer_share": 29.8, "notes": "EMEA-weighted, rising"},
    ]}, fh, indent=2)

# ---- content gaps ------------------------------------------------------
with open("content_gap_analysis.csv", "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    wr.writerow(["Keyword", "Search Volume", "Keyword Difficulty", "Our Rank",
                 "Best Competitor Rank", "Competitors Ranking", "Search Intent",
                 "CPC", "AI Overview"])
    for prompt, intent, vol, kd, ncomp in PROMPTS:
        our = random.choice(["", "", 4, 7, 9, 12, 18, 23, 31, 47, 64])
        wr.writerow([prompt, vol, kd, our, random.randint(1, 4), ncomp, intent,
                     round(random.uniform(1.2, 24.0), 2),
                     random.choice(["Yes", "No", "Yes"])])
    for extra, vol, kd in [("payroll software for restaurants", 590, 43),
                           ("HR compliance calendar 2026", 720, 26),
                           ("what is total rewards", 1100, 31),
                           ("best HR software for nonprofits", 480, 52),
                           ("exit interview questions", 3900, 29),
                           ("how to conduct a stay interview", 260, 19)]:
        wr.writerow([extra, vol, kd, "", random.randint(1, 5), random.randint(2, 6),
                     "informational", round(random.uniform(0.8, 12.0), 2), "No"])

print("Sample data written.")
