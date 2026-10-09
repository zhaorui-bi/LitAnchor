# Changelog

本项目所有显著变更都记录在此文件中。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [1.0.0] - 2026-09-29

首个 ZCode 原生版：把原 [OpenClaw + DashScope 版 paper-param-extractor](https://github.com/Water-Quality-Risk-Control-Engineering/paper-param-extractor) 的提参流水线移植进 ZCode 会话，按量 API 费用 ¥0。

### 移植（来自原 OpenClaw + DashScope 版）

- Stage 0 文本锚定独立为 `scripts/stage0_anchor.py`（本地 PyMuPDF，秒级、零 API），沿用标题/DOI/作者/关键词不可幻觉锚点与 data_page / text_page / skip_page 智能分页。
- Stage 3 三级硬校验独立为 `scripts/validate.py`（纯标准库、零依赖；Level 1 元数据一致性 → Level 2 实体存在性 → Level 3 数值回溯）。
- 流水线重构为四阶段：Stage 0 本地脚本 → Stage 1 会话内选择性视觉精读（Read 读 PNG + 内置 `analyze_image`，仅 data_page）→ Stage 2 会话内约束提参 → Stage 3 本地硬校验。
- 消除全部按量付费 API 与配置项：无需 `DASHSCOPE_API_KEY`、`openclaw.json` 与 OpenClaw Gateway（原版实测约 ¥0.50-0.80/篇 → ¥0）。

### 新增

- ZCode 技能加载单元 `SKILL.md` + `install.sh` 一键安装/更新/卸载（安装到 `~/.zcode/skills/lit-extract/`，无交互、无网络请求、无凭据）。
- 质量标记由三级扩展为五级：新增 `inferred`（推断值）与 `unavailable`（不可用，区分"文献未提供"与"视觉未读取"两种成因）。
- 缓存三件套：`<PDF>_stage0.json` + `<PDF>_pages/` PNG 目录 + 可选逐页转录 `page_00N.md`，各自可独立复用。
- 账户级限流兜底策略：并发上限 3；429 时降并发为 1 并指数退避（45s 起步，单页至多约 6 次）；累计退避约 8–10 分钟未恢复则剩余 data_page 转文本层兜底并留痕。
- ADRMATS 评估智能体测试集 profile（SKILL.md §11）：`visible_input` + `hidden_oracle_label` + `source_trace` 三段式记录，`validate.py` 自动识别 `records[]` schema。
- 一键自测 `tests/selftest.py`（零 API、零凭据）：合成 6 页 PDF 全链路回归（分页/锚点/PNG 渲染/三级校验删除与标记逻辑），真实论文标题锚点回归在 PDF 存在时自动加测、缺失则跳过。

### 修复

- 自测真实论文回归输入不再硬编码机器绝对路径：改为环境变量 `LIT_EXTRACT_SELFTEST_PDF` 或包内 `tests/andersson_main.pdf`（`.gitignore` 已忽略）注入，全项目源码无用户机器路径，他机/CI 缺 PDF 时自动跳过。
- 标题锚点修复：两行标题完整拼接，不再截断、不混入作者行/期刊栏行（含真实论文 Andersson 2026 回归测试）。
- 视觉转写错误在合并阶段按文本层统一纠正并留痕（Andersson 2026 实测纠正 8 处，含 PFHxS 1:3 计量比、PFOA log K 4.2 等关键更正）。

### 真实验证

- Andersson 2026（*Angew. Chem. Int. Ed.* 2026, 65, e26027，DOI 10.1002/anie.202526027，10 页主文）端到端对照：主文可核对 **39/39 项与原版期望结果一致**，三级校验 0 条幻觉删除（Level 3 计数 34 reliable / 7 unavailable）；85 项仅 SI 数据如实置 `null`，无臆测填补；并发现期望文件自身 2 处 log K 记录与原文矛盾（PFHxS/PFHpA）。详见 [`docs/verification-andersson-2026.md`](./docs/verification-andersson-2026.md)。

[1.0.0]: https://github.com/zhaorui-bi/LitAnchor/releases/tag/v1.0.0
