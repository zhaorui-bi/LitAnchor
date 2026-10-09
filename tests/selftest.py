#!/usr/bin/env python3
"""
LitExtract ZCode 工具包一键自测（零 API、无凭据；退出码 0 = 全部通过）

用法: python3 tests/selftest.py   （在包内任意位置均可运行，路径按 __file__ 推导）

测试项:
  1. 生成合成 6 页 PDF（标题/DOI/关键词页、正文页、表格+图注页、图形页、
     References 页、正文页）→ 运行 stage0_anchor.py → 断言分页
     2 data / 3 text / 1 skip、DOI 正确、data_page PNG 生成；
     并校验标题锚点修复（两行标题完整拼接、作者行/期刊栏不混入）与作者锚点。
  2. 构造三条记录的 result.json（文本层可回溯 / 仅图形页溯源 / 材料名全文
     未出现）→ 运行 validate.py → 断言 Level 1 PASS、删除 1 条、
     Level 3 reliable=1、needs_review=1。
  3. 真实论文回归（可选）: 若 LIT_EXTRACT_SELFTEST_PDF 环境变量指向的 PDF、
     或包内 tests/andersson_main.pdf 存在: stage0 后断言 anchor_title 含完整
     两段标题（标题锚点修复的回归验证）；两处均缺失则跳过（不算失败）。
  4. 输出每项 PASS/FAIL 与总结。

测试产物全部写入 tests/_artifacts/（已被 .gitignore 忽略）。

执行方式说明: 脚本以 importlib 加载被测脚本并调用其 main()（patch sys.argv，
捕获 SystemExit 退出码），与本机用 python3 直接运行同一 CLI 入口等价；
全程无 shell、无子进程、无网络、无凭据。
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
SCRIPTS = PKG / "scripts"
TEST = PKG / "tests"
ART = TEST / "_artifacts"
# 真实论文回归输入（Andersson 2026 主文，可选、不随包发布）:
#   1) 环境变量 LIT_EXTRACT_SELFTEST_PDF 指向本机任意路径的 PDF；或
#   2) 复制为包内 tests/andersson_main.pdf（.gitignore 已忽略，勿提交版权 PDF）。
# 两处均缺失时该回归项自动跳过（不算失败）。
ANDERSSON_PDF = Path(os.environ.get(
    "LIT_EXTRACT_SELFTEST_PDF", TEST / "andersson_main.pdf"))

SYN_DOI = "10.9999/ztest.2026.001"
SYN_TITLE_FULL = ("Removal of Perfluoroalkyl Substances from Contaminated Water Using "
                  "Novel Zirconium-Based Adsorbents: A Synthetic Benchmark Study")
SYN_AUTHORS = ["Wei Zhang", "Jing Liu", "Qian Sun"]
ANDERSSON_TITLE_PART1 = "Efficient Removal of Short-Chain Perfluoroalkyl Substances"
ANDERSSON_TITLE_PART2 = "by Cavity-Directed Aggregation in a Molecular Cage Host"

results = []


def record(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def run_script(script_path, cli_args):
    """进程内运行包内脚本: importlib 加载 → patch sys.argv → 调 main()。

    兼容两类脚本: 带 main() 入口的（stage0_anchor.py / validate.py）与
    脚本式顶层执行的（make_synthetic_pdf.py，加载即运行，无 main()）。
    返回 (exit_code, stdout+stderr 文本)；与命令行 python3 <脚本> <参数>
    走同一 argparse 入口与主流程。
    """
    spec = importlib.util.spec_from_file_location(script_path.stem + "__undertest",
                                                  script_path)
    module = importlib.util.module_from_spec(spec)
    buf_out, buf_err = io.StringIO(), io.StringIO()
    old_argv = sys.argv
    sys.argv = [str(script_path)] + [str(a) for a in cli_args]
    code = 0
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            spec.loader.exec_module(module)
            if hasattr(module, "main"):
                module.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = old_argv
    return code, (buf_out.getvalue() + buf_err.getvalue()).strip()


def tail(text, limit=300):
    return text[-limit:]


# ═══════════════════════════════════════════════════════════
# 测试 1: 合成 PDF → stage0_anchor.py
# ═══════════════════════════════════════════════════════════

def test_synthetic_stage0():
    print("── 测试 1: 合成 6 页 PDF → stage0_anchor.py ──")
    shutil.rmtree(ART, ignore_errors=True)
    ART.mkdir(parents=True)
    syn_pdf = ART / "synthetic_paper.pdf"

    code, out = run_script(TEST / "make_synthetic_pdf.py", [syn_pdf])
    if not record("合成 PDF 生成（6 页）",
                  code == 0 and syn_pdf.is_file(), tail(out)):
        return None

    code, out = run_script(SCRIPTS / "stage0_anchor.py",
                           [syn_pdf, "-o", ART / "syn_stage0.json",
                            "--pages-dir", ART / "syn_pages"])
    if not record("stage0_anchor.py 运行成功（退出码 0）", code == 0, tail(out)):
        return None

    s0 = json.loads((ART / "syn_stage0.json").read_text(encoding="utf-8"))
    types = [pt["type"] for pt in s0["page_types"]]
    data_n = types.count("data_page")
    text_n = types.count("text_page")
    skip_n = types.count("skip_page")
    record("分页 2 data / 3 text / 1 skip",
           data_n == 2 and text_n == 3 and skip_n == 1,
           f"实际 data={data_n} text={text_n} skip={skip_n} total={len(types)}")
    record("DOI 锚点正确", s0["anchor_doi"] == SYN_DOI, f"实际 {s0['anchor_doi']!r}")

    pngs = sorted((ART / "syn_pages").glob("page_*.png"))
    record("data_page PNG 生成（P3/P4）",
           {p.name for p in pngs} == {"page_003.png", "page_004.png"}
           and all(p.stat().st_size > 0 for p in pngs),
           f"实际 {[p.name for p in pngs]}")

    title = s0["anchor_title"]
    record("标题锚点修复: 两行标题完整拼接", title == SYN_TITLE_FULL, f"实际 {title!r}")
    record("标题未混入作者行/期刊栏行",
           "Wei Zhang" not in title and "Journal" not in title
           and "Research Article" not in title, f"{title[:60]!r}...")
    record("作者锚点不受拼接影响", s0["anchor_authors"] == SYN_AUTHORS,
           f"实际 {s0['anchor_authors']!r}")
    return s0


# ═══════════════════════════════════════════════════════════
# 测试 2: 三条记录 result.json → validate.py
# ═══════════════════════════════════════════════════════════

def test_validate(s0):
    print("── 测试 2: 三条记录 result.json → validate.py ──")
    if s0 is None:
        record("validate 流水线（依赖测试 1 的 stage0 产物）", False, "测试 1 未产出 stage0 JSON")
        return

    # 元数据直接取锚点值（Level 1 应 PASS）；三条记录分别命中
    # reliable / needs_review / Level 2 删除三种结局
    result = {
        "extraction_meta": {
            "source": s0["anchor_title"],
            "doi": s0["anchor_doi"],
            "authors": s0["anchor_authors"],
        },
        "data": [
            # 1) 98.2 在 P3 表格文本层 → Level 3 精确回溯 reliable
            {"chemical_formula": "PFBA", "removal_pct": "98.2",
             "_source": {"removal_pct": "Page 3, Table 1"}},
            # 2) 377.5 不在文本层（合成 PDF 专门避开 ±1% 区间），
            #    溯源指向 P4 图形页（data_page）→ needs_review
            {"chemical_formula": "PFOA", "uptake_mg_g": "377.5",
             "_source": {"uptake_mg_g": "Page 4, Figure 3"}},
            # 3) 材料名全文未出现 → Level 2 幻觉删除
            {"chemical_formula": "Unobtanium-X", "removal_pct": "55.5",
             "_source": {"removal_pct": "Page 3, Table 1"}},
        ],
    }
    result_path = ART / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    code, out = run_script(SCRIPTS / "validate.py",
                           [result_path, ART / "syn_stage0.json",
                            "-o", ART / "result_validated.json"])
    if not record("validate.py 运行成功（退出码 0）", code == 0, tail(out)):
        return
    v = json.loads((ART / "result_validated.json").read_text(encoding="utf-8"))
    rep = v["validation_report"]

    record("Level 1 元数据一致性 PASS", rep["level_1_metadata"] == "PASS",
           f"实际 {rep['level_1_metadata']!r}")
    record("Level 2 删除 1 条幻觉记录",
           rep["level_2_entities_removed"] == 1 and len(v["data"]) == 2,
           f"removed={rep['level_2_entities_removed']} 剩余 {len(v['data'])} 条")
    record("删的正是材料名未出现的记录",
           all(rec["chemical_formula"] != "Unobtanium-X" for rec in v["data"]),
           f"剩余 {[rec['chemical_formula'] for rec in v['data']]}")
    record("Level 3 reliable=1 / needs_review=1",
           rep["level_3_values_reliable"] == 1
           and rep["level_3_values_needs_review"] == 1,
           f"reliable={rep['level_3_values_reliable']} "
           f"needs_review={rep['level_3_values_needs_review']} "
           f"suspicious={rep['level_3_values_suspicious']}")
    record("记录级判定正确（reliable/needs_review 落点）",
           v["data"][0]["_quality"].get("removal_pct") == "reliable"
           and v["data"][1]["_quality"].get("uptake_mg_g") == "needs_review",
           f"q1={v['data'][0]['_quality']} q2={v['data'][1]['_quality']}")


# ═══════════════════════════════════════════════════════════
# 测试 3: 真实论文 Andersson 回归验证（文件缺失则跳过，不算失败）
# ═══════════════════════════════════════════════════════════

def test_andersson():
    print("── 测试 3: 真实论文标题锚点回归（Andersson）──")
    if not ANDERSSON_PDF.is_file():
        print(f"[SKIP] {ANDERSSON_PDF} 不存在，跳过该项断言（不算失败）")
        return
    code, out = run_script(SCRIPTS / "stage0_anchor.py",
                           [ANDERSSON_PDF, "-o", ART / "andersson_stage0.json",
                            "--pages-dir", ART / "andersson_pages"])
    if not record("真实 PDF stage0 运行成功（退出码 0）", code == 0, tail(out)):
        return
    a0 = json.loads((ART / "andersson_stage0.json").read_text(encoding="utf-8"))
    title = a0["anchor_title"]
    record("anchor_title 含完整两段标题（修复回归）",
           ANDERSSON_TITLE_PART1 in title and ANDERSSON_TITLE_PART2 in title,
           f"实际 {title!r}")
    record("anchor_title 未混入作者行", "Andersson" not in title, f"{title[:70]!r}...")


# ═══════════════════════════════════════════════════════════
# 总结
# ═══════════════════════════════════════════════════════════

def main():
    print(f"LitExtract ZCode 工具包自测 — {PKG}\n")
    s0 = test_synthetic_stage0()
    print()
    test_validate(s0)
    print()
    test_andersson()

    passed = sum(results)
    failed = len(results) - passed
    print("\n═══ 自测总结 ═══")
    print(f"共 {len(results)} 项: PASS {passed}, FAIL {failed}"
          + ("（另有 1 项真实论文回归按 SKIP 跳过）" if not ANDERSSON_PDF.is_file() else ""))
    print(f"测试产物目录: {ART}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
