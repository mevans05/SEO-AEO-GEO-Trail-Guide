"""Client configuration: targets, economics, capacity and source wiring.

A run is fully described by one YAML file. Nothing about a client is hard-coded
in the engine, so onboarding a new brand means writing a config and pointing it
at exports - not editing analysis code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

#: Fully loaded day rates by discipline, used when a config omits them.
DEFAULT_COST_PER_DAY: dict[str, float] = {
    "seo": 950.0,
    "content": 850.0,
    "engineering": 1200.0,
    "design": 900.0,
    "analytics": 1000.0,
    "outreach": 800.0,
    "strategy": 1400.0,
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base``, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class SourceSpec:
    """One configured input: a connector type plus where its data lives."""

    type: str
    path: str | None = None
    name: str | None = None
    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SourceSpec":
        if "type" not in raw:
            raise ConfigError(f"source entry is missing required key 'type': {raw!r}")
        known = {"type", "path", "name", "enabled", "options"}
        spec = cls(
            type=str(raw["type"]).strip().lower(),
            path=raw.get("path"),
            name=raw.get("name"),
            enabled=bool(raw.get("enabled", True)),
            options=dict(raw.get("options") or {}),
        )
        # Allow flat inline options so simple sources stay terse in YAML.
        for key, value in raw.items():
            if key not in known:
                spec.options.setdefault(key, value)
        return spec

    @property
    def label(self) -> str:
        return self.name or self.type


@dataclass
class Config:
    """Parsed client configuration with typed accessors over the raw mapping."""

    raw: dict[str, Any] = field(default_factory=dict)
    base_dir: Path = field(default_factory=Path.cwd)
    path: Path | None = None

    # -- loading ---------------------------------------------------------

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "Config":
        """Load a YAML config, resolving ``extends`` against the same directory."""
        config_path = Path(path).expanduser().resolve()
        if not config_path.is_file():
            raise ConfigError(f"config file not found: {config_path}")
        raw = cls._load_with_extends(config_path, seen=set())
        return cls(raw=raw, base_dir=config_path.parent, path=config_path)

    @classmethod
    def _load_with_extends(cls, path: Path, seen: set[Path]) -> dict[str, Any]:
        if path in seen:
            raise ConfigError(f"circular 'extends' chain at {path}")
        seen.add(path)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"could not parse {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"config root must be a mapping: {path}")
        parent_ref = loaded.pop("extends", None)
        if parent_ref:
            parent_path = (path.parent / str(parent_ref)).resolve()
            if not parent_path.is_file():
                raise ConfigError(f"'extends' target not found: {parent_path}")
            parent = cls._load_with_extends(parent_path, seen)
            return _deep_merge(parent, loaded)
        return loaded

    @classmethod
    def from_dict(cls, raw: dict[str, Any], base_dir: str | os.PathLike[str] | None = None) -> "Config":
        """Build a config from an in-memory mapping (used by tests and the API)."""
        return cls(raw=dict(raw), base_dir=Path(base_dir or Path.cwd()))

    # -- access ----------------------------------------------------------

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Fetch a nested value by dotted path, e.g. ``"planning.horizon_months"``."""
        node: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        """Return a top-level section as a dict, never ``None``."""
        value = self.raw.get(name)
        return dict(value) if isinstance(value, dict) else {}

    def resolve_path(self, path: str | os.PathLike[str]) -> Path:
        """Resolve a possibly-relative source path against the config's directory."""
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.base_dir / candidate).resolve()

    # -- typed views -----------------------------------------------------

    @property
    def client_name(self) -> str:
        return str(self.get("client.name", "Unnamed client"))

    @property
    def domain(self) -> str:
        return str(self.get("client.domain", ""))

    @property
    def brand_terms(self) -> list[str]:
        """Lowercased brand tokens used to split branded from non-branded demand."""
        terms = self.get("client.brand_terms") or []
        if not terms and self.domain:
            terms = [self.domain.split(".")[0]]
        return [str(term).strip().lower() for term in terms if str(term).strip()]

    @property
    def competitors(self) -> list[str]:
        return [str(name).strip() for name in (self.get("client.competitors") or [])]

    @property
    def horizon_months(self) -> int:
        return int(self.get("planning.horizon_months", 12))

    @property
    def revenue_target(self) -> float:
        """Incremental revenue the portfolio must deliver inside the horizon."""
        return float(self.get("planning.revenue_target", 0.0) or 0.0)

    @property
    def baseline_revenue(self) -> float:
        """Current organic-attributed revenue, used for the revenue bridge."""
        return float(self.get("planning.baseline_organic_revenue", 0.0) or 0.0)

    @property
    def currency(self) -> str:
        return str(self.get("planning.currency", self.get("economics.currency", "USD")))

    @property
    def quarters(self) -> int:
        """Number of planning quarters the roadmap is laid out across."""
        return max(1, int(self.get("planning.quarters", max(1, round(self.horizon_months / 3)))))

    @property
    def cost_per_day(self) -> dict[str, float]:
        merged = dict(DEFAULT_COST_PER_DAY)
        merged.update(
            {str(k).lower(): float(v) for k, v in (self.get("effort.cost_per_day") or {}).items()}
        )
        return merged

    @property
    def capacity_per_quarter(self) -> dict[str, float]:
        """Deliverable person-days per discipline per quarter."""
        return {
            str(k).lower(): float(v)
            for k, v in (self.get("capacity.per_quarter") or {}).items()
        }

    @property
    def strategic_multipliers(self) -> dict[str, float]:
        """Topic/cluster weights letting strategy tilt a data-derived ranking."""
        return {
            str(k).strip().lower(): float(v)
            for k, v in (self.get("strategy.cluster_multipliers") or {}).items()
        }

    @property
    def sources(self) -> list[SourceSpec]:
        raw_sources = self.get("sources") or []
        if not isinstance(raw_sources, list):
            raise ConfigError("'sources' must be a list of source mappings")
        return [SourceSpec.from_dict(entry) for entry in raw_sources]

    @property
    def enabled_analyzers(self) -> list[str] | None:
        """Explicit analyzer allowlist, or ``None`` to run everything registered."""
        names = self.get("analysis.enabled")
        if not names:
            return None
        return [str(name).strip().lower() for name in names]

    @property
    def disabled_analyzers(self) -> list[str]:
        return [str(name).strip().lower() for name in (self.get("analysis.disabled") or [])]

    def analyzer_settings(self, analyzer_name: str) -> dict[str, Any]:
        """Per-analyzer overrides, merged over the shared ``analysis.defaults`` block."""
        defaults = self.get("analysis.defaults") or {}
        specific = (self.get("analysis.settings") or {}).get(analyzer_name) or {}
        return _deep_merge(dict(defaults), dict(specific))

    def effort_profile(self, opportunity_type: str) -> dict[str, Any]:
        """Effort template for an opportunity type from the ``effort.profiles`` block."""
        profiles = self.get("effort.profiles") or {}
        return dict(profiles.get(opportunity_type) or {})

    def validate(self) -> list[str]:
        """Return human-readable warnings about a config that will still run.

        Hard errors raise during load; this surfaces the softer problems that
        would quietly skew a run, such as a missing revenue target.
        """
        warnings: list[str] = []
        if not self.get("client.name"):
            warnings.append("client.name is not set; reports will be labelled 'Unnamed client'.")
        if not self.brand_terms:
            warnings.append(
                "client.brand_terms is empty; branded/non-branded splits and the "
                "branded-lift dark traffic estimator will be unreliable."
            )
        if self.revenue_target <= 0:
            warnings.append(
                "planning.revenue_target is not set; the portfolio will be ranked but "
                "cannot be measured against a goal."
            )
        if not self.raw.get("economics"):
            warnings.append("economics block is missing; default ecommerce assumptions will be used.")
        if not self.capacity_per_quarter:
            warnings.append(
                "capacity.per_quarter is not set; every opportunity will be treated as "
                "deliverable and the roadmap will not be capacity-constrained."
            )
        if not self.sources:
            warnings.append("no sources configured; there is nothing to analyze.")
        return warnings
