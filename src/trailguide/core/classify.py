"""Query classification: branded detection, intent and topic clustering.

The branded/non-branded split is load-bearing rather than cosmetic. The POV's
dark-traffic model reads branded search and direct traffic as the *downstream
signal* of non-branded and LLM discovery, so misclassifying branded demand as
organic wins double-counts revenue.

Vendor-supplied intent is always preferred when present; the keyword heuristics
here are the fallback for exports that omit it.
"""

from __future__ import annotations

import re
from typing import Iterable

from .schemas import Intent

#: Tokens that signal each intent when no vendor intent column exists.
INTENT_MARKERS: dict[Intent, tuple[str, ...]] = {
    Intent.TRANSACTIONAL: (
        "buy", "pricing", "price", "cost", "quote", "demo", "trial", "free trial",
        "subscribe", "purchase", "order", "signup", "sign up", "discount", "coupon",
        "cheap", "deal", "book", "hire", "get started",
    ),
    Intent.COMMERCIAL: (
        "best", "top", "vs", "versus", "compare", "comparison", "alternative",
        "alternatives", "review", "reviews", "software", "tools", "platform",
        "services", "vendor", "provider", "for small business", "enterprise",
        "competitor", "rating",
    ),
    Intent.INFORMATIONAL: (
        "what is", "what are", "how to", "how do", "how does", "why", "when",
        "guide", "tutorial", "examples", "template", "checklist", "meaning",
        "definition", "tips", "ideas", "benefits", "explained", "learn",
    ),
}

#: Vendor spellings mapped onto the canonical intent enum.
VENDOR_INTENT_MAP: dict[str, Intent] = {
    "t": Intent.TRANSACTIONAL, "transactional": Intent.TRANSACTIONAL,
    "c": Intent.COMMERCIAL, "commercial": Intent.COMMERCIAL,
    "i": Intent.INFORMATIONAL, "informational": Intent.INFORMATIONAL,
    "n": Intent.NAVIGATIONAL, "navigational": Intent.NAVIGATIONAL,
}

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def normalize_term(text: str | None) -> str:
    """Lowercase and collapse a term for comparison."""
    if not text:
        return ""
    return " ".join(_WORD_SPLIT.split(str(text).lower())).strip()


def is_branded(keyword: str | None, brand_terms: Iterable[str]) -> bool:
    """True when the keyword contains any brand token.

    Multi-word brand terms match as phrases; single tokens match whole words so
    a brand called "Nova" does not capture "innovation".
    """
    text = normalize_term(keyword)
    if not text:
        return False
    tokens = set(text.split())
    for term in brand_terms:
        term = normalize_term(term)
        if not term:
            continue
        if " " in term:
            if term in text:
                return True
        elif term in tokens:
            return True
    return False


def classify_intent(keyword: str | None, vendor_intent: str | None = None) -> Intent:
    """Classify query intent, preferring a vendor-supplied label.

    Heuristic matching checks transactional markers first, then commercial, then
    informational, because a query like "best crm pricing" should be valued as
    the higher-intent term it is.
    """
    if vendor_intent:
        for token in re.split(r"[,/|]", str(vendor_intent).lower()):
            mapped = VENDOR_INTENT_MAP.get(token.strip())
            if mapped:
                return mapped
    text = normalize_term(keyword)
    if not text:
        return Intent.UNKNOWN
    padded = f" {text} "
    for intent in (Intent.TRANSACTIONAL, Intent.COMMERCIAL, Intent.INFORMATIONAL):
        for marker in INTENT_MARKERS[intent]:
            if f" {marker} " in padded or padded.startswith(f" {marker} "):
                return intent
    return Intent.UNKNOWN


def assign_cluster(keyword: str | None, cluster_rules: dict[str, list[str]] | None) -> str | None:
    """Map a keyword to a topic cluster using configured token rules.

    ``cluster_rules`` maps a cluster name to the tokens that imply it, letting
    strategy weight whole topics without hand-labelling every keyword.
    """
    if not cluster_rules:
        return None
    text = normalize_term(keyword)
    if not text:
        return None
    best: tuple[int, str] | None = None
    for cluster, tokens in cluster_rules.items():
        for token in tokens or []:
            token_norm = normalize_term(token)
            if token_norm and token_norm in text:
                # Longer matches win, so "crm software" beats a bare "crm" rule.
                score = len(token_norm)
                if best is None or score > best[0]:
                    best = (score, cluster)
    return best[1] if best else None


def url_template(url: str | None, rules: dict[str, list[str]] | None = None) -> str | None:
    """Infer a page template from its URL path.

    Templates feed the revenue model's per-template multipliers, so a pricing
    page and a blog post are not valued identically.
    """
    if not url:
        return None
    path = re.sub(r"^https?://[^/]+", "", str(url)).lower()
    for template, patterns in (rules or {}).items():
        for pattern in patterns or []:
            if str(pattern).lower() in path:
                return template
    for template, marker in (
        ("blog", "/blog"), ("resources", "/resources"), ("docs", "/docs"),
        ("pricing", "/pricing"), ("product", "/product"), ("solutions", "/solutions"),
        ("case_study", "/case-stud"), ("compare", "/compare"), ("glossary", "/glossary"),
    ):
        if marker in path:
            return template
    return "home" if path in ("", "/") else "other"


#: Vendor spellings of SERP features mapped onto the CTR model's canonical keys.
SERP_FEATURE_ALIASES: dict[str, str] = {
    "ai overview": "ai_overview", "ai overviews": "ai_overview", "sge": "ai_overview",
    "ai mode": "ai_overview", "generative": "ai_overview",
    "featured snippet": "featured_snippet", "featured snippets": "featured_snippet",
    "answer box": "featured_snippet", "instant answer": "featured_snippet",
    "people also ask": "people_also_ask", "related questions": "people_also_ask",
    "knowledge panel": "knowledge_panel", "knowledge graph": "knowledge_panel",
    "knowledge card": "knowledge_panel",
    "local pack": "local_pack", "map pack": "local_pack", "local teaser": "local_pack",
    "shopping": "shopping", "shopping ads": "shopping", "product listing": "shopping",
    "popular products": "shopping",
    "video": "video_carousel", "videos": "video_carousel", "video carousel": "video_carousel",
    "image": "image_pack", "images": "image_pack", "image pack": "image_pack",
    "ads top": "top_ads", "top ads": "top_ads", "adwords top": "top_ads",
    "sitelinks": "sitelinks", "site links": "sitelinks",
    "reviews": "review_snippet", "review": "review_snippet", "review snippet": "review_snippet",
}


def normalize_serp_features(raw: object, separator: str = ",") -> list[str]:
    """Normalize a vendor's SERP-feature cell into canonical CTR model keys.

    Unrecognized features are kept in snake_case rather than dropped, so a newly
    launched SERP feature still shows up in reports even before the CTR model
    has an effect calibrated for it.
    """
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple, set)) else str(raw).split(separator)
    features: list[str] = []
    for item in items:
        text = str(item).strip().lower()
        if not text or text in {"-", "n/a", "none"}:
            continue
        canonical = SERP_FEATURE_ALIASES.get(text)
        if canonical is None:
            for alias, mapped in SERP_FEATURE_ALIASES.items():
                if alias in text:
                    canonical = mapped
                    break
        features.append(canonical or _WORD_SPLIT.sub("_", text).strip("_"))
    # Preserve first-seen order while removing duplicates.
    return list(dict.fromkeys(features))
