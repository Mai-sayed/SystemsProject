"""
compiler/semantic.py
────────────────────
Phase 3 — Semantic Analyser

Responsibilities
────────────────
  a. Check every used variable is declared before use.
  b. Detect repeated (duplicate) variable declarations in the same scope.
  c. Check type compatibility in expressions (with implicit-conversion rules).
  d. Build and return a Symbol Table.

The analyser walks the AST produced by parser.py.
It maintains a stack of scopes so nested blocks are handled correctly.

Output dict (returned by `analyse`)
────────────────────────────────────
  {
    "symbol_table": [ {id, name, data_type, scope, value, status}, … ],
    "errors":       [ {msg, line}, … ],
    "warnings":     [ {msg, line}, … ],
    "includes":     [ {directive, lib}, … ],
  }
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple


# ─── Type compatibility ────────────────────────────────────────────────────────

# Pairs where the right type can be implicitly widened to the left type
_COMPATIBLE_PAIRS: set[Tuple[str, str]] = {
    ("float",  "int"),
    ("double", "int"),
    ("double", "float"),
    ("string", "char"),
}

def _types_compatible(target: str, source: str) -> bool:
    if target == source:
        return True
    return (target, source) in _COMPATIBLE_PAIRS


# ─── Scope helper ─────────────────────────────────────────────────────────────

class Scope:
    def __init__(self, name: str, parent: Optional["Scope"] = None) -> None:
        self.name   = name
        self.parent = parent
        self._syms: Dict[str, Dict[str, Any]] = {}

    def declare(self, name: str, info: Dict[str, Any]) -> bool:
        """Declare a symbol.  Returns False if already declared in *this* scope."""
        if name in self._syms:
            return False
        self._syms[name] = info
        return True

    def lookup(self, name: str) -> Optional[Dict[str, Any]]:
        """Look up a symbol, walking parent scopes."""
        if name in self._syms:
            return self._syms[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def lookup_local(self, name: str) -> Optional[Dict[str, Any]]:
        return self._syms.get(name)


# ─── Semantic Analyser ────────────────────────────────────────────────────────

# Built-in identifiers that don't need declaring
_BUILTINS = frozenset({"cout", "cin", "endl", "std", "main", "nullptr", "true", "false"})

class SemanticAnalyser:

    def __init__(self) -> None:
        self._sym_id   = 0
        self._sym_rows: List[Dict[str, Any]] = []
        self._errors:   List[Dict[str, Any]] = []
        self._warnings: List[Dict[str, Any]] = []

    # ── Public ───────────────────────────────────────────────────────────────

    def analyse(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        global_scope = Scope("global")
        # Pre-populate with declared functions so forward-calls work
        for fn in ast.get("functions", []):
            if fn and fn.get("name"):
                global_scope.declare(fn["name"], {"dataType": fn.get("returnType", "?"), "kind": "function"})

        # Global declarations
        for decl in ast.get("declarations", []):
            self._check_stmt(decl, global_scope)

        # Functions
        for fn in ast.get("functions", []):
            self._check_function(fn, global_scope)

        return {
            "symbol_table": self._sym_rows,
            "errors":       self._errors,
            "warnings":     self._warnings,
            "includes":     ast.get("includes", []),
        }

    # ── Private helpers ──────────────────────────────────────────────────────

    def _new_id(self) -> int:
        self._sym_id += 1
        return self._sym_id

    def _error(self, msg: str, line: Any = "?") -> None:
        self._errors.append({"msg": msg, "line": line})

    def _warn(self, msg: str, line: Any = "?") -> None:
        self._warnings.append({"msg": msg, "line": line})

    def _add_symbol(self, name: str, data_type: Optional[str],
                    scope_name: str, value: str, status: str = "ok") -> None:
        self._sym_rows.append({
            "id":        self._new_id(),
            "name":      name,
            "data_type": data_type or "?",
            "scope":     scope_name,
            "value":     value,
            "status":    status,
        })

    # ── Function ─────────────────────────────────────────────────────────────

    def _check_function(self, fn: Dict, parent_scope: Scope) -> None:
        if not fn:
            return
        name = fn.get("name", "?")
        local = Scope(name, parent=parent_scope)

        self._add_symbol(f"{name}()", fn.get("returnType"), "global", "function")

        # Parameters
        for p in fn.get("params", []):
            pname = p.get("name", "?")
            ptype = p.get("dataType", "?")
            if not local.declare(pname, {"dataType": ptype}):
                self._error(f"Duplicate parameter '{pname}' in function '{name}'")
            else:
                self._add_symbol(pname, ptype, name, "(param)")

        self._check_block(fn.get("body"), local)

    # ── Block ─────────────────────────────────────────────────────────────────

    def _check_block(self, block: Optional[Dict], scope: Scope) -> None:
        if not block:
            return
        for stmt in block.get("statements", []):
            self._check_stmt(stmt, scope)

    # ── Statement ────────────────────────────────────────────────────────────

    def _check_stmt(self, stmt: Optional[Dict], scope: Scope) -> None:
        if not stmt:
            return
        kind = stmt.get("type")

        if kind == "VarDecl":
            self._check_var_decl(stmt, scope)

        elif kind == "ExprStmt":
            self._check_expr(stmt.get("expr"), scope)

        elif kind == "CoutStmt":
            for arg in stmt.get("args", []):
                self._check_expr(arg, scope)

        elif kind == "CinStmt":
            for var in stmt.get("variables", []):
                if not scope.lookup(var) and var not in _BUILTINS:
                    self._error(f"Undeclared variable '{var}' used in cin")

        elif kind == "ReturnStmt":
            self._check_expr(stmt.get("value"), scope)

        elif kind == "IfStmt":
            self._check_expr(stmt.get("condition"), scope)
            self._check_block(stmt.get("then"), Scope("<if-then>", scope))
            if stmt.get("else"):
                self._check_block(stmt.get("else"), Scope("<if-else>", scope))

        elif kind == "WhileStmt":
            self._check_expr(stmt.get("condition"), scope)
            self._check_block(stmt.get("body"), Scope("<while>", scope))

        elif kind == "ForStmt":
            inner = Scope("<for>", scope)
            if stmt.get("init"):
                self._check_stmt(stmt["init"], inner)
            self._check_expr(stmt.get("condition"), inner)
            self._check_expr(stmt.get("update"), inner)
            self._check_block(stmt.get("body"), inner)

    # ── Variable declaration ──────────────────────────────────────────────────

    def _check_var_decl(self, stmt: Dict, scope: Scope) -> None:
        name  = stmt.get("name", "?")
        dtype = stmt.get("dataType", "?")
        init  = stmt.get("init")

        # Check for redeclaration in current scope
        if scope.lookup_local(name):
            self._error(f"Redeclaration of variable '{name}' in scope '{scope.name}'")
            self._add_symbol(name, dtype, scope.name, self._expr_str(init), status="error")
            return

        # Evaluate init expression type for compatibility check
        init_type = self._check_expr(init, scope) if init else None
        if init_type and init_type != "unknown" and not _types_compatible(dtype, init_type):
            self._warn(f"Type mismatch: assigning '{init_type}' to '{dtype}' variable '{name}'")

        scope.declare(name, {"dataType": dtype})
        self._add_symbol(name, dtype, scope.name, self._expr_str(init) or "—")

    # ── Expression type inference ─────────────────────────────────────────────

    def _check_expr(self, expr: Optional[Dict], scope: Scope) -> str:
        """Walk an expression node, check references, and return inferred type."""
        if not expr:
            return "unknown"
        kind = expr.get("type")

        if kind == "Literal":
            lk = expr.get("kind", "")
            if lk == "number":
                return "float" if "." in str(expr.get("value", "")) else "int"
            if lk == "string": return "string"
            if lk == "char":   return "char"
            if lk == "bool":   return "bool"
            return "unknown"

        if kind == "Identifier":
            name = expr.get("name", "?")
            if name in _BUILTINS:
                return "unknown"
            sym = scope.lookup(name)
            if sym is None:
                self._error(f"Undeclared variable '{name}'")
                return "unknown"
            return sym.get("dataType", "unknown")

        if kind == "BinaryOp":
            lt = self._check_expr(expr.get("left"),  scope)
            rt = self._check_expr(expr.get("right"), scope)
            op = expr.get("op", "")
            # assignment operators — type is the left side
            if op in ("=", "+=", "-=", "*=", "/="):
                if rt != "unknown" and lt != "unknown" and not _types_compatible(lt, rt):
                    self._warn(f"Possible type mismatch in assignment: {lt} {op} {rt}")
                return lt
            # comparison → bool
            if op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
                if lt != rt and lt != "unknown" and rt != "unknown":
                    self._warn(f"Comparing incompatible types: {lt} {op} {rt}")
                return "bool"
            # arithmetic
            if lt != rt and lt != "unknown" and rt != "unknown":
                self._warn(f"Arithmetic on mixed types: {lt} {op} {rt}")
            # widening
            for wider in ("double", "float", "int"):
                if wider in (lt, rt):
                    return wider
            return lt

        if kind == "UnaryOp":
            return self._check_expr(expr.get("operand"), scope)

        if kind == "FuncCall":
            fn_sym = scope.lookup(expr.get("name", ""))
            for arg in expr.get("args", []):
                self._check_expr(arg, scope)
            return fn_sym.get("dataType", "unknown") if fn_sym else "unknown"

        return "unknown"

    # ── Expression → string (for symbol table value column) ──────────────────

    @staticmethod
    def _expr_str(expr: Optional[Dict]) -> str:
        if not expr:
            return ""
        kind = expr.get("type")
        if kind == "Literal":    return str(expr.get("value", ""))
        if kind == "Identifier": return expr.get("name", "?")
        if kind == "BinaryOp":
            l = SemanticAnalyser._expr_str(expr.get("left"))
            r = SemanticAnalyser._expr_str(expr.get("right"))
            return f"{l} {expr.get('op','')} {r}"
        if kind == "UnaryOp":
            return f"{expr.get('op','')}{SemanticAnalyser._expr_str(expr.get('operand'))}"
        if kind == "FuncCall":
            args = ", ".join(SemanticAnalyser._expr_str(a) for a in expr.get("args", []))
            return f"{expr.get('name','?')}({args})"
        return "…"


# ─── Convenience ─────────────────────────────────────────────────────────────

def analyse_ast(ast: Dict[str, Any]) -> Dict[str, Any]:
    return SemanticAnalyser().analyse(ast)


# ─── CLI smoke-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    from lexer  import Lexer
    from parser import parse_tokens

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
    tokens  = Lexer().tokenize(src)
    parsed  = parse_tokens(tokens)
    sem_out = analyse_ast(parsed["ast"])

    print("=== Symbol Table ===")
    for row in sem_out["symbol_table"]:
        print(row)
    print("\n=== Errors ===")
    for e in sem_out["errors"]:
        print(e)
    print("\n=== Warnings ===")
    for w in sem_out["warnings"]:
        print(w)
