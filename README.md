# LitAnchor

> **Structured, page-traceable data extraction from PDF papers** — text anchoring, selective visual reading, and three-level hard validation, at zero metered API cost.

[![CI](https://github.com/zhaorui-bi/LitAnchor/actions/workflows/ci.yml/badge.svg)](https://github.com/zhaorui-bi/LitAnchor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python >=3.9](https://img.shields.io/badge/python-%3E%3D3.9-blue.svg)](https://www.python.org/)
[![ZCode Skill](https://img.shields.io/badge/ZCode-Skill-7C3AED.svg)](./SKILL.md)

LitAnchor is a ZCode skill (skill name: `lit-extract`) for structured, page-traceable data extraction from PDF research papers. It is built for ZCode subscribers: Stage 0 anchoring and Stage 3 validation run as local Python scripts, Stage 1 visual reading uses the session's built-in vision tool, and Stage 2 extraction happens in-session — so a full extraction run incurs zero metered API cost and needs no API keys.

**Why LitAnchor.** Pure-vision pipelines hallucinate on long documents: in the worked example below, the vision layer misread a figure value by orders of magnitude (kcat/KM transcribed as "4293 s-1 mM-1" where the paper's text layer says 0.263 mM-1 s-1) — and every such misread was caught and corrected. LitAnchor defends against this with a text-anchoring architecture: ground-truth metadata (title/DOI/authors/keywords) and the full text are hard-extracted from the PDF text layer by a local script, figures and tables are selectively vision-read, and a three-level hard validator makes every output value traceable to its page, table, or figure.

## Table of Contents

- [Quick Start](#-quick-start)
- [How It Works](#-how-it-works)
- [Cost](#-cost)
- [Output Format](#-output-format)
- [Tutorials](#-tutorials)
- [Worked Example: VenusMine (Nature Communications 2025)](#-worked-example-venusmine-nature-communications-2025)
- [FAQ](#-faq)
- [Project Structure](#-project-structure)
- [Documentation Index](#-documentation-index)
- [Contributing](#-contributing)
- [Citation](#-citation)
- [License](#-license)

## 🚀 Quick Start

### Step 1 · Install

Prerequisites:

- A **ZCode subscription session** (Read tool required; the built-in vision tool `analyze_image` is recommended — the skill degrades gracefully without it, see [Degraded mode](#-tutorials))
- **Python >=3.9** with PyMuPDF (`pip install pymupdf`; the validation script is pure stdlib, zero dependencies)
- No Node.js, no API keys of any kind

```bash
# From the package root: copies SKILL.md + scripts/stage0_anchor.py + scripts/validate.py
# into ~/.zcode/skills/lit-extract/ (a previous install is auto-backed-up;
# no interaction, no network requests, no credentials)
bash install.sh

# Uninstall
bash install.sh --uninstall
```

Manual install: copy `SKILL.md`, `scripts/stage0_anchor.py`, and `scripts/validate.py` into `~/.zcode/skills/lit-extract/`, preserving the directory structure.

### Step 2 · Self-test

```bash
python3 tests/selftest.py
```

Zero API, zero credentials: it generates a synthetic 6-page PDF and verifies anchoring, page classification, PNG rendering, and the validation logic. At the time of writing, **14/14 checks PASS** (exit code 0 = pass). One optional real-paper regression is skipped — not failed — when its PDF is absent; enable it via the environment variable `LIT_EXTRACT_SELFTEST_PDF=/path/to.pdf` or by placing that PDF at the path named in `tests/selftest.py`. CI (GitHub Actions, `.github/workflows/ci.yml`) runs `py_compile` plus the self-test on Python 3.11.

### Step 3 · First use

In a ZCode session, just ask to extract data from a PDF (or invoke the skill directly). You supply the field keys, value types, and constraints:

```
Extract PET hydrolase characterization data from ~/papers/VenusMine.pdf:
- enzyme_name: PET hydrolase name
- source_organism: origin organism or metagenome
- optimal_temperature_C: optimal catalytic temperature (deg C)
- Tm_C: melting temperature by DSF (deg C)
- activity_vs_IsPETase_fold: PET-film degradation activity vs IsPETase (fold)
- Km_mM_pNPB / kcat_s_minus1_pNPB / kcat_Km_pNPB: Michaelis-Menten kinetics on pNPB
Constraint: one record per enzyme characterized in the paper.
```

The skill runs Stage 0 (anchoring + page classification) → Stage 1 (visual reading of data pages only) → Stage 2 (in-session merge + constraint-driven extraction) → Stage 3 (three-level hard validation) and delivers `<PDF>_result_validated.json`. The full scenario catalog (multi-paper comparison, ADRMATS test sets, cache reuse, and more) is in [Tutorials](#-tutorials).

## 🧭 How It Works

```
PDF file
  |
  +-- [Stage 0] Text anchoring + smart page classification -- local script stage0_anchor.py (seconds, zero API)
  |     |-- Metadata anchors: title / DOI / authors / keywords (non-hallucinable, hard-extracted
  |     |   from the PDF text layer, bound to every later stage)
  |     |-- Smart page classification: data_page / text_page / skip_page
  |     |   (references, crystallography, NMR peak lists are skipped)
  |     |-- Full text saved to the stage0 JSON (the validation baseline)
  |     +-- Data pages rendered to PNG at 150 DPI -> <PDF>_pages/page_00N.png
  |
  +-- [Stage 1] Selective visual reading (data pages only) -- ZCode session channel
  |     |-- Read tool loads the page PNG (page list MUST come from the stage0 JSON data_page_nums)
  |     +-- Built-in analyze_image with an anti-hallucination transcription prompt
  |         (concurrency cap 3 with rate-limit backoff)
  |
  +-- [Stage 2] Merge + constraint-driven extraction -- in-session, zero external API
  |     |-- Text pages from the stage0 text, data pages from the visual transcription,
  |     |   merged in page order with metadata anchors injected
  |     +-- Session model + your field keys/types + constraints -> structured JSON
  |
  +-- [Stage 3] Three-level hard validation -- local script validate.py (pure stdlib, seconds)
        |-- Level 1: metadata consistency (title/DOI/authors vs anchors)
        |-- Level 2: entity existence (records whose entity names never appear
        |   in the paper are deleted)
        |-- Level 3: numeric traceback (values must be findable in the text layer, ±1%)
        +-- Output <PDF>_result_validated.json (provenance + quality tiers + validation report)
```

| Capability | What it does |
|------------|--------------|
| **PDF text anchoring** | Local script `stage0_anchor.py` extracts the text layer; title/DOI/authors/keywords become non-hallucinable anchors bound through the whole run |
| **Selective visual reading** | Only figure/table pages (data_page) are visually read — Read the PNG, then the built-in `analyze_image` with an anti-hallucination transcription prompt; reference, crystallography, and NMR pages are skipped |
| **Constraint-driven extraction** | You define the field keys, value types, and constraints; the session model extracts against them after merging the text and visual layers in page order |
| **Three-level hard validation** | Local script `validate.py` (pure stdlib, seconds): Level 1 metadata consistency → Level 2 entity existence → Level 3 numeric traceback within ±1% |
| **Provenance + five quality tiers** | Every extracted value carries `_source` provenance (page number, table/Figure id) and a `_quality` tier: `reliable` / `needs_review` / `suspicious` / `inferred` / `unavailable` |
| **Multi-paper comparison** | Each paper runs the full pipeline independently; results merge into one JSON with `paper_id` |
| **ADRMATS test-set profile** | Build evaluation-agent test sets as `visible_input` + `hidden_oracle_label` + `source_trace` records ([SKILL.md](./SKILL.md) §11) |

## 💰 Cost

Everything runs inside the ZCode subscription or as local scripts. Stage 0 anchoring and Stage 3 validation are local Python scripts (seconds, no network); Stage 1 uses the session's built-in vision tool; Stage 2 is done by the session model itself. There is no metered API of any kind and no API keys to configure.

## 📊 Output Format

The deliverable is a single JSON envelope: `extraction_meta` (anchor-bound metadata) + `field_definitions` (your fields) + `data[]` (each record with `_source` page-level provenance and `_quality` tier per value) + `validation_report` + `extraction_notes`. The full schema and field-level provenance rules are in [SKILL.md](./SKILL.md) §5; the ADRMATS three-part schema is in §11.6.

A trimmed record from the worked example (see [below](#-worked-example-venusmine-nature-communications-2025)):

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

## 📖 Tutorials

### 1. Single-paper extraction

Give the PDF path plus your field definitions; optional constraints and output granularity refine what comes back.

```
Extract PET hydrolase characterization data from ~/papers/VenusMine.pdf:
- enzyme_name: PET hydrolase name
- source_organism: origin organism or metagenome
- optimal_temperature_C: optimal catalytic temperature (deg C)
- Tm_C: melting temperature by DSF (deg C)
- activity_vs_IsPETase_fold: PET-film degradation activity vs IsPETase (fold)
- Km_mM_pNPB / kcat_s_minus1_pNPB / kcat_Km_pNPB: Michaelis-Menten kinetics on pNPB
Constraint: one record per enzyme characterized in the paper.
```

For this prompt the skill ran the full pipeline on the 12-page PDF: 7 data pages were visually read, 4 text pages were taken from the text layer, 1 page was skipped, and the validated result contains 4 enzyme records (KbPETase, IsPETase, LCC, FastPETase) — each value carrying page-level `_source` provenance and a `_quality` tier. Full numbers in the [Worked Example](#-worked-example-venusmine-nature-communications-2025).

### 2. Multi-paper comparison

```
Compare Michaelis-Menten kinetics across these PDFs and merge into one JSON:
1. ~/papers/VenusMine.pdf
2. ~/papers/enzyme_screen_2025.pdf
3. ~/papers/kinetics_review_2024.pdf

Fields:
- enzyme_name: enzyme name
- Km_mM: Michaelis constant (mM)
- kcat_s_minus1: turnover number (1/s)
- temperature_C: assay temperature (deg C)
```

Each paper runs the complete Stage 0-3 pipeline independently, and the per-paper validated results are merged into one JSON with a `paper_id` index. Papers may be processed in parallel sessions, but all sessions combined must keep the total in-flight visual reads at 3 or fewer (the shared vision-tool quota is account-level).

### 3. ADRMATS evaluation-agent test-set profile

```
Build a test set for the ADRMATS evaluation agent from the PDFs in ~/papers/.
Split the records by quality tier: 70% high, 20% low, 10% noise.
Output visible_input (constraint_context + merged_proposals) per record, plus a
separate hidden_oracle_label (quality_tier etc.) and a source_trace for every value.
```

This activates the ADRMATS profile ([SKILL.md](./SKILL.md) §11): records are split at fine granularity per material, pollutant, and condition, using the three-part schema `visible_input` (`constraint_context` + `merged_proposals`) + `hidden_oracle_label` (quality tier `high`/`low`/`noise` and related fields, never shipped with the visible input) + `source_trace`. Text anchoring and three-level hard validation run unchanged.

### 4. Cache reuse

`<PDF>_stage0.json` plus the `<PDF>_pages/` PNG directory form the Stage 0 cache unit: when both exist and the PNG count matches the stage0 JSON's `data_page_nums`, Stage 0 is **not re-run**. Re-extracting the same PDF with a different set of fields in the same session reuses the cache and only re-runs Stage 2-3. Note: re-rendering at higher resolution (`--dpi 300`) requires `-o` pointing to a new stage0 JSON path — otherwise the default output path is overwritten and the original cache is lost.

### 5. Merging main text + SI (recommended)

For a paper whose supporting information (SI) carries data, merge main text and SI into a single PDF before extraction (core 3 lines):

```python
import pymupdf
out = pymupdf.open()
for p in ("main.pdf", "SI.pdf"):    # main text first, keeps page numbering continuous
    out.insert_pdf(pymupdf.open(p))
out.save("merged.pdf")
```

With continuous page numbering, `_source` page provenance and the Level 3 numeric-traceback baseline stay in one coordinate system, so values that appear only in the SI can be extracted and validated normally.

### 6. Degraded mode

When the session has no vision tool, the pipeline falls back to text-layer-only: values present in the text layer extract normally (validated as `reliable`), while values that exist only inside figures become `null`/`unavailable` with honest notes — `_source` keeps the page and states why the value was not read, and `extraction_notes` declares the precision risk. A scanned PDF with no text layer **and** no vision tool aborts with an explicit message rather than emitting unanchored results.

## ✅ Worked Example: VenusMine (Nature Communications 2025)

**Paper**: Wu, B., Zhong, B., Zheng, L., Huang, R., Jiang, S., Li, M., Hong, L. & Tan, P. "Harnessing protein language model for structure-based discovery of highly efficient and robust PET hydrolases." *Nature Communications* (2025) 16:6211, DOI [10.1038/s41467-025-61599-z](https://doi.org/10.1038/s41467-025-61599-z).

The paper proposes VenusMine, a structure-based enzyme-discovery pipeline combining FoldSeek (structure retrieval), MMseqs2 (sequence retrieval), ProstT5 protein-language-model embeddings, and a representation tree, used to mine PET-hydrolase enzymes. Of 34 candidates taken to wet-lab validation, 26 were expressed and purified, and 14 showed PET degradation activity across 30-60 °C — 11 of the 14 comparable to IsPETase — with a DSF melting-temperature range of 36.4-80.1 °C. The star result is KbPETase (candidate APET-14, from *Kibdelosporangium banguiense*, GenBank WP_209642273.1): 97x IsPETase activity (at 50 °C vs IsPETase's 30 °C), Tm +32.4 °C over IsPETase (about 80.1 °C), 5.7x LCC at 50 °C and 1.47x LCC at LCC's 65 °C optimum, 1.5x kcat and 1.3x kcat/KM vs LCC, and an X-ray structure at 1.75 Å (PDB 9IW9). Kinetics on pNPB (Table 1): KbPETase Km 1.04 mM / kcat 0.270 s-1 / kcat/KM 0.263 mM-1 s-1; FastPETase 1.57 / 0.215 / 0.141; LCC 1.053 / 0.186 / 0.208.

**LitAnchor run on this PDF:**

| Item | Result |
|------|--------|
| Pages classified | 12 pages → 7 data pages / 4 text pages / 1 skip |
| Data pages visually read | 7/7 (concurrency <= 3, no rate-limit failures) |
| Records produced (Stage 2) | 4 enzyme records: KbPETase, IsPETase, LCC, FastPETase |
| Level 3 outcome (Stage 3) | 15 reliable values, 17 honestly-nulled unavailable values, 0 suspicious |
| Records deleted by validation | 0 |

**Two corrections this run demonstrates:**

1. **Vision misreads corrected against the text layer.** The visual transcription misread figure values — kcat/KM was read as "4293 s-1 mM-1" and the candidate count as "top 54 sequences", where the text layer says 0.263 mM-1 s-1 and "top 34". Every quoted number was corrected against the text layer during merge.
2. **Anchor quirk disclosed, original text prevails.** The title-anchor heuristic captured an abstract line on this two-column layout; the protocol's original-text-prevails rule restored the verbatim title, and the episode is disclosed in the result's `anchor_note`.

The full validated result ships in the repo: [`examples/venusmine_result_validated.json`](./examples/venusmine_result_validated.json), with a guide in [`examples/README.md`](./examples/README.md).

## ❓ FAQ

<details>
<summary><b>How is it billed? Is it really zero metered cost?</b></summary>

Everything runs inside the ZCode subscription or as local scripts: Stage 0 and Stage 3 are local Python scripts, Stage 2 is done by the session model, and Stage 1 goes through the session's built-in vision tool. There is no metered API of any kind and no API keys.
</details>

<details>
<summary><b>What if the PDF is a scanned copy?</b></summary>

When the text layer is near-empty, the pipeline switches to full-page visual reading, and Stage 3 skips the Level 2/3 checks and flags the result as needing manual review. If no vision tool is available either, the pipeline aborts with an explicit message rather than producing results with no anchoring baseline. Native PDFs with a text layer are preferred.
</details>

<details>
<summary><b>Which papers are supported?</b></summary>

Native PDFs with a text layer (as downloaded from the publisher) work best, in Chinese or English alike. Reference lists, crystallography tables, and NMR peak-list pages are auto-skipped by the smart page classifier. Domains beyond chemistry work too — the worked example above is a protein-engineering paper.
</details>

## 📁 Project Structure

```
LitAnchor/
├── SKILL.md                              # The protocol document (installed to ~/.zcode/skills/lit-extract/)
├── install.sh                            # One-command install / update / uninstall
├── README.md                             # This file
├── LICENSE                               # MIT
├── CONTRIBUTING.md                       # Contribution guidelines
├── CHANGELOG.md                          # Changelog
├── CITATION.cff                          # Citation metadata (CFF 1.2.0)
├── scripts/
│   ├── stage0_anchor.py                  # Stage 0: text anchoring + page classification + PNG rendering
│   └── validate.py                       # Stage 3: three-level hard validation (pure stdlib, seconds)
├── tests/
│   ├── selftest.py                       # One-command self-test (zero API, zero credentials)
│   ├── make_synthetic_pdf.py             # Synthetic PDF generator for the self-test
│   └── _artifacts/                       # Self-test artifacts (gitignored)
├── examples/
│   ├── README.md                         # Guide to the example files
│   └── venusmine_result_validated.json   # Worked example: end-to-end validated result
├── docs/                                 # Archived notes
└── .github/
    └── workflows/ci.yml                  # CI: py_compile + selftest (Python 3.11)
```

## 📚 Documentation Index

| Document | Contents |
|----------|----------|
| [`SKILL.md`](./SKILL.md) | Pipeline protocol (§2-§3), output schema (§5), ADRMATS test-set profile (§11) |
| [`examples/README.md`](./examples/README.md) | Worked-example files |

## 🤝 Contributing

Issues and PRs are welcome. Please read [`CONTRIBUTING.md`](./CONTRIBUTING.md) first. Before opening a PR, run `python3 tests/selftest.py` from the repository root and make sure the exit code is 0; paste the full output in the PR description.

## 📝 Citation

If LitAnchor helps your work, please cite it using [`CITATION.cff`](./CITATION.cff) (CFF 1.2.0, validatable with `cffconvert`).

## 📄 License

[MIT License](./LICENSE) — Copyright (c) 2026 Water Quality Risk Control Engineering & contributors.
