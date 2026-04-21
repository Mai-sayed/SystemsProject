"""
compiler/main.py
─────────────────
Entry point — runs all four compiler phases in sequence and
prints a formatted report to stdout.

Usage
─────
  python main.py [file.cpp]        # compile a file
  python main.py                   # compile the built-in sample

The pipeline:
  1. Lexer    → token list
  2. Parser   → AST  +  rightmost-derivation steps
  3. Semantic → symbol table, errors, warnings
  4. TAC      → raw three-address code  +  optimised TAC
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

from lexer    import Lexer,      print_tokens
from parser   import parse_tokens
from semantic import analyse_ast
from tac      import generate_tac


# ─── Sample C++ source ────────────────────────────────────────────────────────

SAMPLE_CPP = """\
#include <iostream>
#include <string>
using namespace std;

int add(int a, int b) {
    int result = a + b;
    return result;
}

float average(float x, float y) {
    float sum = x + y;
    return sum / 2;
}

int main() {
    int n;
    cout << "Enter a number: ";
    cin >> n;

    int doubled = n * 2;
    float avg = average(3.5, 4.5);
    cout << "add(3,4) = " << add(3, 4) << endl;
    return 0;
}
"""

# ─── Formatting helpers ───────────────────────────────────────────────────────

SEP  = "─" * 72
SEP2 = "═" * 72

def _header(title: str) -> None:
    print(f"\n{SEP2}")
    print(f"  {title}")
    print(SEP2)

def _section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

def _ok(msg: str)   -> None: print(f"  ✓  {msg}")
def _err(msg: str)  -> None: print(f"  ✗  {msg}")
def _warn(msg: str) -> None: print(f"  ⚠  {msg}")


# ─── Main pipeline ────────────────────────────────────────────────────────────

def compile_source(source: str, verbose: bool = True) -> dict:
    """
    Run the full compiler pipeline on *source*.

    Returns a dict with all phase outputs for programmatic use.
    When *verbose* is True, prints a formatted report.
    """

    if verbose:
        _header("CXX Educational Compiler  —  Full Pipeline")

    # ── Phase 1: Lexical Analysis ─────────────────────────────────────────────
    if verbose:
        _section("PHASE 1 — Lexical Analysis")

    lexer  = Lexer()
    tokens = lexer.tokenize(source)

    if verbose:
        print_tokens(tokens)
        if lexer.errors:
            print()
            for e in lexer.errors:
                _err(str(e))
        else:
            print(f"\n  Lexed {len(tokens)-1} tokens, {len(lexer.errors)} lex errors.")

    if lexer.errors:
        return {
            "tokens":       tokens,
            "ast":          None,
            "derivation":   [],
            "parse_errors": [],
            "lex_errors":   lexer.errors,
            "symbol_table": [],
            "errors":       [],
            "warnings":     [],
            "includes":     [],
            "raw_tac":      [],
            "opt_tac":      [],
        }

    # ── Phase 2: Syntax Analysis ──────────────────────────────────────────────
    if verbose:
        _section("PHASE 2 — Syntax Analysis  (Rightmost Derivation in Reverse)")

    parse_result = parse_tokens(tokens)
    ast    = parse_result["ast"]
    steps  = parse_result["steps"]
    p_errs = parse_result["errors"]

    if verbose:
        print(f"\n  Derivation steps ({len(steps)} reductions):")
        for i, s in enumerate(steps, 1):
            print(f"    {i:>3}.  {s['rule']}")
        print()
        if p_errs:
            for e in p_errs:
                _err(f"L{e['line']}:C{e['col']}  {e['msg']}")
            _err("Compilation stopped due to parse errors.")
        else:
            _ok("AST constructed with no parse errors.")

            _section("PHASE 2 — AST (JSON)")
            print(json.dumps(ast, indent=2))

    # Check for errors
    has_errors = len(lexer.errors) > 0 or len(p_errs) > 0

    if has_errors:
        return {
            "tokens":       tokens,
            "ast":          ast,
            "derivation":   steps,
            "parse_errors": p_errs,
            "lex_errors":   lexer.errors,
            "symbol_table": [],
            "errors":       [],
            "warnings":     [],
            "includes":     [],
            "raw_tac":      [],
            "opt_tac":      [],
        }

    # ── Phase 3: Semantic Analysis ────────────────────────────────────────────
    if verbose:
        _section("PHASE 3 — Semantic Analysis")

    sem = analyse_ast(ast)

    if verbose:
        # Includes
        if sem["includes"]:
            print("\n  Included libraries:")
            for inc in sem["includes"]:
                lib = f" → {inc['lib']}" if inc.get("lib") else ""
                print(f"    {inc['directive']}{lib}")

        # Symbol table
        print(f"\n  Symbol Table ({len(sem['symbol_table'])} entries):")
        hdr = f"    {'ID':<4} {'Name':<20} {'Type':<10} {'Scope':<15} {'Value':<20} Status"
        print(hdr)
        print("    " + "─" * (len(hdr) - 4))
        for row in sem["symbol_table"]:
            status = "✓ ok" if row["status"] == "ok" else "✗ error"
            print(f"    {row['id']:<4} {row['name']:<20} {row['data_type']:<10} "
                  f"{row['scope']:<15} {str(row['value']):<20} {status}")

        print()
        if sem["errors"]:
            print(f"  Semantic Errors ({len(sem['errors'])}):")
            for e in sem["errors"]:  _err(e["msg"])
        else:
            _ok("No semantic errors.")

        if sem["warnings"]:
            print(f"\n  Warnings ({len(sem['warnings'])}):")
            for w in sem["warnings"]: _warn(w["msg"])

    # Check for any errors before TAC
    total_errors = len(lexer.errors) + len(p_errs) + len(sem["errors"])
    has_symbol_errors = any(s["status"] == "error" for s in sem["symbol_table"])
    if total_errors > 0 or has_symbol_errors:
        return {
            "tokens":       tokens,
            "ast":          ast,
            "derivation":   steps,
            "parse_errors": p_errs,
            "lex_errors":   lexer.errors,
            **sem,
            "raw_tac":      [],
            "opt_tac":      [],
        }

    # ── Phase 4: TAC Generation + Optimisation ────────────────────────────────
    if verbose:
        _section("PHASE 4 — Three-Address Code  (Unoptimised)")

    tac = generate_tac(ast)

    if verbose:
        for ins in tac["raw"]:
            if ins["kind"] == "blank":
                print()
            elif ins["kind"] == "label":
                print(ins["text"])
            else:
                print(ins["text"])

        _section("PHASE 4 — Three-Address Code  (Optimised: Const Folding + DCE)")
        for ins in tac["optimised"]:
            if ins["kind"] == "blank":
                print()
                continue
            prefix = "[DEAD] " if ins.get("dead") else ("       ")
            if ins["kind"] == "label":
                print(ins["text"])
            else:
                print(prefix + ins["text"])

        # Summary
        _section("Compilation Summary")
        total_errors = len(lexer.errors) + len(p_errs) + len(sem["errors"])
        if total_errors == 0:
            _ok(f"Compiled successfully  —  {total_errors} errors, {len(sem['warnings'])} warnings.")
        else:
            _err(f"Compilation finished with {total_errors} error(s).")

    return {
        "tokens":       tokens,
        "ast":          ast,
        "derivation":   steps,
        "parse_errors": p_errs,
        "lex_errors":   lexer.errors,
        **sem,               # symbol_table, errors, warnings, includes
        "raw_tac":      tac["raw"],
        "opt_tac":      tac["optimised"],
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        src_path = Path(sys.argv[1])
        if not src_path.exists():
            print(f"File not found: {src_path}")
            sys.exit(1)
        source = src_path.read_text(encoding="utf-8")
    else:
        source = SAMPLE_CPP

    compile_source(source, verbose=True)
