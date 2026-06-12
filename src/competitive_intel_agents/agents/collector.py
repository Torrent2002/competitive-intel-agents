"""Collector agent — multi-query, retry-aware, relevance-filtered."""

from __future__ import annotations

import json as _json
import sys as _sys
from urllib.parse import urlparse

from competitive_intel_agents.agents.base import BaseAgent
from competitive_intel_agents.agents.prompt_context import (
    coverage_payload,
    request_payload,
    sources_list_payload,
)
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
        self._query_metadata: dict[str, dict] = {}
        self._url_metadata: dict[str, dict] = {}
        self._queried_urls: set[str] = set()
        self._pending_urls: list[dict] = []  # {url, title, snippet}
        self._fetch_attempts: dict[str, int] = {}  # url -> attempt count
        self._attempted_coverage_slots: set[str] = set()
        self._coverage_baseline_slots: set[str] = set()
        self._last_quality_rejections = 0
        self._failed_urls: set[str] = set()

    def run_round(self, context: RunContext, state: AgentState) -> AgentRoundResult:
        existing = self._artifacts.list_sources(context.run_id)

        # Done?
        if self._collection_complete(context, existing):
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
            self._set_coverage_baseline(queries)
            calls = [
                ToolCall(
                    id=f"collector_search_{state.round}_{i+1}",
                    name="web_search",
                    args={"query": q, "metadata": self._metadata_for_query(q)},
                    requested_by=self.name,
                )
                for i, q in enumerate(queries)
            ]
            self._queried_urls = {s.url for s in existing}
            signals = [
                f"search_x{len(calls)}",
                *self._attempt_signals_for_queries(queries),
            ]
            if context.metadata.get("collector_rework_plan"):
                signals.insert(0, "targeted_rework_plan")
            return AgentRoundResult(
                tool_calls=calls,
                signals=signals,
            )

        # --- Phase 2: Got search results → extract URLs to fetch ---
        search_results = self._extract_search_results(tool_results)
        if search_results:
            if self._model_runtime is not None:
                new_urls = self._model_select_urls(context, search_results, count=12)
            else:
                new_urls = self._select_urls(search_results, count=12)
            self._pending_urls = new_urls
            if new_urls:
                batch = self._elidible_fetch_batch(new_urls, 8)
                self._mark_fetch_scheduled(batch)
                calls = [
                    ToolCall(
                        id=f"collector_fetch_{state.round}_{j+1}",
                        name="web_fetch",
                        args={"url": u["url"]},
                        requested_by=self.name,
                    )
                    for j, u in enumerate(batch)  # fetch up to 5 per round
                ]
                return AgentRoundResult(
                    tool_calls=calls,
                    signals=["fetch_x{}".format(len(calls))],
                )
        elif self._only_empty_search_results(tool_results):
            fallback_urls = self._direct_url_fallbacks(context)
            if fallback_urls:
                batch = self._elidible_fetch_batch(fallback_urls, 8)
                self._mark_fetch_scheduled(batch)
                calls = [
                    ToolCall(
                        id=f"collector_direct_fetch_{state.round}_{j+1}",
                        name="web_fetch",
                        args={"url": u["url"]},
                        requested_by=self.name,
                    )
                    for j, u in enumerate(batch)
                ]
                self._pending_urls = fallback_urls[5:]
                return AgentRoundResult(
                    tool_calls=calls,
                    signals=[
                        "direct_url_fallback",
                        f"fetch_x{len(calls)}",
                        *self._attempt_signals_for_urls(batch),
                    ],
                )
            # All searches returned empty AND no direct URLs could be
            # generated. Stop retrying — further rounds would only repeat
            # the same queries.
            existing = self._artifacts.list_sources(context.run_id)
            return AgentRoundResult(
                completed=True,
                output_artifact_ids=[s.id for s in existing],
                signals=["search_exhausted"],
            )

        # --- Phase 3: Got fetch results → filter and save ---
        if tool_results:
            saved = self._filter_and_save(context, tool_results)
            now = self._artifacts.list_sources(context.run_id)
            had_tool_errors = any(not result.ok for result in tool_results)

            if saved:
                print(
                    f"[collector] saved {len(saved)} sources, total={len(now)} "
                    f"(target={self._target_sources})",
                    file=_sys.stderr,
                )

            # More URLs pending from earlier search batches?
            pending = [u for u in self._pending_urls if u["url"] not in self._queried_urls and u["url"] not in self._failed_urls]
            if pending and len(now) < self._target_sources:
                batch = pending[:8]
                self._pending_urls = pending[5:]
                self._mark_fetch_scheduled(batch)
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
                    output_artifact_ids=saved,
                    signals=self._fetch_signals(len(calls), had_tool_errors),
                )

            # Not enough sources → generate refined queries
            if not self._collection_complete(context, now) and self._search_queries:
                refined = self._refine_queries(context, now)
                if not refined:
                    gap_plan = self._coverage_gap_query_plan(context, now)
                    self._query_metadata.update(
                        {item["query"]: item["metadata"] for item in gap_plan}
                    )
                    refined = [item["query"] for item in gap_plan]
                if refined:
                    self._search_queries = refined
                    self._set_coverage_baseline(refined, extend=True)
                    calls = [
                        ToolCall(
                            id=f"collector_search_{state.round}_{m+1}",
                            name="web_search",
                            args={
                                "query": q,
                                "metadata": self._metadata_for_query(q),
                            },
                            requested_by=self.name,
                        )
                        for m, q in enumerate(refined)
                    ]
                    return AgentRoundResult(
                        tool_calls=calls,
                        output_artifact_ids=saved,
                        signals=[
                            "search_refined",
                            "coverage_incomplete",
                            *self._attempt_signals_for_queries(refined),
                        ],
                    )

            completed = self._collection_complete(context, now)
            if completed:
                self._reset()
            return AgentRoundResult(
                completed=completed,
                output_artifact_ids=saved,
                signals=self._save_signals(context, now, saved, completed),
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
        rework_plan = self._targeted_rework_plan(context)
        if rework_plan:
            self._query_metadata = {
                item["query"]: item["metadata"] for item in rework_plan
            }
            return [item["query"] for item in rework_plan]

        # When a real model is available, let it pick from the dimension menu
        # instead of blindly firing all 15 template queries.
        if self._model_runtime is not None:
            queries = self._model_driven_query_selection(context)
            if queries:
                return queries

        # Fallback: template coverage plan
        plan = self._coverage_query_plan(context)
        if plan:
            self._query_metadata = {item["query"]: item["metadata"] for item in plan}
            return [item["query"] for item in plan]

        # Last resort: simple template
        return self._template_queries(context)

    def _model_driven_query_selection(self, context: RunContext) -> list[str]:
        """Let the LLM pick queries from a dimension menu AND propose free queries.

        The model receives a menu of template queries plus the freedom to invent
        its own based on the full user request or reviewer feedback.
        """
        from competitive_intel_agents.prompts import AgentPromptLibrary

        request = context.request
        terms = self._query_terms(context)
        entities = [(request.company, "self")]
        entities.extend((c, "competitor") for c in request.competitors)
        dimensions = self._coverage_dimensions(request.questions)

        # Build a menu of available entity × dimension × source_type combos
        menu_items: list[dict] = []
        for entity, role in entities:
            menu_items.append({
                "label": f"{entity} 官网/产品页",
                "query": f"{entity} {terms['official_product']}",
                "entity": entity, "role": role,
                "dimension": "official", "source_type": "official",
            })
            menu_items.append({
                "label": f"{entity} 功能介绍/文档",
                "query": f"{entity} {terms['docs_features']}",
                "entity": entity, "role": role,
                "dimension": "features", "source_type": "docs",
            })
            for dim in dimensions:
                menu_items.append({
                    "label": f"{entity} {dim}",
                    "query": f"{entity} {self._dimension_query_term(dim, terms)}",
                    "entity": entity, "role": role,
                    "dimension": dim,
                    "source_type": "pricing" if dim == "pricing" else "web",
                })

        for competitor in request.competitors:
            menu_items.append({
                "label": f"{request.company} vs {competitor} 对比",
                "query": f"{request.company} {terms['comparison']} {competitor}",
                "entity": request.company, "role": "self",
                "dimension": "comparison", "source_type": "comparison",
            })

        # Include reviewer feedback if available for rework context
        reviewer_hint = ""
        rework_plan = context.metadata.get("collector_rework_plan")
        if isinstance(rework_plan, dict):
            reviewer_hint = (
                f"\nReviewer feedback requires coverage of: "
                f"{rework_plan.get('dimension','')} — "
                f"{rework_plan.get('required_action','')}"
            )

        prompt_lib = AgentPromptLibrary()
        menu_json = _json.dumps(menu_items, ensure_ascii=False)
        task = (
            f"You are selecting and creating search queries for competitive intelligence.\n"
            f"Target: {request.company} in {request.market or 'its market'}.\n"
            f"Competitors: {', '.join(request.competitors) if request.competitors else 'none'}.\n"
            f"User questions: {', '.join(request.questions) if request.questions else 'none'}.\n"
            f"{reviewer_hint}\n"
            f"Below is a menu of template queries you can pick from. In ADDITION, you can "
            f"invent your own free-form queries that are NOT in the menu — search terms that "
            f"feel more natural, precise, or likely to surface high-quality evidence.\n\n"
            f"Rules:\n"
            f"1. Pick 3-5 items from the menu via their indices.\n"
            f"2. Add 2-4 free-form queries that go beyond the menu. Good free queries are "
            f"specific, search-engine-friendly, and target what you'd actually type into Google "
            f"or Bing to find competitive intelligence. Examples: \"飞书 vs 钉钉 2025市场份额 对比 报告\", "
            f"\"钉钉 企业用户数 2025 最新数据\", \"飞书 字节跳动 协同办公 核心竞争力\".\n"
            f"3. Total (menu + free) should be 5-8 queries.\n\n"
            f"Return ONLY valid JSON:\n"
            f"{{\"selected_indices\": [0, 3, 7], \"free_queries\": [\"飞书 钉钉 2025 市场份额 对比 报告\", ...]}}\n\n"
            f"Menu:\n{menu_json}"
        )
        model_req = prompt_lib.build(self.name, task, {
            "request": request_payload(context),
        })
        resp = self._model_runtime.complete(model_req)
        if not resp.ok or not resp.parsed:
            return []

        selected: list[str] = []
        self._query_metadata = {}

        # Menu selections
        indices = resp.parsed.get("selected_indices", [])
        if isinstance(indices, list):
            for idx in indices:
                if isinstance(idx, int) and 0 <= idx < len(menu_items):
                    item = menu_items[idx]
                    selected.append(item["query"])
                    self._query_metadata[item["query"]] = {
                        "entity": item["entity"],
                        "entity_role": item["role"],
                        "dimension": item["dimension"],
                        "source_type": item["source_type"],
                        "is_official": item["source_type"] in ("official", "docs"),
                    }

        # Free-form queries
        free_queries = resp.parsed.get("free_queries", [])
        if isinstance(free_queries, list):
            for fq in free_queries:
                if isinstance(fq, str) and fq.strip():
                    q = fq.strip()
                    selected.append(q)
                    self._query_metadata[q] = {
                        "entity": request.company,
                        "entity_role": "self",
                        "dimension": "free_search",
                        "source_type": "web",
                    }

        return selected[:8]

    def _targeted_rework_plan(self, context: RunContext) -> list[dict]:
        raw = context.metadata.get("collector_rework_plan")
        if not isinstance(raw, dict):
            return []
        queries = raw.get("queries", [])
        if not isinstance(queries, list):
            return []
        entity = str(raw.get("entity") or context.request.company)
        entity_role = str(raw.get("entity_role") or "self")
        dimension = str(raw.get("dimension") or "evidence_gap")
        source_type = str(raw.get("source_type") or "web")
        return [
            self._query_item(
                str(query),
                entity,
                entity_role,
                dimension,
                source_type,
            )
            for query in queries
            if str(query).strip()
        ]

    def _coverage_query_plan(self, context: RunContext) -> list[dict]:
        request = context.request
        terms = self._query_terms(context)
        entities = [(request.company, "self")]
        entities.extend((competitor, "competitor") for competitor in request.competitors)
        dimensions = self._coverage_dimensions(request.questions)
        plan: list[dict] = []

        for entity, role in entities:
            plan.append(
                self._query_item(
                    f"{entity} {terms['official_product']}",
                    entity,
                    role,
                    "official",
                    "official",
                    is_official=True,
                )
            )
            plan.append(
                self._query_item(
                    f"{entity} {terms['docs_features']}",
                    entity,
                    role,
                    "features",
                    "docs",
                    is_official=True,
                )
            )
            for dimension in dimensions:
                query = f"{entity} {self._dimension_query_term(dimension, terms)}"
                source_type = "pricing" if dimension == "pricing" else "web"
                plan.append(
                    self._query_item(query, entity, role, dimension, source_type)
                )

        for competitor in request.competitors:
            plan.append(
                self._query_item(
                    f"{request.company} {terms['comparison']} {competitor}",
                    request.company,
                    "self",
                    "comparison",
                    "comparison",
                    competitor=competitor,
                )
            )

        plan.extend(self._industry_research_query_plan(context))
        return self._dedupe_query_plan(plan)

    def _coverage_gap_query_plan(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
    ) -> list[dict]:
        covered = self._covered_entities(sources)
        terms = self._query_terms(context)
        plan = []
        for entity, role in self._required_entities(context):
            if entity in covered:
                continue
            plan.append(
                self._query_item(
                    f"{entity} {terms['official_product']}",
                    entity,
                    role,
                    "official",
                    "official",
                    is_official=True,
                )
            )
            plan.append(
                self._query_item(
                    f"{entity} {terms['pricing_features']}",
                    entity,
                    role,
                    "features",
                    "web",
                )
            )
        return self._dedupe_query_plan(plan)

    @staticmethod
    def _coverage_dimensions(questions: list[str]) -> list[str]:
        dimensions = ["pricing", "positioning", "use cases", "limitations"]
        for question in questions:
            normalized = question.strip().lower()
            if not normalized:
                continue
            if "price" in normalized or "pricing" in normalized or "价格" in normalized:
                candidate = "pricing"
            elif "功能" in normalized or "feature" in normalized:
                candidate = "features"
            elif "性能" in normalized or "benchmark" in normalized:
                candidate = "performance"
            elif (
                "受众" in normalized
                or "用户画像" in normalized
                or "audience" in normalized
                or "demographic" in normalized
            ):
                candidate = "audience"
            elif (
                "市场份额" in normalized
                or "市占" in normalized
                or "market share" in normalized
                or "份额" in normalized
            ):
                candidate = "market_share"
            else:
                candidate = normalized
            if candidate not in dimensions:
                dimensions.append(candidate)
        return dimensions[:5]

    @staticmethod
    def _query_terms(context: RunContext) -> dict[str, str]:
        text = " ".join(
            [
                context.request.company,
                *(context.request.competitors),
                *(context.request.questions),
            ]
        )
        if CollectorAgent._contains_cjk(text):
            return {
                "official_product": "官网 产品",
                "docs_features": "文档 功能",
                "comparison": "对比",
                "pricing": "价格",
                "positioning": "定位",
                "use cases": "使用场景",
                "limitations": "缺点 限制",
                "features": "主要功能",
                "performance": "性能 基准测试",
                "pricing_features": "价格 功能",
                "audience": "用户画像 受众群体",
                "market_share": "市场份额 月活 排名",
            }
        return {
            "official_product": "official product",
            "docs_features": "docs features",
            "comparison": "vs",
            "pricing": "pricing",
            "positioning": "positioning",
            "use cases": "use cases",
            "limitations": "limitations",
            "features": "features",
            "performance": "performance benchmark",
            "pricing_features": "pricing features",
            "audience": "audience demographics users",
            "market_share": "market share MAU ranking",
        }

    @staticmethod
    def _dimension_query_term(dimension: str, terms: dict[str, str]) -> str:
        return terms.get(dimension, dimension)

    def _industry_research_query_plan(self, context: RunContext) -> list[dict]:
        text = " ".join(
            [
                context.request.company,
                *context.request.competitors,
                *context.request.questions,
                context.request.market or "",
            ]
        )
        if not self._looks_like_reading_market(text):
            return []

        entities = [context.request.company, *context.request.competitors]
        plan: list[dict] = []
        for entity in entities:
            role = "self" if entity == context.request.company else "competitor"
            plan.extend(
                [
                    self._query_item(
                        f"{entity} QuestMobile 月活 用户画像",
                        entity,
                        role,
                        "audience",
                        "data_provider",
                    ),
                    self._query_item(
                        f"{entity} 易观 用户画像 在线阅读",
                        entity,
                        role,
                        "audience",
                        "data_provider",
                    ),
                    self._query_item(
                        f"{entity} 市场份额 月活 MAU 在线阅读",
                        entity,
                        role,
                        "market_share",
                        "data_provider",
                    ),
                ]
            )
        if context.request.competitors:
            competitor_terms = " ".join(context.request.competitors)
            plan.extend(
                [
                    self._query_item(
                        f"{context.request.company} {competitor_terms} 免费阅读 付费阅读 市场份额",
                        context.request.company,
                        "self",
                        "market_share",
                        "industry_report",
                    ),
                    self._query_item(
                        f"{context.request.company} {competitor_terms} 网文 市场格局 用户画像",
                        context.request.company,
                        "self",
                        "comparison",
                        "industry_report",
                    ),
                ]
            )
        return plan

    @staticmethod
    def _looks_like_reading_market(text: str) -> bool:
        return any(
            keyword in text.lower()
            for keyword in (
                "小说",
                "阅读",
                "网文",
                "起点",
                "番茄",
                "online reading",
                "web novel",
            )
        )

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    @staticmethod
    def _query_item(
        query: str,
        entity: str,
        entity_role: str,
        dimension: str,
        source_type: str,
        is_official: bool = False,
        competitor: str | None = None,
    ) -> dict:
        metadata = {
            "entity": entity,
            "entity_role": entity_role,
            "dimension": dimension,
            "source_type": source_type,
            "is_official": is_official,
        }
        if competitor:
            metadata["competitor"] = competitor
        return {"query": query, "metadata": metadata}

    @staticmethod
    def _dedupe_query_plan(plan: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen: set[str] = set()
        for item in plan:
            query = item["query"]
            key = query.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

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
                "request": request_payload(context),
                "company": context.request.company,
                "competitors": context.request.competitors,
                "questions": context.request.questions,
                "market": context.request.market or "",
                "coverage": coverage_payload(
                    context,
                    self._artifacts.list_sources(context.run_id),
                ),
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
        source_payloads = sources_list_payload(existing_sources or [], snippet_chars=300)
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
                "request": request_payload(context),
                "company": context.request.company,
                "competitors": context.request.competitors,
                "questions": context.request.questions,
                "found_so_far": titles,
                "sources": source_payloads,
                "coverage": coverage_payload(context, existing_sources or []),
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
                metadata = self._metadata_for_query(str(tr.data.get("query", "")))
                for item in items:
                    if isinstance(item, dict) and item.get("url"):
                        enriched = dict(item)
                        enriched["metadata"] = metadata
                        all_results.append(enriched)
        return all_results

    @staticmethod
    def _only_empty_search_results(tool_results: list[ToolResult]) -> bool:
        saw_search_result = False
        for tr in tool_results:
            if not tr.ok:
                continue
            if "results" not in tr.data:
                continue
            saw_search_result = True
            results = tr.data.get("results", [])
            if isinstance(results, list) and results:
                return False
        return saw_search_result

    def _direct_url_fallbacks(self, context: RunContext) -> list[dict]:
        urls: list[dict] = []
        seen: set[str] = set()
        candidate_groups = [
            (entity, role, self._official_url_candidates(entity))
            for entity, role in self._required_entities(context)
        ]
        max_candidates = max((len(group[2]) for group in candidate_groups), default=0)
        for index in range(max_candidates):
            for entity, role, candidates in candidate_groups:
                if index >= len(candidates):
                    continue
                url = candidates[index]
                if url in self._queried_urls or url in seen:
                    continue
                seen.add(url)
                urls.append(
                    {
                        "url": url,
                        "title": f"{entity} official candidate",
                        "snippet": "",
                        "metadata": {
                            "entity": entity,
                            "entity_role": role,
                            "dimension": "official",
                            "source_type": "official",
                            "is_official": True,
                            "discovery": "direct_url_fallback",
                        },
                    }
                )
        return urls

    @staticmethod
    def _official_url_candidates(entity: str) -> list[str]:
        slug = CollectorAgent._domain_slug(entity)
        if not slug:
            return []
        return [
            f"https://www.{slug}.com",
            f"https://{slug}.com",
            f"https://www.{slug}.cn",
            f"https://{slug}.cn",
            f"https://www.{slug}.io",
            f"https://{slug}.io",
            f"https://docs.{slug}.com",
            f"https://docs.{slug}.cn",
            f"https://docs.{slug}.io",
        ]

    @staticmethod
    def _domain_slug(entity: str) -> str:
        import re

        slug = re.sub(r"[^a-z0-9-]+", "", entity.strip().lower())
        return slug.strip("-")

    def _select_urls(self, results: list[dict], count: int) -> list[dict]:
        """Select best URLs: dedup, prefer unique domains, drop already-seen."""
        results = sorted(
            results,
            key=self._url_quality_score,
            reverse=True,
        )
        selected: list[dict] = []
        seen_domains: set[str] = set()

        # First pass: diverse domains
        for r in results:
            url = r.get("url", "")
            if not url or url in self._queried_urls:
                continue
            if any(item["url"] == url for item in selected):
                continue
            domain = self._domain(url)
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            selected.append({
                "url": url,
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "metadata": dict(r.get("metadata", {})),
            })
            if len(selected) >= count:
                return selected

        # Second pass: fill remaining from any domain
        for r in results:
            url = r.get("url", "")
            if not url or url in self._queried_urls:
                continue
            if any(item["url"] == url for item in selected):
                continue
            selected.append({
                "url": url,
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "metadata": dict(r.get("metadata", {})),
            })
            if len(selected) >= count:
                return selected

        return selected

    def _model_select_urls(
        self, context: RunContext, results: list[dict], count: int
    ) -> list[dict]:
        """Let the LLM evaluate search results and pick which URLs to fetch.

        Unlike the hardcoded _url_quality_score, this lets the model apply its
        own judgment about what constitutes a relevant source for THIS specific
        product and market — no domain blocklists needed.
        """
        from competitive_intel_agents.prompts import AgentPromptLibrary

        # Dedup and prepare candidates
        seen_urls: set[str] = set()
        candidates: list[dict] = []
        for r in results:
            url = str(r.get("url", ""))
            if not url or url in self._queried_urls or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append({
                "url": url,
                "title": str(r.get("title", "")),
                "snippet": str(r.get("snippet", ""))[:300],
            })

        # Pre-filter obviously irrelevant URLs before asking the model.
        # Dictionary sites, app stores, and single-character lookups pollute
        # Chinese company searches and inherit misleading is_official metadata
        # from the parent query.
        candidates = [
            c for c in candidates
            if not _is_obviously_irrelevant(c["url"], c.get("title", ""))
        ]

        if not candidates:
            return []

        # Always ask the model to vet URLs — even a single bad result wastes
        # a fetch slot and pollutes the source list.
        # Ask the model to pick the best URLs
        prompt_lib = AgentPromptLibrary()
        candidates_json = _json.dumps(candidates, ensure_ascii=False)
        task = (
            f"You are evaluating search results for a competitive intelligence "
            f"project about {context.request.company}"
            f"{' vs ' + ', '.join(context.request.competitors) if context.request.competitors else ''}.\n\n"
            f"For each search result below, decide if the URL is genuinely about "
            f"{context.request.company} or its competitors/industry. REJECT results that are:\n"
            f"- Dictionary/encyclopedia entries about individual Chinese characters (not the company)\n"
            f"- Travel, hotel, or flight booking sites\n"
            f"- Unrelated software forums (Adobe, Microsoft, Apple, etc.)\n"
            f"- Government portals or generic news sites that don't discuss the target products\n"
            f"- App store download pages with no substantive content\n\n"
            f"RANK the relevant results by quality (BEST FIRST), not by their original order. "
            f"Prioritize:\n"
            f"1. Official company/product pages (pricing, features, about)\n"
            f"2. Industry analysis and comparison articles\n"
            f"3. News or blog coverage with substantive detail\n\n"
            f"DIVERSIFY — avoid selecting 3+ URLs from the same domain. "
            f"Prefer 1 URL per domain unless a second URL adds significant new information.\n\n"
            f"Return the INDICES (0-based) of up to {count} most relevant results, "
            f"ORDERED BY QUALITY (best first). "
            f"If fewer than {count} results are relevant, return only the relevant ones.\n\n"
            f"Return ONLY valid JSON: {{\"selected_indices\": [0, 3, 7, ...]}}\n\n"
            f"Search results:\n{candidates_json}"
        )
        model_req = prompt_lib.build(self.name, task, {
            "request": request_payload(context),
        })
        resp = self._model_runtime.complete(model_req)
        if not resp.ok or not resp.parsed:
            print(
                f"[collector] URL selection model failed: ok={resp.ok} error={resp.error}, "
                f"using algorithmic scoring",
                file=_sys.stderr,
            )
            return self._select_urls(results, count)

        indices = resp.parsed.get("selected_indices", [])
        if not isinstance(indices, list) or len(indices) < 1:
            print("[collector] URL selection returned invalid indices, using algorithmic scoring", file=_sys.stderr)
            return self._select_urls(results, count)

        selected: list[dict] = []
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                selected.append(candidates[idx])
                if len(selected) >= count:
                    break
        return selected

    @staticmethod
    def _domain(url: str) -> str:
        return urlparse(url).netloc

    @staticmethod
    def _url_quality_score(result: dict) -> int:
        url = str(result.get("url", ""))
        title = str(result.get("title", ""))
        snippet = str(result.get("snippet", ""))
        metadata = dict(result.get("metadata", {}))
        haystack = f"{url} {title} {snippet}".lower()
        domain = urlparse(url).netloc.lower()
        score = 0
        score += {
            "data_provider": 45,
            "industry_report": 40,
            "comparison": 32,
            "official": 25,
            "docs": 20,
            "pricing": 15,
            "web": 0,
        }.get(str(metadata.get("source_type", "web")), 0)
        if any(
            trusted in domain
            for trusted in (
                "questmobile",
                "analysys",
                "iresearch",
                "qimai",
                "data.ai",
                "appfigures",
                "sensortower",
                "yuewen",
            )
        ):
            score += 35
        if any(token in haystack for token in ("报告", "research", "market", "市场", "月活", "mau", "用户画像")):
            score += 12
        if any(
            low in domain
            for low in (
                "sj.qq.com",
                "apps.microsoft.com",
                "app.mi.com",
                "wandoujia",
                "softonic",
            )
        ):
            score -= 30
        if any(token in haystack for token in ("下载", "download", "appdetail")):
            score -= 10
        return score

    # ----------------------------------------------------------------
    # Relevance filtering & saving
    # ----------------------------------------------------------------

    def _filter_and_save(self, context: RunContext, tool_results: list[ToolResult]) -> list[str]:
        """Filter fetched results by relevance, then save the good ones."""
        saved: list[str] = []
        self._last_quality_rejections = 0
        existing_sources = self._artifacts.list_sources(context.run_id)
        existing_urls = {s.url for s in existing_sources}
        remaining_slots = self._remaining_source_slots(context, existing_sources)
        missing_entities = self._missing_entities(context, existing_sources)

        for tr in tool_results:
            if len(saved) >= remaining_slots:
                break
            if not tr.ok:
                failed_url = tr.data.get("url", "") if isinstance(tr.data, dict) else ""
                if failed_url:
                    self._failed_urls.add(failed_url)
                continue
            if "url" not in tr.data:
                continue
            url = tr.data.get("url", "")
            if not url or url in existing_urls:
                continue
            metadata = self._metadata_for_url(url)
            entity = metadata.get("entity")
            if missing_entities and entity and entity not in missing_entities:
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
            snippet = (
                tr.data.get("summary", "")
                or tr.data.get("content", "")
                or tr.data.get("snippet", "")
                or tr.data.get("preview", "")
                or ""
            )
            if self._model_runtime is not None and snippet:
                title, snippet = self._model_extract(context, tr.data)
            metadata = self._source_metadata(metadata, tr.data)
            if self._reject_source_for_quality(metadata):
                self._last_quality_rejections += 1
                print(
                    f"[collector] skipping low-quality source: {url[:80]}",
                    file=_sys.stderr,
                )
                continue

            source = SourceArtifact(
                id=aid,
                run_id=context.run_id,
                url=url,
                title=title or url,
                snippet=snippet[:500],
                source_type="web",
                metadata=metadata,
            )
            self._artifacts.save_source(source)
            existing_urls.add(url)
            saved.append(aid)
            if isinstance(entity, str):
                missing_entities.discard(entity)

        return saved

    @staticmethod
    def _source_metadata(base: dict, data: dict) -> dict:
        metadata = dict(base)
        for key in (
            "content_ref",
            "content_hash",
            "char_count",
            "summary",
            "preview",
            "content_field",
        ):
            if key in data and data[key] not in (None, ""):
                metadata[key] = data[key]
        text = " ".join(
            str(data.get(key, ""))
            for key in ("title", "summary", "content", "snippet", "preview")
        )
        covered_dimensions = CollectorAgent._covered_dimensions_from_text(
            text,
            metadata.get("dimension"),
        )
        metadata["covered_dimensions"] = covered_dimensions
        metadata["extract_quality"] = CollectorAgent._extract_quality(
            data,
            text,
            covered_dimensions,
        )
        metadata["source_score"] = CollectorAgent._url_quality_score(
            {
                "url": data.get("url", ""),
                "title": data.get("title", ""),
                "snippet": text,
                "metadata": metadata,
            }
        )
        return metadata

    @staticmethod
    def _extract_quality(data: dict, text: str, covered_dimensions: list[str]) -> str:
        char_count = data.get("char_count")
        if isinstance(char_count, int):
            length = char_count
        else:
            length = len(text.strip())
        lowered = text.lower()
        if "enable javascript" in lowered or "需要启用javascript" in lowered:
            return "js_required"
        if not text.strip() or length < 50:
            return "empty"
        if length >= 500 or len(covered_dimensions) >= 2:
            return "good"
        return "partial"

    @staticmethod
    def _reject_source_for_quality(metadata: dict) -> bool:
        quality = metadata.get("extract_quality")
        if quality == "js_required":
            return True
        return False

    @staticmethod
    def _covered_dimensions_from_text(
        text: str,
        declared_dimension: object,
    ) -> list[str]:
        lowered = text.lower()
        dimensions: set[str] = set()
        if isinstance(declared_dimension, str) and declared_dimension:
            dimensions.add(declared_dimension)
        checks = {
            "audience": ("受众", "用户画像", "年龄", "性别", "demographic", "audience"),
            "market_share": ("市场份额", "市占", "月活", "mau", "排名", "market share"),
            "pricing": ("价格", "定价", "pricing", "付费", "免费"),
            "features": ("功能", "feature", "能力"),
            "business_model": ("商业模式", "广告", "订阅", "收入", "变现"),
            "comparison": ("对比", "竞争", "vs", "相比"),
        }
        for dimension, keywords in checks.items():
            if any(keyword in lowered for keyword in keywords):
                dimensions.add(dimension)
        return sorted(dimensions)

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
                "request": request_payload(context),
                "topic": f"{context.request.company} {context.request.questions} {context.request.competitors}",
                "url": data.get("url", ""),
                "content_sample": content,
                "coverage": coverage_payload(
                    context,
                    self._artifacts.list_sources(context.run_id),
                ),
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
                "request": request_payload(context),
                "url": data.get("url", ""),
                "topic": str(context.request.questions),
                "content": content,
                "coverage": coverage_payload(
                    context,
                    self._artifacts.list_sources(context.run_id),
                ),
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

    def _collection_complete(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
    ) -> bool:
        if len(sources) >= self._target_sources:
            return True
        # Escape hatch: if we have >= 60% of target sources and at least
        # 2 rounds of searching, stop — diminishing returns and risk of
        # abort from tool errors outweigh marginal coverage gains.
        if len(sources) >= max(3, int(self._target_sources * 0.6)) and len(self._attempted_coverage_slots) > 6:
            return True
        if not self._coverage_attempts_complete(context):
            return False
        covered = self._covered_entities(sources)
        if not covered:
            return False
        return all(entity in covered for entity, _ in self._required_entities(context))

    def _coverage_attempts_complete(self, context: RunContext) -> bool:
        required = set(self._coverage_baseline_slots)
        if not required:
            required = {
                key
                for key in (
                    self._coverage_attempt_key(item["metadata"])
                    for item in self._coverage_query_plan(context)
                )
                if key
            }
        return required <= self._attempted_coverage_slots

    def _effective_target_sources(self, context: RunContext) -> int:
        return max(self._target_sources, len(self._required_entities(context)))

    def _remaining_source_slots(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
    ) -> int:
        count_gap = max(0, self._effective_target_sources(context) - len(sources))
        covered = self._covered_entities(sources)
        if not covered:
            return count_gap
        coverage_gap = sum(
            1
            for entity, _ in self._required_entities(context)
            if entity not in covered
        )
        return max(count_gap, coverage_gap)

    def _missing_entities(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
    ) -> set[str]:
        covered = self._covered_entities(sources)
        if not covered:
            return set()
        return {
            entity
            for entity, _ in self._required_entities(context)
            if entity not in covered
        }

    @staticmethod
    def _required_entities(context: RunContext) -> list[tuple[str, str]]:
        entities = [(context.request.company, "self")]
        entities.extend(
            (competitor, "competitor")
            for competitor in context.request.competitors
        )
        return entities

    @staticmethod
    def _covered_entities(sources: list[SourceArtifact]) -> set[str]:
        covered: set[str] = set()
        for source in sources:
            entity = source.metadata.get("entity")
            if isinstance(entity, str) and entity:
                covered.add(entity)
        return covered

    def _save_signals(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
        saved: list[str],
        completed: bool,
    ) -> list[str]:
        signals = ["sources_saved"] if saved else ["no_new_sources"]
        if not completed:
            signals.append("coverage_incomplete")
        elif self._coverage_partial(context, sources):
            signals.append("coverage_partial")
        if self._last_quality_rejections:
            signals.append("source_quality_rejected")
        return signals

    def _coverage_partial(
        self,
        context: RunContext,
        sources: list[SourceArtifact],
    ) -> bool:
        covered = self._covered_entities(sources)
        if not covered:
            return bool(context.request.competitors)
        return any(
            entity not in covered for entity, _ in self._required_entities(context)
        )

    @staticmethod
    def _fetch_signals(fetch_count: int, had_tool_errors: bool) -> list[str]:
        signals = [f"fetch_x{fetch_count}"]
        if had_tool_errors:
            signals.append("alternate_fetch_after_error")
        return signals

    @staticmethod
    def _tool_results_from_memory(state: AgentState) -> list[ToolResult]:
        raw = state.memory.get("tool_results", [])
        if not isinstance(raw, list):
            return []
        return [
            ToolResult.from_dict(item) if isinstance(item, dict) else item
            for item in raw
            if isinstance(item, (dict, ToolResult))
        ]

    def _reset(self) -> None:
        self._search_queries = []
        self._query_metadata = {}
        self._url_metadata = {}
        self._queried_urls = set()
        self._pending_urls = []
        self._fetch_attempts = {}
        self._attempted_coverage_slots = set()
        self._coverage_baseline_slots = set()
        self._last_quality_rejections = 0
        self._failed_urls = set()

    def _set_coverage_baseline(self, queries: list[str], extend: bool = False) -> None:
        slots = {
            key
            for key in (
                self._coverage_attempt_key(self._metadata_for_query(query))
                for query in queries
            )
            if key
        }
        if extend:
            self._coverage_baseline_slots.update(slots)
        else:
            self._coverage_baseline_slots = slots

    def _mark_fetch_scheduled(self, urls: list[dict]) -> None:
        for item in urls:
            url = item.get("url", "")
            if url:
                self._queried_urls.add(url)
                self._url_metadata[url] = dict(item.get("metadata", {}))

    def _elidible_fetch_batch(self, urls: list[dict], size: int) -> list[dict]:
        """Return up to *size* URLs not yet queried and not previously failed."""
        batch: list[dict] = []
        for u in urls:
            if len(batch) >= size:
                break
            if u["url"] not in self._queried_urls and u["url"] not in self._failed_urls:
                batch.append(u)
        return batch

    def _metadata_for_query(self, query: str) -> dict:
        return dict(self._query_metadata.get(query, {}))

    def _metadata_for_url(self, url: str) -> dict:
        return dict(self._url_metadata.get(url, {}))

    def _attempt_signals_for_queries(self, queries: list[str]) -> list[str]:
        return self._attempt_signals(
            self._metadata_for_query(query) for query in queries
        )

    def _attempt_signals_for_urls(self, urls: list[dict]) -> list[str]:
        return self._attempt_signals(
            dict(item.get("metadata", {})) for item in urls
        )

    def _attempt_signals(self, metadata_items) -> list[str]:
        signals: list[str] = []
        seen: set[str] = set()
        for metadata in metadata_items:
            key = CollectorAgent._coverage_attempt_key(metadata)
            if not key or key in seen:
                continue
            seen.add(key)
            self._attempted_coverage_slots.add(key)
            signals.append(f"attempted:{key}")
        return signals

    @staticmethod
    def _coverage_attempt_key(metadata: dict) -> str | None:
        entity = metadata.get("entity")
        dimension = metadata.get("dimension")
        if not isinstance(entity, str) or not entity:
            return None
        if not isinstance(dimension, str) or not dimension:
            return None
        competitor = metadata.get("competitor")
        if isinstance(competitor, str) and competitor:
            return f"{entity}:{dimension}:{competitor}"
        return f"{entity}:{dimension}"


def _is_obviously_irrelevant(url: str, title: str) -> bool:
    """Fast deterministic pre-filter for URLs that are never useful sources.

    Catches dictionary entries, app stores, download portals, and other
    noise that search engines return for short Chinese company names whose
    characters also appear in common words (e.g. 飞→fly, 钉→nail).
    """
    from urllib.parse import urlparse as _urlparse

    domain = _urlparse(url).netloc.lower()

    # Dictionary / character-lookup sites
    if any(kw in domain for kw in (
        "hanyuguoxue.com", "chagushici.com", "zdic.net",
        "zidian.", "cidian.", "hanyu.", "guoxue.",
        "dict.cn", "dict.youdao.com",
    )):
        return True

    # App stores and download portals
    if any(kw in domain for kw in (
        "apps.apple.com", "play.google.com",
        "apps.microsoft.com", "app.mi.com",
        "sj.qq.com", "wandoujia", "softonic",
        "download.cnet.com", "filehippo",
    )):
        return True

    # Single-character or single-pinyin lookups (e.g. /zidian/zi-39134)
    if "/zidian/" in url and any(
        pattern in url for pattern in ("zi-", "zi_", "%E9%A3%9E", "%E9%92%89")
    ):
        return True

    # Snippet farms / content mills
    if any(kw in domain for kw in (
        "baike.com",  # 互动百科 (not baidu baike)
    )):
        return True

    return False
