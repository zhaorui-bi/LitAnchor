# Example Files

| File | Description |
|------|-------------|
| `venusmine_result_validated.json` | End-to-end extraction from **Wu et al., *Nature Communications* (2025) 16:6211**, DOI [10.1038/s41467-025-61599-z](https://doi.org/10.1038/s41467-025-61599-z) — the PET-hydrolase discovery paper behind the VenusMine pipeline (12 pages; 4 enzyme records; three-level validated) |
| `andersson_result_validated.json` | Archived case: pipeline output for a 10-page main text, three-level validated |
| `andersson_expected.json` | Archived case: independently produced reference extraction (main text + 74-page SI), kept for the archived cross-check |

## What the VenusMine example shows

LitAnchor ran the full pipeline on the 12-page PDF: Stage 0 classified 7 data pages / 4 text pages / 1 skip; Stage 1 visually read all 7 data pages (concurrency ≤ 3, no rate-limit failures); Stage 2 produced one record per enzyme (KbPETase, IsPETase, LCC, FastPETase); Stage 3 reported **15 reliable values, 17 honestly-nulled unavailable values, 0 suspicious, 0 records deleted**.

The run also exercises the anti-hallucination design end to end:

- **Vision errors corrected against the text layer** — the visual transcription misread figure values (e.g. kcat/KM read as "4293 s⁻¹·mM⁻¹" and "top 54 sequences" where the text layer says 0.263 mM⁻¹·s⁻¹ and "top 34"); every quoted number was corrected during merge.
- **Anchor-quirk handling disclosed** — the title-anchor heuristic captured an abstract line on this layout; the protocol's original-text-prevails rule restored the verbatim title, recorded in the result's `anchor_note`.
- **Every value page-traceable** — e.g. `"Page 6, Table 1, row KbPETase"` for kinetics, `"Page 3, Fig. 2b"` for the Tm range.

The two archived files retain an earlier cross-checked validation case; the item-by-item comparison report is in [`../docs/verification-andersson-2026.md`](../docs/verification-andersson-2026.md).
