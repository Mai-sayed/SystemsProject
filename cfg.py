"""
compiler/cfg.py
───────────────
Context-Free Grammar for the C++ subset supported by this compiler.

This module is *documentation + data* — it is not used at runtime by the
parser (which is hand-written recursive descent), but it:

  • defines the formal grammar in a structured, machine-readable way
  • provides a pretty-printer for the CFG
  • provides a first/follow set calculator (useful for LL(1) analysis reference)

Grammar notation
────────────────
  Non-terminals  : PascalCase strings, e.g. "Program", "FunctionDef"
  Terminals      : lowercase or quoted symbols, e.g. "int", "'('", "id", "num"
  ε              : empty string (epsilon)
  A → α | β     : two alternative productions for A

All productions correspond 1-to-1 with the reduce steps emitted by parser.py.
"""

from __future__ import annotations
from typing import Dict, FrozenSet, List, Set, Tuple


# ─── Grammar definition ───────────────────────────────────────────────────────
#
# Each rule is (NonTerminal, [alternative_1, alternative_2, …])
# where each alternative is a list of symbols (strings).
# Symbols starting with an uppercase letter are non-terminals.
# Everything else is a terminal.

TERMINALS = {
    "id", "num", "str", "char_lit",
    "int", "float", "double", "char", "bool", "void", "string",
    "if", "else", "while", "for", "do", "return", "break", "continue",
    "true", "false",
    "cout", "cin", "endl",
    "(", ")", "{", "}", ";", ",",
    "=", "+=", "-=", "*=", "/=",
    "==", "!=", "<", ">", "<=", ">=",
    "&&", "||", "!", "++", "--",
    "+", "-", "*", "/", "%",
    "<<", ">>",
    "#include",
    "ε",
}

# Productions: NonTerminal → list of sequences
PRODUCTIONS: List[Tuple[str, List[List[str]]]] = [
    ("Program", [
        ["Declaration*", "FunctionDef*"],
    ]),
    ("FunctionDef", [
        ["Type", "id", "(", "Params", ")", "Block"],
    ]),
    ("Params", [
        ["ε"],
        ["Param", "ParamTail"],
    ]),
    ("ParamTail", [
        ["ε"],
        [",", "Param", "ParamTail"],
    ]),
    ("Param", [
        ["Type", "id"],
    ]),
    ("Block", [
        ["{", "StmtList", "}"],
    ]),
    ("StmtList", [
        ["ε"],
        ["Stmt", "StmtList"],
    ]),
    ("Stmt", [
        ["VarDecl"],
        ["ExprStmt"],
        ["IfStmt"],
        ["WhileStmt"],
        ["ForStmt"],
        ["ReturnStmt"],
        ["CoutStmt"],
        ["CinStmt"],
    ]),
    ("VarDecl", [
        ["Type", "id", ";"],
        ["Type", "id", "=", "Expr", ";"],
    ]),
    ("CoutStmt", [
        ["cout", "CoutArgs", ";"],
    ]),
    ("CoutArgs", [
        ["<<", "Expr"],
        ["<<", "Expr", "CoutArgs"],
    ]),
    ("CinStmt", [
        ["cin", "CinArgs", ";"],
    ]),
    ("CinArgs", [
        [">>", "id"],
        [">>", "id", "CinArgs"],
    ]),
    ("ReturnStmt", [
        ["return", ";"],
        ["return", "Expr", ";"],
    ]),
    ("IfStmt", [
        ["if", "(", "Expr", ")", "Block"],
        ["if", "(", "Expr", ")", "Block", "else", "Block"],
    ]),
    ("WhileStmt", [
        ["while", "(", "Expr", ")", "Block"],
    ]),
    ("ForStmt", [
        ["for", "(", "ForInit", ";", "ForCond", ";", "ForUpdate", ")", "Block"],
    ]),
    ("ForInit", [
        ["ε"],
        ["VarDeclNoSemi"],
    ]),
    ("VarDeclNoSemi", [
        ["Type", "id"],
        ["Type", "id", "=", "Expr"],
    ]),
    ("ForCond", [
        ["ε"],
        ["Expr"],
    ]),
    ("ForUpdate", [
        ["ε"],
        ["Expr"],
    ]),
    ("ExprStmt", [
        ["Expr", ";"],
    ]),
    # ── Expression grammar (stratified by precedence) ──────────────────────
    ("Expr", [
        ["Assign"],
    ]),
    ("Assign", [
        ["Compar"],
        ["Compar", "AssignOp", "Assign"],
    ]),
    ("AssignOp", [
        ["="], ["+="], ["-="], ["*="], ["/="],
    ]),
    ("Compar", [
        ["AddSub"],
        ["AddSub", "CmpOp", "Compar"],
    ]),
    ("CmpOp", [
        ["=="], ["!="], ["<"], [">"], ["<="], [">="], ["&&"], ["||"],
    ]),
    ("AddSub", [
        ["MulDiv"],
        ["MulDiv", "AddOp", "AddSub"],
    ]),
    ("AddOp", [
        ["+"], ["-"],
    ]),
    ("MulDiv", [
        ["Unary"],
        ["Unary", "MulOp", "MulDiv"],
    ]),
    ("MulOp", [
        ["*"], ["/"], ["%"],
    ]),
    ("Unary", [
        ["Primary"],
        ["!", "Unary"],
        ["-", "Unary"],
        ["++", "Primary"],
        ["--", "Primary"],
    ]),
    ("Primary", [
        ["num"],
        ["str"],
        ["char_lit"],
        ["true"],
        ["false"],
        ["id"],
        ["id", "(", "ArgList", ")"],
        ["(", "Expr", ")"],
    ]),
    ("ArgList", [
        ["ε"],
        ["Expr", "ArgTail"],
    ]),
    ("ArgTail", [
        ["ε"],
        [",", "Expr", "ArgTail"],
    ]),
    # ── Type non-terminal ──────────────────────────────────────────────────
    ("Type", [
        ["int"], ["float"], ["double"], ["char"],
        ["bool"], ["void"], ["string"],
    ]),
]

