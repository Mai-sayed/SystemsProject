"""
compiler/tac.py
───────────────
Phase 4 — Optimised Intermediate Code Generation

Generates Three-Address Code (TAC) from the AST, then applies two
classical optimisation passes:

  1. Constant Folding   — evaluate constant expressions at compile time
  2. Dead Code Elimination — remove assignments to temporaries that are
                             never subsequently read

TAC instruction format
──────────────────────
  Each instruction is a dict:
  { "kind": str, "text": str, "raw": str, "folded": bool, "dead": bool }

  kind values:
    label   function / jump label
    begin   BeginFunc marker
    end     EndFunc marker
    param   parameter declaration or call argument
    assign  t = x op y  /  x = y
    call    t = call f, n
    branch  ifFalse t goto L
    jump    goto L
    io      print / read
    return  return t
    blank   empty separator line

Raw vs optimised text are both stored so the dashboard can show both.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple


# ─── Instruction data class ───────────────────────────────────────────────────

def instr(kind: str, text: str, **extra) -> Dict[str, Any]:
    return {"kind": kind, "text": text, "raw": text, "folded": False, "dead": False, **extra}


# ─── TAC Generator ────────────────────────────────────────────────────────────

class TACGenerator:

    def __init__(self) -> None:
        self._temp  = 0
        self._label = 0
        self._code: List[Dict[str, Any]] = []

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _t(self) -> str:
        self._temp += 1
        return f"t{self._temp}"

    def _L(self) -> str:
        self._label += 1
        return f"L{self._label}"

    def _emit(self, ins: Dict[str, Any]) -> None:
        self._code.append(ins)

    # ── Public entry ─────────────────────────────────────────────────────────

    def generate(self, ast: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Walk the AST and emit TAC instructions. Returns the raw instruction list."""
        for fn in ast.get("functions", []):
            self._gen_function(fn)
        return self._code

    # ── Function ─────────────────────────────────────────────────────────────

    def _gen_function(self, fn: Dict) -> None:
        name = fn.get("name", "?")
        self._emit(instr("label",  f"{name}:"))
        self._emit(instr("begin",  f"BeginFunc {name}"))
        for p in fn.get("params", []):
            self._emit(instr("param", f"  param {p.get('name','?')} : {p.get('dataType','?')}"))
        self._gen_block(fn.get("body"))
        self._emit(instr("end",    f"EndFunc {name}"))
        self._emit(instr("blank",  ""))

    # ── Block ─────────────────────────────────────────────────────────────────

    def _gen_block(self, block: Optional[Dict]) -> None:
        if not block:
            return
        for stmt in block.get("statements", []):
            self._gen_stmt(stmt)

    # ── Statement ────────────────────────────────────────────────────────────

    def _gen_stmt(self, stmt: Optional[Dict]) -> None:
        if not stmt:
            return
        kind = stmt.get("type")

        if kind == "VarDecl":
            if stmt.get("init"):
                t = self._gen_expr(stmt["init"])
                self._emit(instr("assign", f"  {stmt['name']} = {t}"))
            else:
                self._emit(instr("assign", f"  {stmt['name']}: {stmt.get('dataType','?')}"))

        elif kind == "ExprStmt":
            self._gen_expr(stmt.get("expr"))

        elif kind == "ReturnStmt":
            if stmt.get("value"):
                t = self._gen_expr(stmt["value"])
                self._emit(instr("return", f"  return {t}"))
            else:
                self._emit(instr("return", f"  return"))

        elif kind == "CoutStmt":
            for arg in stmt.get("args", []):
                t = self._gen_expr(arg)
                self._emit(instr("io", f"  print {t}"))

        elif kind == "CinStmt":
            for var in stmt.get("variables", []):
                self._emit(instr("io", f"  read {var}"))

        elif kind == "IfStmt":
            cond   = self._gen_expr(stmt.get("condition"))
            l_else = self._L()
            l_end  = self._L()
            self._emit(instr("branch", f"  ifFalse {cond} goto {l_else}"))
            self._gen_block(stmt.get("then"))
            if stmt.get("else"):
                self._emit(instr("jump",   f"  goto {l_end}"))
            self._emit(instr("label",  f"{l_else}:"))
            if stmt.get("else"):
                self._gen_block(stmt["else"])
                self._emit(instr("label", f"{l_end}:"))

        elif kind == "WhileStmt":
            l_top = self._L()
            l_end = self._L()
            self._emit(instr("label",  f"{l_top}:"))
            cond = self._gen_expr(stmt.get("condition"))
            self._emit(instr("branch", f"  ifFalse {cond} goto {l_end}"))
            self._gen_block(stmt.get("body"))
            self._emit(instr("jump",   f"  goto {l_top}"))
            self._emit(instr("label",  f"{l_end}:"))

        elif kind == "ForStmt":
            l_top = self._L()
            l_end = self._L()
            if stmt.get("init"):
                self._gen_stmt(stmt["init"])
            self._emit(instr("label",  f"{l_top}:"))
            if stmt.get("condition"):
                cond = self._gen_expr(stmt["condition"])
                self._emit(instr("branch", f"  ifFalse {cond} goto {l_end}"))
            self._gen_block(stmt.get("body"))
            if stmt.get("update"):
                self._gen_expr(stmt["update"])
            self._emit(instr("jump",   f"  goto {l_top}"))
            self._emit(instr("label",  f"{l_end}:"))

    # ── Expression ───────────────────────────────────────────────────────────

    def _gen_expr(self, expr: Optional[Dict]) -> str:
        """Recursively emit TAC for an expression and return the result operand."""
        if not expr:
            return "?"
        kind = expr.get("type")

        if kind == "Literal":
            return str(expr.get("value", "?"))

        if kind == "Identifier":
            return expr.get("name", "?")

        if kind == "FuncCall":
            for arg in expr.get("args", []):
                a = self._gen_expr(arg)
                self._emit(instr("param", f"  param {a}"))
            r = self._t()
            self._emit(instr("call", f"  {r} = call {expr.get('name','?')}, {len(expr.get('args',[]))}"))
            return r

        if kind == "UnaryOp":
            operand = self._gen_expr(expr.get("operand"))
            r       = self._t()
            self._emit(instr("assign", f"  {r} = {expr.get('op','')} {operand}"))
            return r

        if kind == "BinaryOp":
            op  = expr.get("op", "?")
            # assignment operators
            if op in ("=", "+=", "-=", "*=", "/="):
                rhs = self._gen_expr(expr.get("right"))
                lhs = self._expr_name(expr.get("left"))
                if op == "=":
                    self._emit(instr("assign", f"  {lhs} = {rhs}"))
                else:
                    real_op = op[0]   # + from +=, etc.
                    tmp     = self._t()
                    self._emit(instr("assign", f"  {tmp} = {lhs} {real_op} {rhs}"))
                    self._emit(instr("assign", f"  {lhs} = {tmp}"))
                return lhs
            # regular binary
            lt = self._gen_expr(expr.get("left"))
            rt = self._gen_expr(expr.get("right"))
            r  = self._t()
            self._emit(instr("assign", f"  {r} = {lt} {op} {rt}"))
            return r

        return "?"

    @staticmethod
    def _expr_name(expr: Optional[Dict]) -> str:
        if not expr:
            return "?"
        if expr.get("type") == "Identifier":
            return expr.get("name", "?")
        return "?"


