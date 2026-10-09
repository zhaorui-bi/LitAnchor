---
name: lit-extract
description: 文献提参（PDF 结构化数据提取）ZCode 版——文本锚定 + 视觉增强 + 三级硬校验混合流水线，全程使用 ZCode 会话自身能力（本地 PyMuPDF 脚本 + Read 读图 + analyze_image 视觉精读 + 会话内约束提参），零按量付费 API。当用户说"提参 / 提取参数 / 文献数据提取 / PDF 结构化提取"，或要求构建 ADRMATS 评估智能体测试集（visible_input / hidden_oracle_label 三段式）时使用。输出带页码级溯源与五级质量标记的结构化 JSON。
---

# 文献数据提参技能 · ZCode 版（lit-extract）

## 1. 定位与触发

本 Skill 赋予 ZCode 会话 **PDF 文献阅读**和**约束驱动的结构化数据提取**能力。采用 **文本锚定 + 视觉增强 + 硬校验** 混合架构，杜绝纯视觉流水线的幻觉风险。

**与原 OpenClaw/DashScope 版的差异**：本版本不调用任何按量付费 API。Stage 0 / Stage 3 由本技能自带本地脚本完成；Stage 1 视觉精读走 ZCode 会话的 Read 工具 + `mcp__4_5v_mcp__analyze_image`；Stage 2 提参由当前会话模型直接完成。全程计入 ZCode 订阅，无按量付费的外部 API 调用（内置视觉工具的计费口径以 Z.ai 账单为准）。

**触发条件**（满足任一即激活）：
- 用户提供了 PDF 文件路径，要求阅读或分析
- 用户要求从文献中提取特定数据/参数（"提参"、"提取参数"、"文献数据提取"、"PDF 结构化提取"）
- 用户指定了提取的键（key）和值类型（value type），要求输出 JSON
- 用户要求构建 ADRMATS 评估智能体测试集（见 §11）

**核心原则**（不可妥协）：
- **文本锚定**：先用本地脚本提取文本层获得不可幻觉的元数据锚点（标题/DOI/作者/关键词），全程绑定
- **视觉增强**：仅对含图表的页面（data_page）做视觉精读，文字页直接用文本层，跳过无关页（参考文献等）
- **硬校验**：提取结果必须通过三级校验（元数据一致性 / 实体存在性 / 数值回溯），不通过则标记或删除
- **忠于原文**：提取数据必须可追溯到文献原文位置（页码、表格、Figure 编号）
- **缺失透明**：文献中无法找到的字段标记为 `null` 并注明原因

---

## 2. 混合流水线架构（ZCode 通道）

### 2.1 架构总览

```
PDF 文件
  │
  ├─ [Stage 0] 本地脚本 scripts/stage0_anchor.py（秒级，零 API）
  │   ├─ 元数据锚点：标题、DOI、作者、关键词（不可覆盖）
  │   ├─ 智能分页：标记每页类型（data_page / text_page / skip_page）
  │   ├─ 全文文本：pages_text 存入 stage0 JSON，供 Stage 2 合并与 Stage 3 校验
  │   └─ data_page 渲染：PNG 输出到 <PDF>_pages/page_00N.png
  │
  ├─ [Stage 1] 选择性视觉精读（仅 data_page，ZCode 通道）
  │   ├─ Read 工具读取 PNG → 得到 CDN URL
  │   ├─ URL 作为 imageSource 调 mcp__4_5v_mcp__analyze_image（并发 ≤3，限流退避见 §2.3.1）
  │   └─ 收集每页 Markdown 转录（含防幻觉约束）
  │
  ├─ [Stage 2] 合并 + 约束提参（当前会话内完成，零外部 API）
  │   ├─ text_page 用 stage0 文本，data_page 用视觉精读 Markdown
  │   ├─ 按页码顺序合并为全文，注入元数据锚点
  │   └─ 会话模型 + 用户约束 + 锚点 → 结构化提取 JSON
  │
  └─ [Stage 3] 三级硬校验（本地脚本 scripts/validate.py，秒级，零 API）
      ├─ Level 1: 元数据一致性（标题/DOI/作者，不符自动替换为锚点值）
      ├─ Level 2: 实体存在性（材料名/污染物名在原文中的出现次数，0 次删记录）
      ├─ Level 3: 数值回溯（关键数值在原文文本中可查，±1% 近似）
      └─ 输出修补后的最终 JSON（<result>_validated.json）
```

**为什么不纯视觉？**
纯视觉流水线对长文档（>30 页）存在严重幻觉风险——模型可能将训练语料中相似主题论文的内容注入到当前文献的提取结果中。文本锚定提供了不可幻觉的 ground truth 基准。

### 2.2 Stage 0 — 文本锚定与智能分页（本地脚本）

**执行方式**：用 Bash 运行本技能自带脚本（本地执行，仅需 PyMuPDF，无任何 API 调用）：

```bash
python3 ~/.zcode/skills/lit-extract/scripts/stage0_anchor.py <PDF路径> \
  [--output <输出json>] [--dpi 150] [--pages-dir <PNG目录>]
```

| 参数 | 说明 |
|------|------|
| `pdf`（必填） | PDF 文件路径；不允许包含 `..` 跳转组件（脚本会拒绝并报错） |
| `-o / --output` | 输出 JSON 路径，默认 `<PDF去后缀>_stage0.json` |
| `--dpi` | data_page 渲染 DPI，默认 150；图表密集/字小时建议 `--dpi 300` |
| `--pages-dir` | PNG 输出目录，默认 `<PDF去后缀>_pages` |

脚本一次完成文本提取、锚点硬提取、智能分页和 data_page 渲染，控制台会打印分页统计与锚点摘要。产物：

1. **stage0 JSON**（默认 `<PDF去后缀>_stage0.json`），字段：
   - `anchor_title` / `anchor_doi` / `anchor_authors` / `anchor_keywords` — 元数据锚点（作者为第 1-2 页启发式提取，识别失败为 `[]`）
   - `page_types` — 每页类型（`data_page` / `text_page` / `skip_page`）
   - `pages_text` — 全文分页文本（Stage 2 合并与 Stage 3 校验的基准）
   - `data_page_nums` / `total_pages` / `pages_dir` / `preprocess_date`
2. **PNG 目录**（默认 `<PDF去后缀>_pages/`）：仅 data_page 被渲染，命名为 `page_00N.png`（N 为实际页码，三位零填充，如第 5 页 → `page_005.png`）

