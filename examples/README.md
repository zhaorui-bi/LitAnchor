# 案例文件说明（Andersson 2026 真实验证）

| 文件 | 说明 |
|------|------|
| `andersson_result_validated.json` | ZCode 版流水线的提取结果（主文 10 页，三级校验后） |
| `andersson_expected.json` | 原 OpenClaw+DashScope 版对同一论文的期望结果（主文+74 页 SI） |

两个文件可独立复算对照结论；逐项对照报告（39/39 主文可核对一致、85 项仅 SI 未核对、
2 处期望文件自身错误）移至 [`../docs/verification-andersson-2026.md`](../docs/verification-andersson-2026.md)。
原始运行现场（stage0、页面转录、原始 PDF）在父仓库
`agents/verify-andersson/`，未随包发布以控制体积。
