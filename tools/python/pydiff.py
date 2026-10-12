"""vetter's reading of Python (vetter/shells/python) against CPython's own
parser (ast), on real code: the standard library, installed packages, or
the files given. Where they differ: a file CPython reads and vetter
doesn't (or the other way), or the statements each finds (their kinds, in
order, nested ones too) not the same.

    python -m tools.python.pydiff [-v] [--limit N] [PATH...]

Files with what vetter leaves out on purpose (match, type parameters, the
type statement) are skipped.
"""

import argparse
import ast
import pathlib
import sys
import sysconfig

import zgram

from vetter.shells.python.scan import mark
from vetter.shells.python.syntax import PYTHON

# ast's statement classes, as the grammar's rules name them
KINDS = {
    "If": "if_stmt", "While": "while_stmt", "For": "for_stmt", "AsyncFor": "for_stmt", "Try": "try_stmt",
    "TryStar": "try_stmt", "With": "with_stmt", "AsyncWith": "with_stmt", "FunctionDef": "funcdef",
    "AsyncFunctionDef": "funcdef", "ClassDef": "classdef", "Pass": "pass_stmt", "Break": "break_stmt",
    "Continue": "continue_stmt", "Return": "return_stmt", "Raise": "raise_stmt", "Global": "global_stmt",
    "Nonlocal": "nonlocal_stmt", "Delete": "del_stmt", "Import": "import_stmt", "ImportFrom": "from_stmt",
    "Assert": "assert_stmt", "Assign": "assign", "AugAssign": "aug_assign", "AnnAssign": "ann_assign",
    "Expr": "expr_stmt",
}
LEFT_OUT = ("Match", "TypeAlias")
STATEMENT_RULES = set(KINDS.values())


def ast_kinds(tree):
    """Every statement's kind, in source order."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            out.append((node.lineno, node.col_offset, KINDS.get(type(node).__name__, type(node).__name__)))
    return [k for _, _, k in sorted(out)]


def tree_kinds(node, out):
    """The grammar's statements, in order (a node's own before its children's)."""
    if node.rule() in STATEMENT_RULES:
        out.append(node.rule())
    elif node.rule() == "elif_part":
        # (CPython's elif: an If in the if's else)
        out.append("if_stmt")
    for c in node.children():
        tree_kinds(c, out)
    return out


def left_out(tree):
    for node in ast.walk(tree):
        if type(node).__name__ in LEFT_OUT or getattr(node, "type_params", None):
            return True
    return False


def compare(text):
    """None: the same; else what differs."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None and left_out(tree):
        return None
    try:
        ours = PYTHON.parse(mark(text))
    except (zgram.ParseError, ValueError) as e:
        if tree is None:
            return None
        return "vetter can't read it: " + str(e)[:160]
    if tree is None:
        return "vetter reads what CPython doesn't"
    a = ast_kinds(tree)
    b = tree_kinds(ours, [])
    if a != b:
        k = 0
        while k < min(len(a), len(b)) and a[k] == b[k]:
            k += 1
        return f"statements differ at #{k}: CPython {a[k:k + 3]}, vetter {b[k:k + 3]}"
    return None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args(argv)
    roots = [pathlib.Path(p) for p in args.paths] or [pathlib.Path(sysconfig.get_paths()["stdlib"]),
                                                      pathlib.Path(sysconfig.get_paths()["purelib"])]
    files = []
    for r in roots:
        files += [r] if r.is_file() else sorted(r.rglob("*.py"))
    if args.limit:
        files = files[: args.limit]
    bad = 0
    seen = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        seen += 1
        why = compare(text)
        if why is not None:
            bad += 1
            if args.v or bad <= 40:
                print(f"{f}: {why}")
    print(f"\n{seen} files, {bad} differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