**锚点字段与用途**：

| 锚点字段 | 来源 | 用途 |
|----------|------|------|
| `anchor_title` | 第 1 页连续显著行合并（以最长单行为种子拼接相邻显著行，多行标题自动拼接；脚本内置） | 校验提取结果的论文标题 |
| `anchor_doi` | 前 3 页正则匹配 `10\.\d{4,}/[^\s]+`（脚本内置） | 校验 DOI |
| `anchor_authors` | 第 1-2 页标题区间末行后的连续作者行（脚本内置，**尽力而为**，识别失败为 `[]`） | 校验作者 |
| `anchor_keywords` | "Keywords:" 后的关键词列表（脚本内置） | 辅助识别研究主题 |
| `anchor_material_keywords` | **不在 stage0 JSON 中**——由会话在 Stage 2 从 `pages_text` 统计高频专有名词（出现 >5 次）自行生成 | 校验材料实体 |

**锚点已知限制（实测：Andersson 2026, DOI 10.1002/anie.202526027）**：

- **作者启发式可能漏人**：真实案例中锚点只识别出 10 位作者中的 8 位（漏掉两位通讯作者 M. R. Johnston 与 W. M. Bloch）。提参时若第 1 页文本层的作者列表完整可读，`extraction_meta.authors` **应以原文为准**，并把差异记入 `extraction_meta.anchor_note`（该字段由会话回填，脚本不改动），例如："锚点作者 8 人，缺通讯作者 M. R. Johnston 与 W. M. Bloch，已按第 1 页原文 10 位作者为准"。该做法与 Stage 3 兼容：Level 1 只比对**第一作者**（见 §3.1），完整列表的第一作者与 `anchor_authors[0]` 一致时不会被锚点覆盖。
- **标题多行拼接已由脚本处理**：旧实现取第 1 页最长单行作标题，两行式标题会截断为较长的一半（真实案例丢失副题 "by Cavity-Directed Aggregation in a Molecular Cage Host"）；现 `extract_title_span` 以最长显著行为种子把相邻显著行拼接为完整标题，单行标题行为不变。若仍发现锚点标题与第 1 页原文不符，同样以原文为准并在 `anchor_note` 记录差异。

**智能分页规则**（已内置脚本，无需手写；此处供理解与复核）：

| 页面类型 | 判定规则 | 处理方式 |
|----------|----------|----------|
| `data_page` | 页面含 "Figure/Table/Fig/Tab/Scheme + 编号"（编号前的点号与空格均可选：`Figure 4`、`Fig. 4`、`Fig.4`、`Tab. 2` 都命中；编号前还允许 S 前缀，`Figure S4`、`Table S12` 等 SI 编号亦命中）；第 10 页之后还要求含大图片对象与数值 | 渲染 PNG + 视觉精读 |
| `text_page` | 纯文字为主，无图表标记 | 直接使用文本层 |
| `skip_page` | 以 References/Bibliography/Supporting Information 等开头；或晶体学参数页（CCDC/R1 =/wR2 = 等命中 ≥3）；或 NMR 峰列表页 | 完全跳过，不纳入提参上下文 |

### 2.3 Stage 1 — 选择性视觉精读（Read → analyze_image）

**只处理 `data_page` 类型的页面**（以 stage0 JSON 的 `data_page_nums` 和 `pages_dir` 为准），其余页面跳过视觉精读。

**逐页执行流程**：

1. 用 **Read 工具**读取该页 PNG（如 `<PDF>_pages/page_005.png`）——Read 会返回该图片的 **CDN URL**；
2. 把该 URL 作为 `imageSource`，调用 **`mcp__4_5v_mcp__analyze_image`**，`prompt` 参数使用下方视觉转录 Prompt 全文；
3. 收集返回的 Markdown 转录，作为该页的视觉精读结果；建议同时存档为 `<PDF>_pages/page_00N.md`（与 PNG 同名），便于断点续跑与人工复核。

**视觉转录 Prompt**（防幻觉约束必须保留，逐字使用）：

```
你是一个学术文献视觉读取专家。请仔细观察这一页PDF图片，将页面上所有可见信息转录为结构化Markdown。

重要约束：
- 只转录你在图片中实际看到的内容，不要添加任何你"知道"但图片中没有的信息
- 如果某个数值看不清楚，用 [unclear] 标记，不要猜测
- 不要从你的训练知识中补充任何数据

转录要求：
1. 正文文字完整转录，保留标题层级（#/##/###）
2. 表格转为Markdown表格，确保表头与数据行严格对齐
3. Figure/图表：描述图中内容，尽量读出具体数值
4. 图注（Caption）完整转录
5. 公式转为LaTeX格式
6. 脚注完整保留
7. 在每个内容块前标注类型标签：[TEXT]、[TABLE]、[FIGURE]、[CAPTION]、[EQUATION]、[FOOTNOTE]

输出纯Markdown，不要添加任何解释性文字。
```

#### 2.3.1 并发控制与限流退避（实战教训：Andersson 2026）

`analyze_image` 消耗的是**账户级共享配额**，并发必须克制：

1. **常规并发上限 3**：同时在途的 `analyze_image` 调用不超过 3 页，页与页/批与批之间留间隔（量级参考退避起点 45s）。Read 读取 PNG 是本地操作，可批量并行，不受此限。实战教训：7 页一次性并发曾触发**账户级 429**（`MCP error 429 … "code":"1302" 您的账户已达到速率限制，请您控制请求频率`），其中第 7 页累计退避约 8.5 分钟（6 次调用：45s / 90s / ~120s / 100s / 150s，其后错误转为 `-32603 试次数超限`）仍未恢复，该页视觉精读彻底失败。另：**转录页清单必须逐字取自 stage0 JSON 的 `data_page_nums`**，不要按页码顺序臆测——实战中曾把文本页当作数据页转录、同时漏掉真正的数据页，靠文本层兜底才未影响结果。
2. **收到 429 / 账户限流**：立即把并发降为 **1**（后续页面串行 + 页间间隔），失败页按指数退避重试（45s → 90s → 递增，单页至多约 6 次）。
3. **长时间未恢复（累计退避约 8–10 分钟仍失败）**：停止重试，剩余 data_page **改用文本层兜底**——合并时标注 `[Page N - text(fallback)]`；数值处理沿用 §4.4 第 3 条语义：文本层可查（图注、正文转述）→ 正常提取，Stage 3 回溯后 `reliable`；仅存在于图表中、文本层没有 → 置 `null`，`_source` 保留页码并写明"限流未视觉读取"原因（不要预置 `_quality`，`null` 一律判 `unavailable`）；确需保留的文字估读值预标 `needs_review` 并注明依据；在 `extraction_notes` 声明兜底页范围与精度风险。
4. **失败留痕**：限流失败的页把 `page_00N.md` 写成失败声明（记录错误原文、退避序列，并注明"本文件不是该页转录内容"），配额恢复后仅对该页续跑 Stage 1，其余缓存照常复用（§4.3）。
5. **子代理并行**：页面较多（>8 页）时可分组交并行子代理，但**每个子代理内部同样遵守并发 ≤3 与页间间隔**——多子代理并发叠加会更快触发账户限流；若会话不支持并行子代理，则批量交替（先全部 Read，再低并发依次 analyze_image）。

