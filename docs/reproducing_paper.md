# Reproducing The Paper Artifacts

The EMNLP Industry paper source lives in
[`paper_emnlp2026_industry/`](../paper_emnlp2026_industry/). The canonical
submission source is `main_acl.tex`.

## Build The Paper

```bash
cd paper_emnlp2026_industry
latexmk -pdf -interaction=nonstopmode main_acl.tex
```

Run submission checks from the repository root:

```bash
python scripts/audit_emnlp_page_budget.py \
  --pdf paper_emnlp2026_industry/main_acl.pdf

python scripts/verify_submission_package.py \
  --paper-tex paper_emnlp2026_industry/main_acl.tex
```

## Regenerate Tables And Figures

Most paper tables and figures are rendered from snapshot artifacts:

```bash
python scripts/render_paper_artifact_tables.py
python scripts/render_paper_figures.py
```

The reviewer supplement is built with:

```bash
python scripts/build_acl_supplement.py \
  --output-dir dist/acl_supplement/PIPE-Cypher-ACL-supplement \
  --zip-path dist/acl_supplement/PIPE-Cypher-ACL-supplement.zip
```

## Deterministic Tests

```bash
python -m pip install -e ".[dev]"
pytest
```

The deterministic tests do not require a GPU, live Neo4j instance, or model
endpoint. Scaled generation and downstream experiments require live graph
backends and locally served model weights.
