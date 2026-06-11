# 09 Collector Agent — 面试级学习笔记（v3）

## 一句话概括

**Collector 是证据入口，不是搜索脚本：它先把用户问题拆成动态 evidence needs，再执行搜索与抓取，保存全文 `content_ref`，并在 reviewer 要求补证据时优先执行定向 research plan。**

---

## 1. v2 → v3 的演进

| | v2（多查询采集） | v3（research-plan collector） |
|---|---|---|
| 查询来源 | 模型生成 3-5 个角度 | 请求实体、竞品、问题维度、行业模板、reviewer rework plan |
| 目标 | 尽量拿够 5 个 source | 尽量覆盖本产品、竞品、对比维度、用户问题 |
| 网页内容 | 提取标题和摘要 | 摘要 + 完整清洗文本持久化 `content_ref` |
| URL 选择 | 域名去重 | 域名去重 + source quality scoring |
| 行业策略 | 通用查询 | 识别阅读/小说等场景后扩展 MAU、用户画像、市场份额、QuestMobile/易观等查询 |
| 返工 | 通用细化查询 | Reviewer 缺口 → `collector_rework_plan` → 定向补采 |

---

## 2. Round Flow v3

```text
Round 1:
  如果存在 collector_rework_plan:
    生成定向 query，并在 journal 里标记 targeted_rework_plan
  否则:
    根据 company / competitors / questions 生成 coverage query plan

Round 2:
  批量 web_search，保留 attempted:<entity>:<dimension> health signals

Round 3:
  对搜索结果做 URL scoring、域名去重、分批 web_fetch

Round 4:
  对 fetch 结果做相关性判断、结构化摘要、质量标注
  保存 SourceArtifact，metadata 包含 content_ref / content_hash / char_count

Round 5+:
  如果 coverage 仍不足，生成 refined queries；如果达到可用阈值则 stop
```

核心设计仍然不变：**Collector 不直接调用网络库，它只发 `ToolCall`；ToolRuntime 和 Harness 负责执行、记录、报错、写 journal。**

---

## 3. 为什么要有 research plan

竞品分析不是“搜公司名”。优秀 Collector 至少要尝试这些方向：

- 本产品：官方信息、功能、价格、定位、使用场景、限制；
- 竞品：同样的功能/价格/定位/场景/限制；
- 对比：商业模式、市场份额、用户画像、行业报告、增长数据；
- 用户问题：把用户写的“受众群体、市场份额、产品能力”等问题拆成查询维度。

所以代码会把 question 归一化成动态证据需求，而不是固定二维矩阵。需求会保留自然语言问题，也会标注一些可检索维度，例如：

```text
受众群体 -> audience
市场份额 -> market_share
价格/收费 -> pricing
功能/能力 -> features
性能/吞吐/延迟 -> performance
```

当场景像在线阅读/小说平台时，还会补充更贴近行业的 query，例如：

```text
"番茄小说 MAU 月活 用户画像"
"起点阅读 市场份额 QuestMobile"
"免费阅读 付费阅读 商业模式 对比"
"阅文集团 起点阅读 用户规模 年报"
```

这些需求在 prompt context 中会以 `evidence_needs` 的形式出现，每个 item
记录 subject、need、why、status、source_ids。状态不是简单的有/无：

- `covered`：有质量可用的 source 支撑；
- `weak`：有匹配 source，但内容是 JS 壳页、低分或证据薄；
- `missing`：还没有匹配 source。

---

## 4. URL 质量评分

搜索引擎经常返回下载站、应用商店、论坛水帖。Collector 现在会给候选 URL 打分：

- 更高分：官方站、投资者关系、年报、行业报告、数据平台、可信媒体；
- 中等分：产品文档、帮助中心、公司博客；
- 更低分：应用商店、下载站、内容农场、泛论坛。

评分不会阻止抓取所有信息，但会影响优先级，让有限 fetch 预算先用在更可能产出证据的页面上。

---

## 5. SourceArtifact 不再只是摘要

fetch 后的完整清洗文本会被持久化到 workspace content store。Source 里保存：

```json
{
  "title": "番茄小说用户规模报告",
  "snippet": "用于表格和快速预览的摘要",
  "metadata": {
    "content_ref": "file:.competitive-intel/content/...",
    "content_hash": "...",
    "char_count": 18234,
    "covered_dimensions": ["audience", "market_share"],
    "extract_quality": "good",
    "source_score": 8.5
  }
}
```

摘要是导航，`content_ref` 才是证据入口。Analyst、Writer、Reviewer 的 prompt context 会根据 `content_ref` 读取 `content_excerpt`，避免只围绕短摘要打转。

---

## 6. Reviewer 驱动的定向补采

如果 Reviewer 认为报告缺少竞品信息，会输出结构化反馈：

```text
issue: missing_source
target_agent: collector
entity: 起点阅读
dimension: market_share
question: 比较番茄小说和起点阅读的用户规模与市场份额
```

ReworkLoop 会把它转换成：

```python
context.metadata["collector_rework_plan"] = [...]
```

Collector 下一轮会优先执行这个 plan，而不是重新跑一遍通用查询。这样闭环才是：

```text
Reviewer gap -> Collector targeted research -> Analyst claims -> Writer report -> Reviewer
```

---

## 7. 诊断输出

journal 和 stderr 会暴露关键动作：

```text
attempted:番茄小说:official
attempted:起点阅读:market_share
targeted_rework_plan
coverage_incomplete
sources_ready
```

这些信号让 dashboard 能解释“Collector 尝试了什么”，即使外部搜索失败，也能看到它做过哪些覆盖动作。

---

## 8. 测试覆盖

关键测试包括：

```text
test_collector_first_round_requests_search_query_from_run_input
test_collector_turns_search_results_into_deduped_fetch_calls
test_collector_saves_fetch_results_as_source_artifacts
test_collector_records_attempted_coverage_signals
test_collector_prioritizes_targeted_rework_plan
test_collector_source_metadata_contains_content_ref
```

fake 模式保持确定性，真实 web 模式通过工具抽象接入，避免测试依赖网络环境。

---

## 面试怎么讲

> Collector 不是简单搜关键词。它先根据用户问题和竞品列表生成 coverage plan，覆盖本产品、竞品和对比维度；搜索结果会做 URL quality scoring，fetch 后完整清洗文本会持久化为 content_ref，摘要只用于预览。Reviewer 如果发现缺少某个竞品或维度，ReworkLoop 会把反馈变成定向 research plan，Collector 下一轮优先补这个缺口。这让信息采集从“随机搜索”变成可审计、可返工的证据工程。
