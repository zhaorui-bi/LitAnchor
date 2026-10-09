# 📑 LitAnchor — 零按量付费的文献数据提参技能（ZCode 版）

> **Structured, page-traceable data extraction from PDF papers** — text anchoring, selective visual reading, and three-level hard validation, at zero metered API cost.

[![CI](https://github.com/zhaorui-bi/LitAnchor/actions/workflows/ci.yml/badge.svg)](https://github.com/zhaorui-bi/LitAnchor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python ≥3.9](https://img.shields.io/badge/python-%E2%89%A53.9-blue.svg)](https://www.python.org/)
[![ZCode Skill](https://img.shields.io/badge/ZCode-Skill-7C3AED.svg)](./SKILL.md)

[LitExtract](https://github.com/Water-Quality-Risk-Control-Engineering/paper-param-extractor) 的 **ZCode 原生版 —— LitAnchor**（项目名 LitAnchor，技能名保持 `lit-extract`）：把原 OpenClaw + DashScope 流水线搬进 ZCode 会话，Stage 0 / Stage 3 用本地脚本，视觉精读走 Z.ai 内置视觉工具，提参在会话内完成——**按量 API 费用 ¥0**，面向 ZCode 订阅用户。沿用同一套 **文本锚定 + 视觉精读 + 三级硬校验** 混合架构，输出带页码级溯源的结构化 JSON。

> 从原 OpenClaw+DashScope 版迁移过来？直接看 [docs/MIGRATION.md](./docs/MIGRATION.md)。

## 目录

- [Quick Start（三步）](#-quick-start)
- [核心能力](#-核心能力)
- [成本与架构对比](#-成本与架构对比)
- [输出格式](#-输出格式)
- [使用教程](#-使用教程)
- [真实验证](#-真实验证)
- [常见问题](#-常见问题)
- [项目结构](#-项目结构)
- [文档索引](#-文档索引)
- [参与贡献（Contributing）](#-参与贡献contributing)
- [引用（Citation）](#-引用citation)
- [许可证（License）](#-许可证license)
- [致谢](#-致谢)
- [发布前 Checklist](#-发布前-checklist)

## 🚀 Quick Start

### 第 1 步 · 安装

前置要求：

- **ZCode 订阅会话**（需 Read 工具；建议配备内置视觉精读工具 `analyze_image`，缺失时自动降级为纯文本模式，见[使用教程 · 降级模式](#-使用教程)）
- **Python ≥3.9** + PyMuPDF（`pip install pymupdf`；校验脚本纯标准库、零依赖）
- 无需 Node.js、无需 OpenClaw、无需 DashScope API Key

```bash
# 在本包根目录执行：复制 SKILL.md + 两个脚本到 ~/.zcode/skills/lit-extract/
# （旧版自动备份为 lit-extract.bak.<日期>；无交互、无网络请求、无凭据）
bash install.sh

# 卸载
bash install.sh --uninstall
```

手动安装：把 `SKILL.md`、`scripts/stage0_anchor.py`、`scripts/validate.py` 三个文件按相同目录结构复制到 `~/.zcode/skills/lit-extract/` 即可。

### 第 2 步 · 自测

```bash
python3 tests/selftest.py
```

零 API、无凭据；生成合成 6 页 PDF 验证分页/锚点/PNG 渲染，构造记录验证三级校验的删除与标记逻辑，退出码 0 = 全部通过（编写本文档时实测 17/17 PASS；CI 同样以 `py_compile` + selftest 把关，见 `.github/workflows/ci.yml`）。另有可选的真实论文回归项：设置环境变量 `LIT_EXTRACT_SELFTEST_PDF=/path/to/andersson_main.pdf`、或把该 PDF 复制为包内 `tests/andersson_main.pdf`（`.gitignore` 已忽略）即自动加测，缺失则跳过、不算失败。

### 第 3 步 · 首次使用

安装并自测通过后，在 ZCode 会话里直接说需求即可触发技能（命中"提参 / 提取参数 / 文献数据提取"等关键词或提供 PDF 路径）：

```
帮我从 ~/papers/Andersson2026.pdf 中提取所有 PFAS 吸附去除数据：
- removal_rate_percent: 去除率(%)
- adsorption_capacity_mg_g: 吸附容量(mg/g)
```

技能将依次执行 Stage 0（锚定+分页）→ Stage 1（data_page 视觉精读）→ Stage 2（会话内合并提参）→ Stage 3（三级硬校验），交付 `<PDF>_result_validated.json`。完整场景（多文献对比、ADRMATS 测试集、缓存复用等）见[使用教程](#-使用教程)。

## 🎯 核心能力

| 能力 | 说明 | 与原版对应 |
|------|------|-----------|
| **PDF 文本锚定** | 本地脚本 `stage0_anchor.py` 提取文本层，标题/DOI/作者/关键词作为不可幻觉锚点，全程绑定 | 同原版（原为 `preprocess.py` 的 Stage 0 段） |
| **选择性视觉精读** | 仅对含图表页（data_page）精读：Read 读 PNG → 内置 `analyze_image`；跳过参考文献、晶体学数据页 | 原版 qwen3.6-plus VL → 本版 Z.ai 内置视觉工具 |
| **约束驱动提参** | 用户定义键值结构 + 筛选条件，由当前会话模型按约束精确提取 | 原版 DashScope 文本模式调用 → 本版会话内完成 |
| **三级硬校验** | Level 1 元数据一致性 → Level 2 实体存在性 → Level 3 数值回溯，本地脚本秒级执行，杜绝幻觉数据 | 同原版（本版 `validate.py` 纯标准库、零依赖） |
| **溯源标记** | 每个值标注 `Page N, Table X` 级来源；五级质量标记 reliable / needs_review / suspicious / inferred / unavailable | 原版三级质量标记 → 本版五级（新增 inferred / unavailable） |
| **多文献对比** | 逐篇独立执行完整校验流水线，合并为带 `paper_id` 的统一 JSON | 同原版 |
| **ADRMATS 测试集 Profile** | 一键构建评估智能体测试集：`visible_input` + `hidden_oracle_label` + `source_trace` 三段式记录（SKILL.md §11） | 对应原版 skill 的 ADRMATS profile |

## 💰 成本与架构对比

| 对比项 | 原版 OpenClaw + DashScope | ZCode 版 |
|--------|--------------------------|----------|
| 视觉精读（Stage 1） | DashScope qwen3.6-plus VL，按量计费 | Z.ai 内置视觉工具（订阅内） |
| 约束提参（Stage 2） | DashScope qwen3.6-plus，按量计费 | 当前会话模型，会话内完成 |
| 文本锚定 / 硬校验（Stage 0/3） | 本地脚本 | 本地脚本（不变） |
| **单篇按量费用** | **约 ¥0.50-0.80**（84 页含 SI 论文实测口径） | **¥0**（内置工具计费口径以 Z.ai 账单为准） |
| API Key / 网关配置 | `DASHSCOPE_API_KEY` + `openclaw.json` + OpenClaw Gateway | 无需配置 |
| 入口 | WebUI / TUI / CLI（`http://127.0.0.1:18789`） | ZCode 会话对话，直接说需求 |

### 流水线架构（四阶段）

```
PDF 文件
  │
  ├─ [Stage 0] 文本锚定与智能分页 —— 本地脚本 stage0_anchor.py（秒级，零 API）
  │    ├─ 元数据锚点：标题 / DOI / 作者 / 关键词（不可覆盖）
  │    ├─ 智能分页：data_page / text_page / skip_page
  │    └─ data_page 渲染 PNG → <PDF>_pages/page_00N.png
  │
  ├─ [Stage 1] 选择性视觉精读（仅 data_page）—— ZCode 会话通道
  │    ├─ Read 工具读取 PNG → 获得图片 URL
  │    └─ 内置 analyze_image 视觉精读 → 每页 Markdown 转录（并发 ≤3）
  │
  ├─ [Stage 2] 合并 + 约束提参 —— 当前会话模型（零外部 API）
  │    ├─ 文本页用 stage0 文本、数据页用视觉转录，按页码合并
  │    └─ 注入元数据锚点 + 用户约束 → 结构化 JSON
  │
  └─ [Stage 3] 三级硬校验 —— 本地脚本 validate.py（秒级，零 API）
       ├─ Level 1 元数据一致性 / Level 2 实体存在性 / Level 3 数值回溯
       └─ 输出 <result>_validated.json（溯源 + 质量标记 + 校验报告）
```

## 📊 输出格式

提取结果为标准 JSON：`extraction_meta`（锚点绑定元数据）+ `field_definitions`（用户字段）+ `data[]`（每条记录含 `_source` 页码级溯源与 `_quality` 五级质量标记）+ `validation_report`（三级校验报告）+ `extraction_notes`。完整 schema 与字段级溯源规则见 [`SKILL.md`](./SKILL.md) §5；ADRMATS Profile 的三段式 schema 见 §11.6。

## 📖 使用教程

### 场景 1：单篇论文提参

```
帮我从 ~/papers/Andersson2026.pdf 中提取所有 PFAS 吸附去除数据：

提取字段：
- material_type: 吸附剂类型
- target_pollutant: 目标PFAS
- removal_rate_percent: 去除率(%)
- adsorption_capacity_mg_g: 吸附容量(mg/g)
- binding_thermodynamics: 结合热力学参数

约束：每种 PFAS 一条记录，包含水质信息。
```

技能会依次执行 Stage 0（锚定+分页）→ Stage 1（data_page 视觉精读）→ Stage 2（会话内合并提参）→ Stage 3（三级硬校验），最终交付 `<PDF>_result_validated.json`——每个值带 `_source` 页码溯源与 `_quality` 质量标记。

### 场景 2：多文献对比提参

```
从这三篇论文中提取 MOF 材料性能对比数据：
1. ~/papers/Li2025.pdf
2. ~/papers/Wang2024.pdf
3. ~/papers/Zhang2026.pdf

提取字段：
- material_name: 材料名称
- BET_surface_area: 比表面积(m²/g)
- CO2_uptake: CO₂吸附量(mmol/g)
```

每篇独立执行完整 Stage 0–3 校验流水线，最后合并为带 `paper_id` 的统一 JSON。多篇可并行处理，但所有会话/子代理合计的视觉精读在途并发仍受 ≤3 约束。

### 场景 3：构建 ADRMATS 评估智能体测试集

```
我要为 ADRMATS 评估智能体构建测试集，请从 ~/papers/ 的 PDF 中按 high/low/noise
三级提取，输出 visible_input + hidden_oracle_label。噪声样本占 10%，低质量占 20%，
高质量占 70%。
```

激活 ADRMATS Profile（SKILL.md §11）：按"材料 × 污染物 × 水质 × 实验类型"最小粒度拆分记录，输出 `visible_input`（constraint_context + merged_proposals）+ `hidden_oracle_label`（quality_tier / noise_type 等，不随可见输入下发）+ `source_trace` 三段式；三级硬校验照常执行。

### 缓存复用

`<PDF>_stage0.json` + `<PDF>_pages/` PNG 目录是缓存单元：两者齐备且 PNG 数与 `data_page_nums` 一致时**不会重跑** Stage 0。同一会话对同一 PDF 换一批字段重新提参，只重跑 Stage 2–3。注意：用 `--dpi 300` 重渲染时必须同时 `-o` 指定新的 stage0 JSON 输出路径，否则默认路径会覆盖原缓存。

### 主文 + SI 合并（推荐）

同一论文的补充材料建议先用 PyMuPDF 合并成单一 PDF 再提参（核心 3 行）：

```python
import pymupdf
out = pymupdf.open()
for p in ("main.pdf", "SI.pdf"):    # 主文在前，保证页码顺序
    out.insert_pdf(pymupdf.open(p))
out.save("merged.pdf")
```

合并后页码连续，SI 中的数值可正常回溯校验。实测对照（Andersson 2026）：仅跑 10 页主文时，85 项只在 74 页 SI 中才有的数据全部只能置 `null`。

### 降级模式（无视觉工具时）

会话中 `analyze_image` 不可用时自动退回纯文本层模式：文本层可查的数值正常提取（校验后 `reliable`）；仅存在于图表中的数值置 `null`（校验后 `unavailable`），`_source` 保留页码并写明未读取原因，`extraction_notes` 声明精度风险。纯扫描 PDF（无文本层）且视觉工具同时不可用时，流水线终止并明确告知，不产出无基准的结果。

## ✅ 真实验证

**Andersson 2026**（*Angew. Chem. Int. Ed.* 2026, DOI 10.1002/anie.202526027，10 页主文）端到端实测，并与原 OpenClaw+DashScope 版期望结果逐项对照（详见 [`docs/verification-andersson-2026.md`](./docs/verification-andersson-2026.md)；两版结果文件随包发布在 [`examples/`](./examples/)，可独立复算）：

| 验证项 | 结果 |
|--------|------|
| 主文可核对条目 | **39/39 项与原工具期望结果一致**（BET/孔容/七种 PFAS 计量比/ITC ΔH/log K/容量/去除率/CCDC 号等） |
| 三级校验 | **0 条幻觉删除**；Level 3 计数 **34 reliable / 7 unavailable**，与逐记录复核完全吻合 |
| 期望文件自身问题 | 对照中发现期望结果文件 **2 处 log K 记录与原文矛盾**（PFHxS/PFHpA）——本版按主文原句处理更忠实 |
| 视觉精读 | **6/7 页成功**（第 7 页因视觉工具账户限流由文本层兜底，失败页留痕声明） |
| SI 字段 | SI 未获取，故 **85 项仅 SI 字段未核对**，全部如实置 `null` 并注明原因，无臆测填补 |

## ❓ 常见问题

<details>
<summary><b>怎么计费？真的免费吗？</b></summary>

全程使用 ZCode 订阅：Stage 0/3 是本地脚本，Stage 2 由会话模型完成，Stage 1 走 Z.ai 内置视觉工具——**无任何按量付费 API、无需 DashScope Key，按量费用 ¥0**。内置工具（analyze_image）的具体计费口径以 Z.ai 账单为准。
</details>

<details>
<summary><b>如果 PDF 是扫描版怎么办？</b></summary>

文本层几乎为空（全文 <200 字符）时，改走全页视觉精读，Stage 3 自动跳过 Level 2/3 并在结果中声明需人工复核。若同时没有视觉工具，流水线会终止并告知——不产出无校验基准的结果。建议优先使用带文本层的原生 PDF。
</details>

<details>
<summary><b>和原 OpenClaw 版是什么关系？会冲突吗？</b></summary>

同一方法论的 ZCode 原生实现，**两者可共存**：原版部署在 OpenClaw Gateway（`paper-param-extractor` 仓库），本版只安装到 `~/.zcode/skills/lit-extract/`，互不干扰。已在 Andersson 2026 上做过两版对照：主文可核对 39/39 项一致。从原版迁移见 [docs/MIGRATION.md](./docs/MIGRATION.md)。
</details>

<details>
<summary><b>支持哪些论文？</b></summary>

中英文均可。带文本层的原生 PDF（出版商直接下载版）效果最佳；参考文献、晶体学参数、NMR 峰列表等页面会被智能分页自动跳过；跨页表格由 Stage 2 自动关联拼接。
</details>

## 📁 项目结构

```
LitAnchor/
├── SKILL.md                              # ★ 正式版协议（安装后位于 ~/.zcode/skills/lit-extract/）
├── install.sh                            # 一键安装 / 更新 / 卸载
├── README.md                             # 本文件
├── LICENSE                               # MIT
├── CONTRIBUTING.md                       # 贡献指南
├── CHANGELOG.md                          # 变更日志（Keep a Changelog 风格）
├── CITATION.cff                          # 研究软件引用元数据（CFF 1.2.0）
├── scripts/
│   ├── stage0_anchor.py                  # Stage 0：文本锚定 + 智能分页 + PNG 渲染
│   └── validate.py                       # Stage 3：三级硬校验（纯标准库，秒级）
├── tests/
│   ├── selftest.py                       # 一键自测（零 API、零凭据）
│   ├── make_synthetic_pdf.py             # 自测用合成 PDF 生成器
│   └── _artifacts/                       # 自测产物（.gitignore 已忽略）
├── examples/
│   ├── README.md                         # 案例文件说明（Andersson 2026）
│   ├── andersson_result_validated.json   # ZCode 版端到端结果（三级校验后）
│   └── andersson_expected.json           # 原 OpenClaw+DashScope 版期望结果
├── docs/
│   ├── MIGRATION.md                      # 从 OpenClaw+DashScope 版迁移指南
│   └── verification-andersson-2026.md    # 与原 OpenClaw+DashScope 版的对照评审
└── .github/
    └── workflows/ci.yml                  # CI：py_compile + selftest（Python 3.11）
```

## 📚 文档索引

| 文档 | 内容 |
|------|------|
| [`docs/MIGRATION.md`](./docs/MIGRATION.md) | 从原 OpenClaw+DashScope 版迁移到 ZCode 版的指南 |
| [`docs/verification-andersson-2026.md`](./docs/verification-andersson-2026.md) | Andersson 2026 两版逐项对照评审报告（39/39 主文可核对一致、85 项仅 SI 未核对、期望文件自身 2 处错误） |
| [`examples/README.md`](./examples/README.md) | 案例文件说明：两份结果 JSON 可独立复算对照结论 |

协议主文档为 [`SKILL.md`](./SKILL.md)（流水线协议 §2–§3、输出 schema §5、ADRMATS Profile §11），随技能一并安装。

## 🤝 参与贡献（Contributing）

欢迎 Issue 与 PR。开始前请阅读 [`CONTRIBUTING.md`](./CONTRIBUTING.md)：提交前在仓库根目录运行 `python3 tests/selftest.py` 并确保退出码 0（PR 正文请贴完整输出）；脚本行为变更必须同步更新 `SKILL.md` 对应章节，二者不一致视为缺陷。

## 📝 引用（Citation）

如本项目对你的工作有帮助，请按 [`CITATION.cff`](./CITATION.cff)（CFF 1.2.0，可用 `cffconvert` 校验）引用；如已注册 DOI，可在其中补充 `identifiers`（type: doi）条目。

## 📄 许可证（License）

[MIT License](./LICENSE) — Copyright (c) 2026 Water Quality Risk Control Engineering & contributors。

## 🙏 致谢

基于 [Water-Quality-Risk-Control-Engineering/paper-param-extractor](https://github.com/Water-Quality-Risk-Control-Engineering/paper-param-extractor)（维护者 [Axl1Huang](https://github.com/Axl1Huang)）构建。
