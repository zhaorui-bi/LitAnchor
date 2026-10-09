#!/usr/bin/env python3
"""
LitExtract Stage 3 独立脚本 — 三级硬校验（本地、零 API）

实现 SKILL.md §3 的三级硬校验协议，校验基准为 stage0_anchor.py 输出的
pages_text 全文文本；同时兼容两种提参 schema:
  - 标准 §5.1: 顶层 data[] 数组
  - ADRMATS §11.6: 顶层 records[]，校验目标在
    records[*].visible_input.merged_proposals[*]

三级校验内容:
  Level 1 元数据一致性 — extraction_meta.source/doi/authors 对照锚点，
      不符则替换为锚点值并记录；标题+DOI+作者全都不符（非缺失）时
      在 validation_report 标记整体幻觉风险（overall_hallucination_risk）。
  Level 2 实体存在性 — 材料/污染物实体在全文中出现 0 次 → 删除该记录并
      写入 extraction_notes；出现 < 3 次 → 标 suspicious。
  Level 3 数值回溯 — 数值字段转字符串在全文精确查找；找不到做 ±1% 相对
      近似匹配；仍找不到但该值溯源指向 data_page → needs_review；
      都找不到 → suspicious。

ADRMATS 衔接（§11.7）:
  - 实体校验对象: chemical_formula（空则回退 material_type）与 target_pollutant
  - 数值回溯对象: adsorption_performance.capacity_mg_g 与 removal_rate
  - record_origin = literature_comparison 的记录豁免 Level 3
  - 删除记录写入 extraction_meta.extraction_notes；
    needs_review / suspicious 写入 source_trace.extraction_warnings

用法:
  python3 validate.py <result.json> <stage0.json> [-o 输出json]

默认输出: <result去后缀>_validated.json（输入文件旁，不覆盖原文件）。
退出码: 0 = 校验完成（含发现可疑项）；1 = 输入/参数错误。

安全约束: 命令行路径统一经 resolve_path 规范化校验（拒绝 '..' 跳转组件
与空字节，输入文件必须存在），读写仅发生在校验后的路径上。
"""

import argparse
import bisect
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 路径校验（与 stage0_anchor.py 相同约定）
# ═══════════════════════════════════════════════════════════


def resolve_path(raw, must_exist=False, kind="路径"):
    """规范化并校验命令行路径，防止路径穿越（拒绝 '..' 组件与空字节）。"""
    if not raw or "\x00" in raw:
        sys.exit(f"ERROR: 非法{kind}: {raw!r}")
    if any(part == ".." for part in raw.split("/")):
        sys.exit(f"ERROR: {kind} 不允许包含 '..' 跳转组件: {raw}")
    path = os.path.realpath(os.path.abspath(os.path.expanduser(raw)))
    if must_exist and not os.path.isfile(path):
        sys.exit(f"ERROR: {kind} 不存在: {path}")
    return path


# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

# 实体字段候选（标准 schema 中为用户自定义字段，按常见命名逐一探测）
MATERIAL_KEYS = ["chemical_formula", "material_type", "material",
                 "adsorbent_name", "adsorbent"]
POLLUTANT_KEYS = ["target_pollutant", "pollutant_name", "pollutant", "contaminant"]

# 实体关键词/标题匹配时的结构停用词
TOKEN_STOPWORDS = {"and", "or", "the", "a", "an", "of", "with", "for", "from",
                   "via", "using", "based"}

VERDICT_REPORT_KEY = {
    "reliable": "level_3_values_reliable",
    "needs_review": "level_3_values_needs_review",
    "suspicious": "level_3_values_suspicious",
    "unavailable": "level_3_values_unavailable",
}


# ═══════════════════════════════════════════════════════════
# 基准文本索引（Stage 0 全文）
# ═══════════════════════════════════════════════════════════

