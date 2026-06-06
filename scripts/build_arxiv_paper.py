#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SOURCE_DIR = Path("paper_emnlp2026_industry")
DEFAULT_OUTPUT_DIR = Path("paper_arxiv")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the non-anonymous arXiv paper source.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--github-url",
        default="https://github.com/suraj-ranganath/PIPE-Cypher",
    )
    parser.add_argument(
        "--hf-dataset-url",
        default="https://huggingface.co/datasets/suraj-ranganath/PIPE-Cypher-benchmarks",
    )
    args = parser.parse_args()
    build_arxiv_paper(
        output_dir=Path(args.output_dir),
        github_url=args.github_url,
        hf_dataset_url=args.hf_dataset_url,
    )


def build_arxiv_paper(*, output_dir: Path, github_url: str, hf_dataset_url: str) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(
        SOURCE_DIR,
        output_dir,
        ignore=shutil.ignore_patterns(
            "*.aux",
            "*.bbl",
            "*.blg",
            "*.fdb_latexmk",
            "*.fls",
            "*.log",
            "*.out",
            "*.synctex.gz",
            "main.pdf",
            "main.tex",
            "main_acl.pdf",
            "paper.md",
        ),
    )
    main_path = output_dir / "main_arxiv.tex"
    text = (output_dir / "main_acl.tex").read_text(encoding="utf-8")
    text = text.replace(r"\usepackage[review]{acl}", r"\usepackage{acl}")
    text = text.replace(
        r"\author{Anonymous Authors}",
        _author_block(),
    )
    text = text.replace(
        r"\FloatBarrier" + "\n" + r"\clearpage" + "\n" + r"\input{appendix_example_cards}",
        _artifact_section(github_url=github_url, hf_dataset_url=hf_dataset_url)
        + "\n\n"
        + r"\FloatBarrier"
        + "\n"
        + r"\clearpage"
        + "\n"
        + r"\input{appendix_example_cards}",
    )
    main_path.write_text(text, encoding="utf-8")
    (output_dir / "main_acl.tex").unlink()


def _author_block() -> str:
    return r"""\author{
Suraj Ranganath\\
School of Computing, Information and Data Sciences\\
University of California, San Diego\\
United States of America\\
\texttt{suranganath@ucsd.edu}
\And
Anish Raghavendra\\
Independent Researcher
}"""


def _artifact_section(*, github_url: str, hf_dataset_url: str) -> str:
    return rf"""\section{{Public Artifacts}}

The public code repository is available at \url{{{github_url}}}. The public-proxy benchmark exports for FinBench/SNB and ICIJ Offshore Leaks are available at \url{{{hf_dataset_url}}}. These artifacts are linked only in the non-anonymous arXiv version; the EMNLP review submission uses anonymous supplementary material."""


if __name__ == "__main__":
    main()
