"""Command line interface.

    trailguide run       --config config/client.yml --out ./out
    trailguide validate  --config config/client.yml
    trailguide sources
    trailguide analyzers
    trailguide init      --out config/new-client.yml
    trailguide intake    --client "Acme" --domain acme.com --out ./intake
    trailguide collect   --workbook ./intake/acme-intake.xlsx --out ./intake/data
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import __version__
from .analysis import registered_analyzers
from .config import Config
from .connectors import registered_connectors
from .errors import TrailGuideError
from .intake import (
    ClientProfile, intake_sheets, read_workbook, render_config, render_readme,
    write_csv_stubs, write_workbook,
)
from .pipeline import run as run_pipeline
from .report import (
    render_appendix, render_markdown, write_csvs, write_docx, write_jira_csv,
    write_json, write_pptx,
)

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
        "--format", "-f", default="md,json,csv,jira",
        help=(
            "comma-separated outputs: md, json, csv, jira, docx, pptx "
            "(default: md,json,csv,jira; docx and pptx need the 'deliverables' extra)"
        ),
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

    intake_parser = subparsers.add_parser(
        "intake", help="generate the data collection pack for a new audit"
    )
    intake_parser.add_argument("--client", required=True, help="client name")
    intake_parser.add_argument("--domain", default="", help="primary domain, no protocol")
    intake_parser.add_argument(
        "--brand-terms", default="", help="comma-separated branded search terms"
    )
    intake_parser.add_argument(
        "--competitors", default="", help="comma-separated competitor domains"
    )
    intake_parser.add_argument(
        "--model", default="b2b", choices=("b2b", "ecommerce"), help="economics model"
    )
    intake_parser.add_argument("--currency", default="USD")
    intake_parser.add_argument(
        "--revenue-target", type=float, default=0.0,
        help="incremental revenue the roadmap must deliver",
    )
    intake_parser.add_argument("--out", "-o", default="./intake", help="output directory")
    intake_parser.add_argument(
        "--no-workbook", action="store_true",
        help="skip the xlsx workbook (writes CSV stubs, config and README only)",
    )

    collect_parser = subparsers.add_parser(
        "collect", help="split a filled intake workbook into the CSVs the connectors read"
    )
    collect_parser.add_argument("--workbook", "-w", required=True, help="filled intake xlsx")
    collect_parser.add_argument("--out", "-o", default="./data", help="where to write CSVs")
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
    if "jira" in formats:
        written.append(write_jira_csv(result, out_dir / "jira-tickets.csv"))
        appendix = out_dir / "jira-tickets.md"
        appendix.write_text(render_appendix(result), encoding="utf-8")
        written.append(appendix)

    slug = re.sub(r"[^a-z0-9]+", "-", result.config.client_name.lower()).strip("-") or "client"
    if "docx" in formats:
        written.append(
            write_docx(result, out_dir / f"{slug}-opportunity-analysis.docx", args.max_detail)
        )
    if "pptx" in formats:
        written.append(write_pptx(result, out_dir / f"{slug}-highlights.pptx"))

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


def _command_intake(args: argparse.Namespace) -> int:
    def split(value: str) -> tuple[str, ...]:
        return tuple(part.strip() for part in value.split(",") if part.strip())

    profile = ClientProfile(
        name=args.client,
        domain=args.domain or "example.com",
        brand_terms=split(args.brand_terms),
        competitors=split(args.competitors),
        economics_model=args.model,
        currency=args.currency,
        revenue_target=args.revenue_target,
    )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets = intake_sheets()
    written: list[Path] = []

    if not args.no_workbook:
        written.append(
            write_workbook(out_dir / f"{profile.slug}-intake.xlsx", profile, sheets)
        )

    written.extend(write_csv_stubs(out_dir / "data", sheets))

    config_path = out_dir / f"{profile.slug}.yml"
    config_path.write_text(render_config(profile, "data", sheets), encoding="utf-8")
    written.append(config_path)

    readme_path = out_dir / "README.md"
    readme_path.write_text(render_readme(profile, sheets), encoding="utf-8")
    written.append(readme_path)

    counts: dict[str, int] = {}
    for sheet in sheets:
        counts[sheet.priority] = counts.get(sheet.priority, 0) + 1

    print(f"\nIntake pack for {profile.name} ({profile.domain})")
    print("=" * 64)
    print(f"  Exports requested       {len(sheets)}")
    for priority in ("core", "recommended", "optional"):
        if counts.get(priority):
            print(f"    {priority:20}{counts[priority]}")
    print(f"\n  Written to {out_dir}/")
    print(f"    {profile.slug}-intake.xlsx   the workbook to hand over"
          if not args.no_workbook else "    (workbook skipped)")
    print(f"    {profile.slug}.yml           config, wired to data/")
    print("    data/*.csv            header-only stubs")
    print("    README.md             what to collect and why")
    print("\n  Next:")
    print("    1. Fill the workbook (or drop CSVs into data/).")
    print(f"    2. trailguide collect --workbook {out_dir}/{profile.slug}-intake.xlsx "
          f"--out {out_dir}/data")
    print(f"    3. trailguide validate --config {config_path}")
    print(f"    4. trailguide run --config {config_path} --out ./out\n")
    return 0


def _command_collect(args: argparse.Namespace) -> int:
    written = read_workbook(args.workbook, args.out)
    if not written:
        print(
            "No filled tabs found. Paste exports under the headers in the workbook, "
            "keeping row 1 as it is.",
            file=sys.stderr,
        )
        return 1
    print(f"\nExtracted {len(written)} export(s) from {args.workbook}:")
    for path in written:
        rows = max(0, sum(1 for _ in path.open(encoding="utf-8")) - 1)
        print(f"    {path}  ({rows:,} rows)")
    print()
    return 0


_COMMANDS = {
    "run": _command_run,
    "intake": _command_intake,
    "collect": _command_collect,
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
