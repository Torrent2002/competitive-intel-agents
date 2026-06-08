"""Collector agent — multi-query, retry-aware, relevance-filtered."""

from __future__ import annotations

import json as _json
import sys as _sys

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
from competitive_intel_agents.runtime.model_runtime import ModelRuntime


class CollectorAgent(BaseAgent):
    """Multi-query collector with relevance filtering and fetch retry."""

    name = "collector"

    def __init__(
        self,
        artifacts: ArtifactStore,
        target_sources: int = 2,
        model_runtime: ModelRuntime | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._target_sources = target_sources
        self._model_runtime = model_runtime
        # Per-run state (reset each pipeline run since agent is reused)
        self._search_queries: list[str] = []
        self._queried_urls: set[str] = set()
        self._pending_urls: list[dict] = []  # {url, title, snippet}
        self._fetch_attempts: dict[str, int] = {}  # url -> attempt count

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        existing = self._artifacts.list_sources(context.run_id)

        # Done?
        if len(existing) >= self._target_sources:
            self._reset()
            return AgentRoundResult(
                completed=True,
                output_artifact_ids=[s.id for s in existing],
                signals=["sources_ready"],
            )

        tool_results = self._tool_results_from_memory(state)

        # --- Phase 1: No tool results yet → generate search queries ---
        if not tool_results and not self._search_queries:
            queries = self._generate_queries(context)
            self._search_queries = queries
            calls = [
                ToolCall(
                    id=f"collector_search_{state.round}_{i+1}",
                    name="web_search",
                    args={"query": q},
                    requested_by=self.name,
                )
                for i, q in enumerate(queries)
            ]
            self._queried_urls = {s.url for s in existing}
            return AgentRoundResult(
                tool_calls=calls,
                signals=[f"search_x{len(calls)}"],
            )

        # --- Phase 2: Got search results → extract URLs to fetch ---
        search_results = self._extract_search_results(tool_results)
        if search_results:
            new_urls = self._select_urls(search_results, count=8)
            self._pending_urls = new_urls
            if new_urls:
                calls = [
                    ToolCall(
                        id=f"collector_fetch_{state.round}_{j+1}",
                        name="web_fetch",
                        args={"url": u["url"]},
                        requested_by=self.name,
                    )
                    for j, u in enumerate(new_urls[:5])  # fetch up to 5 per round
                ]
                return AgentRoundResult(
                    tool_calls=calls,
                    signals=["fetch_x{}".format(len(calls))],
                )

        # --- Phase 3: Got fetch results → filter and save ---
        if tool_results:
            saved = self._filter_and_save(context, tool_results)
            now = self._artifacts.list_sources(context.run_id)

            if saved:
                print(
                    f"[collector] saved {len(saved)} sources, total={len(now)} "
                    f"(target={self._target_sources})",
                    file=_sys.stderr,
                )

            # More URLs pending from earlier search batches?
            pending = [u for u in self._pending_urls if u["url"] not in self._queried_urls]
            if pending and len(now) < self._target_sources:
                batch = pending[:5]
                self._pending_urls = pending[5:]
                calls = [
                    ToolCall(
                        id=f"collector_fetch_{state.round}_{k+1}",
                        name="web_fetch",
                        args={"url": u["url"]},
                        requested_by=self.name,
                    )
                    for k, u in enumerate(batch)
                ]
                return AgentRoundResult(
                    tool_calls=calls,
                    signals=[f"fetch_x{len(calls)}"],
                )

            # Not enough sources → generate refined queries
            if len(now) < self._target_sources and self._search_queries:
                refined = self._refine_queries(context, now)
                if refined:
                    self._search_queries = refined
                    calls = [
                        ToolCall(
                            id=f"collector_search_{state.round}_{m+1}",
                            name="web_search",
                            args={"query": q},
                            requested_by=self.name,
                        )
                        for m, q in enumerate(refined)
                    ]
                    return AgentRoundResult(
                        tool_calls=calls,
                        signals=["search_refined"],
                    )

            completed = len(now) >= self._target_sources or not pending
            self._reset()
            return AgentRoundResult(
                completed=completed,
                output_artifact_ids=saved,
                signals=["sources_saved"] if saved else ["no_new_sources"],
            )

        # No search results, no fetch results, no sources
        self._reset()
        return AgentRoundResult(
            completed=False,
            signals=["no_new_sources"],
        )

    # ----------------------------------------------------------------
    # Query generation
    # ----------------------------------------------------------------

    def _generate_queries(self, context: RunContext) -> list[str]:
        """Generate 3-5 diverse search queries covering different angles."""
        if self._model_runtime is not None:
            queries = self._model_queries(context)
            if queries and len(queries) >= 2:
                return queries[:5]

        # Fallback: simple template
        return self._template_queries(context)

    def _model_queries(self, context: RunContext) -> list[str]:
        """Ask model for diverse search queries."""
        from competitive_intel_agents.prompts import AgentPromptLibrary

        prompt_lib = AgentPromptLibrary()
        task = (
            "Generate 3-5 DIVERSE web search queries to research this topic from "
            "different angles (e.g. product details, pricing, market comparison, "
            "news, technical specs). Each query should be 4-10 words, in the same "
            "language as the research topic. "
            "Return ONLY a JSON object with a 'queries' array of strings."
        )
        model_req = prompt_lib.build(
            self.name,
            task,
            {
                "company": context.request.company,
                "competitors": context.request.competitors,
                "questions": context.request.questions,
                "market": context.request.market or "",
            },
        )
        resp = self._model_runtime.complete(model_req)
        if resp.ok:
            data = self._parse_json(resp)
            queries = data.get("queries", []) if isinstance(data, dict) else []
            if isinstance(queries, list) and queries:
                return [str(q) for q in queries if q]
        return []

    def _template_queries(self, context: RunContext) -> list[str]:
        r = context.request
        qs = [r.company]
        if r.competitors:
            qs.append(f"{r.company} vs {r.competitors[0]}")
        if r.questions:
            qs.append(f"{r.company} {' '.join(r.questions)}")
        return qs

    def _refine_queries(self, context: RunContext, existing_sources) -> list[str]:
        """Generate more targeted queries when initial ones didn't yield enough."""
        if self._model_runtime is None:
            return []
        from competitive_intel_agents.prompts import AgentPromptLibrary

        prompt_lib = AgentPromptLibrary()
        titles = [s.title for s in existing_sources] if existing_sources else ["none"]
        task = (
            "The initial search found these sources but we need MORE and DIFFERENT ones. "
            "Generate 2-3 NEW search queries covering angles NOT yet captured. "
            "Return ONLY a JSON object with a 'queries' array of strings."
        )
        model_req = prompt_lib.build(
            self.name,
            task,
            {
                "company": context.request.company,
                "competitors": context.request.competitors,
                "questions": context.request.questions,
                "found_so_far": titles,
            },
        )
        resp = self._model_runtime.complete(model_req)
        if resp.ok:
            data = self._parse_json(resp)
            queries = data.get("queries", []) if isinstance(data, dict) else []
            if isinstance(queries, list) and queries:
                return [str(q) for q in queries if q]
        return []

    # ----------------------------------------------------------------
    # URL selection
    # ----------------------------------------------------------------

    def _extract_search_results(self, tool_results: list[ToolResult]) -> list[dict]:
        all_results: list[dict] = []
        for tr in tool_results:
            if not tr.ok:
                continue
            items = tr.data.get("results", [])
            if isinstance(items, list):
                all_results.extend(
                    item for item in items if isinstance(item, dict) and item.get("url")
                )
        return all_results

    def _select_urls(self, results: list[dict], count: int) -> list[dict]:
        """Select best URLs: dedup, prefer unique domains, drop already-seen."""
        selected: list[dict] = []
        seen_domains: set[str] = set()

        # First pass: diverse domains
        for r in results:
            url = r.get("url", "")
            if not url or url in self._queried_urls:
                continue
            domain = self._domain(url)
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            selected.append({"url": url, "title": r.get("title", ""), "snippet": r.get("snippet", "")})
            self._queried_urls.add(url)
            if len(selected) >= count:
                return selected

        # Second pass: fill remaining from any domain
        for r in results:
            url = r.get("url", "")
            if not url or url in self._queried_urls:
                continue
            selected.append({"url": url, "title": r.get("title", ""), "snippet": r.get("snippet", "")})
            self._queried_urls.add(url)
            if len(selected) >= count:
                return selected

        return selected

    @staticmethod
    def _domain(url: str) -> str:
        from urllib.parse import urlparse
        return urlparse(url).netloc

    # ----------------------------------------------------------------
    # Relevance filtering & saving
    # ----------------------------------------------------------------

    def _filter_and_save(self, context: RunContext, tool_results: list[ToolResult]) -> list[str]:
        """Filter fetched results by relevance, then save the good ones."""
        saved: list[str] = []
        existing_urls = {s.url for s in self._artifacts.list_sources(context.run_id)}

        for tr in tool_results:
            if not tr.ok or "url" not in tr.data:
                continue
            url = tr.data.get("url", "")
            if not url or url in existing_urls:
                continue

            # Check relevance
            if self._model_runtime is not None:
                if not self._is_relevant(context, tr.data):
                    print(
                        f"[collector] skipping irrelevant: {url[:80]}",
                        file=_sys.stderr,
                    )
                    continue

            aid = self._next_source_id(context.run_id)
            title = tr.data.get("title", "") or url
            snippet = tr.data.get("content", "") or tr.data.get("snippet", "") or ""
            if self._model_runtime is not None and snippet:
                title, snippet = self._model_extract(context, tr.data)

            source = SourceArtifact(
                id=aid,
                run_id=context.run_id,
                url=url,
                title=title or url,
                snippet=snippet[:500],
                source_type="web",
            )
            self._artifacts.save_source(source)
            existing_urls.add(url)
            saved.append(aid)

        return saved

    def _is_relevant(self, context: RunContext, data: dict) -> bool:
        """Quick relevance check: does this page relate to our research?"""
        from competitive_intel_agents.prompts import AgentPromptLibrary

        content = (data.get("content", "") or data.get("snippet", ""))[:1500]
        if not content:
            return True  # no content to judge, save it anyway

        prompt_lib = AgentPromptLibrary()
        task = (
            "Is this web page content relevant to the research topic? "
            "Return ONLY a JSON object with a single key 'relevant' set to true or false."
        )
        model_req = prompt_lib.build(
            self.name,
            task,
            {
                "topic": f"{context.request.company} {context.request.questions} {context.request.competitors}",
                "url": data.get("url", ""),
                "content_sample": content,
            },
        )
        resp = self._model_runtime.complete(model_req)
        if resp.ok:
            data_parsed = self._parse_json(resp)
            if isinstance(data_parsed, dict) and "relevant" in data_parsed:
                return bool(data_parsed["relevant"])
        return True  # if model fails, default to keeping

    def _model_extract(self, context: RunContext, data: dict) -> tuple[str, str]:
        """Use model to produce a meaningful title and summary snippet."""
        from competitive_intel_agents.prompts import AgentPromptLibrary

        content = (data.get("content", "") or data.get("snippet", ""))[:3000]
        prompt_lib = AgentPromptLibrary()
        task = (
            "Extract the most relevant information from this web page for competitive "
            "intelligence research. Return ONLY a JSON object with 'title' "
            "(concise factual title, max 80 chars) and 'summary' "
            "(2-3 sentences of key facts, max 400 chars)."
        )
        model_req = prompt_lib.build(
            self.name,
            task,
            {
                "url": data.get("url", ""),
                "topic": str(context.request.questions),
                "content": content,
            },
        )
        resp = self._model_runtime.complete(model_req)
        if resp.ok:
            parsed = self._parse_json(resp)
            if isinstance(parsed, dict):
                t = str(parsed.get("title", "")) or data.get("title", "")
                s = str(parsed.get("summary", "")) or str(content)[:400]
                return t, s[:500]
        return data.get("title", ""), str(content)[:400]

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    @staticmethod
    def _parse_json(resp) -> dict:
        """Robust JSON extraction from model response."""
        if resp.parsed and isinstance(resp.parsed, dict):
            return resp.parsed
        content = resp.content.strip()
        if not content:
            return {}
        # Try direct parse
        try:
            return _json.loads(content)
        except (_json.JSONDecodeError, TypeError):
            pass
        # Try extracting from ```json blocks
        import re
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if m:
            try:
                return _json.loads(m.group(1))
            except (_json.JSONDecodeError, TypeError):
                pass
        # Try finding { } in text
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            try:
                return _json.loads(m.group(0))
            except (_json.JSONDecodeError, TypeError):
                pass
        return {}

    def _next_source_id(self, run_id: str) -> str:
        n = len(self._artifacts.list_sources(run_id, status=None)) + 1
        return f"source_{run_id}_{n:03d}"

    @staticmethod
    def _tool_results_from_memory(state: AgentState) -> list[ToolResult]:
        raw = state.memory.get("tool_results", [])
        if not isinstance(raw, list):
            return []
        return [
            ToolResult.from_dict(item) if isinstance(item, dict) else item
            for item in raw
            if isinstance(item, dict | ToolResult)
        ]

    def _reset(self) -> None:
        self._search_queries = []
        self._pending_urls = []
        self._fetch_attempts = {}
