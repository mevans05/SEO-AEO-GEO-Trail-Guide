"""Connector framework: file readers, the base class and the registry.

A connector's only job is translation: read whatever a vendor exports and emit
canonical records. All judgement about what the numbers *mean* belongs in the
analyzers, which keeps a new source cheap to add - implement ``load``, register
it, and every existing analysis picks the data up automatically.
"""

from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from ..config import Config, SourceSpec
from ..errors import ConnectorError, UnknownSourceError
from ..core.schemas import Dataset

#: Extensions read as delimited text, mapped to their delimiter.
_DELIMITERS = {".csv": ",", ".tsv": "\t", ".txt": ","}


def read_rows(
    path: str | Path,
    skip_lines: int = 0,
    encoding: str = "utf-8-sig",
    delimiter: str | None = None,
    json_path: str | None = None,
) -> list[dict[str, Any]]:
    """Read CSV/TSV/JSON/JSONL into a list of dicts.

    ``skip_lines`` drops vendor preamble rows that sit above the real header
    (Semrush and some GA4 exports do this). ``json_path`` selects a nested list
    inside a JSON document using dotted notation, e.g. ``"data.rows"``.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise ConnectorError(f"input file not found: {file_path}")

    suffix = file_path.suffix.lower()
    try:
        if suffix == ".jsonl" or suffix == ".ndjson":
            rows = []
            with file_path.open(encoding=encoding) as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
            return rows

        if suffix == ".json":
            with file_path.open(encoding=encoding) as handle:
                payload = json.load(handle)
            return _extract_json_rows(payload, json_path, file_path)

        with file_path.open(encoding=encoding, newline="") as handle:
            for _ in range(skip_lines):
                handle.readline()
            sep = delimiter or _DELIMITERS.get(suffix, ",")
            return [dict(row) for row in csv.DictReader(handle, delimiter=sep)]
    except ConnectorError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        raise ConnectorError(f"could not read {file_path}: {exc}") from exc


def _extract_json_rows(
    payload: Any, json_path: str | None, file_path: Path
) -> list[dict[str, Any]]:
    """Pull a list of row-dicts out of a JSON document."""
    node = payload
    if json_path:
        for part in json_path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                raise ConnectorError(f"json_path '{json_path}' not found in {file_path}")
    if isinstance(node, list):
        return [row if isinstance(row, dict) else {"value": row} for row in node]
    if isinstance(node, dict):
        return [node]
    raise ConnectorError(f"expected a list or object in {file_path}, got {type(node).__name__}")


def iter_source_files(spec: SourceSpec, config: Config) -> Iterator[Path]:
    """Yield every file a source spec points at.

    ``path`` may be a single file, a glob, or a directory, so a connector can be
    handed one export or a month of daily dumps without changing the config
    shape.
    """
    if not spec.path:
        raise ConnectorError(f"source '{spec.label}' has no 'path' configured")
    raw_path = str(spec.path)
    if any(char in raw_path for char in "*?["):
        base = config.resolve_path(".")
        matches = sorted(Path(base).glob(raw_path))
        if not matches:
            raise ConnectorError(f"source '{spec.label}' glob matched no files: {raw_path}")
        yield from matches
        return
    resolved = config.resolve_path(raw_path)
    if resolved.is_dir():
        matches = sorted(
            child for child in resolved.iterdir()
            if child.suffix.lower() in {".csv", ".tsv", ".json", ".jsonl", ".ndjson"}
        )
        if not matches:
            raise ConnectorError(f"source '{spec.label}' directory has no readable files: {resolved}")
        yield from matches
        return
    yield resolved


@dataclass(frozen=True)
class IntakeColumn:
    """One column an export is expected to carry.

    ``name`` is the header written into the intake template. Connectors accept
    several spellings for most fields (matching is separator- and
    case-insensitive), so this is the recommended spelling rather than the only
    one that will load.
    """

    name: str
    description: str
    example: str = ""
    required: bool = False


@dataclass(frozen=True)
class IntakeSheet:
    """One export an analyst collects at the start of an audit.

    Connectors declare these so the intake template is generated from the code
    that actually reads the data. A column cannot drift out of the template
    without the connector changing too.
    """

    key: str
    title: str
    source_type: str
    export_from: str
    columns: tuple[IntakeColumn, ...]
    #: ``core`` sources carry the analysis; without them most output is empty.
    #: ``recommended`` materially sharpen it; ``optional`` add a surface.
    priority: str = "recommended"
    #: What this export switches on, for the "why am I collecting this" column.
    unlocks: str = ""
    notes: str = ""

    @property
    def filename(self) -> str:
        return f"{self.key}.csv"

    @property
    def headers(self) -> list[str]:
        return [column.name for column in self.columns]


#: Priority ordering used when the template is laid out.
INTAKE_PRIORITIES = ("core", "recommended", "optional")


class Connector(ABC):
    """Translates one vendor export into canonical records."""

    #: Canonical registry key.
    name: str = ""
    #: Alternative keys accepted in config (vendor naming varies by team).
    aliases: tuple[str, ...] = ()
    #: One-line description surfaced by ``trailguide sources``.
    description: str = ""
    #: Dataset collections this connector populates.
    produces: tuple[str, ...] = ()
    #: Exports this connector reads, declared so ``trailguide intake`` can
    #: generate a collection template straight from the connector registry.
    intake: tuple[IntakeSheet, ...] = ()

    def __init__(self, spec: SourceSpec, config: Config) -> None:
        self.spec = spec
        self.config = config

    @abstractmethod
    def load(self) -> Dataset:
        """Read the configured files and return canonical records."""

    # -- helpers available to every connector ----------------------------

    def rows(self) -> Iterator[tuple[Path, dict[str, Any]]]:
        """Iterate ``(file, row)`` pairs across every file in the source spec."""
        options = self.spec.options
        for file_path in iter_source_files(self.spec, self.config):
            for row in read_rows(
                file_path,
                skip_lines=int(options.get("skip_lines", 0)),
                encoding=str(options.get("encoding", "utf-8-sig")),
                delimiter=options.get("delimiter"),
                json_path=options.get("json_path"),
            ):
                yield file_path, self._apply_column_map(row)

    def documents(self) -> Iterator[tuple[Path, Any]]:
        """Iterate whole parsed JSON documents (for Lighthouse/PageSpeed reports)."""
        for file_path in iter_source_files(self.spec, self.config):
            if file_path.suffix.lower() not in {".json", ".jsonl", ".ndjson"}:
                continue
            try:
                yield file_path, json.loads(file_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ConnectorError(f"could not parse {file_path}: {exc}") from exc

    def _apply_column_map(self, row: dict[str, Any]) -> dict[str, Any]:
        """Apply a config ``column_map`` so odd exports can be remapped without code.

        Maps ``{canonical_name: source_column}``, which is the escape hatch for
        an export whose headers this connector has never seen.
        """
        column_map = self.spec.options.get("column_map") or {}
        if not column_map:
            return row
        mapped = dict(row)
        for canonical, source_column in column_map.items():
            if source_column in row:
                mapped[canonical] = row[source_column]
        return mapped

    @property
    def source_name(self) -> str:
        return self.spec.name or self.name


#: Registry of connector classes by canonical name and alias.
_REGISTRY: dict[str, type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    """Class decorator that registers a connector under its name and aliases."""
    if not cls.name:
        raise ValueError(f"{cls.__name__} must define a 'name'")
    for key in (cls.name, *cls.aliases):
        existing = _REGISTRY.get(key)
        if existing is not None and existing is not cls:
            raise ValueError(f"connector key '{key}' already registered by {existing.__name__}")
        _REGISTRY[key] = cls
    return cls


def get_connector(source_type: str) -> type[Connector]:
    """Look up a connector class by name or alias."""
    key = str(source_type).strip().lower()
    if key not in _REGISTRY:
        known = ", ".join(sorted({cls.name for cls in _REGISTRY.values()}))
        raise UnknownSourceError(
            f"no connector registered for source type '{source_type}'. "
            f"Registered types: {known}. "
            f"Use type 'generic' with a column_map to load an unsupported export."
        )
    return _REGISTRY[key]


def registered_connectors() -> list[type[Connector]]:
    """All distinct registered connector classes, sorted by name."""
    return sorted(set(_REGISTRY.values()), key=lambda cls: cls.name)


def load_sources(
    config: Config,
    on_error: Callable[[SourceSpec, Exception], None] | None = None,
) -> tuple[Dataset, list[dict[str, Any]]]:
    """Load every enabled source into one merged dataset.

    A failing source degrades the run rather than ending it: the error is
    recorded in the returned manifest and reported as reduced input coverage,
    because a missing LinkedIn export should not block a technical analysis.
    """
    dataset = Dataset()
    manifest: list[dict[str, Any]] = []
    for spec in config.sources:
        if not spec.enabled:
            manifest.append({"source": spec.label, "type": spec.type, "status": "disabled", "records": 0})
            continue
        try:
            connector = get_connector(spec.type)(spec, config)
            loaded = connector.load()
            record_count = sum(len(getattr(loaded, name)) for name in Dataset.COLLECTIONS)
            record_count += sum(len(rows) for rows in loaded.extras.values())
            dataset.extend(loaded)
            manifest.append({
                "source": spec.label,
                "type": spec.type,
                "status": "ok",
                "records": record_count,
                "path": str(spec.path or ""),
            })
        except Exception as exc:  # noqa: BLE001 - one bad export must not end the run
            if on_error is not None:
                on_error(spec, exc)
            manifest.append({
                "source": spec.label,
                "type": spec.type,
                "status": "error",
                "records": 0,
                "error": str(exc),
                "path": str(spec.path or ""),
            })
    return dataset, manifest