### 2.4 Stage 2 — 合并与约束提参（会话内完成）

**执行者**：当前 ZCode 会话模型，直接在会话内完成，不调用任何外部 API。

**合并策略**（按页码升序遍历 `page_types`）：
- `text_page`：直接使用 stage0 JSON `pages_text` 中该页文本，前面标注 `[Page N - text]`
- `data_page`：使用 Stage 1 视觉精读的 Markdown，前面标注 `[Page N - visual]`
- `skip_page`：完全不纳入

**提参 Prompt 模板**（会话内套用；含强制元数据锚点注入）：

```
你是一个严谨的科学文献数据提取专家。

## 论文元数据（已从PDF文本层硬提取，不可修改，你的提取结果必须与此一致）
- 标题: {anchor_title}
- DOI: {anchor_doi}
- 第一作者: {anchor_first_author}
- 关键词: {anchor_keywords}
- 核心材料/实体关键词（文中高频出现）: {anchor_material_keywords}

## 重要约束
- extraction_meta 中的 source、doi、authors 必须使用上面的锚点值，不可修改
- data 中的 material_type 和 chemical_formula 必须是上面"核心材料关键词"中出现的实体
- data 中的 target_pollutant 必须是本文实际研究的污染物，不可引入文中未提及的物质
- 所有数值必须直接来源于下面的文献内容，不得从你的知识库中补充

## 文献内容
{merged_full_text}

## 用户约束
- 提取字段：{field_definitions}
- 筛选条件：{constraints}
- 输出粒度：{granularity}

## 提取规则
1. 每个值必须直接来源于上面的文献内容，不得推断或编造
2. 数值必须保留原文单位，若需转换须注明
3. 文献中未明确给出的字段，值设为 null，并在 _source 字段说明原因
4. 若同一字段在文献不同位置有多个值，全部列出并标注出处
5. 表格数据优先从 [TABLE] 标记的内容中提取
6. Figure中的数值（来自 [FIGURE] 标记）如为估读值，在 _quality 中标记 needs_review
7. 注意跨页内容的连续性，同一个表格可能分布在相邻页面

## 输出格式
返回严格的 JSON，结构如下：
{output_schema}
```

`{output_schema}` 填 §5.1 标准 schema；激活 §11 ADRMATS Profile 时替换为 §11.6 三段式 schema，并按 §11.2–11.4 追加业务约束与领域启发。

Stage 2 产出的 JSON 先写入文件（建议 `<PDF去后缀>_result.json`），供 Stage 3 脚本校验。

### 2.5 输入预处理：主文 + SI 合并（推荐）

同一论文的补充材料（SI）**建议与主文用 PyMuPDF 合并为单一 PDF 后再跑 Stage 0**（核心 3 行）：

```python
import pymupdf  # 旧版写法 import fitz，二者等价
out = pymupdf.open()
for p in ("main.pdf", "SI.pdf"):    # 主文在前，保证页码顺序
    out.insert_pdf(pymupdf.open(p))
out.save("merged.pdf")
```

**为什么合并**：合并后页码连续（主文 p1–pN，SI 从 pN+1 起），锚点提取、`_source` 页码溯源与 Stage 3 数值回溯基准（`pages_text`）统一在同一坐标系——SI 中的数值可正常回溯校验，`_quality` 判定不被文档边界干扰。实测对照（Andersson 2026）：仅跑 10 页主文时，**85 项**期望数据（分子式/分子量、个体去除率、晶体学接触距离、Hill 参数、成本对比等）因只在 74 页 SI 中而全部只能置 `null`；主文+SI 合并后这些数据才可提取与校验。注意：合并后以 "Supporting Information" / "Electronic Supplementary Material" 开头的 SI 封面页会被智能分页判为 `skip_page`，属预期行为（SI 封面通常无数据）。

**逐篇独立跑的取舍**（不合并时）：主文与 SI 各自跑完整流水线，缓存/产物按文档独立、主文结果可先行交付；代价是页码各自从 1 起，跨文档溯源必须用 §5.2 的 `Supplementary, Table SN` 前缀区分，且**SI 的提取结果必须用 SI 自己的 stage0 JSON 过 Stage 3**——若把 SI 数据并入主文结果后仍按主文 stage0 校验，Level 3 会因主文文本层查不到这些数值而误判 `suspicious`。

---

## 3. 三级硬校验协议（Anti-Hallucination Validation）

Stage 2 完成后，**必须**用本技能脚本执行三级校验（本地、零 API；校验基准为 stage0 JSON 的 `pages_text` 全文）：

```bash
python3 ~/.zcode/skills/lit-extract/scripts/validate.py <result.json> <stage0.json> \
  [--output <输出json>]
```

| 参数 | 说明 |
|------|------|
| `result`（必填） | Stage 2 产出的提参 JSON，兼容 §5.1 `data[]` 与 §11.6 `records[]` 两种 schema（自动识别） |
| `stage0`（必填） | stage0_anchor.py 输出的 Stage 0 JSON |
| `-o / --output` | 修补后 JSON 输出路径，默认 `<result去后缀>_validated.json`（输入文件旁，不覆盖原文件） |

退出码 0 = 校验完成（含发现可疑项）；非 0 = 出错——1 = 文件不存在/JSON 解析失败等输入错误，2 = 命令行用法错误（argparse 约定，如缺少位置参数）。自动化判断用"非 0 即失败"。

### 3.1 Level 1 — 元数据一致性校验（脚本自动执行）

