from __future__ import annotations

import os
import sys
from pathlib import Path


DEFAULT_BALKANID_ROOT = (
    "/Users/suraj/Documents/Archive/BalkanID/Dev/copilot-api"
)


class OptionalCypherParser:
    """Optional adapter around the BalkanID ANTLR Cypher grammar.

    The parser is treated as an enhancement, not a hard dependency, so deterministic tests
    and docs can run without antlr4 or the archived BalkanID project on the import path.
    """

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or os.environ.get("PIPE_CYPHER_BALKANID_ROOT", DEFAULT_BALKANID_ROOT))
        self.available = False
        self._lexer = None
        self._parser = None
        self._input_stream = None
        self._token_stream = None
        self._load_error: str | None = None
        self._load()

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def _load(self) -> None:
        if not self.root.exists():
            self._load_error = f"BalkanID root not found: {self.root}"
            return
        if str(self.root) not in sys.path:
            sys.path.append(str(self.root))
        try:
            from antlr4 import CommonTokenStream, InputStream
            from modules.llm_manager.cypher_parser.CypherLexer import CypherLexer
            from modules.llm_manager.cypher_parser.CypherParser import CypherParser

            self._input_stream = InputStream
            self._token_stream = CommonTokenStream
            self._lexer = CypherLexer
            self._parser = CypherParser
            self.available = True
        except Exception as exc:  # pragma: no cover - depends on local archive deps
            self._load_error = str(exc)

    def parse_error(self, query: str) -> str | None:
        if not self.available:
            return None
        try:
            stream = self._input_stream(query)
            lexer = self._lexer(stream)
            tokens = self._token_stream(lexer)
            parser = self._parser(tokens)
            parser.oC_Cypher()
            if parser.getNumberOfSyntaxErrors() > 0:
                return f"ANTLR parser reported {parser.getNumberOfSyntaxErrors()} syntax error(s)"
            return None
        except Exception as exc:  # pragma: no cover - depends on parser runtime
            return str(exc)

