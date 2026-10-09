# 贡献指南（Contributing）

欢迎为 LitAnchor（lit-extract 技能的 ZCode 版）贡献代码、修复与文档改进。开始前请先阅读 [README.md](./README.md) 了解流水线架构，协议级改动还需对照 [SKILL.md](./SKILL.md)。

## 环境准备

- **Python 3.11+**（CI 以 3.11 为准）
- 安装唯一第三方依赖：`pip install pymupdf`（`validate.py` 为纯标准库、零依赖，请保持）
- 无需 Node.js、无需任何 API Key、无需网络
- ZCode 订阅会话仅在做端到端手工验证时需要

## 改动前：先跑自测

任何改动提交前，在仓库根目录运行：

```bash
python3 tests/selftest.py
```

- 退出码 0 = 全部通过；请确保你的改动不破坏现有断言。
- 真实论文回归项（Andersson 标题锚点）在本机提供对应 PDF 时自动加测，缺失则自动跳过（不算失败）——CI 环境没有该 PDF，同样按跳过处理。提供方式二选一：设置环境变量 `LIT_EXTRACT_SELFTEST_PDF=/path/to/andersson_main.pdf`，或把 PDF 复制为包内 `tests/andersson_main.pdf`（已加入 `.gitignore`，版权 PDF 勿提交）。
- 新增功能请同步在 `tests/selftest.py` 补充断言，保持"零 API、零凭据"的自测约束。

## 代码约定

- `scripts/stage0_anchor.py`：仅允许 标准库 + PyMuPDF。
- `scripts/validate.py`：仅允许标准库（纯零依赖是它的卖点，不要引入第三方包）。
- `install.sh`：保持无交互、无网络请求、无凭据，仅操作本包目录与 `~/.zcode/skills/lit-extract/`。
- 脚本行为变更（参数、输出 schema、校验规则）必须同步更新 `SKILL.md` 对应章节，二者不一致视为缺陷。

## PR 规范

1. 标题用一句话概括改动（中英文均可）。
2. 描述中说明动机、实现方式与影响面；涉及行为变更的请引用 `SKILL.md` 章节号。
3. 在 PR 正文贴出 `python3 tests/selftest.py` 的完整输出（含总结行）。
4. 一个 PR 聚焦一件事，避免混合功能与重构。
5. 文档改动（README / docs/）与代码改动可以同 PR，但请在描述中分开列出。

## Issue 说明

- **Bug 报告**请包含：复现步骤、`python3 tests/selftest.py` 输出、涉及的 PDF 情况（出版商/是否扫描版/页数，正文数据可脱敏）、期望行为与实际行为。
- **功能建议**请说明使用场景，以及它与现有四阶段流水线（SKILL.md §2–§3）的关系。
- 仓库后续可在 `.github/ISSUE_TEMPLATE/` 下补充正式的 issue 模板（当前未附，先按上述要素手写）。

## 许可

提交即表示你同意贡献内容以 [MIT License](./LICENSE)（Copyright (c) 2026 Water Quality Risk Control Engineering & contributors）授权发布。