class TextIndex:
    """全文缓存: 原文（精确子串匹配）、小写文（实体计数）、数值集合（±1% 匹配）。"""

    def __init__(self, full_text: str):
        self.full_text = full_text
        self.lower_text = full_text.lower()
        self.nums = sorted(set(float(m)
                               for m in re.findall(r"-?\d+(?:\.\d+)?", full_text)))

    def exact_substring(self, candidates) -> bool:
        return any(c in self.full_text for c in candidates)

    def within_1pct(self, num: float) -> bool:
        """全文中是否存在落在 [num*0.99, num*1.01] 区间内的数值。"""
        if not self.nums:
            return False
        tol = abs(num) * 0.01 + 1e-12
        i = bisect.bisect_left(self.nums, num - tol)
        return i < len(self.nums) and self.nums[i] <= num + tol


def build_context(stage0: dict):
    """由 stage0.json 构造 (全文, data_page 页码集合)。"""
    pages_text = stage0.get("pages_text") or []
    full_text = "\n".join(p.get("text", "")
                          for p in pages_text if isinstance(p, dict))
    data_pages = set()
    for x in stage0.get("data_page_nums") or []:
        try:
            data_pages.add(int(x))
        except (TypeError, ValueError):
            pass
    for pt in stage0.get("page_types") or []:
        if isinstance(pt, dict) and pt.get("type") == "data_page":
            try:
                data_pages.add(int(pt.get("page")))
            except (TypeError, ValueError):
                pass
    return full_text, data_pages


# ═══════════════════════════════════════════════════════════
# Level 1 — 元数据一致性（SKILL.md §3.1）
# ═══════════════════════════════════════════════════════════

def normalize_doi(doi) -> str:
    if not isinstance(doi, str):
        return ""
    d = doi.strip().lower()
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d.rstrip(".,;)")


def title_match_fraction(source: str, anchor_title: str) -> float:
    """source 覆盖 anchor_title 主要词组的比例（§3.1: 必须包含主要词组）。"""
    toks = [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]*", anchor_title)
            if len(t) >= 3 and t.lower() not in TOKEN_STOPWORDS]
    if not toks:
        return 1.0 if source.strip() else 0.0
    s = source.lower()
    return sum(1 for t in toks if t in s) / len(toks)


def meta_first_author(authors) -> str:
    if isinstance(authors, list):
        first = str(authors[0]) if authors else ""
    elif isinstance(authors, str):
        first = authors
    else:
        first = ""
    return re.split(r",|;|\band\b", first)[0].strip()


def author_first_match(meta_first: str, anchor_first: str) -> bool:
    a = re.sub(r"[^a-z]", "", (meta_first or "").lower())
    b = re.sub(r"[^a-z]", "", (anchor_first or "").lower())
    if not a or not b:
        return False
    return a in b or b in a