# ─── Optimisation passes ──────────────────────────────────────────────────────

def _constant_fold(code: List[Dict]) -> List[Dict]:
    """
    Constant Folding Pass
    ─────────────────────
    Replace instructions of the form  t = <num> op <num>  with the
    pre-computed result.  Update a const-map so downstream reads of the
    folded temp are also replaced (constant propagation).
    Also handles constant assignment and propagates known constants.
    """
    import re
    
    pattern = re.compile(
        r"^\s*(\w+)\s*=\s*(-?[\d.]+)\s*([\+\-\*\/])\s*(-?[\d.]+)\s*$"
    )
    const_assign = re.compile(r"^\s*(\w+)\s*=\s*(-?[\d.]+)\s*$")
    
    consts: Dict[str, str] = {}
    out: List[Dict] = []

    for ins in code:
        if ins["kind"] == "assign":
            # Case 1: Binary operation with constants: t = num op num
            m = pattern.match(ins["text"])
            if m:
                dest, a, op, b = m.groups()
                try:
                    fa, fb = float(a), float(b)
                    if op == "+": val = fa + fb
                    elif op == "-": val = fa - fb
                    elif op == "*": val = fa * fb
                    elif op == "/":
                        val = fa / fb if fb != 0 else None
                    else:
                        val = None
                    if val is not None:
                        # Use int representation when possible
                        val_str = str(int(val)) if val == int(val) else str(val)
                        consts[dest] = val_str
                        new_ins = dict(ins)
                        new_ins["text"]   = ins["text"].rstrip() + f"   # folded → {val_str}"
                        new_ins["folded"] = True
                        out.append(new_ins)
                        continue
                except (ValueError, ZeroDivisionError):
                    pass

            # Case 2: Direct constant assignment: t = num
            m2 = const_assign.match(ins["text"])
            if m2:
                dest, val_str = m2.groups()
                consts[dest] = val_str
                new_ins = dict(ins)
                new_ins["text"] = ins["text"]
                out.append(new_ins)
                continue

            # Case 3: Constant propagation: replace known temps on RHS
            new_text = ins["text"]
            modified = False
            for k, v in consts.items():
                # Match uses of k on the RHS (after =), not on LHS
                if "=" in new_text:
                    lhs, rhs = new_text.split("=", 1)
                    new_rhs = re.sub(rf"\b{k}\b", v, rhs)
                    if new_rhs != rhs:
                        new_text = lhs + "=" + new_rhs
                        modified = True
            
            new_ins = dict(ins)
            if modified:
                new_ins["text"] = new_text
                new_ins["folded"] = True
            out.append(new_ins)
        else:
            out.append(dict(ins))

    return out