| 校验项 | 校验方法 | 不通过处理 |
|--------|----------|-----------|
| `extraction_meta.source` | 必须覆盖 `anchor_title` 的主要词组（≥50%） | 替换为 `anchor_title` |
| `extraction_meta.doi` | 规范化后必须等于 `anchor_doi` | 替换为 `anchor_doi` |
| `extraction_meta.authors` | 第一作者必须匹配 `anchor_authors[0]` | 替换为 `anchor_authors` |

锚点为空时对应项跳过。**如果标题+DOI+作者三项全部"实际值不符"（缺失不算），说明提取结果整体来自幻觉**——脚本会在 `validation_report` 标记 `overall_hallucination_risk: true`，此时必须丢弃结果并重新执行 Stage 2。

### 3.2 Level 2 — 实体存在性校验（脚本自动执行）

对每条记录的材料/污染物实体在全文中计数：

- 材料/污染物实体在原文出现 **0 次** → **删除该记录**，并在 `extraction_notes` 中标注 "已删除: {entity} 在原文中未出现（幻觉）"
- 实体出现 **< 3 次** → 在 `_quality` 中标记 `suspicious`
- 标准 schema 探测字段：`chemical_formula` / `material_type` / `material` / `adsorbent_name` / `adsorbent` 与 `target_pollutant` / `pollutant_name` / `pollutant` / `contaminant`；ADRMATS schema 按 §11.7 校验 `chemical_formula` 与 `target_pollutant`

### 3.3 Level 3 — 数值回溯校验（脚本自动执行）

对每条记录中的数值字段，判定顺序：

- 数值（字符串形式，允许前置 `>` `<` `~` `≈`）在文本层中**精确匹配** → `reliable`
- 精确失败但全文存在 **±1% 区间内**的数值 → `reliable`
- 找不到但该值溯源指向 `data_page`（如 `_source` 写 "Page 9, Figure 4"）→ `needs_review`（可能是 Figure 估读值）
- 文本层和视觉溯源都找不到 → `suspicious`（可能是幻觉值）
- 字段值为 `null` → `unavailable`

**纯扫描 PDF**：文本层过短（全文 <200 字符）时脚本自动跳过 Level 2/3，并在结果中声明需人工复核。

---

## 4. 数据提参协议（Execution Protocol）

### 4.1 用户输入规范

| 输入项 | 必需 | 说明 | 示例 |
|--------|------|------|------|
| **PDF 文件路径** | 是 | 本地 PDF 文件路径或多个文件路径 | `~/papers/Zhang2024.pdf` |
| **提取字段定义** | 是 | 键名 + 值类型/含义描述 | `{"adsorbent_name": "吸附剂名称", "BET_surface_area": "比表面积(m²/g)"}` |
| **约束条件** | 否 | 筛选或过滤条件 | "只提取温度25°C下的实验数据" |
| **输出粒度** | 否 | 每条数据对应的实体单位 | "每种吸附剂材料一条记录" |

### 4.2 完整执行流程（ZCode 通道）

```
Step 0: 缓存检查（跳过重跑）
  若 <PDF去后缀>_stage0.json 存在，且 <PDF去后缀>_pages/ 下 PNG 数量
  与其中 data_page_nums 数量一致 → 直接加载，跳过 Stage 0
  （各页 page_00N.md 视觉转录若已存档，同样直接复用，跳过该页 Stage 1）

Step 1: 解析用户约束
  理解用户定义的 key-value 结构和筛选条件

Step 2: Stage 0 — 文本锚定（本地脚本，秒级）
  运行 scripts/stage0_anchor.py → 锚点 + 分页 + data_page PNG
  （主文与 SI 分属两个 PDF 时，建议先按 §2.5 合并为单一 PDF 再跑）

Step 3: Stage 1 — 视觉精读（仅 data_page）
  对每个 data_page 的 PNG：Read 取 CDN URL → analyze_image 视觉转录
  analyze_image 并发 ≤3 且页/批间留间隔（§2.3.1）；产物按页存为 page_00N.md

Step 4: Stage 2 — 合并与提参（会话内）
  [Page N - text]（text_page，来自 stage0 JSON）与
  [Page N - visual]（data_page，来自 Stage 1）按页码合并
  注入元数据锚点，套用 §2.4 Prompt 模板 → 写出 <PDF去后缀>_result.json

Step 5: Stage 3 — 三级硬校验（本地脚本，秒级）
  运行 scripts/validate.py result.json stage0.json
  → <PDF去后缀>_result_validated.json（最终交付物）

Step 6: 输出综合 JSON
  附带校验结果、溯源和质量标记，向用户呈报
```

### 4.3 缓存与复用

- Stage 0 的 stage0 JSON 与 PNG 目录是缓存单元：两者齐备且 PNG 数与 `data_page_nums` 一致时**禁止重跑** Stage 0；需要更高清渲染时用 `--dpi 300 --pages-dir <新目录>` 另行生成，且**必须同时用 `-o` 指定新的 stage0 JSON 输出路径**——不带 `-o` 重跑会写默认输出路径，覆盖原缓存 JSON（PNG 在新目录不会覆盖，但 JSON 会被替换）。
- 同一会话对同一 PDF 多次提不同参数时，直接复用已有 stage0 JSON / PNG / page_00N.md，只重跑 Stage 2–3。

### 4.4 降级路径：analyze_image 不可用

当会话中没有 `mcp__4_5v_mcp__analyze_image` 工具时，退回**纯文本层模式**：

1. data_page 也改用 stage0 JSON `pages_text` 的文本层文本（标注 `[Page N - text]`），Stage 0/2/3 流程不变；
2. 数值在文本层可查（图注、正文转述）→ 正常提取，Stage 3 回溯通过后为 `reliable`；
3. 仅存在于图表中、文本层没有的数值 → 值设为 `null`，**不要预置 `_quality`**——Stage 3 脚本对 `null` 一律判 `unavailable`，预置的任何标记都会被覆盖。真实语义（文献有图、本会话读不了）由两处承载，它们不会被 Stage 3 改写：
   - `_source` 写明原因并保留页码溯源，如 `"Page 4, Figure 3, 图表数值未读取（本会话视觉精读通道不可用）"`；
   - `extraction_notes` 声明精度风险，例如："本会话视觉精读通道不可用，采用纯文本层模式，Figure 内数值未能读取，相关字段精度受限"；