# ─── Index for fast lookup ───────────────────────────────────────────────────

NT_SET: FrozenSet[str] = frozenset(nt for nt, _ in PRODUCTIONS)
PROD_MAP: Dict[str, List[List[str]]] = {nt: alts for nt, alts in PRODUCTIONS}


# ─── Pretty-printer ───────────────────────────────────────────────────────────

def print_cfg(numbered: bool = True) -> None:
    """Print the entire CFG to stdout."""
    print("Context-Free Grammar (C++ subset)")
    print("═" * 60)
    rule_num = 1
    for nt, alts in PRODUCTIONS:
        for i, alt in enumerate(alts):
            prefix = f"{rule_num:>3}. " if numbered else "     "
            lhs    = nt if i == 0 else " " * len(nt)
            arrow  = "→" if i == 0 else "|"
            rhs    = "  ".join(alt)
            print(f"{prefix}{lhs:<18} {arrow}  {rhs}")
            rule_num += 1
    print()


# ─── FIRST / FOLLOW sets (reference only) ────────────────────────────────────

def _first(symbol: str, memo: Dict) -> Set[str]:
    if symbol in memo:
        return memo[symbol]
    memo[symbol] = set()
    if symbol not in NT_SET:          # terminal or ε
        memo[symbol] = {symbol}
        return memo[symbol]
    for alt in PROD_MAP.get(symbol, []):
        i = 0
        while i < len(alt):
            f = _first(alt[i], memo)
            memo[symbol] |= (f - {"ε"})
            if "ε" not in f:
                break
            i += 1
        else:
            memo[symbol].add("ε")
    return memo[symbol]


def compute_first_sets() -> Dict[str, Set[str]]:
    memo: Dict = {}
    for nt in NT_SET:
        _first(nt, memo)
    return {nt: memo[nt] for nt in NT_SET}


def print_first_sets() -> None:
    first = compute_first_sets()
    print("FIRST sets")
    print("─" * 50)
    for nt, alts in PRODUCTIONS:
        symbols = ", ".join(sorted(first.get(nt, set())))
        print(f"  FIRST({nt:<20}) = {{ {symbols} }}")
    print()


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print_cfg()
    print_first_sets()
