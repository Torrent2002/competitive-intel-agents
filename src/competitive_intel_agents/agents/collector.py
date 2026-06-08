"""Collector agent for gathering source artifacts."""

from __future__ import annotations

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.artifacts import ArtifactStore
from competitive_intel_agents.models import (
    AgentRoundResult,
    AgentState,
    RunContext,
    SourceArtifact,
    ToolCall,
    ToolResult,
)


class CollectorAgent(BaseAgent):
    """Collect source artifacts through search and fetch tool calls."""

    name = "collector"

    def __init__(self, artifacts: ArtifactStore, target_sources: int = 2) -> None:
        self._artifacts = artifacts
        self._target_sources = target_sources

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        existing_sources = self._artifacts.list_sources(context.run_id)
        if len(existing_sources) >= self._target_sources:
            return AgentRoundResult(
                completed=True,
                output_artifact_ids=[source.id for source in existing_sources],
                signals=["sources_ready"],
            )

        tool_results = self._tool_results_from_memory(state)
        if not tool_results:
            return AgentRoundResult(
                tool_calls=[self._search_call(context, state.round)],
                signals=["search_requested"],
            )

        search_results = self._search_results(tool_results)
        if search_results:
            fetch_calls = self._fetch_calls(context, state.round, search_results)
            if fetch_calls:
                return AgentRoundResult(
                    tool_calls=fetch_calls,
                    signals=["fetch_requested"],
                )

        saved_ids = self._save_fetch_results(context, tool_results)
        sources_after_save = self._artifacts.list_sources(context.run_id)
        completed = len(sources_after_save) >= self._target_sources
        signals = ["sources_saved"] if saved_ids else ["no_new_sources"]
        return AgentRoundResult(
            completed=completed,
            output_artifact_ids=saved_ids,
            signals=signals,
        )

    def _search_call(self, context: RunContext, round_index: int) -> ToolCall:
        return ToolCall(
            id=f"collector_search_{round_index}",
            name="web_search",
            args={"query": self._query(context)},
            requested_by=self.name,
        )

    def _fetch_calls(
        self,
        context: RunContext,
        round_index: int,
        search_results: list[dict],
    ) -> list[ToolCall]:
        existing_urls = {source.url for source in self._artifacts.list_sources(context.run_id)}
        seen_urls: set[str] = set()
        calls: list[ToolCall] = []
        for result in search_results:
            url = result.get("url", "")
            if not url or url in existing_urls or url in seen_urls:
                continue
            seen_urls.add(url)
            calls.append(
                ToolCall(
                    id=f"collector_fetch_{round_index}_{len(calls) + 1}",
                    name="web_fetch",
                    args={"url": url},
                    requested_by=self.name,
                )
            )
        return calls

    def _save_fetch_results(
        self,
        context: RunContext,
        tool_results: list[ToolResult],
    ) -> list[str]:
        existing_urls = {source.url for source in self._artifacts.list_sources(context.run_id)}
        saved_ids: list[str] = []
        for result in tool_results:
            if not result.ok or "url" not in result.data:
                continue
            url = result.data.get("url", "")
            if not url or url in existing_urls:
                continue
            artifact_id = self._next_source_id(context.run_id)
            source = SourceArtifact(
                id=artifact_id,
                run_id=context.run_id,
                url=url,
                title=result.data.get("title", ""),
                snippet=self._snippet(result.data),
                source_type="web",
            )
            self._artifacts.save_source(source)
            existing_urls.add(url)
            saved_ids.append(artifact_id)
        return saved_ids

    def _next_source_id(self, run_id: str) -> str:
        next_index = len(self._artifacts.list_sources(run_id)) + 1
        return f"source_{run_id}_{next_index:03d}"

    @staticmethod
    def _tool_results_from_memory(state: AgentState) -> list[ToolResult]:
        raw_results = state.memory.get("tool_results", [])
        if not isinstance(raw_results, list):
            return []
        return [
            ToolResult.from_dict(item) if isinstance(item, dict) else item
            for item in raw_results
            if isinstance(item, dict | ToolResult)
        ]

    @staticmethod
    def _search_results(tool_results: list[ToolResult]) -> list[dict]:
        results: list[dict] = []
        for result in tool_results:
            if not result.ok:
                continue
            search_results = result.data.get("results")
            if isinstance(search_results, list):
                results.extend(item for item in search_results if isinstance(item, dict))
        return results

    @staticmethod
    def _snippet(data: dict) -> str:
        snippet = data.get("snippet") or data.get("content") or ""
        return str(snippet)[:240]

    @staticmethod
    def _query(context: RunContext) -> str:
        request = context.request
        parts = [request.company]
        if request.market:
            parts.append(request.market)
        parts.extend(request.competitors)
        parts.extend(request.questions)
        return " ".join(part for part in parts if part)