4. 降级模式下不会出现 `needs_review` 数值：非 null 值均来自文本层（回溯后 `reliable` 或 `suspicious`），null 值为 `unavailable`——其两种成因的语义区分见 §5.3 表后说明。
5. **终止条件**：若同时满足"文本层过短（全文 <200 字符，纯扫描 PDF）"与本降级（analyze_image 不可用），则不存在任何提取基准——终止流水线，不产出 JSON，明确告知用户：该 PDF 无文本层且本会话视觉通道不可用，无法可靠提取；建议在启用视觉工具的会话中重试，或提供带文本层的原生 PDF。

**与限流兜底的关系**：§2.3.1 中限流长时间未恢复时对**剩余部分** data_page 的文本层兜底，数值语义沿用本节第 3 条（null + `_source` 原因 + `extraction_notes` 声明），区别仅在于兜底是部分页面而非全部、且原因写"限流未视觉读取"。

---

## 5. 输出规范

### 5.1 标准 JSON 输出结构

```json
{
  "extraction_meta": {
    "source": "论文标题（必须等于 anchor_title）",
    "doi": "DOI（必须等于 anchor_doi）",
    "authors": "作者列表（必须等于 anchor_authors）",
    "extraction_date": "YYYY-MM-DD",
    "total_pages": 84,
    "pages_visual_read": 15,
    "pages_text_only": 40,
    "pages_skipped": 29,
    "constraints_applied": "用户约束条件描述",
    "total_records": 7,
    "records_removed_by_validation": 0,
    "pipeline": "text-anchored + visual-enhanced + hard-validated"
  },
  "field_definitions": {
    "key_name": "用户定义的值含义描述"
  },
  "data": [
    {
      "key_1": "extracted_value_1",
      "key_2": 123.4,
      "key_3": null,
      "_source": {
        "key_1": "Page 5, Table 2, Row 3",
        "key_2": "Page 8, Section 3.2, para 1",
        "key_3": "文献未提供该参数"
      },
      "_quality": {
        "key_1": "reliable",
        "key_2": "reliable",
        "key_3": "unavailable"
      }
    }
  ],
  "validation_report": {
    "level_1_metadata": "PASS",
    "level_2_entities_checked": 7,
    "level_2_entities_removed": 0,
    "level_3_values_reliable": 15,
    "level_3_values_needs_review": 3,
    "level_3_values_suspicious": 0
  },
  "extraction_notes": [
    "Figure 3 中的去除率数据为从柱状图估读，精度约±2%"
  ]
}
```

`validation_report` 由 Stage 3 脚本回填（实际字段以脚本输出为准，含 `level_1_details` / `level_2_entities_suspicious` / `level_3_values_unavailable` 等）。

### 5.2 字段级溯源规则

每条提取记录必须包含 `_source` 对象，格式统一带页码：

| 溯源类型 | 格式 | 示例 |
|----------|------|------|
| 表格数据 | `Page N, Table X, Row M` | `"Page 6, Table 2, Row 5"` |
| 正文段落 | `Page N, Section X.Y, para M` | `"Page 3, Section 2.3, para 2"` |
| Figure数据 | `Page N, Figure X` + 读取方式 | `"Page 9, Figure 4, 柱状图估读"` |
| 图注 | `Page N, Figure X caption` | `"Page 9, Figure 4 caption"` |
| 摘要 | `Page 1, Abstract` | `"Page 1, Abstract"` |
| 补充材料 | `Supplementary, Table SN` | `"Supplementary, Table S2"` |
| 未找到 | 原因说明 | `"全文未报告该参数"` |

溯源字符串中的页码会被 Stage 3 脚本解析（识别 `Page N`）用于判定数值是否来自 data_page，因此**页码必须写实际页码**。

### 5.3 数据质量标记（五级）

| 质量等级 | 标记 | 含义 | 典型场景 |
|----------|------|------|----------|
| **可靠** | `reliable` | 原文文本层可查，数值/单位清晰 | 表格中的精确数值，Level 3 回溯通过 |
| **需确认** | `needs_review` | 值来自视觉精读的图表估读，文本层中无对应文本 | Figure中的柱状图高度、折线图数据点 |
| **可疑** | `suspicious` | Level 3 回溯未通过，可能是幻觉值 | 数值在文本层和视觉层都找不到 |
| **推断值** | `inferred` | 非原文直接给出，由相关数据推算 | 由进出水浓度推算去除率 |
| **不可用** | `unavailable` | 文献中未提供该信息 | 字段值为 null |

**`unavailable` 的两种成因**（以 `_source` 原因说明区分，见 §5.2"未找到"行）：其一，文献确实未提供该参数（`_source` 如 "全文未报告该参数"）；其二，视觉读取未发生（§4.4 会话无 analyze_image，或 §2.3.1 限流兜底）导致图表数值未能读取（`_source` 必须保留页码并写明"未读取"原因，配合 `extraction_notes` 精度风险声明）。两者校验标记同为 `unavailable`，但 `_source` 不得混写——"文献有图而本会话未读取"绝不写成"文献未提供"。

---

## 6. 多文献综合提参

对多篇文献，**逐篇独立执行完整流水线（Stage 0–3）**，最后合并：

```
Paper_1.pdf → Stage 0-3 → JSON_1（含 validation_report）
Paper_2.pdf → Stage 0-3 → JSON_2（含 validation_report）
                  ↓
         合并为统一JSON（附 paper_id 索引）
```

每篇使用**独立的缓存目录**：默认输出按各自 PDF 路径派生（`<PDF>_stage0.json` / `<PDF>_pages/`），天然按篇隔离；若并行子代理共用同一工作目录、显式指定 `-o` / `--pages-dir`，**必须每篇不同**，防止 stage0 JSON 与 PNG 相互覆盖。同篇的主文与 SI 若不合并（§2.5），同样各自独立缓存。多篇可并行处理（子代理各领一篇），但所有子代理合计的 `analyze_image` 在途并发仍受 §2.3.1 约束。

---

## 7. 成本说明

**全程使用 ZCode 订阅，不调用任何按量付费的外部 API；内置视觉工具（analyze_image）的计费口径以 Z.ai 账单为准。**

| 环节 | 执行通道 | 费用 |
|------|----------|------|
| Stage 0 文本锚定 | 本地脚本（PyMuPDF） | 免费，秒级 |
| Stage 1 视觉精读 | Read 工具 + `mcp__4_5v_mcp__analyze_image`（ZCode 订阅内 MCP） | 订阅内，低并发并行（§2.3.1） |
| Stage 2 约束提参 | 当前会话模型 | 订阅内 |
| Stage 3 三级硬校验 | 本地脚本（纯标准库） | 免费，秒级 |

