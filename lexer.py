"""
compiler/lexer.py
─────────────────
Phase 1 — Lexical Analyser
Tokenises a C++ source string.  Understands: keywords, types, identifiers,
numeric / string / char literals, operators, punctuation, preprocessor
directives (#include <…> / "…"), C++ stream operators (<<, >>),
and single-line comments.

Rightmost-derivation note:
  Tokens are the *terminals* consumed by the parser's handle-pruning
  (bottom-up / LR) steps, which correspond to reading the input left-to-right
  while the parser tracks the rightmost sentential form in reverse.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional


# ─── Token kinds ───────────────────────────────────────────────────────────────

class TK(Enum):
    KEYWORD   = auto()   # if, else, while, for, return, …
    TYPE      = auto()   # int, float, double, char, bool, void, string
    IDENT     = auto()   # user-defined names
    NUMBER    = auto()   # integer / float literals
    STRING    = auto()   # "…"
    CHAR_LIT  = auto()   # '…'
    OP        = auto()   # +, -, *, /, ==, !=, <<, >>, …
    PUNCT     = auto()   # ; , ( ) { } [ ]
    PREPROC   = auto()   # #include …
    COMMENT   = auto()   # // …
    ERROR     = auto()   # lexical errors
    EOF       = auto()


# ─── Vocabulary ────────────────────────────────────────────────────────────────

TYPES: frozenset[str] = frozenset({
    "int", "float", "double", "char", "bool", "void", "string",
})

KEYWORDS: frozenset[str] = frozenset({
    "return", "true", "false", "const", "nullptr", "new", "delete",
    "class", "struct", "public", "private", "protected",
    "namespace", "using",
    *TYPES,
})
UNSUPPORTED_KEYWORDS: frozenset[str] = frozenset({
    "if", "else", "while", "for", "do", "break", "continue",
})

TWO_CHAR_OPS: frozenset[str] = frozenset({
    "==", "!=", "<=", ">=", "&&", "||",
    "++", "--", "<<", ">>",
    "+=", "-=", "*=", "/=", "%=",
    "::",
})

SINGLE_OPS: frozenset[str] = frozenset("+-*/%=<>!&|^~?")
PUNCTUATION: frozenset[str] = frozenset(";,(){}[]:")


# ─── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class Token:
    kind:  TK
    value: str
    line:  int
    col:   int
    lib:   Optional[str] = field(default=None, repr=False)  # for PREPROC tokens

    def __str__(self) -> str:
        return f"Token({self.kind.name:<10} {self.value!r:<20} L{self.line}:C{self.col})"


@dataclass
class LexError(Exception):
    msg:  str
    line: int
    col:  int

    def __str__(self) -> str:
        return f"LexError at L{self.line}:C{self.col} — {self.msg}"


# ─── Lexer ─────────────────────────────────────────────────────────────────────

_INCLUDE_RE = re.compile(r"^#\s*include\s*[<\"]([^>\"]+)[>\"]")


class Lexer:
    """
    Single-pass lexer.  Call `tokenize(source)` to obtain the token list.
    Errors are collected in `self.errors`; lexing continues on error so the
    parser gets as complete a token stream as possible.
    """

    def __init__(self) -> None:
        self.tokens: List[Token] = []
        self.errors: List[LexError] = []

    # ── Public ──────────────────────────────────────────────────────────────

    def tokenize(self, source: str) -> List[Token]:
        """Tokenise *source* and return the full token list (incl. COMMENT/PREPROC).
        
        Handles:
          - Single-line comments (//)
          - Multi-line comments (/* */)
          - String literals with escape sequences
          - Char literals with escape sequences
          - Keywords, identifiers, numbers, operators, punctuation
          - Preprocessor directives
        """
        self.tokens = []
        self.errors = []

        # First pass: remove multi-line comments
        source = self._remove_multiline_comments(source)

        for line_no, raw_line in enumerate(source.splitlines(), start=1):
            self._lex_line(raw_line, line_no)

        self.tokens.append(Token(TK.EOF, "", 0, 0))
        return self.tokens

    def _remove_multiline_comments(self, source: str) -> str:
        """Remove /* */ style comments while preserving line numbers and reporting unterminated comments."""
        result = []
        i = 0
        line_no = 1
        start_line = None
        
        while i < len(source):
            # Check for start of multi-line comment
            if i < len(source) - 1 and source[i:i+2] == "/*":
                if start_line is None:
                    start_line = line_no
                # Replace comment with spaces/newlines to preserve line numbers
                j = i + 2
                while j < len(source) - 1:
                    if source[j:j+2] == "*/":
                        j += 2
                        start_line = None
                        break
                    if source[j] == '\n':
                        result.append('\n')
                        line_no += 1
                    else:
                        result.append(' ')
                    j += 1
                if j >= len(source) - 1 and start_line is not None:
                    # Unterminated comment
                    self.errors.append(LexError("Unterminated multi-line comment", start_line, 1))
                    start_line = None
                i = j
            else:
                result.append(source[i])
                if source[i] == '\n':
                    line_no += 1
                i += 1
        
        return ''.join(result)

    # ── Private ─────────────────────────────────────────────────────────────

    def _lex_line(self, raw: str, line_no: int) -> None:
        stripped = raw.lstrip()

        # ── Preprocessor directive ───────────────────────────────────────────
        if stripped.startswith("#"):
            m = _INCLUDE_RE.match(stripped)
            lib = m.group(1) if m else None
            self.tokens.append(Token(TK.PREPROC, stripped, line_no, 1, lib=lib))
            return

        line = raw
        i    = 0

        while i < len(line):
            ch = line[i]

            # Whitespace
            if ch.isspace():
                i += 1
                continue

            # Single-line comment
            if line[i:i+2] == "//":
                self.tokens.append(Token(TK.COMMENT, line[i:], line_no, i + 1))
                break                          # rest of line is comment

            # String literal
            if ch == '"':
                tok, i = self._read_string(line, i, line_no, '"', TK.STRING)
                self.tokens.append(tok)
                continue

            # Char literal
            if ch == "'":
                tok, i = self._read_string(line, i, line_no, "'", TK.CHAR_LIT)
                self.tokens.append(tok)
                continue

            # Numeric literal (including floats like 3.5)
            if ch.isdigit() or (ch == "." and i + 1 < len(line) and line[i+1].isdigit()):
                j = i
                num_str = ""
                has_dot = False
                is_octal = False
                is_hex = False
                
                # Check for hex prefix
                if line[i:i+2] == "0x" or line[i:i+2] == "0X":
                    is_hex = True
                    j = i + 2
                    while j < len(line) and (line[j].isalnum() or line[j] == "_"):
                        if line[j] == "_":
                            # Remove underscores for validation
                            pass
                        elif is_hex and not (line[j].isalnum() and (line[j].isdigit() or line[j].lower() in "abcdef")):
                            break
                        j += 1
                    num_str = line[i:j]
                else:
                    # Decimal or octal
                    if ch == "0" and i + 1 < len(line) and line[i+1].isdigit():
                        is_octal = True
                    
                    while j < len(line) and (line[j].isdigit() or (line[j] == "." and not has_dot) or line[j] == "_"):
                        if line[j] == ".":
                            has_dot = True
                        elif line[j] == "_":
                            # Remove underscores
                            pass
                        elif is_octal and not line[j].isdigit():
                            break
                        j += 1
                    num_str = line[i:j]
                
                # Validate the number
                if is_hex:
                    # Check for invalid hex digits
                    hex_part = num_str[2:]
                    if not all(c.isalnum() and (c.isdigit() or c.lower() in "abcdef") for c in hex_part if c != "_"):
                        self.errors.append(LexError(f"Invalid hexadecimal literal '{num_str}'", line_no, i + 1))
                        self.tokens.append(Token(TK.ERROR, num_str, line_no, i + 1))
                    else:
                        self.tokens.append(Token(TK.NUMBER, num_str, line_no, i + 1))
                elif is_octal:
                    # Check for invalid octal digits
                    octal_part = num_str[1:]
                    if not all(c.isdigit() and c in "01234567" for c in octal_part if c != "_"):
                        self.errors.append(LexError(f"Invalid octal literal '{num_str}'", line_no, i + 1))
                        self.tokens.append(Token(TK.ERROR, num_str, line_no, i + 1))
                    else:
                        self.tokens.append(Token(TK.NUMBER, num_str, line_no, i + 1))
                else:
                    # Decimal float
                    clean_num = "".join(c for c in num_str if c != "_")
                    if clean_num.count(".") > 1:
                        self.errors.append(LexError(f"Malformed numeric literal '{num_str}'", line_no, i + 1))
                        self.tokens.append(Token(TK.ERROR, num_str, line_no, i + 1))
                    else:
                        self.tokens.append(Token(TK.NUMBER, num_str, line_no, i + 1))
                
                i = j
                continue

            # Identifier / keyword / type or number
            if ch.isalpha() or ch == "_":
                tok, i = self._read_word(line, i, line_no)
                if tok:
                    self.tokens.append(tok)
                    if tok.kind is TK.ERROR:
                        self.errors.append(LexError(f"Unsupported keyword '{tok.value}'", line_no, tok.col))
                continue

            # Two-char operator
            two = line[i:i+2]
            if two in TWO_CHAR_OPS:
                self.tokens.append(Token(TK.OP, two, line_no, i + 1))
                i += 2
                continue

            # Single-char operator
            if ch in SINGLE_OPS:
                self.tokens.append(Token(TK.OP, ch, line_no, i + 1))
                i += 1
                continue

            # Punctuation
            if ch in PUNCTUATION:
                self.tokens.append(Token(TK.PUNCT, ch, line_no, i + 1))
                i += 1
                continue

            # Unknown character — record error, include in tokens
            err = LexError(f"Unexpected character {ch!r}", line_no, i + 1)
            self.tokens.append(Token(TK.ERROR, ch, line_no, i + 1))
            self.errors.append(err)
            i += 1

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _read_string(self, line: str, start: int, line_no: int, delim: str, kind: TK):
        """Read a string or char literal, handling and validating escape sequences."""
        j = start + 1
        has_error = False
        while j < len(line) and line[j] != delim:
            if line[j] == "\\":
                # Check escape sequence
                if j + 1 >= len(line):
                    has_error = True
                    break
                escape_char = line[j + 1]
                valid_escapes = "abfnrtv\\'\"?01234567x"
                if escape_char not in valid_escapes:
                    has_error = True
                elif escape_char in "01234567":
                    # Octal escape: up to 3 digits
                    k = j + 2
                    count = 1
                    while k < len(line) and line[k] in "01234567" and count < 3:
                        k += 1
                        count += 1
                    j = k - 1
                elif escape_char == "x":
                    # Hex escape: one or more hex digits
                    k = j + 2
                    if k >= len(line) or not (line[k].isalnum() and (line[k].isdigit() or line[k].lower() in "abcdef")):
                        has_error = True
                    else:
                        while k < len(line) and line[k].isalnum() and (line[k].isdigit() or line[k].lower() in "abcdef"):
                            k += 1
                        j = k - 1
                else:
                    j += 1
                j += 1
            else:
                j += 1
        
        if j >= len(line):
            # Unterminated string/char literal
            value = line[start:]
            self.errors.append(LexError(f"Unterminated { 'string' if delim == '\"' else 'character' } literal", line_no, start + 1))
            return Token(TK.ERROR, value, line_no, start + 1), len(line)
        
        value = line[start : j + 1]
        if has_error:
            self.errors.append(LexError("Invalid escape sequence in string literal", line_no, start + 1))
            return Token(TK.ERROR, value, line_no, start + 1), j + 1
        return Token(kind, value, line_no, start + 1), j + 1

    def _read_word(self, line: str, start: int, line_no: int):
        j = start
        while j < len(line) and (line[j].isalnum() or line[j] == "_"):
            j += 1
        value = line[start:j]
        # Should only be called for identifiers (starting with letter/underscore)
        if value in TYPES:
            kind = TK.TYPE
        elif value in UNSUPPORTED_KEYWORDS:
            kind = TK.ERROR
        elif value in KEYWORDS:
            kind = TK.KEYWORD
        else:
            kind = TK.IDENT
        return Token(kind, value, line_no, start + 1), j


# ─── Pretty-print helper ───────────────────────────────────────────────────────

def print_tokens(tokens: List[Token]) -> None:
    """Print a formatted token table to stdout."""
    header = f"{'#':<5} {'Kind':<12} {'Value':<25} {'Line':>4} {'Col':>4}"
    print(header)
    print("─" * len(header))
    for i, t in enumerate(tokens):
        if t.kind is TK.EOF:
            break
        print(f"{i:<5} {t.kind.name:<12} {t.value!r:<25} {t.line:>4} {t.col:>4}")