def run_level1(result: dict, stage0: dict, report: dict, notes: list) -> None:
    meta = result.get("extraction_meta")
    if not isinstance(meta, dict):
        meta = {}
        result["extraction_meta"] = meta

    anchor_title = (stage0.get("anchor_title") or "").strip()
    anchor_doi = (stage0.get("anchor_doi") or "").strip()
    anchor_authors = stage0.get("anchor_authors") or []

    status = {}  # 每项: pass / mismatch / missing / skipped

    # source 对照 anchor_title
    source = str(meta.get("source") or "")
    if not anchor_title:
        status["title"] = "skipped"
        report["level_1_details"].append("标题锚点为空，跳过 source 校验")
    elif title_match_fraction(source, anchor_title) >= 0.5:
        status["title"] = "pass"
    else:
        meta["source"] = anchor_title
        status["title"] = "mismatch" if source.strip() else "missing"
        report["level_1_details"].append(
            f"source 与锚点标题不符，已替换为 anchor_title（原值: {source[:60] or '空'}）")

    # doi 对照 anchor_doi
    doi = str(meta.get("doi") or "")
    if not anchor_doi:
        status["doi"] = "skipped"
        report["level_1_details"].append("DOI 锚点为空，跳过 doi 校验")
    elif normalize_doi(doi) and normalize_doi(doi) == normalize_doi(anchor_doi):
        status["doi"] = "pass"
    else:
        meta["doi"] = anchor_doi
        status["doi"] = "mismatch" if doi.strip() else "missing"
        report["level_1_details"].append(
            f"doi 与锚点不符，已替换为 anchor_doi（原值: {doi or '空'}）")

    # authors 第一作者对照 anchor_authors[0]
    authors = meta.get("authors")
    if not anchor_authors:
        status["authors"] = "skipped"
        report["level_1_details"].append("作者锚点为空，跳过 authors 校验")
    elif author_first_match(meta_first_author(authors), str(anchor_authors[0])):
        status["authors"] = "pass"
    else:
        meta["authors"] = anchor_authors
        had_value = bool(meta_first_author(authors))
        status["authors"] = "mismatch" if had_value else "missing"
        orig = authors if isinstance(authors, str) else json.dumps(
            authors, ensure_ascii=False)[:60] if authors else "空"
        report["level_1_details"].append(
            f"authors 第一作者与锚点不符，已替换为 anchor_authors（原值: {orig}）")

    # 整体幻觉风险: 标题+DOI+作者三项均为"实际值不符"（缺失不算幻觉证据）
    hard_fails = [k for k in ("title", "doi", "authors") if status.get(k) == "mismatch"]
    fixed = [k for k in ("title", "doi", "authors")
             if status.get(k) in ("mismatch", "missing")]
    if len(hard_fails) == 3:
        report["overall_hallucination_risk"] = True
        report["level_1_metadata"] = "FAIL_OVERALL_HALLUCINATION_RISK"
        msg = ("元数据校验全部失败（标题+DOI+作者均与锚点不符）：提取结果整体存在"
               "幻觉风险，建议丢弃本次结果并重新执行 Stage 2 提参（SKILL.md §3.1/§8）")
        report["level_1_details"].append(msg)
        notes.append(msg)
    elif fixed:
        report["level_1_metadata"] = f"PARTIAL_FIXED ({len(fixed)} 项已替换为锚点值)"
    else:
        report["level_1_metadata"] = "PASS"


# ═══════════════════════════════════════════════════════════
# Level 2 — 实体存在性（SKILL.md §3.2）
# ═══════════════════════════════════════════════════════════

def entity_keywords(entity: str) -> list:
    """实体字符串 → 关键词列表（保留 ZIF-8 等连字符整体词，剔除结构停用词）。"""
    if not isinstance(entity, str):
        return []
    toks = re.findall(r"[A-Za-z][A-Za-z0-9]*(?:[-\u2013][A-Za-z0-9]+)*", entity)
    kws = [t for t in toks if len(t) >= 2 and t.lower() not in TOKEN_STOPWORDS]
    return kws or [t for t in toks if len(t) >= 2]


def entity_count(entity: str, idx: TextIndex) -> int:
    """实体在全文中的出现次数 = 各关键词出现次数的最大值（取最常用称谓）。"""
    kws = entity_keywords(entity)
    if not kws:
        return 0
    return max(idx.lower_text.count(k.lower()) for k in kws)


def run_level2_standard(result: dict, idx: TextIndex, report: dict, notes: list) -> None:
    kept = []
    for i, rec in enumerate(result.get("data") or []):
        if not isinstance(rec, dict):
            kept.append(rec)
            continue
        ents = [(k, str(rec[k]).strip()) for k in MATERIAL_KEYS + POLLUTANT_KEYS
                if isinstance(rec.get(k), str) and rec[k].strip()]
        report["level_2_entities_checked"] += len(ents)
        counts = {k: entity_count(v, idx) for k, v in ents}
        zero = [(k, v) for k, v in ents if counts[k] == 0]
        if zero:
            k, v = zero[0]
            notes.append(f"已删除: 记录{i + 1} 实体 '{v}'（字段 {k}）在原文中未出现（幻觉）")
            report["level_2_entities_removed"] += 1
            continue  # 删除该记录
        kept.append(rec)
        rec.setdefault("_quality", {})
        for k, v in ents:
            if 0 < counts[k] < 3:
                rec["_quality"][k] = "suspicious"
                report["level_2_entities_suspicious"] += 1
    result["data"] = kept


