#!/usr/bin/env python3
"""
LitExtract Stage 0 独立脚本 — 文本锚定 + 智能分页 + data_page 渲染（零 API）

分页判定（is_skip_page / is_data_page）与 title/doi/keywords 锚点提取逻辑
移植自 scripts/preprocess.py 的 run_stage0（保持一致），并修复其继承缺陷：
anchor_title 原实现取第 1 页前 10 个显著行中的最长单行，两行式标题会被
截断为较长的那一半（真实案例：Andersson 2026, DOI 10.1002/anie.202526027
的标题后半句 "by Cavity-Directed Aggregation in a Molecular Cage Host"
整行丢失）。现改为把第 1 页前若干显著行中的连续显著行合并为标题：以最长
单行为种子，相邻行足够长、且不似单位/日期/作者行时拼接并入；单行标题无
相邻可拼行，行为与原实现一致。anchor_authors 为第 1-2 页的启发式补充提取
（尽力而为，识别失败返回 []），扫描起点同步改为标题区间末行之后。

用法:
  python3 stage0_anchor.py <pdf> [-o 输出json] [--dpi 150] [--pages-dir 目录]

默认:
  输出 JSON → <pdf去后缀>_stage0.json
  页面 PNG  → <pdf去后缀>_pages/page_00N.png（N 为实际页码，仅渲染 data_page）

输出 JSON 字段:
  anchor_title / anchor_doi / anchor_authors / anchor_keywords
  page_types / pages_text / data_page_nums / total_pages
  pages_dir / preprocess_date

依赖: 标准库 + PyMuPDF (pip install pymupdf)

安全约束: 所有命令行路径统一经 resolve_path 规范化校验
（展开 ~ → realpath，拒绝 '..' 跳转组件与空字节，输入 PDF 必须存在），
文件写入仅发生在校验后的输出路径上。
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

try:
    import fitz  # PyMuPDF（新版包亦可用 import pymupdf，此处按源实现保持一致）
except ImportError:
    try:
        import pymupdf as fitz  # PyMuPDF >= 1.24 的新导入名
    except ImportError:
        print("ERROR: 缺少 PyMuPDF，请先安装: pip install pymupdf", file=sys.stderr)
        sys.exit(1)


def resolve_path(raw, must_exist=False, kind="路径"):
    """规范化并校验命令行路径，防止路径穿越。

    - 展开 ~，转为绝对真实路径（realpath）
    - 拒绝空字节与 '..' 跳转组件
    - must_exist=True 时要求为已存在的常规文件
    """
    if not raw or "\x00" in raw:
        sys.exit(f"ERROR: 非法{kind}: {raw!r}")
    if any(part == ".." for part in raw.split("/")):
        sys.exit(f"ERROR: {kind} 不允许包含 '..' 跳转组件: {raw}")
    path = os.path.realpath(os.path.abspath(os.path.expanduser(raw)))
    if must_exist and not os.path.isfile(path):
        sys.exit(f"ERROR: {kind} 不存在: {path}")
    return path


# ═══════════════════════════════════════════════════════════
# 分页判定 — 移植自 scripts/preprocess.py:54-94（逻辑一致）
# ═══════════════════════════════════════════════════════════

SKIP_KEYWORDS = ["References", "Bibliography", "REFERENCES", "BIBLIOGRAPHY",
                 "Supporting Information", "Electronic Supplementary Material"]
CRYSTAL_KEYWORDS = ["CCDC number", "CCDC ", "R1 =", "wR2 =", "Crystal system",
                    "Crystal data", "space group", "Rint", "Goodness-of-fit",
                    "Flack parameter", "Residual density"]
NMR_SKIP_MARKERS = [r"δ\s*/\s*ppm", r"δ\(ppm\)", r"chemical shift.*\(ppm\)",
                    r"\d+\.\d+\s*\([dtsm]\)", r"Hz,\s*\d+H"]


def is_skip_page(text: str) -> bool:
    """参考文献 / 晶体学参数 / NMR 峰列表页判定 — 同 preprocess.py:65-78"""
    stripped = text.strip()
    for kw in SKIP_KEYWORDS:
        if stripped.startswith(kw):
            return True
    crystal_score = sum(1 for kw in CRYSTAL_KEYWORDS if kw in text)
    if crystal_score >= 3:
        return True
    nmr_matches = sum(1 for pat in NMR_SKIP_MARKERS if re.search(pat, text, re.IGNORECASE))
    many_numbers = len(re.findall(r"\d+\.\d+", text)) > 15
    many_nmr_lines = len(re.findall(r"^\s*\d+\.\d+", text, re.MULTILINE)) > 5
    if (nmr_matches >= 2 and many_numbers) or many_nmr_lines:
        return True
    return False


def is_data_page(text: str, page_obj, page_num: int) -> bool:
    r"""图表页（data_page）判定 — 基于 preprocess.py:81-94，修正其正则缺陷：
    原式 `Fig\.|Tab\.` 中的 `\b` 在点号后遇空格即失配（"Fig. 4" 不命中），
    现改为点号可选 + 任意空白，Figure 4 / Fig. 4 / Fig.4 / Tab. 2 均命中。"""
    has_ft = bool(re.search(r"\b(?:Figure|Table|Fig|Tab|Scheme)\.?\s*[S]?\d+",
                            text, re.IGNORECASE))
    number_count = len(re.findall(r"\b\d+\.?\d*\b", text))
    try:
        images = page_obj.get_images(full=True)
        total_img_size = sum(img[2] for img in images if len(img) > 2)
    except Exception:
        total_img_size = 0
    if page_num <= 10:
        return has_ft
    if total_img_size > 50000 and has_ft and number_count > 2:
        return True
    return False


# ═══════════════════════════════════════════════════════════
# anchor_authors 启发式 — 标题区间之后、单位/摘要之前的连续作者行
# （SKILL.md §2.2 要求锚点含作者；preprocess.py 未实现，此处尽力补充）
# ═══════════════════════════════════════════════════════════

# 命中任一小写子串 → 判定为单位/页眉杂行，终止作者行扫描
AFFILIATION_STOP_HINTS = ("university", "institute", "department", "school", "academy",
                          "laborator", "college", "center", "centre", "research",
                          "corresponding", "email", "e-mail", "@", "abstract",
                          "keywords", "received", "accepted", "published", "citation",
                          "doi", "http", "www.", "issn", "vol.", "article",
                          "highlights", "elsevier", "springer", "wiley")

# 明显是栏目名而非人名的词（小写比较）
SECTION_STOPWORDS = {"abstract", "keywords", "introduction", "highlights", "graphical",
                     "contents", "article", "letter", "communication", "corresponding",
                     "author", "authors", "professor", "editor", "frontiers"}

# 人名词形：大写开头词 / 缩写（J.）/ 常见小写姓氏前缀（van, de, al 等）
NAME_WORD_RE = re.compile(
    r"^(?:[A-Z]\.|[A-Z][a-zA-Z'\u2019\-\.]*|van|von|de|del|della|der|den|da|dos|el|al|bin|ibn|le|la|du|di)$")


def _split_author_line(line):
    """把一行文本解析为作者名列表；不像作者行则返回 None。

    允许 "Wei Zhang, Jing Liu1 and Qian Sun*" 这类带上标标记、逗号/and 分隔的行。
    """
    cleaned = re.sub(r"[\d\*\u2020\u2021\u00a7\u00b6]+", "", line).strip(" ,;.\u2013\u2014-")
    if not cleaned or len(cleaned) < 3:
        return None
    parts = [p.strip() for p in re.split(r",|;|\band\b|&", cleaned) if p.strip()]
    if not parts:
        return None
    names = []
    for p in parts:
        words = p.split()
        if not 1 <= len(words) <= 5:
            return None
        for w in words:
            if w.lower().strip(".") in SECTION_STOPWORDS:
                return None
            if not NAME_WORD_RE.match(w):
                return None
        names.append(" ".join(words))
    if len(names) == 1 and len(names[0].split()) == 1:
        return None  # 单个孤词无法与普通标题词区分，不采信
    return names


def extract_anchor_authors(pages_text):
    """尽力从第 1-2 页提取作者列表：标题区间（与 anchor_title 同规则）末行
    之后、首个非作者行/单位行之前的连续作者行。失败返回 []。"""
    for page in pages_text[:2]:
        lines = [l.strip() for l in page["text"].split("\n") if l.strip()]
        _, _, title_end = extract_title_span(lines)
        if title_end == 0:
            continue
        authors = _scan_author_lines(lines[title_end:title_end + 10])
        if authors:
            return authors
    return []


def _scan_author_lines(candidate_lines):
    """从候选行里收集连续作者行（标题区后允许跳过偶发杂行，收集到作者行后
    遇到首个非作者行即终止）。"""
    authors = []
    for line in candidate_lines:
        if len(line) > 300:
            break
        if any(h in line.lower() for h in AFFILIATION_STOP_HINTS):
            break
        names = _split_author_line(line)
        if names is None:
            if authors:
                break  # 已收集到作者行，遇到首个非作者行即终止
            continue  # 标题后偶有期刊栏等杂行，允许跳过继续找
        authors.extend(names)
    if authors:
        seen, uniq = set(), []
        for a in authors:
            if a not in seen:
                seen.add(a)
                uniq.append(a)
        return uniq
    return []


# ═══════════════════════════════════════════════════════════
# anchor_title 提取 — 修复自 preprocess.py 继承的多行标题截断缺陷
#
# preprocess.py（及本脚本早期版本）取第 1 页前 10 个显著行中的最长单行作
# 标题，两行式标题只剩较长的一半。现以最长单行为种子，向上下相邻显著行
# 扩展：相邻行足够长（>= TITLE_MERGE_MIN_LEN 且 >= 种子行一半长）、且不
# 似单位/日期/期刊栏行、不似作者行时，拼接并入标题。单行标题无相邻可拼
# 行，输出与原实现一致。
# ═══════════════════════════════════════════════════════════

TITLE_SUBSTANTIAL_MIN = 10   # 显著行门槛（同原实现的 len > 10）
TITLE_WINDOW = 10            # 只在前 10 个显著行范围内取标题（同原实现）
TITLE_MERGE_MIN_LEN = 25     # 参与拼接的相邻行最低字符数

# 标题行不应命中的期刊栏/收稿日期模式（小写子串或正则）
TITLE_BLOCK_HINTS = AFFILIATION_STOP_HINTS + (
    "journal", "how to cite", "cite:", "available online", "issue")
TITLE_DATE_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
    r"|\b(?:received|revised|accepted|published)\b", re.IGNORECASE)


def _is_title_blocker(line: str) -> bool:
    """单位 / 期刊栏 / 收稿日期行判定——这类行不参与标题拼接。"""
    low = line.lower()
    return (any(h in low for h in TITLE_BLOCK_HINTS)
            or bool(TITLE_DATE_RE.search(line)))


def _mergeable_title_line(line: str, seed_len: int) -> bool:
    """相邻行是否可并入标题：足够长、且不似单位/日期/期刊栏/作者行。"""
    l = line.strip()
    return (len(l) >= TITLE_MERGE_MIN_LEN
            and len(l) >= 0.5 * seed_len
            and not _is_title_blocker(l)
            and _split_author_line(l) is None)


def extract_title_span(lines):
    """从第 1 页（已 strip 去空行）行列表提取标题。

    返回 (title, start_idx, end_idx)：end_idx 为标题区间末行的下一行下标
    （供作者行扫描衔接）；无显著行时返回 ("", 0, 0)。
    """
    substantial = [i for i, l in enumerate(lines) if len(l.strip()) > TITLE_SUBSTANTIAL_MIN]
    window = set(substantial[:TITLE_WINDOW])
    if not window:
        return "", 0, 0
    seed = max(window, key=lambda i: len(lines[i]))
    seed_len = len(lines[seed])
    lo = hi = seed
    while (hi + 1) in window and _mergeable_title_line(lines[hi + 1], seed_len):
        hi += 1
    while (lo - 1) in window and _mergeable_title_line(lines[lo - 1], seed_len):
        lo -= 1
    title = " ".join(l.strip() for l in lines[lo:hi + 1])
    return title, lo, hi + 1


# ═══════════════════════════════════════════════════════════
# Stage 0 主流程
# ═══════════════════════════════════════════════════════════

def run_stage0(pdf_path: str, dpi: int, pages_dir: str) -> dict:
    doc = fitz.open(pdf_path)
    pages_text, page_types = [], []
    for i, page in enumerate(doc):
        text = page.get_text()
        pages_text.append({"page": i + 1, "text": text})
        if is_skip_page(text):
            page_types.append({"page": i + 1, "type": "skip_page"})
        elif is_data_page(text, page, i + 1):
            page_types.append({"page": i + 1, "type": "data_page"})
        else:
            page_types.append({"page": i + 1, "type": "text_page"})

    # ── 锚点提取（同 preprocess.py:110-117；DOI 去掉正则捕获的尾部标点）──
    front_text = " ".join(p["text"] for p in pages_text[:3])
    doi_match = re.search(r"10\.\d{4,}/[^\s]+", front_text)
    anchor_doi = doi_match.group(0).rstrip(".,;)") if doi_match else None
    # anchor_title: 连续显著行合并（修复 preprocess.py 继承的单行截断缺陷，
    # 详见 extract_title_span docstring；单行标题行为不变）
    page1_lines = [l.strip() for l in pages_text[0]["text"].split("\n") if l.strip()]
    anchor_title, _, _ = extract_title_span(page1_lines)
    kw_match = re.search(r"(?:Keywords|KEYWORDS)[:：]\s*(.+)", front_text, re.IGNORECASE)
    anchor_keywords = ([k.strip().rstrip(".") for k in kw_match.group(1).split(",")]
                       if kw_match else [])
    anchor_keywords = [k for k in anchor_keywords if k]
    anchor_authors = extract_anchor_authors(pages_text)

    # ── 渲染 data_page → PNG（按实际页码命名，供视觉精读 / 溯源复核）──
    os.makedirs(pages_dir, exist_ok=True)
    data_page_nums = [pt["page"] for pt in page_types if pt["type"] == "data_page"]
    for pg in data_page_nums:
        pix = doc[pg - 1].get_pixmap(dpi=dpi)
        pix.save(os.path.join(pages_dir, f"page_{pg:03d}.png"))

    text_count = sum(1 for pt in page_types if pt["type"] == "text_page")
    skip_count = sum(1 for pt in page_types if pt["type"] == "skip_page")

    # ── 控制台摘要 ──
    print(f"Stage 0: {len(doc)} pages → {len(data_page_nums)} data, "
          f"{text_count} text, {skip_count} skip")
    print(f"  Title:    {anchor_title[:80]}")
    print(f"  DOI:      {anchor_doi or '(未识别)'}")
    print(f"  Authors:  {', '.join(anchor_authors) if anchor_authors else '(未识别)'}")
    print(f"  Keywords: {', '.join(anchor_keywords) if anchor_keywords else '(未识别)'}")
    print(f"  Rendered {len(data_page_nums)} data pages @ {dpi} DPI → {pages_dir}")
    doc.close()

    return {
        "anchor_title": anchor_title,
        "anchor_doi": anchor_doi,
        "anchor_authors": anchor_authors,
        "anchor_keywords": anchor_keywords,
        "page_types": page_types,
        "pages_text": pages_text,
        "data_page_nums": data_page_nums,
        "total_pages": len(pages_text),
        "pages_dir": pages_dir,
        "preprocess_date": date.today().isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LitExtract Stage 0 独立版 — 文本锚定 + 智能分页 + data_page 渲染（零 API）")
    parser.add_argument("pdf", help="PDF 文件路径（不允许包含 '..' 跳转组件）")
    parser.add_argument("-o", "--output", default=None,
                        help="输出 JSON 路径（默认 <pdf去后缀>_stage0.json）")
    parser.add_argument("--dpi", type=int, default=150,
                        help="data_page 渲染 DPI（默认 150）")
    parser.add_argument("--pages-dir", default=None,
                        help="PNG 输出目录（默认 <pdf去后缀>_pages）")
    args = parser.parse_args()

    pdf_path = resolve_path(args.pdf, must_exist=True, kind="PDF")
    stem = os.path.splitext(pdf_path)[0]
    output_path = (resolve_path(args.output, kind="输出JSON") if args.output
                   else stem + "_stage0.json")
    pages_dir = (resolve_path(args.pages_dir, kind="PNG目录") if args.pages_dir
                 else stem + "_pages")

    stage0 = run_stage0(pdf_path, args.dpi, pages_dir)
    Path(output_path).write_text(
        json.dumps(stage0, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Stage 0 JSON saved to: {output_path}")


if __name__ == "__main__":
    main()
