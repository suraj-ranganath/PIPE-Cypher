# EMNLP Industry Track Requirements Notes

Date checked: June 1, 2026. Page-limit wording rechecked against the official call on June 1, 2026.

Primary sources:

- EMNLP 2026 Industry Track call for papers: `https://2026.emnlp.org/calls/industry_track/`
- ACL style files repository: `https://github.com/acl-org/acl-style-files`

## Requirements To Track

- Submission deadline: June 16, 2026 AoE.
- Format: ACL rolling-review style template, double-blind.
- Industry papers: at most 6 counted pages for the main paper. The main narrative should end with `Conclusion` by the end of page 6.
- Excluded from the 6-page limit: `Limitations`, ethical considerations, references, acknowledgements in the final version, and appendices.
- The Industry Track does not use ARR.
- There is no anonymity period requirement, but the submitted PDF must still be double-blind.
- A dedicated section titled `Limitations` is required before references, does not count toward the page limit, and missing it can trigger desk rejection.
- Appendices come after the bibliography and do not count toward the page limit. They can carry reproducibility details, audit templates, additional generated examples, full tables, plots, and error analysis. The submission should still be self-contained because reviewers are not required to review appendices.
- The paper should be explicit about automated evaluation, human audits, and deployment constraints because the Industry Track expects practical deployed-system relevance.

## Current Repo State

- `paper_emnlp2026_industry/main.tex` is a simple article draft for fast iteration.
- `paper_emnlp2026_industry/main_acl.tex` is the ACL-style submission draft.
- `paper_emnlp2026_industry/acl.sty` and `paper_emnlp2026_industry/acl_natbib.bst` are staged from the ACL style-file repository.
- `scripts/audit_emnlp_page_budget.py` checks the compiled ACL-style PDF and fails if `Conclusion` starts after page 6, `Limitations` is missing, references precede limitations, or appendix material appears before references. On June 2, 2026 at 01:02 UTC, `paper_emnlp2026_industry/main_acl.pdf` passed with `Conclusion`, `Limitations`, `Ethics Statement`, and `References` on page 4 and `Additional Results` on page 5.

## Submission Cleanup Checklist

- Replace placeholder anonymous author block only for arXiv/non-anonymous drafts or camera-ready material, not for the submitted double-blind PDF.
- Ensure `Conclusion` ends by the end of page 6 in the ACL-style submission draft by running `python scripts/audit_emnlp_page_budget.py --pdf paper_emnlp2026_industry/main_acl.pdf` after every meaningful LaTeX edit.
- Keep `Limitations`, optional ethics, references, and appendices after the main conclusion; they are outside the counted six-page limit.
- Move long reproducibility details, full ablations, judge packets, graph-specific tables, examples, and error analysis to appendix/supplement.
- Update results tables from the full 3,000-example run and final ablations.