无 DashScope/百炼 API Key、无任何按 token 计费的外部调用。耗时量级：Stage 0/3 均为秒级；Stage 1 取决于 data_page 数量、并发上限（§2.3.1）与限流退避状况；Stage 2 为一次会话内生成。

---

## 8. 异常处理

| 异常场景 | Agent 行为 |
|----------|----------|
| PDF 加密/无法打开 | 告知用户，要求提供无密码版本 |
| 脚本报缺少 PyMuPDF | 先 `pip install pymupdf` 再重试（脚本会打印安装提示） |
| 路径含 `..` 或文件不存在 | 脚本直接拒绝并报错；改用规范化绝对路径重试 |
| PyMuPDF 文本层为空（纯扫描 PDF） | stage0 会把空文本页判为 text_page 且不渲染 PNG；检测到 `pages_text` 几乎全空（全文 <200 字符）时，用 PyMuPDF 在会话内把所需页面渲染为 PNG，再走 Read → analyze_image 视觉精读；Stage 3 脚本会自动跳过 Level 2/3 并在结果中声明需人工复核 |
| 会话中 analyze_image 不可用 | 按 §4.4 降级为纯文本层模式：图表专属数值置 null（校验后为 `unavailable`），`_source` 写明未读取原因与页码，并在 extraction_notes 声明精度风险 |
| analyze_image 429 / 账户级速率限制 | 按 §2.3.1 处理：并发降为 1 + 指数退避重试；累计退避约 8–10 分钟仍未恢复则剩余 data_page 文本层兜底，相关数值按 §4.4 语义处理（null / needs_review），在 extraction_notes 声明，失败页 page_00N.md 写失败声明留痕 |
| 锚点作者列表不完整（启发式漏人） | 第 1 页作者列表完整可读时以原文为准，差异记入 `extraction_meta.anchor_note`（§2.2 已知限制）；Level 1 只比对第一作者，完整列表不会被锚点覆盖 |
| 纯扫描 PDF 且 analyze_image 同时不可用 | 终止提取并告知用户（§4.4 第 5 条）：无文本层基准且无视觉通道，无法可靠提取；不得输出无基准的结果 |
| 页面为纯扫描图且分辨率极低 | 用 `--dpi 300` 重新渲染再试；仍读不清按 [unclear] 处理并在 extraction_notes 中声明精度风险 |
| Figure 数据密集且数值密集重叠 | 标记为 needs_review，建议用户人工校验 |
| 跨页表格 | 逐页读取后，Stage 2 负责跨页关联拼接 |
| 单位不统一 | 保留原文单位，在 extraction_notes 中提供换算建议 |
| Level 1 校验全部失败（overall_hallucination_risk） | 说明提取结果整体来自幻觉，丢弃并重新执行 Stage 2 |
| Level 2 删除了所有记录 | 在 extraction_notes 中说明，建议用户检查 PDF 是否正确 |
| 字段值存在矛盾（摘要 vs 正文 vs 表格） | 优先级：表格 > 正文 > 摘要，在 _source 中记录矛盾 |

---

## 9. 典型使用场景

### 场景 A：单篇论文提参（图文混合型，含 SI）

**用户输入**：
> 帮我从 `~/papers/Andersson2026.pdf` 中提取所有 PFAS 吸附去除数据：
> - material_type: 吸附剂类型
> - target_pollutant: 目标PFAS
> - removal_rate_percent: 去除率(%)
> - adsorption_capacity_mg_g: 吸附容量(mg/g)
> - binding_thermodynamics: 热力学参数
>
> 约束：每种 PFAS 一条记录，含水质信息。

**Agent 执行**：
1. Stage 0: 主文 + SI 先按 §2.5 合并为单一 PDF，运行 stage0_anchor.py → 锚点 + 智能分页 + data_page PNG（如 84 页中约 15 页 data_page）
2. Stage 1: 仅对 15 个 data_page 做 Read → analyze_image 视觉精读（并发 ≤3，页间留间隔，§2.3.1）
3. Stage 2: 会话内合并 + 锚点注入 + 约束提参 → result.json
4. Stage 3: 运行 validate.py → result_validated.json（最终输出）

### 场景 B：多文献对比提参

**用户输入**：
> 从这 3 篇 PDF 中提取 MOF 材料性能对比数据。

**Agent 执行**：3 篇并行处理（子代理各领一篇，各自 Stage 0–3）→ 合并为带 paper_id 的统一 JSON

---

## 10. 安装位置、依赖与脚本说明

- **安装位置**：本技能安装于 `~/.zcode/skills/lit-extract/`，本文档中的 `scripts/…` 均指该技能目录下的 `scripts/` 子目录（即 `~/.zcode/skills/lit-extract/scripts/`）。若技能位于其他目录，以本文档（SKILL.md）所在目录的 `scripts/` 为准。
- **安装方式**：在本技能包根目录执行 `bash install.sh`，自动把 SKILL.md 与 `scripts/` 两个脚本复制到 `~/.zcode/skills/lit-extract/`（旧版先备份为 `lit-extract.bak.<日期>`）；`bash install.sh --uninstall` 卸载。
- **`scripts/stage0_anchor.py`**：Stage 0 独立脚本——文本锚定 + 智能分页 + data_page 渲染。依赖标准库 + PyMuPDF（`pip install pymupdf`）。命令行见 §2.2。
- **`scripts/validate.py`**：Stage 3 独立脚本——三级硬校验，纯标准库、零依赖。自动识别 §5.1 `data[]` 与 §11.6 `records[]` 两种 schema。命令行见 §3。
- 两个脚本均内置路径校验（展开 `~`、拒绝 `..` 跳转组件与空字节、要求输入文件存在），文件读写仅发生在校验后的路径上。
- 提取的 JSON 可直接供下游技能/脚本消费（材料筛选、对比分析、知识图谱构建、ADRMATS 动态权重生成等）。

---

## 11. 业务 Profile：ADRMATS 评估智能体测试集构建

### 11.1 Profile 定位

本 Profile 用于生成 **ADRMATS 评估智能体（Evaluation Agent）** 的性能测试集。测试对象仅限评估智能体本身（不含约束识别智能体、设计智能体、提取模块）。测试输入必须对齐评估智能体在主链路中实际接收的两类结构化信息：

