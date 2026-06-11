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
    BingSearch,
    CachedWebFetch,
    DuckDuckGoSearch,
    FallbackSearch,
    LocalContentStore,
    PersistedContentTool,
    SogouSearch,
    ToolRuntime,
    WebFetchTool,
    WebSearchTool,
)
from competitive_intel_agents.export import export_run
from competitive_intel_agents.golden import GoldenReplayRunner
from competitive_intel_agents.runtime.model_runtime import ConfiguredProviderFactory, ModelRuntime
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
    run_parser.add_argument("--real-model", action="store_true")

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
    chat_parser.add_argument("--real-model", action="store_true")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--run-id", required=True)
    export_parser.add_argument(
        "--format", default="markdown", choices=["markdown", "json", "html"]
    )
    export_parser.add_argument("--output")
    export_parser.add_argument("--workspace", default=".competitive-intel")

    golden_parser = subparsers.add_parser("golden")
    golden_parser.add_argument("--root", default="tests/golden")

    web_parser = subparsers.add_parser("web")
    web_parser.add_argument("--workspace", default=".competitive-intel")
    web_parser.add_argument("--port", type=int, default=8080)
    web_parser.add_argument("--host", default="127.0.0.1")

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
    if args.command == "export":
        return _export_command(parser, args)
    if args.command == "golden":
        return _golden_command(parser, args)
    if args.command == "web":
        return _web_command(parser, args)

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
    orchestrator = _make_orchestrator(
        config_path, workspace, real_web=args.real_web, real_model=args.real_model
    )
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

    print("Competitive Intel — describe what you want to research:")
    print("(e.g. 小米在手机市场2026Q1和荣耀的对比分析)")
    user_input = input("> ").strip()
    if not user_input:
        parser.error("input is required")

    request = _parse_user_input(user_input, real_model=args.real_model)

    print(f"  Company: {request.company}")
    if request.market:
        print(f"  Market: {request.market}")
    if request.competitors:
        print(f"  Competitors: {', '.join(request.competitors)}")
    if request.questions:
        print(f"  Questions: {', '.join(request.questions)}")
    print()

    workspace = LocalWorkspace(args.workspace) if args.workspace else None
    orchestrator = _make_orchestrator(
        config_path, workspace, real_web=args.real_web, real_model=args.real_model
    )
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
    real_model: bool = False,
) -> Orchestrator:
    model_runtime = _make_model_runtime() if real_model else None

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
            model_runtime=model_runtime,
            enable_rework=True,
        )
    if workspace is None:
        return Orchestrator(
            agent_profiles=load_agent_profiles(config_path),
            model_runtime=model_runtime,
            enable_rework=True,
        )
    return Orchestrator(
        artifacts=workspace.artifacts,
        journal=workspace.journal,
        agent_profiles=load_agent_profiles(config_path),
        model_runtime=model_runtime,
        enable_rework=True,
    )


def _make_model_runtime() -> ModelRuntime:
    """Create ModelRuntime from environment variables using ConfiguredProviderFactory."""
    factory = ConfiguredProviderFactory()
    provider = factory.create()
    return ModelRuntime(provider=provider)


def _real_web_harness(journal: JournalStore, workspace: LocalWorkspace | None):
    tools = ToolRuntime()
    tools.register(WebSearchTool(FallbackSearch([BingSearch(), SogouSearch(), DuckDuckGoSearch(timeout=2)])))
    content_root = (workspace.path if workspace is not None else Path(".competitive-intel")) / "content"
    fetch_tool = PersistedContentTool(
        WebFetchTool(max_chars=None),
        content_store=LocalContentStore(content_root),
    )
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


def _export_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    workspace = LocalWorkspace(args.workspace)
    if workspace.get_run_result(args.run_id) is None:
        parser.error(f"run not found: {args.run_id}")

    try:
        content = export_run(
            workspace.artifacts,
            workspace.journal,
            args.run_id,
            args.format,
        )
    except Exception as exc:
        parser.error(f"export failed: {exc}")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        print(f"Exported to: {output_path}")
    else:
        print(content)
    return 0


def _golden_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    root_path = Path(args.root)
    if not root_path.exists():
        parser.error(f"golden root not found: {root_path}")

    runner = GoldenReplayRunner(root_path)
    summary = runner.run_all()

    for result in summary.results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.case_name}")
        if result.failures:
            for failure in result.failures:
                print(
                    f"  {failure.metric}: "
                    f"expected {failure.expected}, got {failure.actual}"
                    f" — {failure.message}"
                )

    print(f"\n{summary.total_cases} cases: "
          f"{sum(1 for r in summary.results if r.passed)} passed, "
          f"{sum(1 for r in summary.results if not r.passed)} failed")

    return 0 if summary.passed else 1


