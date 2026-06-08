# 学习文档 30：Demo and Operator Polish

## 一句话概括

模块 30 的目标是让一个新 reviewer 能在 10 分钟内 clone、运行、理解和评估这个项目。

## 为什么需要它

编码完成了不代表项目"可交付"。很多优秀的工程在 GitHub 上长期沉寂，因为第一次接触的人不知道从哪开始。模块 30 解决的是：

- **Quickstart 的可执行性**：README 里的命令必须能直接 copy-paste 运行。
- **Demo 脚本**：一个命令跑通全流程，验证环境正确。
- **Troubleshooting**：常见问题有现成答案，不用自己搜。

## 做了什么

### 1. README 更新
- Quickstart 小节：venv 和 PYTHONPATH 两种方式。
- 新增 CLI 命令文档：`export`、`golden`、`web`。
- 项目结构从 planned 更新为 actual。
- 项目状态更新为 V1。

### 2. Demo 脚本 (`scripts/demo.sh`)
端到端演示，覆盖 6 个步骤：
1. fake pipeline run（带 dashboard 和 output）
2. 列出 workspace 中的 runs
3. 终端 dashboard
4. JSON 格式导出
5. HTML 格式导出
6. Golden suite 回归

### 3. Troubleshooting 文档 (`docs/troubleshooting.md`)
覆盖：
- Homebrew Python SSL 证书问题
- 可编辑安装失败的替代方案（PYTHONPATH）
- Web dashboard 端口冲突
- Workspace 为空的原因
- Golden suite 失败怎么定位

## 面试怎么讲

可以说：

> 我理解一个项目的 README 是文档的第一入口。README 里的 quickstart 命令我保证可以直接 copy-paste 跑通。`scripts/demo.sh` 是一条命令跑完 pipeline→dashboard→export→golden suite 全流程。troubleshooting 覆盖了 macOS 上常见的 Homebrew Python 和证书问题——这是我做 Agent Infra 时实际遇到的，提前写好了。

## 后续扩展

- asciinema 录屏嵌入 README。
- CI badge（GitHub Actions golden replay status）。
- 发布到 PyPI。