```
visible_input = constraint_context + merged_proposals
hidden_oracle_label（不得随 visible_input 传入）
```

**激活条件**（满足任一）：
- 用户明确提到「ADRMATS 评估智能体测试集」「评估智能体性能测试」「排序准确率测试集」
- 用户要求输出包含 `visible_input` / `hidden_oracle_label` / `source_trace` 的三段式记录
- 用户要求提取结果同时包含 `constraint_context` 与 `merged_proposals`

激活后，本 Profile 作为 §4 Stage 2 提参 Prompt 的业务约束层注入，Stage 0/1/3 的文本锚定、视觉增强与三级硬校验机制全部保留。

### 11.2 最小记录粒度与拆分规则

单条记录以 **一个材料 × 一个污染物 × 一个水质场景 × 一个实验类型 × 一组独立实验条件** 为最小单元。以下场景强制拆分为多条 records：

1. 文献中存在多个材料 → 每种材料一条
2. 单一材料对应多种水质场景（超纯水 / 自来水 / 地下水 / 模拟废水 / 真实废水）→ 每种水质一条
3. 单一材料对应多种污染物（如 PFBA / PFOA / PFOS / OTC）→ 每种污染物一条
4. 单一材料在不同 pH / 盐度 / 硬度 / 共存离子 / 有机物条件下测试 → 按独立实验条件拆分
5. 批量吸附实验与柱实验 → 分开记录（工程意义不同）

**来源标记**（写入 `source_trace.record_origin`）：

| 取值 | 适用场景 |
|------|----------|
| `this_work` | 本文实验获得的数据 |
| `control` | 本文设置的对照 / 未改性 / 商业基准材料 |
| `literature_comparison` | 本文引用自其他文献的对比表数据 |
| `synthetic_noise` | 人工构造的错配 / 单位错置 / 矛盾样本 |

### 11.3 字段提取要求

**A. 构造 `constraint_context` 所需文献信息**

- 水质：`water_source_type` / `real_or_synthetic_water` / `pH` / `temperature` / `salinity_or_ionic_strength` / `hardness` / `major_ions` / `organic_load` / `coexisting_species` / `microbial_activity` / `special_water_characteristics`
- 污染物：`pollutant_name` / `CAS` / `molecular_formula` / `molecular_weight` / `pollutant_class` / `initial_concentration` / `pKa` / `charge_state_at_test_pH` / `molecular_size_or_chain_length` / `hydrophobicity` / `functional_groups` / `special_properties`
- `evaluation_weights` 与 `design_guidelines` 由下游脚本基于以上水质/污染物信息生成，本阶段可置 null；文献提参阶段仅需保证水质与污染物信息足以支撑权重生成

**B. 构造 `merged_proposals` 所需文献信息**

| 目标字段 | 文献对应内容 |
|----------|-------------|
| `material_type` | carbon / resin / MOF / COF / polymer / cage / xerogel / hybrid |
| `chemical_formula` | 化学式、材料缩写、复合材料主组成 |
| `element_composition` | 元素组成、掺杂元素、金属比例、XPS/EDS 结果 |
| `active_sites` | 胺基 / 季铵基 / 羧基 / 羟基 / 氟碳链 / 金属位点 / 孔穴 / 疏水域 / π 结构 |
| `pore_structure` | 微孔 / 介孔 / 大孔 / 孔径 / 孔容 / 孔径分布 |
| `specific_surface_area` | BET 比表面积 |
| `morphology` | 粉末 / 颗粒 / 树脂 / 凝胶 / 干凝胶 / 磁性颗粒 / 柱填料等 |
| `zeta_potential` | zeta 电位；若无则记录 pHpzc 或表面电荷推断并注明 |
| `target_pollutant` | 污染物名称 + CAS |
| `adsorption_performance.capacity_mg_g` | qmax / qe / 穿透容量 / 估算容量 |
| `adsorption_performance.removal_rate` | 平衡去除率 / 低浓度去除率 / 柱实验去除率 |
| `adsorption_performance.kinetics` | 平衡时间 / 速率常数 / t90 / 动力学模型 |
| `design_rationale` | 机理、水质适配性、稳定性、合成可行性、再生性、环保/经济风险的压缩说明 |
| `literature_support` | 支撑该方案的文献证据、页码、图表、关键结论 |
| `do_not_compliance` | 是否违反水质约束或设计禁忌（高盐失效 / pH 不稳 / 二次污染等） |

**C. 需提取但不单列为 visible 字段的支撑证据**

下列信息不作为 `merged_proposals` 的一级字段直接暴露，必须压缩写入 `design_rationale` / `literature_support` / `do_not_compliance`：

- 合成：`synthesis_method` / `key_reagents` / `solvents` / `temperature` / `reaction_time` / `equipment` / `steps_count` / `scale_up_claim` / `commercial_availability` / `hazard_notes`
- 稳定性：`water_stability` / `pH_stability` / `mechanical_strength` / `swelling` / `leaching` / `solid_liquid_separation` / `long_term_operation`
- 再生性：`regeneration_method` / `regenerant` / `cycle_count` / `performance_retention` / `desorption_efficiency` / `secondary_waste_risk`
- 经济/环保：`raw_material_source` / `renewable_or_biomass_source` / `commercial_material_basis` / `toxic_precursors` / `fluorinated_reagent_risk` / `metal_leaching_risk` / `LCA_or_carbon_footprint` / `end_of_life`
- 抗菌：`antibacterial_tested` / `tested_microorganisms` / `inhibition_rate` / `biofilm_resistance` / `antimicrobial_durability`

**未报告抗菌不等同于抗菌性差**，应写 `not_reported`，是否扣分由下游动态权重决定。

### 11.4 领域启发（供 Stage 2 Prompt 注入）

以下启发用于帮助模型在 `design_rationale` 与 `do_not_compliance` 中给出合理判断，**不得直接写入 `evaluation_weights`**（权重生成由下游脚本负责）：

- **短链 PFAS / 痕量浓度 / 共存阴离子**：选择性与抗竞争能力重要性上升
- **高盐 / 高硬度 / 真实水样**：水稳定性、结构稳定性、再生性权重上升
- **高微生物活性 / 长期运行场景**：抗菌 / 抗生物污染维度重要性上升
- **含氟试剂 / 重金属浸出风险**：`do_not_compliance` 应显式标注
- **综述表格或引用数据**：禁止误判为本文实验，应标记 `record_origin = literature_comparison`

