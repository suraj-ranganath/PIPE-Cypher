# EMNLP Industry Track Requirements Notes

Date checked: June 1, 2026.

Primary sources:

- EMNLP 2026 Industry Track call for papers: `https://2026.emnlp.org/calls/industry_track/`
- ACL style files repository: `https://github.com/acl-org/acl-style-files`

## Requirements To Track

- Submission deadline: June 16, 2026 AoE.
- Format: ACL rolling-review style template, double-blind.
- Industry papers: up to 6 content pages plus references.
- The Industry Track does not use ARR.
- There is no anonymity period requirement, but the submitted PDF must still be double-blind.
- A dedicated section titled `Limitations` is required before references and does not count toward the page limit.
- Appendices and supplementary material can carry reproducibility details, audit templates, additional generated examples, and full tables.
- The paper should be explicit about automated evaluation, human audits, and deployment constraints because the Industry Track expects practical deployed-system relevance.

## Current Repo State

- `paper_emnlp2026_industry/main.tex` is a simple article draft for fast iteration.
- `paper_emnlp2026_industry/main_acl.tex` is the ACL-style submission draft.
- `paper_emnlp2026_industry/acl.sty` and `paper_emnlp2026_industry/acl_natbib.bst` are staged from the ACL style-file repository.

## Submission Cleanup Checklist

- Replace placeholder anonymous author block only for arXiv/non-anonymous drafts or camera-ready material, not for the submitted double-blind PDF.
- Fit the ACL-style body to 6 pages before references.
- Move long reproducibility details to appendix/supplement.
- Keep limitations and ethics after the main conclusion, outside the core argument.
- Update results tables from the full 3,000-example run and final ablations.
