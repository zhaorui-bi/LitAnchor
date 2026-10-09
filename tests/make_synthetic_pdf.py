#!/usr/bin/env python3
"""生成 6 页合成论文 PDF，用于 LitExtract ZCode 移植版端到端测试。

用法: python3 make_synthetic_pdf.py [输出PDF路径]
      默认输出 tests/_artifacts/synthetic_paper.pdf（目录自动创建）

页面设计与 stage0_anchor.py 分页规则的对应关系：
  P1 text_page  — 标题 + 作者 + DOI + Keywords + 摘要（无 Figure/Table 标记；
                  标题为两行显著行，供 anchor_title 连续行拼接与
                  anchor_authors 提取）
  P2 text_page  — 纯正文段落（无任何图表标记）
  P3 data_page  — 正文含 "Table 1" + 三行迷你表格 + "Figure 2" 图注
  P4 data_page  — draw_rect/draw_circle 画的假图表 + "Figure 3" 图注
  P5 skip_page  — 以 "References" 开头的参考文献页
  P6 text_page  — 纯正文段落

文本层还满足 validate.py 的测试需要：
  - PFBA/PFOA/PFOS 全文出现 >=3 次（Level 2 不标 suspicious）
  - 98.2/412/96.5/388/91.0/356 出现在 P3 文本层（Level 3 精确回溯）
  - 全文无 377.5±1% 区间内的数值（needs_review 用例的探针值）
"""
import sys
from pathlib import Path

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 推荐导入名（避免 fitz 弃用告警）
except ImportError:  # 兼容仅提供旧别名的旧版包
    import fitz

DEFAULT_OUT = Path(__file__).resolve().parent / "_artifacts" / "synthetic_paper.pdf"

out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
out.parent.mkdir(parents=True, exist_ok=True)

doc = fitz.open()
W, H = 612, 792  # US Letter (points)


def line(page, x, y, text, size=11, font="helv", bold=False):
    page.insert_text((x, y), text, fontsize=size, fontname=font if not bold else "hebo")


# ── P1: 标题页（text_page）────────────────────────────────────
p1 = doc.new_page(width=W, height=H)
line(p1, 72, 56, "ZCode Synthetic Test Journal", 10)
line(p1, 72, 80, "Research Article", 10)
line(p1, 72, 116, "Removal of Perfluoroalkyl Substances from Contaminated Water Using",
     16, bold=True)
line(p1, 72, 138, "Novel Zirconium-Based Adsorbents: A Synthetic Benchmark Study",
     16, bold=True)
line(p1, 72, 166, "Wei Zhang, Jing Liu and Qian Sun", 12)
line(p1, 72, 186, "Synthetic Test Institute of Environmental Engineering", 10)
line(p1, 72, 201, "Testcity 000000, China", 10)
line(p1, 72, 220, "Correspondence: zcode-synth@example.org", 10)
line(p1, 72, 244, "DOI: 10.9999/ztest.2026.001", 11)
line(p1, 72, 266, "Keywords: PFAS, adsorption, zirconium", 11)
p1.insert_textbox(
    fitz.Rect(72, 292, 540, 460),
    "Abstract: This synthetic article is generated for end-to-end testing of the "
    "parameter extraction pipeline. Perfluoroalkyl substances including PFBA, PFOA "
    "and PFOS are persistent contaminants of concern. We describe a zirconium-based "
    "adsorbent evaluated under controlled synthetic conditions across six pages of "
    "machine-generated text. All content is fictitious and exists solely for "
    "software validation purposes.",
    fontsize=10.5, fontname="helv", align=0)

# ── P2: 纯正文（text_page）───────────────────────────────────
p2 = doc.new_page(width=W, height=H)
p2.insert_textbox(
    fitz.Rect(72, 90, 540, 400),
    "The persistence of PFBA in surface water has been documented across many "
    "regions. In the present synthetic study, PFBA served as a short-chain probe "
    "compound. The behaviour of PFOA was contrasted with that of PFBA to quantify "
    "chain-length effects during uptake experiments.\n\n"
    "Batch experiments were simulated with fixed initial concentrations and a "
    "constant temperature. The synthetic narrative deliberately keeps this page "
    "free of any graphic element. Replicate variability was negligible by "
    "construction. All statements on this page are filler prose used only for "
    "pagination testing.",
    fontsize=11, fontname="helv", align=0)

