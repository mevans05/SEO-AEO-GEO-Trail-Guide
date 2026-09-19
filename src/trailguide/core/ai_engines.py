"""Identification of AI answer/generative engines across referrers, bots and panels.

Three surfaces need to agree on what counts as an LLM:

* **Referrers** in analytics - the Track 1 known-attribution signal.
* **Crawler user agents** in server logs - the retrieval-side evidence that an
  engine actually fetched a page.
* **Engine labels** in the citation panel - the visibility signal.

Keeping the vocabulary in one place means a newly launched assistant is added
once and is immediately recognized everywhere.
"""

from __future__ import annotations

#: Referrer host fragments that indicate an LLM-referred session.
LLM_REFERRER_DOMAINS: dict[str, str] = {
    "chatgpt.com": "chatgpt",
    "chat.openai.com": "chatgpt",
    "openai.com": "chatgpt",
    "perplexity.ai": "perplexity",
    "gemini.google.com": "gemini",
    "bard.google.com": "gemini",
    "copilot.microsoft.com": "copilot",
    "bing.com/chat": "copilot",
    "claude.ai": "claude",
    "you.com": "you",
    "poe.com": "poe",
    "phind.com": "phind",
    "mistral.ai": "mistral",
    "meta.ai": "meta_ai",
    "grok.com": "grok",
    "x.ai": "grok",
    "duckduckgo.com/aichat": "duckassist",
}

#: Traditional search engine host fragments, used to separate organic from LLM.
SEARCH_ENGINE_DOMAINS: tuple[str, ...] = (
    "google.", "bing.com", "yahoo.", "duckduckgo.com", "ecosia.org",
    "baidu.com", "yandex.", "brave.com", "startpage.com",
)

#: User-agent fragments of AI crawlers, mapped to the engine they feed.
AI_CRAWLER_AGENTS: dict[str, str] = {
    "gptbot": "chatgpt",
    "oai-searchbot": "chatgpt",
    "chatgpt-user": "chatgpt",
    "perplexitybot": "perplexity",
    "perplexity-user": "perplexity",
    "claudebot": "claude",
    "claude-web": "claude",
    "anthropic-ai": "claude",
    "google-extended": "gemini",
    "googleother": "gemini",
    "bingbot-chat": "copilot",
    "applebot-extended": "apple",
    "ccbot": "common_crawl",
    "meta-externalagent": "meta_ai",
    "amazonbot": "amazon",
    "bytespider": "bytedance",
    "youbot": "you",
    "diffbot": "diffbot",
    "cohere-ai": "cohere",
    "mistralai-user": "mistral",
}

#: User-agent fragments of classic search crawlers.
SEARCH_CRAWLER_AGENTS: dict[str, str] = {
    "googlebot": "google",
    "bingbot": "bing",
    "duckduckbot": "duckduckgo",
    "yandexbot": "yandex",
    "baiduspider": "baidu",
    "applebot": "apple",
}

#: Canonical engine names for the citation panel.
ENGINE_ALIASES: dict[str, str] = {
    "chatgpt": "chatgpt", "openai": "chatgpt", "gpt": "chatgpt", "gpt-4": "chatgpt",
    "perplexity": "perplexity", "pplx": "perplexity",
    "gemini": "gemini", "bard": "gemini", "google ai": "gemini", "ai overview": "gemini",
    "copilot": "copilot", "bing chat": "copilot", "microsoft copilot": "copilot",
    "claude": "claude", "anthropic": "claude",
    "grok": "grok", "meta ai": "meta_ai", "you.com": "you", "deepseek": "deepseek",
}


def llm_engine_from_referrer(referrer: str | None) -> str | None:
    """Return the LLM engine behind a referrer/source string, or ``None``."""
    if not referrer:
        return None
    text = str(referrer).strip().lower()
    for domain, engine in LLM_REFERRER_DOMAINS.items():
        if domain in text:
            return engine
    return None


def is_llm_referral(referrer: str | None) -> bool:
    """True when a referrer or source/medium string points at an LLM surface."""
    return llm_engine_from_referrer(referrer) is not None


def is_search_referral(referrer: str | None) -> bool:
    """True when a referrer string points at a traditional search engine."""
    if not referrer:
        return False
    text = str(referrer).strip().lower()
    if is_llm_referral(text):
        return False
    return any(domain in text for domain in SEARCH_ENGINE_DOMAINS) or "organic" in text


def is_direct(channel: str | None) -> bool:
    """True for direct/none traffic, the main carrier of dark demand."""
    if not channel:
        return False
    text = str(channel).strip().lower()
    return "direct" in text or text in {"(none)", "none", "(direct) / (none)"}


def classify_bot(user_agent: str | None) -> tuple[str, bool]:
    """Classify a crawler user agent.

    Returns ``(engine_name, is_ai_bot)``; unknown agents come back as
    ``("other", False)`` so they are counted but never inflate AI coverage.
    """
    if not user_agent:
        return ("other", False)
    text = str(user_agent).strip().lower()
    for fragment, engine in AI_CRAWLER_AGENTS.items():
        if fragment in text:
            return (engine, True)
    for fragment, engine in SEARCH_CRAWLER_AGENTS.items():
        if fragment in text:
            return (engine, False)
    return ("other", False)


def normalize_engine(name: str | None) -> str:
    """Canonicalize an engine label from a citation panel export."""
    if not name:
        return "unknown"
    text = str(name).strip().lower()
    if text in ENGINE_ALIASES:
        return ENGINE_ALIASES[text]
    for alias, canonical in ENGINE_ALIASES.items():
        if alias in text:
            return canonical
    return text.replace(" ", "_")
