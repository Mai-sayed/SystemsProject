"""
compiler/parser.py
──────────────────
Phase 2 — Syntax Analyser
Recursive-descent parser that simulates *rightmost derivation in reverse*
(i.e., an LR-style bottom-up parse) by recording every production rule as
it is reduced.

Grammar coverage
────────────────
  • C++ function definitions (return-type, name, param list, body)
  • Variable declarations with optional initialiser
  • Expressions: assignment, comparison, additive, multiplicative, unary, primary
  • Statements: return, cout, cin, expression
  • Preprocessor directives are preserved in the AST (not parsed further)

Output
──────
  • ast  : a nested dict (JSON-serialisable) — the Abstract Syntax Tree
  • steps: list of {"rule": str, "sentential_form": str} for the derivation trace
  • errors: list of {"msg": str, "line": int, "col": int}
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lexer import TK, Token


# ─── AST node factories (simple dicts for easy JSON export) ────────────────────

def node(node_type: str, **kwargs) -> Dict[str, Any]:
    return {"type": node_type, **kwargs}


# ─── Parser ───────────────────────────────────────────────────────────────────

class Parser:
    """
    Parses a list of Token objects into an AST dict.

    Rightmost derivation in reverse
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Each call to `_reduce(rule, form)` records a derivation step.
    A step corresponds to recognising a handle (the right-hand side of a
    production) and reducing it to the non-terminal on the left-hand side —
    exactly what an LR parser does at each REDUCE action.
    The collected sequence, read from first to last, gives the *reverse* of
    the rightmost derivation.
    """

    def __init__(self, tokens: List[Token]) -> None:
        # Filter out comments and preprocessor tokens for parsing;
        # keep preprocessors separate so the semantic phase can read #includes.
        self._all = tokens
        self._toks = [t for t in tokens if t.kind not in (TK.COMMENT, TK.PREPROC, TK.EOF)]
        self._preprocTokens = [t for t in tokens if t.kind is TK.PREPROC]
        self._pos  = 0
        self.steps: List[Dict[str, str]] = []   # derivation trace
        self.errors: List[Dict[str, Any]] = []  # parse errors
        
        # Validate preprocessor directives
        self._validate_preprocessor_directives()

    # ── Public ──────────────────────────────────────────────────────────────

    def parse(self) -> Dict[str, Any]:
        """Entry point. Returns the AST for the whole translation unit."""
        return self._parse_program()

    # ── Derivation recording ─────────────────────────────────────────────────

    def _reduce(self, rule: str, form: str = "") -> None:
        """Record a REDUCE step (handle → non-terminal)."""
        self.steps.append({"rule": rule, "sentential_form": form})

    # ── Token stream helpers ─────────────────────────────────────────────────

    def _peek(self, offset: int = 0) -> Token:
        idx = self._pos + offset
        if idx < len(self._toks):
            return self._toks[idx]
        return Token(TK.EOF, "", 0, 0)

    def _consume(self, kind: Optional[TK] = None, value: Optional[str] = None) -> Optional[Token]:
        t = self._peek()
        if t.kind is TK.EOF:
            self.errors.append({"msg": f"Unexpected EOF (expected {kind} {value!r})", "line": "?", "col": "?"})
            return None
        if kind and t.kind is not kind:
            self.errors.append({"msg": f"Expected {kind.name} '{value or ''}', got '{t.value}'", "line": t.line, "col": t.col})
            return None
        if value and t.value != value:
            self.errors.append({"msg": f"Expected '{value}', got '{t.value}'", "line": t.line, "col": t.col})
            return None
        self._pos += 1
        return t

    def _match(self, kind: Optional[TK] = None, value: Optional[str] = None) -> bool:
        t = self._peek()
        ok = True
        if kind:  ok = ok and (t.kind is kind)
        if value: ok = ok and (t.value == value)
        return ok

    def _skip_until(self, *values: str) -> None:
        """Error-recovery: advance until one of *values* is found."""
        while not self._match(TK.EOF) and self._peek().value not in values:
            self._pos += 1

    def _validate_preprocessor_directives(self) -> None:
        """Validate preprocessor directives: #include must have proper syntax."""
        import re
        for tok in self._preprocTokens:
            if tok.value.startswith("#include"):
                # Check for proper syntax: #include <header> or #include "header"
                if not re.match(r'^\s*#\s*include\s*[<"]([^>"]*)[>"]', tok.value):
                    if "<" in tok.value and ">" not in tok.value:
                        self.errors.append({"msg": f"Syntax error: #include missing closing '>'", "line": tok.line, "col": tok.col})
                    elif '"' in tok.value and tok.value.count('"') == 1:
                        self.errors.append({"msg": f"Syntax error: #include missing closing '\"'", "line": tok.line, "col": tok.col})
                    else:
                        self.errors.append({"msg": f"Syntax error: malformed #include directive - use #include <header> or #include \"header\"", "line": tok.line, "col": tok.col})

    # ── Grammar productions ──────────────────────────────────────────────────

    # Program → Decl* FuncDef*
    def _parse_program(self) -> Dict[str, Any]:
        self._reduce("Program → Declaration* FunctionDef*", "<program>")
        declarations: List[Dict] = []
        functions:    List[Dict] = []
        includes = [{"directive": t.value, "lib": t.lib} for t in self._preprocTokens]

        while not self._match(TK.EOF):
            t = self._peek()
            # Function: type ident (
            if t.kind in (TK.TYPE, TK.KEYWORD) and self._peek(1).kind is TK.IDENT and self._peek(2).value == "(":
                functions.append(self._parse_function_def())
            elif t.kind is TK.TYPE:
                declarations.append(self._parse_var_decl())
            elif t.kind is TK.KEYWORD and t.value == "using":
                using = self._parse_using_directive()
                if using:
                    declarations.append(using)
            elif t.kind is TK.KEYWORD and t.value == "namespace":
                self.errors.append({"msg": "Unsupported top-level namespace directive", "line": t.line, "col": t.col})
                self._pos += 1
                while not self._match(TK.PUNCT, ";"):
                    if self._match(TK.EOF): break
                    self._pos += 1
                if self._match(TK.PUNCT, ";"):
                    self._pos += 1
            else:
                self._pos += 1   # skip unknown top-level token

        return node("Program", includes=includes, declarations=declarations, functions=functions)

    # FunctionDef → Type IDENT ( Params ) Block
    def _parse_function_def(self) -> Dict[str, Any]:
        self._reduce("FunctionDef → Type IDENT ( Params ) Block")
        ret_tok  = self._consume()                          # type / keyword
        name_tok = self._consume(TK.IDENT)
        self._consume(TK.PUNCT, "(")
        params = self._parse_params()
        self._consume(TK.PUNCT, ")")
        body   = self._parse_block()
        return node("FunctionDef",
                    returnType=ret_tok.value if ret_tok else None,
                    name=name_tok.value if name_tok else None,
                    params=params,
                    body=body)

    # Params → ε | Param (, Param)*
    def _parse_params(self) -> List[Dict]:
        self._reduce("Params → ε | Param (, Param)*")
        params: List[Dict] = []
        while not self._match(TK.PUNCT, ")") and not self._match(TK.EOF):
            ty   = self._consume()
            name = self._consume(TK.IDENT)
            params.append(node("Param",
                               dataType=ty.value if ty else None,
                               name=name.value if name else None))
            if self._match(TK.PUNCT, ","):
                self._consume(TK.PUNCT, ",")
        return params

    # Block → { Stmt* }
    def _parse_block(self) -> Dict[str, Any]:
        self._reduce("Block → { Stmt* }")
        self._consume(TK.PUNCT, "{")
        stmts: List[Dict] = []
        while not self._match(TK.PUNCT, "}") and not self._match(TK.EOF):
            stmts.append(self._parse_stmt())
        self._consume(TK.PUNCT, "}")
        return node("Block", statements=stmts)

    # Stmt → VarDecl | ExprStmt | ReturnStmt | CoutStmt | CinStmt
    def _parse_stmt(self) -> Dict[str, Any]:
        t = self._peek()
        if t.kind is TK.IDENT and t.value == "cout":
            return self._parse_cout()
        if t.kind is TK.IDENT and t.value == "cin":
            return self._parse_cin()
        if t.kind is TK.KEYWORD:
            if t.value == "return": return self._parse_return()
            if t.value in ("if", "while", "for"):
                self.errors.append({"msg": f"Unsupported construct '{t.value}'", "line": t.line, "col": t.col})
                # Skip the construct
                self._pos += 1  # consume the keyword
                self._skip_until(";", "}")
                return node("ErrorStmt", value=t.value)
        if t.kind is TK.TYPE:
            return self._parse_var_decl()
        if t.kind is TK.IDENT:
            return self._parse_expr_stmt()
        # fallback: skip token
        self._pos += 1
        return node("Unknown", value=t.value)

    # CoutStmt → cout (<< Expr)+ ;
    def _parse_cout(self) -> Dict[str, Any]:
        self._reduce("CoutStmt → cout (<< Expr)+ ;")
        self._consume(TK.IDENT)          # "cout"
        args: List[Dict] = []
        while self._match(TK.OP, "<<"):
            self._consume(TK.OP, "<<")
            args.append(self._parse_expr())
        self._consume(TK.PUNCT, ";")
        return node("CoutStmt", args=args)

    # CinStmt → cin (>> IDENT)+ ;
    def _parse_cin(self) -> Dict[str, Any]:
        self._reduce("CinStmt → cin (>> IDENT)+ ;")
        self._consume(TK.IDENT)          # "cin"
        variables: List[str] = []
        while self._match(TK.OP, ">>"):
            self._consume(TK.OP, ">>")
            id_tok = self._consume(TK.IDENT)
            if id_tok:
                variables.append(id_tok.value)
        self._consume(TK.PUNCT, ";")
        return node("CinStmt", variables=variables)

    # UsingDirective → using namespace IDENT ;
    def _parse_using_directive(self) -> Optional[Dict[str, Any]]:
        self._reduce("UsingDirective → using namespace IDENT ;")
        self._consume(TK.KEYWORD, "using")
        self._consume(TK.KEYWORD, "namespace")
        name_tok = self._consume(TK.IDENT)
        self._consume(TK.PUNCT, ";")
        return node("UsingDirective", namespace=name_tok.value if name_tok else None)

    # ReturnStmt → return Expr? ;
    def _parse_return(self) -> Dict[str, Any]:
        self._reduce("ReturnStmt → return Expr? ;")
        self._consume(TK.KEYWORD, "return")
        value = None
        if not self._match(TK.PUNCT, ";"):
            value = self._parse_expr()
        self._consume(TK.PUNCT, ";")
        return node("ReturnStmt", value=value)

    # VarDecl → Type IDENT (= Expr)? ;
    def _parse_var_decl(self, no_semi: bool = False) -> Dict[str, Any]:
        self._reduce("VarDecl → Type IDENT (= Expr)? ;")
        ty   = self._consume()
        name = self._consume(TK.IDENT)
        init = None
        if self._match(TK.OP, "="):
            self._consume(TK.OP, "=")
            init = self._parse_expr()
        if not no_semi:
            self._consume(TK.PUNCT, ";")
        return node("VarDecl",
                    dataType=ty.value if ty else None,
                    name=name.value if name else None,
                    init=init)

    # ExprStmt → Expr ;
    def _parse_expr_stmt(self) -> Dict[str, Any]:
        self._reduce("ExprStmt → Expr ;")
        expr = self._parse_expr()
        self._consume(TK.PUNCT, ";")
        return node("ExprStmt", expr=expr)

    # ── Expression hierarchy (precedence climbing) ───────────────────────────

    def _parse_expr(self) -> Dict[str, Any]:
        self._reduce("Expr → Assign")
        return self._parse_assign()

    def _parse_assign(self) -> Dict[str, Any]:
        left = self._parse_compar()
        if self._peek().kind is TK.OP and self._peek().value in ("=", "+=", "-=", "*=", "/="):
            op = self._consume()
            # NEW ERROR CHECK
            if self._peek().kind is TK.OP:
                self.errors.append({
                    "msg": f"Syntax error: unexpected operator '{self._peek().value}' after '{op.value}'",
                    "line": self._peek().line,
                    "col": self._peek().col
                })
                self._pos += 1
                # bail out early since we can't form a valid assignment
                return left
            right = self._parse_assign()
            self._reduce(f"Assign → Compar {op.value} Assign")
            return node("BinaryOp", op=op.value, left=left, right=right)
        return left

    def _parse_compar(self) -> Dict[str, Any]:
        left = self._parse_addsub()
        _OPS = {"==", "!=", "<", ">", "<=", ">=", "&&", "||"}
        while self._peek().kind is TK.OP and self._peek().value in _OPS:
            op    = self._consume()
            right = self._parse_addsub()
            self._reduce(f"Compar → AddSub {op.value} AddSub")
            left  = node("BinaryOp", op=op.value, left=left, right=right)
        return left

    def _parse_addsub(self) -> Dict[str, Any]:
        left = self._parse_muldiv()
        while self._peek().kind is TK.OP and self._peek().value in ("+", "-"):
            op    = self._consume()
            right = self._parse_muldiv()
            self._reduce(f"AddSub → MulDiv {op.value} MulDiv")
            left  = node("BinaryOp", op=op.value, left=left, right=right)
        return left

    def _parse_muldiv(self) -> Dict[str, Any]:
        left = self._parse_unary()
        while self._peek().kind is TK.OP and self._peek().value in ("*", "/", "%"):
            op    = self._consume()
            right = self._parse_unary()
            self._reduce(f"MulDiv → Unary {op.value} Unary")
            left  = node("BinaryOp", op=op.value, left=left, right=right)
        return left

    def _parse_unary(self) -> Dict[str, Any]:
        if self._peek().kind is TK.OP and self._peek().value in ("!", "-", "++", "--"):
            op      = self._consume()
            operand = self._parse_primary()
            self._reduce(f"Unary → {op.value} Primary")
            return node("UnaryOp", op=op.value, operand=operand)
        return self._parse_primary()

    def _parse_primary(self) -> Dict[str, Any]:
        t = self._peek()
        if t.kind is TK.NUMBER:
            self._pos += 1
            return node("Literal", kind="number", value=t.value)
        if t.kind is TK.STRING:
            self._pos += 1
            return node("Literal", kind="string", value=t.value)
        if t.kind is TK.CHAR_LIT:
            self._pos += 1
            return node("Literal", kind="char", value=t.value)
        if t.kind is TK.KEYWORD and t.value in ("true", "false"):
            self._pos += 1
            return node("Literal", kind="bool", value=t.value)
        if t.kind is TK.IDENT:
            self._pos += 1
            # function call
            if self._match(TK.PUNCT, "("):
                self._consume(TK.PUNCT, "(")
                args: List[Dict] = []
                while not self._match(TK.PUNCT, ")") and not self._match(TK.EOF):
                    args.append(self._parse_expr())
                    if self._match(TK.PUNCT, ","):
                        self._consume(TK.PUNCT, ",")
                self._consume(TK.PUNCT, ")")
                self._reduce(f"Primary → IDENT '(' Args ')'")
                return node("FuncCall", name=t.value, args=args)
            # post-increment / decrement
            if self._match(TK.OP, "++"):
                self._pos += 1
                return node("UnaryOp", op="++(post)", operand=node("Identifier", name=t.value))
            if self._match(TK.OP, "--"):
                self._pos += 1
                return node("UnaryOp", op="--(post)", operand=node("Identifier", name=t.value))
            return node("Identifier", name=t.value)
        if self._match(TK.PUNCT, "("):
            self._consume(TK.PUNCT, "(")
            e = self._parse_expr()
            self._consume(TK.PUNCT, ")")
            return e
        # No valid primary expression found — syntax error
        self.errors.append({
            "msg": f"Syntax error: unexpected token '{t.value}' in expression",
            "line": t.line,
            "col": t.col
        })
        self._pos += 1
        # Return a placeholder node to allow parsing to continue
        return node("Error", value=t.value)


# ─── Convenience function ─────────────────────────────────────────────────────

def parse_tokens(tokens: List[Token]) -> Dict[str, Any]:
    """Parse *tokens* and return ``{"ast": …, "steps": […], "errors": […]}``."""
    p   = Parser(tokens)
    ast = p.parse()
    return {"ast": ast, "steps": p.steps, "errors": p.errors}


# ─── CLI smoke-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from lexer import Lexer

    src = """
#include <iostream>
using namespace std;

int add(int a, int b) {
    int result = a + b;
    return result;
}

int main() {
    int x = 5;
    int y = add(x, 3);
    cout << y << endl;
    return 0;
}
"""
    tokens = Lexer().tokenize(src)
    result = parse_tokens(tokens)
    print(json.dumps(result["ast"], indent=2))
    print(f"\n{len(result['steps'])} derivation steps, {len(result['errors'])} errors.")
