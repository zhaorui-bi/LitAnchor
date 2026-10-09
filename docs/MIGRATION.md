# 🔄 从 OpenClaw + DashScope 版迁移到 ZCode 版（lit-extract）

原版 [paper-param-extractor](https://github.com/Water-Quality-Risk-Control-Engineering/paper-param-extractor)（OpenClaw Gateway + 阿里百炼 DashScope）与 ZCode 版是同一套 **文本锚定 + 视觉精读 + 三级硬校验** 流水线的两种执行通道。本文说明两者的概念对应、行为差异与迁移步骤。

**迁移能得到什么**：按量 API 费用 ¥0（内置视觉工具计费口径以 Z.ai 账单为准；原版实测约 ¥0.50-0.80/篇）、零配置（无 API Key、无网关）、入口就是 ZCode 会话。
**需要适应什么**：视觉通道换成 Z.ai 内置视觉工具（有账户级限流约束）、缓存格式不通用（重建很快，见下）。

## 1. 概念映射表

| OpenClaw + DashScope 版 | ZCode 版 | 说明 |
|--------------------------|----------|------|
| `openclaw gateway`（端口 18789）+ WebUI + TUI | ZCode 会话 | 对话即入口：无网关、无端口、无 Web 页面 |
| qwen3.6-plus VL（DashScope 多模态 API） | **Read 工具 + 内置 `analyze_image`** | Read 读取页面 PNG 获得 URL → `analyze_image` 视觉精读 |
| `scripts/preprocess.py` 的 API 段（`run_stage1_parallel` 调 DashScope） | 会话内视觉精读（Stage 1） | 原 API 调用段不再需要，由会话按 SKILL.md §2.3 逐页执行 |
| `openclaw.json` + `DASHSCOPE_API_KEY` 环境变量 | **无需配置** | 全程 ZCode 订阅，无按量付费 API（内置视觉工具计费口径以 Z.ai 账单为准） |
| `<paper>_visual_cache.json`（Stage 0 锚点 + Stage 1 视觉转录合一个文件） | **stage0 JSON + PNG 目录**：`<PDF>_stage0.json` + `<PDF>_pages/`（PNG 与可选的 `page_00N.md` 转录存档） | 缓存拆为三件套，锚点/分页/全文文本在 JSON，图像与转录按页存档，各自可独立复用 |
| Stage 0 文本锚定脚本段 | `scripts/stage0_anchor.py` | 本地 PyMuPDF，秒级、零 API |
| 三级校验脚本段 | `scripts/validate.py` | 本地纯标准库；自动识别标准 `data[]` 与 ADRMATS `records[]` 两种 schema |

## 2. 行为差异

### 2.1 缓存单元

- **原版**：单一 `<paper>_visual_cache.json` 同时承载锚点与视觉转录。
- **ZCode 版**：缓存 = stage0 JSON（锚点、分页、全文文本层）+ PNG 目录（`page_00N.png`）+ 可选逐页转录 `page_00N.md`。PNG 数量与 stage0 JSON 的 `data_page_nums` 一致时**禁止重跑** Stage 0；同一会话对同一 PDF 换字段重复提参只重跑 Stage 2–3。
- **原版缓存文件不能直接导入**（格式不同）。不必心疼：对原 PDF 重跑 Stage 0 是本地秒级、零 API 的操作，首次使用时自动生成。
- 注意：用 `--dpi 300` 重渲染时必须同时 `-o` 指定新的 stage0 JSON 输出路径，否则会覆盖默认路径下的原缓存 JSON。

### 2.2 并发与限流（最重要的行为差异）

原版 `preprocess.py` 可用 `--max-workers` 高并发打 DashScope，按量计费下并发瓶颈主要是账单。ZCode 版的 `analyze_image` 消耗的是**账户级共享配额**，并发必须克制：

1. **常规并发上限 3**，页与页/批与批之间留间隔；
2. 收到 **429 / 账户级限流**：并发立即降为 1，失败页按指数退避重试（45s 起步，单页至多约 6 次）；
3. **累计退避约 8–10 分钟仍未恢复**：停止重试，剩余 data_page 改用文本层兜底——图注/正文转述可查的数值正常提取，仅存在于图表中的置 `null`，`_source` 保留页码并写明"限流未视觉读取"；
4. 实战教训（Andersson 2026）：7 页一次性并发触发**账户级 429**，第 7 页累计退避约 8.5 分钟（6 次重试）仍未恢复，最终由文本层兜底、失败页写失败声明留痕。转录页清单务必逐字取自 stage0 JSON 的 `data_page_nums`，不要按页码顺序臆测。

多文献并行时，所有子代理**合计**的在途 `analyze_image` 调用同样受上述约束。

### 2.3 主文 + SI 合并建议

- **推荐**：主文与 SI 先用 PyMuPDF 合并为单一 PDF 再跑 Stage 0——页码连续后，SI 数值可正常通过 Level 3 回溯校验。实测对照（Andersson 2026）：仅跑 10 页主文时，85 项只在 SI 中才有的数据全部只能置 `null`。
- **不合并时**：主文与 SI 各自跑完整流水线，跨文档溯源用 `Supplementary, Table SN` 前缀区分；且 **SI 的提取结果必须用 SI 自己的 stage0 JSON 过 Stage 3**——若并入主文结果后仍按主文 stage0 校验，Level 3 会因主文文本层查不到这些数值而误判 `suspicious`。

### 2.4 其他差异

- **质量标记**：原版 README 口径三级（reliable / needs_review / suspicious）→ ZCode 版五级（新增 `inferred` 推断值、`unavailable` 不可用），`unavailable` 的两种成因（文献未提供 vs 视觉未读取）由 `_source` 原因说明区分。
- **异常处理**：新增限流兜底（见 §2.2）、锚点已知限制披露（`anchor_note`，如作者启发式漏人时以原文为准并记录差异）、纯扫描 PDF + 无视觉工具时终止流水线。
- **输出 schema**：兼容原版标准结构；`validate.py` 自动识别 ADRMATS `records[]`，`literature_comparison` 记录豁免 Level 3 回溯。

## 3. 迁移步骤（3 步）

**Step 1 · 安装 ZCode 版（原版可保留，两者共存互不干扰）**

```bash
cd LitAnchor
bash install.sh        # 安装/更新到 ~/.zcode/skills/lit-extract/，旧版自动备份
```

**Step 2 · 重建缓存（可选，也可留待首次使用时自动生成）**

原 `<paper>_visual_cache.json` 不兼容新缓存单元。对常用 PDF 重跑 Stage 0（本地秒级、零 API）：

```bash
python3 ~/.zcode/skills/lit-extract/scripts/stage0_anchor.py ~/papers/xxx.pdf
```

**Step 3 · 验证**

```bash
python3 tests/selftest.py    # 零 API；退出码 0 = 全部通过
```

再用一篇原版已提取过的 PDF（如 Andersson 2026）在 ZCode 会话里走一遍提参，与旧结果对照。参照基准：两版在 Andersson 2026 主文可核对范围内 **39/39 项一致**（见 [`docs/verification-andersson-2026.md`](./verification-andersson-2026.md)）。

## 4. 回退

```bash
bash install.sh --uninstall   # 卸载 ~/.zcode/skills/lit-extract/
```

原版 OpenClaw 部署（Gateway、`openclaw.json`、百炼 Key）不受任何影响，可随时切回。
