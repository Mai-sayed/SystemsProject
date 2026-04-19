# CXX Educational Compiler

A full compiler pipeline for a C++ subset, built as a university compiler-design project.

---

## Project Structure

```
compiler/
├── index.html      ← Dashboard (open in any browser, no server needed)
├── main.py         ← Pipeline entry point — runs all 4 phases
├── lexer.py        ← Phase 1: Lexical Analyser
├── parser.py       ← Phase 2: Syntax Analyser (Rightmost Derivation in Reverse)
├── semantic.py     ← Phase 3: Semantic Analyser + Symbol Table
├── tac.py          ← Phase 4: TAC Generator + Optimiser
├── cfg.py          ← Context-Free Grammar (reference, not used at runtime)
└── README.md       ← This file
```

---

## Team Assignment

| Phase | File | Responsibility |
|-------|------|----------------|
| CFG + Lexer | `cfg.py` + `lexer.py` | Member 1 |
| Parser + Semantic | `parser.py` + `semantic.py` | Member 2 |
| TAC + Optimisation | `tac.py` | Member 3 |

---

## Phase Details

### Phase 1 — Lexical Analysis (`lexer.py`)
- Tokenises C++ source line by line
- Recognises: keywords, types, identifiers, numbers, strings, chars, operators, punctuation, `#include` directives, comments
- Handles `cout <<` and `cin >>` operators (`<<`, `>>`)
- Returns a list of `Token(kind, value, line, col)` objects
- Errors collected in `lexer.errors` — lexing continues on error

### Phase 2 — Syntax Analysis (`parser.py`)
- Recursive-descent parser simulating **rightmost derivation in reverse** (LR-style)
- Each `_reduce(rule)` call records a derivation step
- Produces an AST as a nested JSON-serialisable dict
- Supported constructs:
  - Functions with typed parameters
  - Variable declarations with optional initialiser
  - `if / else`, `while`, `for`
  - `cout << …`, `cin >> …`
  - `return`
  - Full expression hierarchy (assignment, comparison, arithmetic, unary, function calls)

### Phase 3 — Semantic Analysis (`semantic.py`)
- Scope-stack (global + per-function + nested blocks)
- **Checks**: undeclared variables, redeclarations in same scope, type compatibility
- **Generates**: Symbol Table with ID, name, type, scope, initial value, status
- Implicit widening rules: `int→float→double`, `char→string`
- Warnings (not errors) for safe widening assignments

### Phase 4 — TAC Generation + Optimisation (`tac.py`)
- Emits classic Three-Address Code: `t1 = a op b`, `param x`, `t2 = call f, n`, `ifFalse t goto L`, `goto L`
- **Optimisation pass 1**: Constant Folding — `t1 = 2 + 3` becomes `t1 = 5`
- **Optimisation pass 2**: Dead Code Elimination — temporaries never read after assignment are marked dead

### CFG (`cfg.py`)
- Formal grammar definition (not used at runtime)
- Machine-readable production rules
- FIRST-set calculator included
- Run standalone: `python cfg.py` prints the full grammar + FIRST sets

---

## Running the Backend

```bash
# Requires Python 3.9+, no external dependencies

# Run on the built-in sample
python main.py

# Run on your own file
python main.py your_file.cpp

# Run individual phases
python lexer.py
python parser.py
python semantic.py
python tac.py
python cfg.py
```

---

## Running the Dashboard

Just open `index.html` in a browser — no server, no build step, no `npm`.

The dashboard is a self-contained React app (loaded from CDN) that:
- Has a code editor with line numbers and tab support
- Shows all compiler phases as icons at the top (click to jump to that tab)
- Shows: token table, interactive AST tree, derivation steps, symbol table, TAC (raw + optimised), errors
- Has a **View CFG** button that opens the grammar in a modal

---

## Supported C++ Subset

```cpp
#include <iostream>        // recognised, lib name extracted
#include <string>
using namespace std;       // skipped gracefully

int add(int a, int b) { … }     // function definitions
float average(float x, float y) { … }

int main() {
    int x = 5;                   // variable declarations
    float f = 3.14;
    cout << "hello" << endl;     // output
    cin >> x;                    // input
    if (x > 0) { … } else { … } // if/else
    while (x > 0) { … }         // while
    for (int i=0; i<n; i++) { … } // for
    return 0;
}
```

---

## Limitations (future work)
- No multi-line comments (`/* … */`) yet — add to `lexer.py`
- No array or pointer types
- No class/struct bodies (parsed but not semantically checked)
- TAC assumes single-file programs (no linking)
