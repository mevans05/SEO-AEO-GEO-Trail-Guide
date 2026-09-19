"""Command line interface.

    trailguide run       --config config/client.yml --out ./out
    trailguide validate  --config config/client.yml
    trailguide sources
    trailguide analyzers
    trailguide init      --out config/new-client.yml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analysis import registered_analyzers
from .config import Config
from .connectors import registered_connectors
from .errors import TrailGuideError
from .pipeline import run as run_pipeline
from .report import render_markdown, write_csvs, write_json

_TEMPLATE = """# Trail Guide client configuration.
# Every number here is an assumption the analysis is built on. Review them with
# the client before trusting the output.

client:
  name: Example Client
  domain: example.com
  brand_terms: [example, "example co"]
  competitors: [competitor-a.com, competitor-b.com]

planning:
  horizon_months: 12
  quarters: 4
  currency: USD
  revenue_target: 1500000          # incremental revenue the portfolio must deliver
  baseline_organic_revenue: 0      # leave 0 to use the modeled Track 1 + Track 2 baseline

economics:
  model: b2b                       # b2b | ecommerce
  gross_margin: 0.80
  b2b:
    visit_to_lead: 0.022
    lead_to_mql: 0.45
    mql_to_sql: 0.40
    sql_to_win: 0.22
    average_contract_value: 24000
    sales_cycle_days: 75

capacity:
  reserved_for_enabling: 0.10      # share of capacity held for instrumentation work
  per_quarter:
    seo: 45
    content: 60
    engineering: 20
    design: 15
    analytics: 10
    strategy: 8
    outreach: 10

sources:
  - type: gsc
    name: search_console_queries
    path: data/gsc_queries.csv
  # Add any other export; use type 'generic' with a column_map for unsupported tools.

analysis:
  defaults: {}
  settings: {}
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trailguide",
        description=(
            "Data-first SEO/AEO/GEO opportunity analysis with revenue-targeted prioritization."
        ),
    )
    parser.add_argument("--version", action="version", version=f"trailguide {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run a full analysis")
    run_parser.add_argument("--config", "-c", required=True, help="path to the client config YAML")
    run_parser.add_argument("--out", "-o", default="./out", help="output directory")
    run_parser.add_argument(
        "--format", "-f", default="md,json,csv",
        help="comma-separated outputs: md, json, csv (default: all)",
    )
    run_parser.add_argument(
        "--max-detail", type=int, default=25,
        help="opportunities to write in full detail in the markdown report",
    )
    run_parser.add_argument("--quiet", "-q", action="store_true", help="suppress the console summary")

    validate_parser = subparsers.add_parser(
        "validate", help="check a config and confirm its sources load"
    )
    validate_parser.add_argument("--config", "-c", required=True)

    subparsers.add_parser("sources", help="list registered source connectors")
    subparsers.add_parser("analyzers", help="list registered analyzers")

    init_parser = subparsers.add_parser("init", help="write a starter config")
    init_parser.add_argument("--out", "-o", default="trailguide.yml")
    return parser


