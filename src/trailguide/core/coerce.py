"""Tolerant type coercion for third-party exports.

Vendor exports are messy: Semrush writes ``"1,200"``, Search Console writes
``"12.4%"``, Screaming Frog writes ``"N/A"``, HubSpot writes ``"$1,250.00"``.
Every connector funnels values through these helpers so a single malformed cell
degrades to a null rather than aborting an entire analysis run.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Iterable

_NULLISH = {"", "-", "--", "n/a", "na", "none", "null", "nan", "#n/a", "(not set)", "(not provided)"}

_NUMERIC_STRIP = re.compile(r"[,$£€¥\s]")
_TRUEISH = {"true", "yes", "y", "1", "t", "indexable", "pass", "passed"}
_FALSEISH = {"false", "no", "n", "0", "f", "non-indexable", "fail", "failed"}


def is_null(value: Any) -> bool:
    """Return True for the many ways an export can say "no value"."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    if isinstance(value, str) and value.strip().lower() in _NULLISH:
        return True
    return False


def to_float(value: Any, default: float | None = None) -> float | None:
    """Coerce to float, tolerating currency symbols, thousands separators and %.

    A trailing ``%`` is treated as a percentage and divided by 100, so
    ``"12.4%"`` becomes ``0.124``.
    """
    if is_null(value):
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    percent = text.endswith("%")
    if percent:
        text = text[:-1]
    text = _NUMERIC_STRIP.sub("", text)
    if text.startswith("(") and text.endswith(")"):  # accounting negatives
        text = "-" + text[1:-1]
    try:
        number = float(text)
    except ValueError:
        return default
    return number / 100.0 if percent else number


def to_int(value: Any, default: int | None = None) -> int | None:
    """Coerce to int via :func:`to_float`, rounding half away from zero."""
    number = to_float(value, None)
    if number is None:
        return default
    return int(round(number))


def to_bool(value: Any, default: bool | None = None) -> bool | None:
    """Coerce common truthy/falsey spellings used by crawlers and CMS exports."""
    if is_null(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUEISH:
        return True
    if text in _FALSEISH:
        return False
    return default


def to_str(value: Any, default: str | None = None) -> str | None:
    """Coerce to a stripped string, mapping null-ish spellings to ``default``."""
    if is_null(value):
        return default
    return str(value).strip()


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m",
    "%b %Y",
    "%B %Y",
)


def to_date(value: Any, default: _dt.date | None = None) -> _dt.date | None:
    """Parse the date spellings that appear across analytics and CMS exports."""
    if is_null(value):
        return default
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    text = str(value).strip()
    # GA4 and Search Console bulk exports frequently use YYYYMMDD.
    if re.fullmatch(r"\d{8}", text):
        try:
            return _dt.datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return default
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(text.replace("Z", ""), fmt).date()
        except ValueError:
            continue
    return default


def to_list(value: Any, separator: str = ",") -> list[str]:
    """Split a delimited cell into a clean list of tokens."""
    if is_null(value):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if not is_null(item)]
    return [token.strip() for token in str(value).split(separator) if token.strip()]


_SEPARATORS = re.compile(r"[\s_\-.]+")


def canonical_key(name: Any) -> str:
    """Collapse a column name to a separator- and case-insensitive form.

    ``"Monthly prompt volume"``, ``"monthly_prompt_volume"`` and
    ``"Monthly-Prompt-Volume"`` all reduce to ``"monthly prompt volume"``.
    Vendors are inconsistent about separators between export versions, locales
    and API-versus-UI downloads, so matching on the collapsed form means a
    connector declares each alias once instead of once per spelling.
    """
    return _SEPARATORS.sub(" ", str(name).strip().lower()).strip()


def first_present(row: dict[str, Any], names: Iterable[str]) -> Any:
    """Return the first non-null value among ``names``.

    Matching ignores case and separator style (see :func:`canonical_key`), so
    ``"Search Volume"``, ``"search_volume"`` and ``"volume"`` all resolve.
    """
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        normalized.setdefault(canonical_key(key), value)
    for name in names:
        value = normalized.get(canonical_key(name))
        if not is_null(value):
            return value
    return None


def clamp(value: float, low: float, high: float) -> float:
    """Constrain ``value`` to the inclusive ``[low, high]`` interval."""
    return max(low, min(high, value))
