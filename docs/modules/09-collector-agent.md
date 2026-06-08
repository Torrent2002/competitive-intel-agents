# 09 Collector Agent（v2：多查询 + 相关性过滤）

## Goal

收集竞品情报来源，保存为 `SourceArtifact`。v2 支持多角度搜索、域名去重、模型相关性过滤、查询细化。

## Scope

In scope:
- 模型生成 3-5 个多角度搜索查询（产品、定价、竞品对比、技术、新闻）。
- 批量搜索 → 域名去重选 URL → 分批抓取。
- 模型判断抓取内容是否与研究主题相关，无关则跳过。
- 模型提取结构化 title + 2-3 句事实摘要。
- 首轮不足时自动生成细化查询。
- Fake 模式保持 2 source 目标；model-backed 模式目标为 5。

Out of scope:
- Deep crawling、source credibility scoring。

## Round Flow v2

```
Round 1: 生成 3-5 个多角度查询 → 批量 web_search
Round 2: 接收搜索结果 → 域名去重 → 批量 web_fetch (最多 5 个/轮)
Round 3: 接收抓取结果 → 模型相关性过滤 → 模型提取 title+摘要 → 保存
Round 4+: 不够 target → 生成细化查询 → 重复搜索/抓取
```

## 关键细节

- **多查询生成**：模型根据不同角度（产品、定价、竞品、技术、新闻）生成多样化查询。
- **URL 选择**：优先覆盖不同域名，再补充同域名其他页面。
- **相关性过滤**：模型快速判断页面是否相关（`{"relevant": true/false}`），不相关直接跳过。
- **内容提取**：模型从原始 HTML 提取 80 字标题 + 400 字事实摘要。
- **细化查询**：当前来源不够时，模型根据已找到的内容生成补充角度查询。
- **诊断输出**：stderr 实时打印保存进度和跳过原因。

## Tests

- 多查询生成（fake 模式 ≥1 个 tool call）。
- 从 fake 搜索结果去重获取 URL。
- 通过 RuntimeHarness 运行（fake tools）。
- 默认 target 为 2（fake）/ 5（model-backed）。

## Done Criteria

- [x] Collector 支持多角度搜索查询。
- [x] 域名去重和 URL 选择策略。
- [x] 模型相关性过滤（model-backed 模式）。
- [x] 模型内容提取（model-backed 模式）。
- [x] 首轮不足时查询细化。
- [x] 186 测试全绿。