def _proposals(rec: dict) -> list:
    vi = rec.get("visible_input")
    if not isinstance(vi, dict):
        return []
    mp = vi.get("merged_proposals")
    return [p for p in mp if isinstance(p, dict)] if isinstance(mp, list) else []


def _warnings(rec: dict) -> list:
    trace = rec.get("source_trace")
    if not isinstance(trace, dict):
        trace = {}
        rec["source_trace"] = trace
    w = trace.get("extraction_warnings")
    if not isinstance(w, list):
        w = []
        trace["extraction_warnings"] = w
    return w


def run_level2_adrmats(result: dict, idx: TextIndex, report: dict, notes: list) -> None:
    kept = []
    for i, rec in enumerate(result.get("records") or []):
        if not isinstance(rec, dict):
            kept.append(rec)
            continue
        fail = None
        for prop in _proposals(rec):
            for k in ("chemical_formula", "material_type", "target_pollutant"):
                # §11.7 以 chemical_formula 为准；非空时不再回退 material_type
                if k == "material_type" and str(prop.get("chemical_formula") or "").strip():
                    continue
                v = prop.get(k)
                if isinstance(v, str) and v.strip():
                    c = entity_count(v.strip(), idx)
                    report["level_2_entities_checked"] += 1
                    if c == 0:
                        fail = (k, v.strip())
                        break
                    if c < 3:
                        _warnings(rec).append(
                            f"Level 2 suspicious: {k} '{v.strip()}' 在原文出现 {c} 次(<3)")
                        report["level_2_entities_suspicious"] += 1
            if fail:
                break
        if fail:
            cid = rec.get("case_id")
            label = f"case_id={cid}" if cid is not None else f"records[{i}]"
            notes.append(f"已删除: {label} 实体 '{fail[1]}'（字段 {fail[0]}）"
                         f"在原文中未出现（幻觉）")
            report["level_2_entities_removed"] += 1
            continue  # §11.7: Level 2 失败删除整条 record
        kept.append(rec)
    result["records"] = kept


# ═══════════════════════════════════════════════════════════
# Level 3 — 数值回溯（SKILL.md §3.3）
# ═══════════════════════════════════════════════════════════

NUM_PREFIX_RE = re.compile(r"^\s*[<>~\u2248]?\s*(-?\d+(?:\.\d+)?)")
PAGE_REF_RE = re.compile(r"[Pp]age\s*(\d+)")


def numeric_variants(value):
    """提取 (数值, 精确匹配候选字符串集合)；非数值返回 (None, [])。

    字符串仅当以数字开头（允许前置 >/<~/≈）才视为数值型（"123.4 mg/g"、"99.2%"），
    "MOF-8" 这类以字母开头的字符串不进入数值回溯。
    """
    if isinstance(value, bool):
        return None, []
    if isinstance(value, (int, float)):
        num = float(value)
        cands = {str(value)}
        if num.is_integer():
            cands.add(str(int(num)))
        return num, cands
    if isinstance(value, str):
        m = NUM_PREFIX_RE.match(value)
        if not m:
            return None, []
        num = float(m.group(1))
        cands = {m.group(1)}
        if num.is_integer():
            cands.add(str(int(num)))
        return num, cands
    return None, []


def validate_value(value, idx: TextIndex, from_data_page: bool):
    """三级判定: 精确 → ±1% → 溯源 data_page → suspicious。

    返回 (verdict, detail)；verdict 为 None 表示非数值字段，跳过不计数。
    """
    if value is None:
        return "unavailable", "字段值为 null"
    num, cands = numeric_variants(value)
    if num is None:
        return None, "非数值字段，跳过"
    if idx.exact_substring(cands):
        return "reliable", f"精确匹配 {sorted(cands)}"
    if idx.within_1pct(num):
        return "reliable", f"±1% 近似匹配 ({num})"
    if from_data_page:
        return "needs_review", "文本层未找到，溯源指向 data_page（视觉估读）"
    return "suspicious", "文本层与视觉溯源均未找到，疑似幻觉"


