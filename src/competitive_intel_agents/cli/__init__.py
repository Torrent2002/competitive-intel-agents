"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from competitive_intel_agents.models import CompetitiveIntelRequest
from competitive_intel_agents.orchestrator import Orchestrator, load_agent_profiles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="competitive-intel")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--input", required=True)
    run_parser.add_argument("--config", default="config/agent_profiles.yaml")
    run_parser.add_argument("--fake-model", action="store_true")
    run_parser.add_argument("--output")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _run_command(parser, args)

    parser.print_help()
    return 0


def _run_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        parser.error(f"input file does not exist: {input_path}")

    config_path = Path(args.config)
    if not config_path.exists():
        parser.error(f"config file does not exist: {config_path}")

    try:
        request = CompetitiveIntelRequest.from_dict(
            json.loads(input_path.read_text(encoding="utf-8"))
        )
    except json.JSONDecodeError as exc:
        parser.error(f"invalid JSON in input file: {exc}")
    except ValueError as exc:
        parser.error(f"invalid request: {exc}")

    orchestrator = Orchestrator(agent_profiles=load_agent_profiles(config_path))
    result = orchestrator.run(request)
    _print_summary(input_path, orchestrator, result)

    if args.output:
        output_path = Path(args.output)
        _write_report(output_path, orchestrator, result.run_id)
        print(f"Wrote report: {output_path}")

    return 0


def _print_summary(input_path: Path, orchestrator: Orchestrator, result) -> None:
    source_count = len(orchestrator.artifacts.list_sources(result.run_id))
    claim_count = len(orchestrator.artifacts.list_claims(result.run_id))

    print(f"Loaded request: {input_path}")
    print(f"Run id: {result.run_id}")
    print(f"Run status: {result.status}")
    print(f"Sources: {source_count}")
    print(f"Claims: {claim_count}")
    if result.report_id:
        print(f"Report id: {result.report_id}")
    if result.review_feedback:
        print(f"Review feedback: {len(result.review_feedback)}")


def _write_report(output_path: Path, orchestrator: Orchestrator, run_id: str) -> None:
    report = orchestrator.artifacts.get_latest_report(run_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if report is None:
        output_path.write_text(
            "# Competitive Intelligence Report\n\nNo report was produced.\n",
            encoding="utf-8",
        )
        return

    lines = ["# Competitive Intelligence Report", ""]
    for section, content in report.sections.items():
        lines.extend([f"## {section}", "", content.strip(), ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")
