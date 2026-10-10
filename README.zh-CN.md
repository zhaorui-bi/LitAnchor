# LitAnchor

[English](README.md) | **简体中文**

> **从 PDF 论文提取结构化、可按页溯源的数据**——文本锚定、选择性视觉精读与三级硬校验，零按量付费 API 成本。

[![CI](https://github.com/zhaorui-bi/LitAnchor/actions/workflows/ci.yml/badge.svg)](https://github.com/zhaorui-bi/LitAnchor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python >=3.9](https://img.shields.io/badge/python-%3E%3D3.9-blue.svg)](https://www.python.org/)
[![ZCode Skill](https://img.shields.io/badge/ZCode-Skill-7C3AED.svg)](./SKILL.md)

LitAnchor 是一个 ZCode skill（技能名：`lit-extract`），用于从 PDF 研究论文中提取结构化、可按页溯源的数据。它专为 ZCode 订阅用户打造：Stage 0 锚定与 Stage 3 校验以本地 Python 脚本运行，Stage 1 视觉精读使用会话内置的视觉工具，Stage 2 提取在会话内完成——因此一次完整提取运行零按量付费 API 成本，也无需任何 API key。

**为什么选择 LitAnchor。** 纯视觉流水线在长文档上会产生幻觉：在下文的实战案例中，视觉层把一个图上的数值读错了几个数量级（kcat/KM 被转录为 “4293 s-1 mM-1”，而论文文本层写的是 0.263 mM-1 s-1）——而每一处这样的误读都被捕获并纠正。LitAnchor 用文本锚定架构来防御这一点：真值元数据（标题/DOI/作者/关键词）与全文由本地脚本从 PDF 文本层硬提取，图表只做选择性视觉精读，三级硬校验器让每个输出值都能溯源到具体的页、表或图。

## 目录

- [快速开始](#-快速开始)
- [工作原理](#-工作原理)
- [成本](#-成本)
- [输出格式](#-输出格式)
- [教程](#-教程)
- [实战案例：VenusMine (Nature Communications 2025)](#-实战案例venusmine-nature-communications-2025)
- [FAQ](#-faq)
- [项目结构](#-项目结构)
- [文档索引](#-文档索引)
- [参与贡献](#-参与贡献)
- [引用](#-引用)
- [许可证](#-许可证)

## 🚀 快速开始

### 第 1 步 · 安装

前置条件：

- 一个 **ZCode 订阅会话**（必须要有 Read 工具；推荐使用内置视觉工具 `analyze_image`——没有它时技能会优雅降级，见[降级模式](#-教程)）
- **Python >=3.9** 并装有 PyMuPDF（`pip install pymupdf`；校验脚本为纯标准库，零依赖）
- 无需 Node.js，无需任何类型的 API key

```bash
# 在包根目录运行: 会把 SKILL.md + scripts/stage0_anchor.py + scripts/validate.py
# 复制到 ~/.zcode/skills/lit-extract/ (已有的旧安装会自动备份;
# 无交互, 无网络请求, 无凭证)
bash install.sh

# 卸载
bash install.sh --uninstall
```

手动安装：将 `SKILL.md`、`scripts/stage0_anchor.py` 与 `scripts/validate.py` 复制到 `~/.zcode/skills/lit-extract/`，并保持目录结构不变。

### 第 2 步 · 自检

```bash
python3 tests/selftest.py
```

零 API、零凭证：它会生成一个合成的 6 页 PDF，并验证锚定、页面分类、PNG 渲染与校验逻辑。截至撰写时，**14/14 项检查 PASS**（退出码 0 = 通过）。其中一个可选的真实论文回归测试在 PDF 缺失时会被跳过——注意是跳过而非失败；可通过环境变量 `LIT_EXTRACT_SELFTEST_PDF=/path/to.pdf` 启用，或把该 PDF 放到 `tests/selftest.py` 中指名的路径。CI（GitHub Actions，`.github/workflows/ci.yml`）在 Python 3.11 上运行 `py_compile` 加自检。

### 第 3 步 · 首次使用

在 ZCode 会话里，直接提出从某个 PDF 提取数据即可（或直接调用该技能）。字段键、值类型与约束由你提供：

```
从 ~/papers/VenusMine.pdf 提取 PET 水解酶表征数据:
- enzyme_name: PET 水解酶名称
- source_organism: 来源生物体或宏基因组
- optimal_temperature_C: 最适催化温度 (°C)
- Tm_C: DSF 法测定的熔解温度 (°C)
- activity_vs_IsPETase_fold: PET 膜降解活性相对 IsPETase 的倍数 (fold)
- Km_mM_pNPB / kcat_s_minus1_pNPB / kcat_Km_pNPB: 基于 pNPB 的 Michaelis-Menten 动力学
约束: 论文中每表征一种酶, 输出一条记录.
```

技能会依次运行 Stage 0（锚定 + 页面分类）→ Stage 1（仅对数据页做视觉精读）→ Stage 2（会话内合并 + 约束驱动提取）→ Stage 3（三级硬校验），交付 `<PDF>_result_validated.json`。完整的场景目录（多论文对比、ADRMATS 测试集、缓存复用等）见[教程](#-教程)。

## 🧭 工作原理

```
PDF 文件
  |
  +-- [Stage 0] 文本锚定 + 智能页面分类 -- 本地脚本 stage0_anchor.py (秒级, 零 API)
  |     |-- 元数据锚点: 标题 / DOI / 作者 / 关键词 (不可幻觉, 从 PDF 文本层硬提取,
  |     |   绑定到后续每一个阶段)
  |     |-- 智能页面分类: data_page / text_page / skip_page
  |     |   (参考文献 / 晶体学 / NMR 峰列表页会被跳过)
  |     |-- 全文存入 stage0 JSON (校验基线)
  |     +-- 数据页按 150 DPI 渲染为 PNG -> <PDF>_pages/page_00N.png
  |
  +-- [Stage 1] 选择性视觉精读 (仅数据页) -- ZCode 会话通道
  |     |-- Read 工具加载页面 PNG (页面清单必须来自 stage0 JSON 的 data_page_nums)
  |     +-- 内置 analyze_image 配合防幻觉转录提示词
  |         (并发上限 3, 限速自动退避)
  |
  +-- [Stage 2] 合并 + 约束驱动提取 -- 会话内完成, 零外部 API
  |     |-- 文本页取自 stage0 文本, 数据页取自视觉转录,
  |     |   按页码顺序合并并注入元数据锚点
  |     +-- 会话模型 + 你的字段键/类型/约束 -> 结构化 JSON
  |
  +-- [Stage 3] 三级硬校验 -- 本地脚本 validate.py (纯标准库, 秒级)
        |-- 第 1 级: 元数据一致性 (标题/DOI/作者 vs 锚点)
        |-- 第 2 级: 实体存在性 (实体名称从未在论文中出现的记录会被删除)
        |-- 第 3 级: 数值回溯 (数值必须能在文本层中找到, ±1%)
        +-- 输出 <PDF>_result_validated.json (溯源 + 质量分级 + 校验报告)
```

| 能力 | 作用 |
|------|------|
| **PDF 文本锚定** | 本地脚本 `stage0_anchor.py` 提取文本层；标题/DOI/作者/关键词成为不可幻觉的锚点，绑定贯穿整个运行 |
| **选择性视觉精读** | 只对图表页（data_page）做视觉精读——先用 Read 读入 PNG，再由内置 `analyze_image` 配合防幻觉转录提示词处理；参考文献、晶体学与 NMR 页面直接跳过 |
| **约束驱动提取** | 由你定义字段键、值类型与约束；会话模型在按页码顺序合并文本层与视觉层后，依据它们进行提取 |
| **三级硬校验** | 本地脚本 `validate.py`（纯标准库，秒级）：第 1 级元数据一致性 → 第 2 级实体存在性 → 第 3 级数值回溯（±1% 以内） |
| **溯源 + 五级质量分级** | 每个提取值都带 `_source` 溯源（页码、表/图编号）与一个 `_quality` 分级：`reliable` / `needs_review` / `suspicious` / `inferred` / `unavailable` |
| **多论文对比** | 每篇论文独立运行完整流水线；结果合并为一个带 `paper_id` 的 JSON |
| **ADRMATS 测试集画像** | 以 `visible_input` + `hidden_oracle_label` + `source_trace` 记录构建评估智能体测试集（[SKILL.md](./SKILL.md) §11） |

## 💰 成本

一切都在 ZCode 订阅内或以本地脚本运行。Stage 0 锚定与 Stage 3 校验是本地 Python 脚本（秒级、无网络）；Stage 1 使用会话内置的视觉工具；Stage 2 由会话模型自身完成。不存在任何按量付费 API，也无需配置任何 API key。

## 📊 输出格式

交付物是单个 JSON 信封：`extraction_meta`（锚点绑定的元数据）+ `field_definitions`（你的字段定义）+ `data[]`（每条记录的每个值都带 `_source` 页级溯源与 `_quality` 分级）+ `validation_report` + `extraction_notes`。完整模式与字段级溯源规则见 [SKILL.md](./SKILL.md) §5；ADRMATS 三段式模式见 §11.6。

以下是实战案例中一条裁剪后的记录（见[下文](#-实战案例venusmine-nature-communications-2025)）：

```json
{
  "enzyme_name": "KbPETase (APET-14)",
  "source_organism": "Kibdelosporangium banguiense",
  "optimal_temperature_C": 50,
  "Tm_C": 80.1,
  "Km_mM_pNPB": 1.04,
  "kcat_s_minus1_pNPB": 0.27,
  "kcat_Km_pNPB": 0.263,
  "_source": {
    "Tm_C": "Page 3, upper bound of the DSF Tm range 36.4-80.1 °C (Fig. 2b) plus the stated '+32.4 °C over IsPETase'",
    "Km_mM_pNPB": "Page 6, Table 1, row KbPETase"
  },
  "_quality": { "Tm_C": "reliable", "Km_mM_pNPB": "reliable" }
}
```

## 📖 教程

### 1. 单篇论文提取

给出 PDF 路径和字段定义；可选的约束与输出粒度可进一步收敛返回结果。

```
从 ~/papers/VenusMine.pdf 提取 PET 水解酶表征数据:
- enzyme_name: PET 水解酶名称
- source_organism: 来源生物体或宏基因组
- optimal_temperature_C: 最适催化温度 (°C)
- Tm_C: DSF 法测定的熔解温度 (°C)
- activity_vs_IsPETase_fold: PET 膜降解活性相对 IsPETase 的倍数 (fold)
- Km_mM_pNPB / kcat_s_minus1_pNPB / kcat_Km_pNPB: 基于 pNPB 的 Michaelis-Menten 动力学
约束: 论文中每表征一种酶, 输出一条记录.
```

针对这条提示词，技能在这份 12 页 PDF 上跑完了完整流水线：7 个数据页做了视觉精读，4 个文本页取自文本层，1 页被跳过；校验后的结果包含 4 条酶记录（KbPETase、IsPETase、LCC、FastPETase）——每个值都带页级 `_source` 溯源与 `_quality` 分级。完整数字见[实战案例](#-实战案例venusmine-nature-communications-2025)。

### 2. 多论文对比

```
对比以下 PDF 的 Michaelis-Menten 动力学并合并为一个 JSON:
1. ~/papers/VenusMine.pdf
2. ~/papers/enzyme_screen_2025.pdf
3. ~/papers/kinetics_review_2024.pdf

字段:
- enzyme_name: 酶名称
- Km_mM: 米氏常数 (mM)
- kcat_s_minus1: 转换数 (1/s)
- temperature_C: 测定温度 (°C)
```

每篇论文独立运行完整的 Stage 0-3 流水线，各论文校验后的结果合并为一个带 `paper_id` 索引的 JSON。可以在多个并行会话中处理论文，但所有会话加总后，同时进行中的视觉精读总数必须保持不超过 3（共享的视觉工具配额是账号级的）。

### 3. ADRMATS 评估智能体测试集画像

```
用 ~/papers/ 中的 PDF 为 ADRMATS 评估智能体构建测试集.
按质量分级拆分记录: 70% high, 20% low, 10% noise.
每条记录输出 visible_input (constraint_context + merged_proposals),
另出一份独立的 hidden_oracle_label (quality_tier 等),
并为每个值给出 source_trace.
```

这会激活 ADRMATS 画像（[SKILL.md](./SKILL.md) §11）：记录按材料、污染物与条件做细粒度拆分，采用三段式模式 `visible_input`（`constraint_context` + `merged_proposals`）+ `hidden_oracle_label`（质量分级 `high`/`low`/`noise` 及相关字段，绝不随可见输入一同分发）+ `source_trace`。文本锚定与三级硬校验照常运行。

### 4. 缓存复用

`<PDF>_stage0.json` 加 `<PDF>_pages/` PNG 目录构成 Stage 0 的缓存单元：两者都存在、且 PNG 数量与 stage0 JSON 的 `data_page_nums` 一致时，Stage 0 **不会重跑**。同一会话中换一组字段对同一份 PDF 重新提取时，会复用缓存，只重跑 Stage 2-3。注意：以更高分辨率重渲染（`--dpi 300`）时，必须让 `-o` 指向一个新的 stage0 JSON 路径——否则默认输出路径会被覆盖，原有缓存随之丢失。

### 5. 合并正文 + SI（推荐）

若论文的补充信息（SI）含有数据，提取前先把正文与 SI 合并为单个 PDF（核心 3 行）：

```python
import pymupdf
out = pymupdf.open()
for p in ("main.pdf", "SI.pdf"):    # 先放正文, 保持页码连续
    out.insert_pdf(pymupdf.open(p))
out.save("merged.pdf")
```

页码连续后，`_source` 页级溯源与第 3 级数值回溯基线保持在同一坐标系中，只出现在 SI 里的值也能正常提取和校验。

### 6. 降级模式

当会话没有视觉工具时，流水线降级为只用文本层：文本层中存在的值照常提取（校验为 `reliable`），只存在于图中的值变为 `null`/`unavailable` 并附如实的说明——`_source` 保留页码并说明该值为何未被读取，`extraction_notes` 声明精度风险。既没有文本层**又**没有视觉工具的扫描版 PDF，会以明确的报错中止，而不是产出无锚定的结果。

## ✅ 实战案例：VenusMine (Nature Communications 2025)

**论文**：Wu, B., Zhong, B., Zheng, L., Huang, R., Jiang, S., Li, M., Hong, L. & Tan, P. "Harnessing protein language model for structure-based discovery of highly efficient and robust PET hydrolases." *Nature Communications* (2025) 16:6211, DOI [10.1038/s41467-025-61599-z](https://doi.org/10.1038/s41467-025-61599-z)。

该论文提出了 VenusMine——一条基于结构的酶发现流水线，组合 FoldSeek（结构检索）、MMseqs2（序列检索）、ProstT5 蛋白质语言模型嵌入与一棵表示树，用于挖掘 PET 水解酶。34 个候选进入湿实验验证，其中 26 个得到表达和纯化，14 个在 30-60 °C 范围内表现出 PET 降解活性——这 14 个中有 11 个与 IsPETase 相当——DSF 熔解温度范围为 36.4-80.1 °C。明星结果是 KbPETase（候选 APET-14，来自 *Kibdelosporangium banguiense*，GenBank WP_209642273.1）：活性为 IsPETase 的 97 倍（在 50 °C，对比 IsPETase 的 30 °C），Tm 比 IsPETase 高 +32.4 °C（约 80.1 °C），50 °C 下为 LCC 的 5.7 倍、在 LCC 最适的 65 °C 下为其 1.47 倍，相对 LCC 的 kcat 为 1.5 倍、kcat/KM 为 1.3 倍，并解析了 1.75 Å 分辨率的 X 射线结构（PDB 9IW9）。pNPB 动力学（Table 1）：KbPETase Km 1.04 mM / kcat 0.270 s-1 / kcat/KM 0.263 mM-1 s-1；FastPETase 1.57 / 0.215 / 0.141；LCC 1.053 / 0.186 / 0.208。

**LitAnchor 在这份 PDF 上的运行：**

| 项目 | 结果 |
|------|------|
| 页面分类 | 12 页 → 7 个数据页 / 4 个文本页 / 1 页跳过 |
| 数据页视觉精读 | 7/7（并发 <= 3，零限速失败） |
| 产出记录（Stage 2） | 4 条酶记录：KbPETase、IsPETase、LCC、FastPETase |
| 第 3 级结果（Stage 3） | 15 个 reliable 值、17 个如实置空的 unavailable 值、0 个 suspicious |
| 被校验删除的记录 | 0 |

**这次运行展示的两处纠正：**

1. **对照文本层纠正视觉误读。** 视觉转录误读了图上的数值——kcat/KM 被读成 “4293 s-1 mM-1”，候选数量被读成 “top 54 sequences”，而文本层写的是 0.263 mM-1 s-1 与 “top 34”。每个被引用的数字都在合并阶段对照文本层得到了纠正。
2. **锚点异常如实披露，原文优先。** 标题锚点启发式在这份双栏排版上抓到了一行摘要；协议的“原文优先”规则恢复了逐字的标题，这一插曲也在结果的 `anchor_note` 中如实披露。

完整的校验结果随仓库一同发布：[`examples/venusmine_result_validated.json`](./examples/venusmine_result_validated.json)，配套导读见 [`examples/README.md`](./examples/README.md)。

## ❓ FAQ

<details>
<summary><b>如何计费？真的是零按量付费吗？</b></summary>

一切都在 ZCode 订阅内或以本地脚本运行：Stage 0 与 Stage 3 是本地 Python 脚本，Stage 2 由会话模型完成，Stage 1 走会话内置的视觉工具。不存在任何按量付费 API，也没有 API key。
</details>

<details>
<summary><b>如果 PDF 是扫描件怎么办？</b></summary>

当文本层几乎为空时，流水线切换为整页视觉精读，Stage 3 跳过第 2/3 级检查，并把结果标记为需人工复核。如果此时也没有视觉工具，流水线会以明确的报错中止，而不是在没有任何锚定基线的情况下产出结果。优先使用带文本层的原生 PDF。
</details>

<details>
<summary><b>支持哪些论文？</b></summary>

带文本层的原生 PDF（从出版商下载的原件）效果最好，中英文皆宜。参考文献列表、晶体学表格和 NMR 峰列表页会被智能页面分类器自动跳过。化学之外的领域同样适用——上文的实战案例就是一篇蛋白质工程论文。
</details>

## 📁 项目结构

```
LitAnchor/
├── SKILL.md                              # 协议文档 (安装到 ~/.zcode/skills/lit-extract/)
├── install.sh                            # 一条命令安装 / 更新 / 卸载
├── README.md                             # 英文版 README
├── README.zh-CN.md                       # 本文件（简体中文版）
├── LICENSE                               # MIT
├── CONTRIBUTING.md                       # 贡献指南
├── CHANGELOG.md                          # 更新日志
├── CITATION.cff                          # 引用元数据 (CFF 1.2.0)
├── scripts/
│   ├── stage0_anchor.py                  # Stage 0: 文本锚定 + 页面分类 + PNG 渲染
│   └── validate.py                       # Stage 3: 三级硬校验 (纯标准库, 秒级)
├── tests/
│   ├── selftest.py                       # 一条命令自检 (零 API, 零凭证)
│   ├── make_synthetic_pdf.py             # 为自检生成合成 PDF
│   └── _artifacts/                       # 自检产物 (已 gitignore)
├── examples/
│   ├── README.md                         # 示例文件导读
│   └── venusmine_result_validated.json   # 实战案例: 端到端校验后的结果
├── docs/                                 # 归档笔记
└── .github/
    └── workflows/ci.yml                  # CI: py_compile + selftest (Python 3.11)
```

## 📚 文档索引

| 文档 | 内容 |
|------|------|
| [`SKILL.md`](./SKILL.md) | 流水线协议（§2-§3）、输出模式（§5）、ADRMATS 测试集画像（§11） |
| [`examples/README.md`](./examples/README.md) | 实战案例文件 |

## 🤝 参与贡献

欢迎 Issue 与 PR。请先阅读 [`CONTRIBUTING.md`](./CONTRIBUTING.md)。提交 PR 前，请在仓库根目录运行 `python3 tests/selftest.py` 并确认退出码为 0；然后把完整输出粘贴到 PR 描述中。

## 📝 引用

如果 LitAnchor 对你的工作有帮助，请按 [`CITATION.cff`](./CITATION.cff) 引用（CFF 1.2.0，可用 `cffconvert` 校验）。

## 📄 许可证

[MIT 许可证](./LICENSE)——Copyright (c) 2026 Water Quality Risk Control Engineering & contributors.