def source_points_to_data_page(source_hint, data_pages: set) -> bool:
    """标准 schema: _source 字符串（如 "Page 5, Table 2"）是否指向 data_page。"""
    if not isinstance(source_hint, str):
        return False
    return any(int(p) in data_pages for p in PAGE_REF_RE.findall(source_hint))


def run_level3_standard(result: dict, idx: TextIndex, data_pages: set,
                        report: dict) -> None:
    for rec in result.get("data") or []:
        if not isinstance(rec, dict):
            continue
        sources = rec.get("_source") if isinstance(rec.get("_source"), dict) else {}
        qual = rec.setdefault("_quality", {})
        for key, val in list(rec.items()):
            if key.startswith("_"):
                continue
            verdict, detail = validate_value(
                val, idx, source_points_to_data_page(sources.get(key), data_pages))
            if verdict is None:
                continue
            qual[key] = verdict
            report[VERDICT_REPORT_KEY[verdict]] += 1


def _record_pages(rec: dict) -> list:
    trace = rec.get("source_trace") if isinstance(rec.get("source_trace"), dict) else {}
    pages = []
    for p in trace.get("source_pages") or []:
        try:
            pages.append(int(p))
        except (TypeError, ValueError):
            pass
    return pages


def run_level3_adrmats(result: dict, idx: TextIndex, data_pages: set,
                       report: dict) -> None:
    for rec in result.get("records") or []:
        if not isinstance(rec, dict):
            continue
        trace = rec.get("source_trace") if isinstance(rec.get("source_trace"), dict) else {}
        origin = trace.get("record_origin")
        from_dp = any(p in data_pages for p in _record_pages(rec))
        for prop in _proposals(rec):
            ap = prop.get("adsorption_performance")
            if not isinstance(ap, dict):
                continue
            for k in ("capacity_mg_g", "removal_rate"):
                if k not in ap:
                    continue
                if origin == "literature_comparison":
                    # §11.7: 文献对比数据本不在本文实验中，豁免数值回溯
                    report["level_3_exempt_literature_comparison"] += 1
                    continue
                verdict, detail = validate_value(ap[k], idx, from_dp)
                if verdict is None:
                    continue
                report[VERDICT_REPORT_KEY[verdict]] += 1
                if verdict in ("needs_review", "suspicious"):
                    _warnings(rec).append(f"Level 3 {verdict}: {k}={ap[k]!r} — {detail}")


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def detect_schema(result: dict) -> str:
    if isinstance(result.get("records"), list):
        return "adrmats"   # §11.6: records 存在时覆盖标准 data[]
    if isinstance(result.get("data"), list):
        return "standard"
    sys.exit("ERROR: result.json 无法识别——既无 data[]（§5.1）也无 records[]（§11.6）")


def notes_list(result: dict, schema: str) -> list:
    """extraction_notes 落点: 标准 schema 在顶层（§5.1）；ADRMATS 在
    extraction_meta.extraction_notes（§11.7）。"""
    if schema == "adrmats":
        meta = result.get("extraction_meta")
        if not isinstance(meta, dict):
            meta = {}
            result["extraction_meta"] = meta
        notes = meta.get("extraction_notes")
        if not isinstance(notes, list):
            notes = []
            meta["extraction_notes"] = notes
        return notes
    notes = result.get("extraction_notes")
    if not isinstance(notes, list):
        notes = []
        result["extraction_notes"] = notes
    return notes


