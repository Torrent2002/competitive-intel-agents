"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from competitive_intel_agents.artifacts import InMemoryArtifactStore
from competitive_intel_agents.dashboard import (
    build_dashboard_snapshot,
    render_dashboard,
)
from competitive_intel_agents.harness import InMemoryCheckpointStore, RuntimeHarness
from competitive_intel_agents.journal import InMemoryJournalStore, JournalStore
from competitive_intel_agents.models import CompetitiveIntelRequest
from competitive_intel_agents.orchestrator import Orchestrator, load_agent_profiles
from competitive_intel_agents.runtime import (
    CachedWebFetch,
    DuckDuckGoSearch,
    ToolRuntime,
    WebFetchTool,
    WebSearchTool,
)
from competitive_intel_agents.workspace import LocalWorkspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="competitive-intel")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--input", required=True)
    run_parser.add_argument("--config", default="config/agent_profiles.yaml")
    run_parser.add_argument("--fake-model", action="store_true")
    run_parser.add_argument("--output")
    run_parser.add_argument("--workspace")
    run_parser.add_argument("--show-dashboard", action="store_true")
    run_parser.add_argument("--real-web", action="store_true")

    dashboard_parser = subparsers.add_parser("dashboard")
    dashboard_parser.add_argument("--run-id", required=True)
    dashboard_parser.add_argument("--workspace", default=".competitive-intel")

    runs_parser = subparsers.add_parser("runs")
    runs_parser.add_argument("--workspace", default=".competitive-intel")

    chat_parser = subparsers.add_parser("chat")
    chat_parser.add_argument("--config", default="config/agent_profiles.yaml")
    chat_parser.add_argument("--fake-model", action="store_true")
    chat_parser.add_argument("--workspace")
    chat_parser.add_argument("--real-web", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _run_command(parser, args)
    if args.command == "dashboard":
        return _dashboard_command(parser, args)
    if args.command == "runs":
        return _runs_command(args)
    if args.command == "chat":
        return _chat_command(parser, args)

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

    workspace = LocalWorkspace(args.workspace) if args.workspace else None
    orchestrator = _make_orchestrator(config_path, workspace, real_web=args.real_web)
    result = orchestrator.run(request)
    if workspace is not None:
        workspace.save_run_result(result)
    _print_summary(input_path, orchestrator, result)

    if args.output:
        output_path = Path(args.output)
        _write_report(output_path, orchestrator, result.run_id)
        print(f"Wrote report: {output_path}")
    if args.show_dashboard:
        print()
        print(
            render_dashboard(
                build_dashboard_snapshot(
                    orchestrator.journal,
                    orchestrator.artifacts,
                    result.run_id,
                )
            )
        )

    return 0


def _dashboard_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    workspace = LocalWorkspace(args.workspace)
    if workspace.get_run_result(args.run_id) is None:
        parser.error(f"run not found: {args.run_id}")
    snapshot = build_dashboard_snapshot(
        workspace.journal,
        workspace.artifacts,
        args.run_id,
    )
    print(render_dashboard(snapshot))
    return 0


def _runs_command(args: argparse.Namespace) -> int:
    workspace = LocalWorkspace(args.workspace)
    print("Run id\tStatus\tReport")
    for result in workspace.list_run_results():
        print(f"{result.run_id}\t{result.status}\t{result.report_id or '-'}")
    return 0


def _chat_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    if not config_path.exists():
        parser.error(f"config file does not exist: {config_path}")

    print("Competitive Intel interactive session")
    company = input("Company: ").strip()
    market = input("Market: ").strip()
    competitors = _split_csv(input("Competitors: "))
    questions = _split_csv(input("Questions: "))
    try:
        request = CompetitiveIntelRequest(
            company=company,
            market=market or None,
            competitors=competitors,
            questions=questions,
        )
    except ValueError as exc:
        parser.error(f"invalid request: {exc}")

    workspace = LocalWorkspace(args.workspace) if args.workspace else None
    orchestrator = _make_orchestrator(config_path, workspace, real_web=args.real_web)
    result = orchestrator.run(request)
    if workspace is not None:
        workspace.save_run_result(result)
    print(f"Run id: {result.run_id}")
    print(f"Run status: {result.status}")
    print("Type: dashboard, report, sources, claims, feedback, save <path>, new, exit")

    while True:
        try:
            command = input("> ").strip()
        except EOFError:
            break
        if command in {"exit", "quit"}:
            break
        if command == "new":
            print("Start a new session by running competitive-intel chat again.")
            continue
        if command == "dashboard":
            print(
                render_dashboard(
                    build_dashboard_snapshot(
                        orchestrator.journal,
                        orchestrator.artifacts,
                        result.run_id,
                    )
                )
            )
            continue
        if command == "report":
            print(_render_report(orchestrator, result.run_id))
            continue
        if command == "sources":
            _print_sources(orchestrator, result.run_id)
            continue
        if command == "claims":
            _print_claims(orchestrator, result.run_id)
            continue
        if command == "feedback":
            _print_feedback(result)
            continue
        if command.startswith("save "):
            output_path = Path(command.split(" ", 1)[1].strip())
            _write_report(output_path, orchestrator, result.run_id)
            print(f"Wrote report: {output_path}")
            continue
        if command:
            print(f"Unknown command: {command}")
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


def _make_orchestrator(
    config_path: Path,
    workspace: LocalWorkspace | None,
    real_web: bool = False,
) -> Orchestrator:
    if real_web:
        artifacts = (
            workspace.artifacts if workspace is not None else InMemoryArtifactStore()
        )
        journal = workspace.journal if workspace is not None else InMemoryJournalStore()
        return Orchestrator(
            artifacts=artifacts,
            journal=journal,
            agent_profiles=load_agent_profiles(config_path),
            harness=_real_web_harness(journal, workspace),
        )
    if workspace is None:
        return Orchestrator(
            agent_profiles=load_agent_profiles(config_path),
        )
    return Orchestrator(
        artifacts=workspace.artifacts,
        journal=workspace.journal,
        agent_profiles=load_agent_profiles(config_path),
    )


def _real_web_harness(journal: JournalStore, workspace: LocalWorkspace | None):
    tools = ToolRuntime()
    tools.register(WebSearchTool(DuckDuckGoSearch()))
    fetch_tool = WebFetchTool()
    if workspace is not None:
        tools.register(
            CachedWebFetch(
                fetch_tool,
                cache_dir=workspace.path / "cache" / "web_fetch",
            )
        )
    else:
        tools.register(fetch_tool)
    return RuntimeHarness(journal, tools, InMemoryCheckpointStore())


def _write_report(output_path: Path, orchestrator: Orchestrator, run_id: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_report(orchestrator, run_id), encoding="utf-8")


def _render_report(orchestrator: Orchestrator, run_id: str) -> str:
    report = orchestrator.artifacts.get_latest_report(run_id)
    if report is None:
        return "# Competitive Intelligence Report\n\nNo report was produced.\n"

    lines = ["# Competitive Intelligence Report", ""]
    for section, content in report.sections.items():
        lines.extend([f"## {section}", "", content.strip(), ""])
    return "\n".join(lines)


def _print_sources(orchestrator: Orchestrator, run_id: str) -> None:
    sources = orchestrator.artifacts.list_sources(run_id)
    if not sources:
        print("No sources.")
        return
    for source in sources:
        print(f"{source.id}\t{source.title}\t{source.url}")


def _print_claims(orchestrator: Orchestrator, run_id: str) -> None:
    claims = orchestrator.artifacts.list_claims(run_id)
    if not claims:
        print("No claims.")
        return
    for claim in claims:
        print(f"{claim.id}\t{claim.text}\tsources={','.join(claim.source_ids)}")


def _print_feedback(result) -> None:
    if not result.review_feedback:
        print("No reviewer feedback.")
        return
    for item in result.review_feedback:
        print(
            f"{item.issue}\t{item.target_agent}\t"
            f"{item.target_artifact_id}\t{item.required_action}"
        )


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
