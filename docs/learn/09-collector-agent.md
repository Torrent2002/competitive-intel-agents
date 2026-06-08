# 09 Collector Agent — 面试级学习笔记（v2）

## 一句话概括

**Collector 是 pipeline 的信息入口：多角度搜索 → 域名去重 → 模型相关性过滤 → 结构化 source。模型驱动模式下，不是"搜一个词拿两条结果就停"，而是多轮迭代直到收集够高质量来源。**

---

## 1. v1 → v2 的演进

| | v1（fake pipeline） | v2（model-backed） |
|---|---|---|
| 搜索查询数 | 1 个 | 3-5 个（产品/定价/竞品/技术/新闻） |
| 目标来源数 | 2 | 5 |
| URL 选择 | 直接取前几个 | 优先不同域名，再补同域其他页 |
| 内容过滤 | 抓到什么存什么 | 模型判断相关性，不相关直接跳过 |
| 内容提取 | 原始 title/snippet | 模型提取结构化标题+事实摘要 |
| 不足时 | 直接结束 | 模型生成细化查询，继续搜 |

---

## 2. Round Flow v2

```
Round 1: 模型生成 3-5 个多角度查询 → 批量 web_search x5
Round 2: 收到搜索结果 → 域名去重选 5-8 个 URL → 批量 web_fetch x5
Round 3: 收到抓取结果 → 模型相关性过滤 → 模型提取 title+摘要 → 保存
Round 4+: 不够 5 个 → 模型生成细化查询 → 重复搜索/抓取
```

核心设计：**Collector 不依赖 ToolRuntime，只通过 ToolCall/ToolResult 通信**。

---

## 3. 为什么多查询很重要

单查询"小米 荣耀 2026Q1 手机"容易出现：

- 前 5 条全是同一事件的转载（搜狐、企鹅号、头条号）
- 没有竞品视角（荣耀的市场份额数据）
- 没有产品细节（具体型号、定价）

多查询策略：每个角度一条 query，模型生成如：

```
"小米 2026Q1 智能手机出货量"
"荣耀 Honor 2026Q1 市场份额"
"小米 vs 荣耀 2026 产品对比"
"小米 2026Q1 财报 手机业务"
```

这样 Analyst 拿到的是多角度、不同信源的素材，分析质量才有保证。

---

## 4. 相关性过滤

搜"阿里 Qoder"，抓取回来的可能是：

- ✅ Qoder 产品页面（相关）
- ✅ Qoder 技术架构分析（相关）
- ❌ 阿里巴巴 IR 投资者关系页面（无关）
- ❌ 阿里云通用产品目录（弱相关）

模型做快速二分类：`{"relevant": true/false}`。无关页面直接跳过，不浪费 Analyst 的 token 和用户的时间。

---

## 5. 内容提取

原始 HTML 可能有 2000+ 字，包含导航栏、广告、相关文章链接。模型从中提取：

```json
{
  "title": "Qoder: Alibaba's AI Coding Assistant Challenges Cursor",
  "summary": "Alibaba launched Qoder, an AI IDE with three modes (Ask, Agent, Quest). Built on Qwen Coder model with MoE architecture. Currently free, aims to compete with Cursor and Windsurf."
}
```

而不是把整个 HTML dump 进 SourceArtifact。

---

## 6. 诊断输出

stderr 实时反馈采集进度：

```
[collector] saved 4 sources, total=4 (target=5)
[collector] skipping irrelevant: https://ir.alibaba.com/financial-reports
```

面试时可以讲：**"我们不是在黑箱里跑 agent，collector 的每一步决策都有 stderr 输出可审计。"**

---

## 7. 测试覆盖

```text
test_collector_first_round_requests_search_query_from_run_input  → ≥1 个查询
test_collector_turns_search_results_into_deduped_fetch_calls
test_collector_saves_fetch_results_as_source_artifacts
test_collector_skips_urls_already_saved
test_collector_can_run_through_harness_with_fake_tools             → 不依赖真实网络
```

fake 模式保持 2 source 目标，model-backed 模式 5 个目标。Orchestrator 根据 `model_runtime` 是否存在自动选择。

---

## 面试怎么讲

> Collector 不是"搜一下关键词 dump 结果"。它是多角度的信息采集器：模型生成 3-5 个不同角度的查询，按域名去重抓取，每条内容先做相关性判断再提取结构化摘要。不够的时候会自动细化查询继续采集。整个过程有 stderr 实时输出可审计。这就是为什么 analyst 拿到的不再是一堆噪音 URL，而是真正相关的信息。