def print_summary(report: dict, out_path: str) -> None:
    print("═══ LitExtract 三级硬校验 ═══")
    print(f"Schema: {report['schema_detected']}")
    print(f"[Level 1] 元数据一致性: {report['level_1_metadata']}")
    for d in report["level_1_details"]:
        print(f"    - {d}")
    print(f"[Level 2] 实体存在性: 检查 {report['level_2_entities_checked']} 项, "
          f"删除记录 {report['level_2_entities_removed']} 条, "
          f"suspicious {report['level_2_entities_suspicious']} 项")
    line3 = (f"[Level 3] 数值回溯: reliable {report['level_3_values_reliable']}, "
             f"needs_review {report['level_3_values_needs_review']}, "
             f"suspicious {report['level_3_values_suspicious']}, "
             f"unavailable {report['level_3_values_unavailable']}")
    if report["level_3_exempt_literature_comparison"]:
        line3 += (f", 豁免(literature_comparison) "
                  f"{report['level_3_exempt_literature_comparison']}")
    print(line3)
    for n in report["validation_notes"]:
        print(f"    ! {n}")
    if report["overall_hallucination_risk"]:
        print("⚠ 整体幻觉风险: 元数据校验全部失败，建议丢弃结果并重新执行 Stage 2 提参")
    print(f"已输出: {out_path}")


def default_validated_path(result_path: str) -> str:
    d, name = os.path.split(result_path)
    stem = os.path.splitext(name)[0]
    return os.path.join(d, stem + "_validated.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LitExtract Stage 3 独立版 — 三级硬校验（本地、零 API）")
    parser.add_argument("result", help="提参结果 JSON（§5.1 data[] 或 §11.6 records[]）")
    parser.add_argument("stage0", help="stage0_anchor.py 输出的 Stage 0 JSON")
    parser.add_argument("-o", "--output", default=None,
                        help="修补后 JSON 输出路径（默认 <result去后缀>_validated.json）")
    args = parser.parse_args()

    result_path = resolve_path(args.result, must_exist=True, kind="result.json")
    stage0_path = resolve_path(args.stage0, must_exist=True, kind="stage0.json")

    try:
        result = json.loads(Path(result_path).read_text(encoding="utf-8"))
        stage0 = json.loads(Path(stage0_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: JSON 解析失败: {e}")
    if not isinstance(result, dict):
        sys.exit("ERROR: result.json 顶层必须是 JSON 对象")
    if not isinstance(stage0, dict):
        sys.exit("ERROR: stage0.json 顶层必须是 JSON 对象")

    schema = detect_schema(result)
    full_text, data_pages = build_context(stage0)
    idx = TextIndex(full_text)

    report = {
        "schema_detected": schema,
        "validation_date": date.today().isoformat(),
        "level_1_metadata": "PASS",
        "level_1_details": [],
        "level_2_entities_checked": 0,
        "level_2_entities_removed": 0,
        "level_2_entities_suspicious": 0,
        "level_3_values_reliable": 0,
        "level_3_values_needs_review": 0,
        "level_3_values_suspicious": 0,
        "level_3_values_unavailable": 0,
        "level_3_exempt_literature_comparison": 0,
        "overall_hallucination_risk": False,
        "validation_notes": [],
    }

    run_level1(result, stage0, report, notes_list(result, schema))

    if len(full_text.strip()) < 200:
        # 纯扫描 PDF 无文本层，实体/数值校验无基准，跳过并声明（SKILL.md §8）
        msg = ("Stage 0 文本层过短(<200 字符，疑似纯扫描 PDF)，Level 2/3 校验跳过，"
               "结果需人工复核")
        report["validation_notes"].append(msg)
        notes_list(result, schema).append(msg)
    else:
        if schema == "standard":
            run_level2_standard(result, idx, report, notes_list(result, schema))
            run_level3_standard(result, idx, data_pages, report)
        else:
            run_level2_adrmats(result, idx, report, notes_list(result, schema))
            run_level3_adrmats(result, idx, data_pages, report)

    meta = result.get("extraction_meta")
    if isinstance(meta, dict):
        meta["records_removed_by_validation"] = report["level_2_entities_removed"]

    result["validation_report"] = report

    out_path = (resolve_path(args.output, kind="输出JSON") if args.output
                else default_validated_path(result_path))
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    Path(out_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print_summary(report, out_path)


if __name__ == "__main__":
    main()