# ── P3: 迷你表格页（data_page）───────────────────────────────
p3 = doc.new_page(width=W, height=H)
line(p3, 72, 90, "Table 1 summarizes the synthetic uptake metrics for the three probe compounds.", 11)
ty = 130
line(p3, 72, ty, "Compound    Removal (%)    Uptake (mg/kg)", 11, bold=True)
p3.draw_line(fitz.Point(72, ty + 8), fitz.Point(400, ty + 8))
rows = [("PFBA", "98.2", "412"), ("PFOA", "96.5", "388"), ("PFOS", "91.0", "356")]
for i, (name, pct, cap) in enumerate(rows):
    y = ty + 32 + i * 24
    line(p3, 72, y, f"{name}    {pct}    {cap}", 11)
line(p3, 72, ty + 120, "The ranking PFBA > PFOA > PFOS held across all synthetic replicates.", 11)
line(p3, 72, ty + 156, "Figure 2. Distribution of synthetic uptake values across the probe series.", 11)

# ── P4: 假图表页（data_page）─────────────────────────────────
p4 = doc.new_page(width=W, height=H)
line(p4, 72, 90, "Figure 3. Synthetic kinetic curves for the zirconium adsorbent.", 12, bold=True)
# 坐标轴
ox, oy, ax_h, ax_w = 110, 420, 280, 380
p4.draw_line(fitz.Point(ox, oy - ax_h), fitz.Point(ox, oy))            # y 轴
p4.draw_line(fitz.Point(ox, oy), fitz.Point(ox + ax_w, oy))            # x 轴
# 假柱状图（draw_rect）
for i, h in enumerate([80, 150, 230, 180, 120]):
    p4.draw_rect(fitz.Rect(ox + 30 + i * 70, oy - h, ox + 80 + i * 70, oy),
                 color=(0.1, 0.3, 0.7), fill=(0.5, 0.7, 0.9))
# 假数据点 + 趋势线（draw_circle）
pts = [fitz.Point(ox + 55 + i * 70, oy - (90 + i * 38)) for i in range(5)]
for pt in pts:
    p4.draw_circle(pt, 5, color=(0.8, 0.2, 0.2), fill=(0.9, 0.4, 0.4))
for a, b in zip(pts, pts[1:]):
    p4.draw_line(a, b, color=(0.8, 0.2, 0.2))
# 轴刻度文字（避开 377.5±1% 区间）
for i, v in enumerate(["0", "50", "100"]):
    line(p4, 84, oy - i * 140 + 4, v, 9)
for i, lbl in enumerate(["A", "B", "C", "D", "E"]):
    line(p4, ox + 42 + i * 70, oy + 20, lbl, 9)
line(p4, 110, 460, "uptake increases monotonically in the synthetic series", 10)

# ── P5: 参考文献页（skip_page）───────────────────────────────
p5 = doc.new_page(width=W, height=H)
line(p5, 72, 90, "References", 13, bold=True)
refs = [
    "[1] A. Author, B. Writer, Synthetic studies of adsorption equilibria, "
    "J. ZCode Test. 12 (2019) 45-52.",
    "[2] C. Author, D. Writer, Perfluorinated compounds in aquatic systems, "
    "J. ZCode Test. 13 (2020) 88-94.",
    "[3] E. Author, F. Writer, Zirconium materials for water remediation, "
    "J. ZCode Test. 14 (2021) 7-15.",
]
for i, r in enumerate(refs):
    line(p5, 72, 120 + i * 30, r, 10.5)

# ── P6: 纯正文（text_page）───────────────────────────────────
p6 = doc.new_page(width=W, height=H)
p6.insert_textbox(
    fitz.Rect(72, 90, 540, 400),
    "Discussion continues with further synthetic prose. The removal ranking "
    "observed for PFOS remained stable in extended simulated runs. No numeric "
    "claims are attached to this paragraph beyond the year of the simulated "
    "campaign, which was 2025. This final page exists to confirm that trailing "
    "narrative pages are classified as ordinary reading material.",
    fontsize=11, fontname="helv", align=0)

doc.save(str(out), garbage=4, deflate=True)
print(f"saved {out} with {doc.page_count} pages")
doc.close()
