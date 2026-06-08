# 学习文档 28：Report Export Package

## 一句话概括

模块 28 把一次 run 的全部产物（报告、sources、claims、reviewer feedback、provenance graph）打包为 markdown / JSON / HTML 三种格式的完整报告包。

## 为什么需要它

termina dashboard 能做运行中检查，但对外交付需要一份可以离开终端阅读的报告。模块 28 解决的是：

- **分享**：把报告发给非开发者，不需要他们会跑 CLI。
- **审计**：evidence index 和 provenance appendix 让每一条结论都有迹可循。
- **归档**：JSON 格式包含完整数据，可以作为 CI artifact 或数据分析来源。

## 关键代码

- `src/competitive_intel_agents/export/__init__.py`
  - `ReportExporter` — 从 ArtifactStore + JournalStore 读取，生成三种格式的报告。
  - `export_run()` — 便利函数，一次调用拿到格式化输出。
  - `ExportError` — 报告不存在、journal events 缺失等问题的结构化错误。

### 三种格式

| 格式 | 用途 |
|---|---|
| `markdown` | 人类阅读，带 evidence index、sources 列表、reviewer feedback、provenance appendix |
| `json` | 机器处理，包含 report/sources/claims/feedback/provenance 全部结构化数据 |
| `html` | 浏览器阅读，自包含的单文件 HTML 页面 |

### CLI 集成

```bash
competitive-intel export --run-id <id> --format markdown --output report.md
competitive-intel export --run-id <id> --format json --output report.json
competitive-intel export --run-id <id> --format html --output report.html
```

不指定 `--output` 则打印到 stdout。

## 面试怎么讲

可以说：

> 导出不是简单地 dump 一份 markdown。Export 模块会读取 artifact store、journal store 和 provenance graph，把 sources→claims→report 的证据链一起打包进最终输出。这意味着交付给别人看的报告，每一段分析都可以追溯到具体的 source id 和 journal event。这在企业场景里很重要，因为竞品分析报告需要经得起法务和产品团队的审查。

## 后续扩展

- PDF 渲染（通过 markdown→PDF 管线）。
- 导出包中嵌入 golden replay 指标。
- 批量导出多个 run。
- 自定义 section 排序和排版。