def _web_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    from competitive_intel_agents.web import start_web_server

    workspace = LocalWorkspace(args.workspace)
    print(f"Starting web dashboard on http://{args.host}:{args.port}")
    print(f"Workspace: {args.workspace}")
    start_web_server(workspace, host=args.host, port=args.port)
    return 0


def _parse_user_input(
    text: str,
    real_model: bool = False,
) -> CompetitiveIntelRequest:
    """Parse free-form user input into a structured request.

    Uses model if available, otherwise falls back to basic heuristic parsing.
    """
    if real_model:
        try:
            return _model_parse_input(text)
        except Exception:
            pass
    return _heuristic_parse_input(text)


def _model_parse_input(text: str) -> CompetitiveIntelRequest:
    """Use LLM to extract company, market, competitors, questions from free text."""
    factory = ConfiguredProviderFactory()
    provider = factory.create()
    model = ModelRuntime(provider=provider)

    import json as _json
    task = (
        "Parse this user research request into structured fields. "
        "Identify the MAIN company being researched, the market/industry (if mentioned), "
        "competitors (if mentioned), and specific questions or angles to investigate. "
        "Return ONLY a JSON object with keys: company, market, competitors (list), questions (list). "
        "If a field is not mentioned, use empty string for market and empty lists for others."
    )
    from competitive_intel_agents.prompts import AgentPromptLibrary
    prompt_lib = AgentPromptLibrary()
    model_req = prompt_lib.build("analyst", task, {"user_input": text})
    resp = model.complete(model_req)

    if resp.ok:
        data = resp.parsed or {}
        content = resp.content.strip()
        if not data and content:
            try:
                data = _json.loads(content)
            except (_json.JSONDecodeError, TypeError):
                pass

        if isinstance(data, dict) and data.get("company"):
            competitors = data.get("competitors", [])
            if isinstance(competitors, str):
                competitors = [c.strip() for c in competitors.split(",") if c.strip()]
            elif not isinstance(competitors, list):
                competitors = []
            questions = data.get("questions", [])
            if isinstance(questions, str):
                questions = [q.strip() for q in questions.split(",") if q.strip()]
            elif not isinstance(questions, list):
                questions = []
            return CompetitiveIntelRequest(
                company=str(data["company"]).strip(),
                market=str(data.get("market", "")).strip() or None,
                competitors=[str(c) for c in competitors if c],
                questions=[str(q) for q in questions if q],
            )

    raise ValueError("model failed to parse input")


def _heuristic_parse_input(text: str) -> CompetitiveIntelRequest:
    """Basic parsing without model: extract company from first words, split by keywords."""
    text = text.strip()

    # Try to find market keywords
    market = None
    for kw in ["市场", "行业", "领域", "market", "industry", "sector"]:
        if kw in text:
            idx = text.find(kw)
            before = text[:idx].rstrip("在的的于 ")
            after = text[idx + len(kw):].lstrip("是:：")
            # extract market word(s) before/after keyword
            parts = before.split() if before else []
            if after[:2].strip():
                market = after[:10].strip()
            elif parts:
                market = parts[-1][:10]
            break

    # Find competitors: words after "和" or "对比" or "vs" or "竞争"
    competitors: list[str] = []
    for sep in ["和", "对比", "比较", "竞争", " vs ", " VS ", " versus "]:
        if sep in text:
            parts = text.split(sep, 1)
            if len(parts) > 1:
                candidate = parts[1].strip()
                # Take first few words as competitor name
                comp_name = candidate[:15].rstrip("的与和在市场行业领域分析研究对比")
                if comp_name and len(comp_name) >= 1:
                    competitors = [comp_name.strip()]

    # Company is usually the first word or phrase
    company = text[:20].strip()
    # Remove common prefixes
    for prefix in ["分析", "研究", "帮我", "请", "我想", "我要"]:
        if company.startswith(prefix):
            company = company[len(prefix):].strip()

    # Split company from market/competitor keywords
    for sep in ["在", "的", "市场", "行业", "和", "对比", " vs "]:
        if sep in company:
            company = company.split(sep)[0].strip()

    if not company or len(company) < 1:
        company = "unknown"

    # Extract questions
    questions: list[str] = []
    for qkw in ["怎么样", "如何", "为什么", "谁更", "哪个", "对比"]:
        if qkw in text and len(questions) < 2:
            # Take the segment containing this question word
            idx = text.find(qkw)
            start = max(0, idx - 5)
            end = min(len(text), idx + 10)
            q = text[start:end].strip().lstrip("，,。.")
            if q:
                questions.append(q)

    return CompetitiveIntelRequest(
        company=company,
        market=market,
        competitors=competitors,
        questions=questions if questions else ["competitive analysis"],
    )


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