def _command_run(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    result = run_pipeline(config)
    formats = {token.strip().lower() for token in args.format.split(",") if token.strip()}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if "md" in formats or "markdown" in formats:
        report_path = out_dir / "opportunity-analysis.md"
        report_path.write_text(render_markdown(result, args.max_detail), encoding="utf-8")
        written.append(report_path)
    if "json" in formats:
        written.append(write_json(result, out_dir / "analysis.json"))
    if "csv" in formats:
        written.extend(write_csvs(result, out_dir))

    if not args.quiet:
        _print_summary(result, written)
    return 0


def _print_summary(result, written: list[Path]) -> None:
    summary = result.summary()
    portfolio = result.portfolio
    currency = result.config.currency
    print(f"\nTrail Guide v{summary['version']} - {summary['client']}")
    print("=" * 64)
    print(f"  Sources loaded          {', '.join(summary['sources_loaded']) or 'none'}")
    print(f"  Opportunities found     {summary['opportunities_found']}")
    print(f"  Scheduled / deferred    {summary['scheduled']} / {summary['deferred']}")
    print(
        f"  Dark traffic multiplier SEO {result.dark.seo.multiplier:.2f}x  "
        f"GEO {result.dark.geo.multiplier:.2f}x"
    )
    print(
        f"  Baseline attributed     {summary['baseline_revenue']:,.0f} {currency} "
        f"(Track 1 + Track 2)"
    )
    print(
        f"  Projected incremental   {portfolio.projected_revenue:,.0f} {currency} "
        f"({portfolio.projected_revenue_low:,.0f} - {portfolio.projected_revenue_high:,.0f})"
    )
    if summary["target_revenue"]:
        attainment = summary["target_attainment"] or 0.0
        print(
            f"  Target                  {summary['target_revenue']:,.0f} {currency} "
            f"-> {attainment * 100:.0f}% attainment"
        )
    print(f"  Delivery cost           {portfolio.total_cost:,.0f} {currency} "
          f"({portfolio.total_days:,.0f} person-days)")
    if result.warnings:
        print(f"\n  {len(result.warnings)} warning(s):")
        for warning in result.warnings[:8]:
            print(f"    - {warning}")
        if len(result.warnings) > 8:
            print(f"    ... and {len(result.warnings) - 8} more (see the report)")
    print("\n  Written:")
    for path in written:
        print(f"    {path}")
    print()


def _command_validate(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    warnings = config.validate()
    print(f"Config: {config.path}")
    print(f"Client: {config.client_name} ({config.domain or 'no domain set'})")
    print(f"Sources configured: {len(config.sources)}")

    from .connectors import load_sources

    dataset, manifest = load_sources(config)
    failures = [entry for entry in manifest if entry["status"] == "error"]
    for entry in manifest:
        marker = {"ok": "  ok  ", "error": " FAIL ", "disabled": " off  "}.get(entry["status"], "  ?   ")
        detail = f"  {entry.get('error', '')}" if entry.get("error") else ""
        print(f"  [{marker}] {entry['source']:28} {entry['records']:>7,} records{detail}")

    print("\nCanonical coverage:")
    for name, count in dataset.coverage().items():
        print(f"  {name:20} {count:>7,}")

    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if failures:
        print(f"\n{len(failures)} source(s) failed to load.")
        return 1
    print("\nConfig is valid.")
    return 0


def _command_sources(_: argparse.Namespace) -> int:
    print(f"{'TYPE':<18} {'ALSO ACCEPTS':<52} DESCRIPTION")
    for connector in registered_connectors():
        aliases = ", ".join(connector.aliases) or "-"
        print(f"{connector.name:<18} {aliases[:50]:<52} {connector.description}")
    print(
        "\nAny other export loads through type 'generic' with a column_map - see "
        "docs/ADDING_A_SOURCE.md."
    )
    return 0


def _command_analyzers(_: argparse.Namespace) -> int:
    print(f"{'NAME':<22} {'SURFACE':<13} {'REQUIRES':<22} DESCRIPTION")
    for analyzer in registered_analyzers():
        requires = ", ".join(analyzer.required_inputs) or "-"
        print(
            f"{analyzer.name:<22} {analyzer.surface.value:<13} {requires[:20]:<22} "
            f"{analyzer.description}"
        )
    return 0


def _command_init(args: argparse.Namespace) -> int:
    target = Path(args.out)
    if target.exists():
        print(f"refusing to overwrite existing file: {target}", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_TEMPLATE, encoding="utf-8")
    print(f"Wrote starter config to {target}")
    print("Next: point the 'sources' block at your exports, then run:")
    print(f"  trailguide validate --config {target}")
    print(f"  trailguide run --config {target} --out ./out")
    return 0


_COMMANDS = {
    "run": _command_run,
    "validate": _command_validate,
    "sources": _command_sources,
    "analyzers": _command_analyzers,
    "init": _command_init,
}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except TrailGuideError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON input: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