def _dead_code_eliminate(code: List[Dict]) -> List[Dict]:
    """
    Dead Code Elimination Pass
    ──────────────────────────
    A temporary variable tN is "dead" if it is defined exactly once and
    never appears on the *right-hand side* of any subsequent instruction.
    Mark such assignments as dead (they remain in the output but are
    visually struck through in the dashboard).
    """
    import re

    # Count uses: an operand use is any occurrence outside the definition position
    define_re = re.compile(r"^\s*(t\d+)\s*=")
    use_counts: Dict[str, int] = {}

    for ins in code:
        if ins["kind"] not in ("assign", "branch", "return", "io", "call", "param"):
            continue
        text = ins["text"]
        # Strip the definition from the text before counting uses
        def_m = define_re.match(text)
        scan_text = text[def_m.end():] if def_m else text
        for t in re.findall(r"\bt\d+\b", scan_text):
            use_counts[t] = use_counts.get(t, 0) + 1

    out: List[Dict] = []
    for ins in code:
        if ins["kind"] == "assign":
            def_m = define_re.match(ins["text"])
            if def_m:
                dest = def_m.group(1)
                # Dead if never used (or only in its own definition)
                if use_counts.get(dest, 0) == 0:
                    new_ins = dict(ins)
                    new_ins["dead"] = True
                    out.append(new_ins)
                    continue
        out.append(dict(ins))
    return out


def optimise(code: List[Dict]) -> List[Dict]:
    """Apply all optimisation passes and return the optimised instruction list."""
    code = _constant_fold(code)
    code = _dead_code_eliminate(code)
    return code


# ─── Convenience ─────────────────────────────────────────────────────────────

def generate_tac(ast: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate and optimise TAC from *ast*.
    Returns ``{"raw": […], "optimised": […]}``.
    """
    gen = TACGenerator()
    raw = gen.generate(ast)
    opt = optimise([dict(i) for i in raw])  # optimise a copy
    return {"raw": raw, "optimised": opt}


# ─── CLI smoke-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from lexer     import Lexer
    from parser    import parse_tokens
    from semantic  import analyse_ast

    src = """
#include <iostream>
using namespace std;

int add(int a, int b) {
    int result = a + b;
    return result;
}

int main() {
    int x = 2 + 3;
    int y = x * 4;
    cout << y << endl;
    return 0;
}
"""
    tokens  = Lexer().tokenize(src)
    parsed  = parse_tokens(tokens)
    result  = generate_tac(parsed["ast"])

    print("=== Raw TAC ===")
    for ins in result["raw"]:
        if ins["kind"] != "blank":
            print(ins["text"])

    print("\n=== Optimised TAC ===")
    for ins in result["optimised"]:
        if ins["kind"] == "blank":
            continue
        prefix = "[DEAD] " if ins.get("dead") else ("[FOLD] " if ins.get("folded") else "       ")
        if ins["kind"] == "label":
            print(ins["text"])
        else:
            print(prefix + ins["text"])
class TACOptimizer:
    def __init__(self, tac_instructions):
        self.tac = tac_instructions

    def constant_folding(self):
        optimized = []
        for instr in self.tac:
            # Example: t1 = 5 + 3
            if instr.op in ['+', '-', '*', '/', '%']:
                if instr.arg1.isdigit() and instr.arg2.isdigit():
                    # Evaluate at compile time
                    value = eval(f"{instr.arg1}{instr.op}{instr.arg2}")
                    optimized.append(TACInstr(instr.result, str(value), None, '='))
                else:
                    optimized.append(instr)
            else:
                optimized.append(instr)
        self.tac = optimized

    def dead_code_elimination(self):
        # Track variables that are actually used
        used_vars = set()
        for instr in self.tac:
            if instr.arg1 and not instr.arg1.isdigit():
                used_vars.add(instr.arg1)
            if instr.arg2 and not instr.arg2.isdigit():
                used_vars.add(instr.arg2)

        optimized = []
        for instr in self.tac:
            # If result is never used, skip it
            if instr.result and instr.result not in used_vars:
                continue
            optimized.append(instr)
        self.tac = optimized

    def optimize(self):
        self.constant_folding()
        self.dead_code_elimination()
        return self.tac


# Example TAC instruction structure
class TACInstr:
    def __init__(self, result, arg1, arg2, op):
        self.result = result
        self.arg1 = arg1
        self.arg2 = arg2
        self.op = op

    def __repr__(self):
        if self.op == '=':
            return f"{self.result} = {self.arg1}"
        elif self.arg2:
            return f"{self.result} = {self.arg1} {self.op} {self.arg2}"
        else:
            return f"{self.result} = {self.op} {self.arg1}"