### 11.5 隐藏标签设计（`hidden_oracle_label`）

每条记录必须保留隐藏标签，**严禁并入 `visible_input`**：

| 字段 | 说明 |
|------|------|
| `quality_tier` | `high` / `low` / `noise` |
| `quality_reason` | 判定依据的一句话说明 |
| `expected_rank_group` | 预期排序分组（如 top / middle / bottom） |
| `noise_type` | 仅 noise 类需填：`unit_mismatch` / `mechanism_mismatch` / `capacity_implausible` / `water_condition_fake` / `regeneration_contradiction` 等 |
| `corruption_fields` | 被人工污染的字段名列表 |

**等级判定参考**：
- `high`：材料与污染物机制匹配、性能强、水质条件明确、有稳定性/再生性证据
- `low`：真实文献中的低效对照 / 未改性 / 商业基准 / 缺关键稳定性证据
- `noise`：人工构造的错配 / 矛盾样本（单位错置、机制错配、容量明显不合理等）

**下游评价指标建议**（不在本 Skill 执行，仅提示）：优先使用排序类指标——pairwise ranking accuracy / Spearman correlation / NDCG@k / top-k high-quality hit rate，而非绝对分数阈值。

### 11.6 Profile 专用输出 Schema

本 Profile 激活时，**覆盖** §5.1 标准 JSON 输出结构，改用如下三段式。`extraction_meta` 与 `validation_report` 保留（来自通用流水线），`data` 替换为 `records`：

```json
{
  "extraction_meta": { "...同 §5.1，锚点由 Stage 0 硬提取": "" },
  "paper_id": "{paper_id}",
  "records": [
    {
      "case_id": null,
      "visible_input": {
        "constraint_context": {
          "water_quality_and_pollutant": {
            "water_quality_profile": {
              "water_source_type": null,
              "ph_range": null,
              "temperature_range": null,
              "salinity_level": null,
              "typical_ion_composition": {},
              "organic_load": null,
              "microbial_activity": null,
              "special_characteristics": []
            },
            "pollutant_characteristics": [
              {
                "name": null,
                "cas_number": null,
                "typical_concentration": null,
                "pka_value": null,
                "dissociation_analysis": null,
                "charge_state": null,
                "molecular_size": null,
                "hydrophobicity": null,
                "special_properties": []
              }
            ]
          },
          "evaluation_weights": {
            "adsorption_performance": null,
            "structural_stability": null,
            "synthesis_feasibility": null,
            "economic_viability": null,
            "environmental_impact": null,
            "antimicrobial_property": null,
            "regenerability": null,
            "weight_adjustment_rationale": null
          },
          "design_guidelines": {
            "mandatory_requirements": [],
            "do_not_list": [],
            "recommended_approaches": [],
            "cautionary_notes": []
          }
        },
        "merged_proposals": [
          {
            "proposal_id": 1,
            "material_type": null,
            "chemical_formula": null,
            "element_composition": {},
            "active_sites": [],
            "pore_structure": {},
            "specific_surface_area": null,
            "morphology": null,
            "zeta_potential": null,
            "target_pollutant": null,
            "adsorption_performance": {
              "capacity_mg_g": null,
              "removal_rate": null,
              "kinetics": null
            },
            "design_rationale": null,
            "literature_support": [],
            "do_not_compliance": null
          }
        ]
      },
      "hidden_oracle_label": {
        "quality_tier": null,
        "quality_reason": null,
        "expected_rank_group": null,
        "noise_type": null,
        "corruption_fields": []
      },
      "source_trace": {
        "paper_title": null,
        "record_origin": "this_work | control | literature_comparison | synthetic_noise",
        "source_pages": [],
        "source_tables_or_figures": [],
        "evidence_text": [],
        "extraction_warnings": []
      }
    }
  ],
  "validation_report": { "...同 §5.1": "" }
}
```

### 11.7 Profile 与通用流水线的衔接

| 流水线阶段 | 本 Profile 的影响 |
|-----------|-------------------|
| Stage 0 文本锚定 | 不变（scripts/stage0_anchor.py），锚点（title/doi/authors/keywords）仍强制注入 |
| Stage 1 视觉精读 | 不变，data_page 仍经 Read → analyze_image 视觉精读（不可用时按 §4.4 降级） |
| Stage 2 合并提参 | **替换** `output_schema` 为 §11.6；将 §11.2–11.4 作为用户约束与领域启发注入 Prompt（由会话模型执行） |
| Stage 3 三级硬校验 | 不变（scripts/validate.py 自动识别 records[] schema）；对 `records[*].visible_input.merged_proposals[*].chemical_formula` 与 `target_pollutant` 执行实体存在性校验（`chemical_formula` 为空时回退校验 `material_type`）；对 `adsorption_performance.capacity_mg_g` 与 `removal_rate` 执行数值回溯校验 |

**校验失败处理**（validate.py 已实现，此处为协议要求）：
- Level 2 实体校验失败的 record 必须删除，并在 `extraction_meta.extraction_notes` 中记录
- Level 3 数值回溯失败但来自 `data_page` 的 → 保留，在 `source_trace.extraction_warnings` 中标注 `needs_review`
- `record_origin = literature_comparison` 的记录豁免 Level 3 数值回溯（数据本不在本文实验中）

### 11.8 典型触发示例

**用户输入示例**：
> 我要为 ADRMATS 评估智能体构建测试集，请从 `~/papers/` 的 PDF 中按 `high/low/noise` 三级提取，输出 `visible_input` + `hidden_oracle_label`。噪声样本占 10%，低质量占 20%，高质量占 70%。

**Agent 执行**：
1. 激活本 Profile（检测到 `visible_input` / `hidden_oracle_label` 关键词）
2. 对每篇 PDF 执行 Stage 0–3 通用流水线（Stage 0/3 用本技能脚本，Stage 1 走 Read → analyze_image）
3. Stage 2 使用 §11.6 的 Profile Schema，按 §11.2 规则拆分 records，按 §11.4 启发生成 `design_rationale` / `do_not_compliance`
4. Stage 3 运行 scripts/validate.py，按 §11.7 衔接规则自动校验（records[] schema 自动识别）
5. 合并所有 PDF 的 records 为最终测试集 JSON，由用户后续脚本挂接动态权重生成与质量标签采样
