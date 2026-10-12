"""The values vetter computes in Python code, against Python's: random
expressions over strings and numbers (spaces of every kind, cases,
slashes, format strings), each given to a program as `true VALUE`; what
vetter says it is (both of zrun's modes) must be what Python makes it,
where vetter says it knows. A truth too: `if EXPR:` takes the branch
Python takes.

    python -m tools.python.valuediff [-n N] [--seed S] [-v]
"""

import argparse
import os
import pathlib
import random
import shlex
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tests"))

import shared  # noqa: E402

STRINGS = ["", " ", "a", "ab c", " a b ", "x\ty", "a\nb\n", "a\rb", "A\x0bB", "a\x1cb", "\x0c", "é", "ß", "İx",
           "a\u2028b", "\u3000a", "~", "~/x", "~u/x", "a//b/", "/", "//a", "///a", "../x", "a/./b", "x.tar.gz", ".bashrc",
           "%s", "%d", "{}", "{0}", "{x}", "{{}}", "a-b", "a b", "rm -rf ~", "'q'", "C:\\x", "-n", "a#b", "0", "00"]
INTS = [0, 1, 2, -1, 3, 10, 255, 2 ** 40]


def lit(rng):
    return repr(rng.choice(STRINGS))


def strexpr(rng, depth):
    """A random expression that's a str in Python (mostly)."""
    if depth <= 0 or rng.random() < 0.25:
        return lit(rng)
    a = strexpr(rng, depth - 1)
    b = strexpr(rng, depth - 1)
    n = rng.choice(INTS[:6])
    forms = [
        "{a} + {b}", "({a}) * {n}", "({a}).strip()", "({a}).lstrip()", "({a}).rstrip()", "({a}).strip({b})",
        "({a}).lower()", "({a}).upper()", "' '.join(({a}).split())", "'|'.join(({a}).split({b} or ','))",
        "({a}).replace({b}, 'Z')", "({a}).removeprefix({b})", "({a}).removesuffix({b})",
        "'|'.join(({a}).splitlines())", "'%s-%s' % ({a}, {b})", "'{{}}{{}}'.format({a}, {b})", "f'{{{a}}}{{{b}}}'",
        "os.path.join({a}, {b})", "os.path.dirname({a})", "os.path.basename({a})", "os.path.normpath({a} or '.')",
        "os.path.expanduser({a})", "str(pathlib.Path({a}))", "str(pathlib.Path({a}) / {b})",
        "str(pathlib.Path({a} or '.').parent)", "pathlib.Path({a} or '.').name", "pathlib.Path({a} or '.').stem",
        "pathlib.Path({a} or '.').suffix", "shlex.quote({a})", "shlex.join([{a}, {b}])", "'|'.join(shlex.split({a}))",
        "({a})[{n}]", "({a}) or {b}", "({a}) and {b}", "{a} if {b} else 'E'", "str({n} + {m})", "str({n} * {m})",
        "str({n} // ({m} or 1))", "str({n} % ({m} or 1))", "str(-{n})", "({a}).encode().decode()",
        "({a}).format({b})", "'|'.join(({a}).split({b}))" if True else "",
    ]
    return rng.choice(forms).format(a=a, b=b, n=n, m=rng.choice(INTS))


def python_value(expr, home):
    code = "import os, pathlib, shlex\nprint(repr(" + expr + "))"
    try:
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=10,
                             env={"HOME": home, "PATH": "/usr/bin:/bin"})
    except subprocess.TimeoutExpired:
        return None, False
    if out.returncode != 0:
        return None, False
    v = eval(out.stdout.strip())  # noqa: S307 (repr of a str, from Python itself)
    return v, True


def vetter_value(p, expr, mode, cwd, home):
    """What vetter says `true VALUE` is given: (str, True), (None, True)
    not known, (None, False) no such command found."""
    code = "import os, pathlib, shlex, subprocess\nsubprocess.run(['true', " + expr + "])"
    command = "python3 -I -c " + shlex.quote(code)
    r = p.call("resolve", command, cwd, home, mode=mode)
    if r == "no":
        return None, False
    for e in r[0]:
        argv = e[0]
        if len(argv) == 2 and argv[0][0] == ["true"]:
            parts = argv[1][0]
            if all(isinstance(x, str) for x in parts):
                return "".join(parts), True
            return None, True
    return None, False


def vetter_branch(p, expr, mode, cwd, home):
    code = "import os, pathlib, shlex, subprocess\nif " + expr + ":\n    subprocess.run(['true', 'T'])\nelse:\n" \
           "    subprocess.run(['true', 'F'])"
    r = p.call("resolve", "python3 -I -c " + shlex.quote(code), cwd, home, mode=mode)
    if r == "no":
        return set()
    out = set()
    for e in r[0]:
        argv = e[0]
        if len(argv) == 2 and argv[0][0] == ["true"]:
            out.add("".join(x for x in argv[1][0] if isinstance(x, str)))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args(argv)
    rng = random.Random(args.seed)
    p = shared.program()
    cwd, home = "/home/user/project", "/home/user"
    bad = 0
    known = 0
    for i in range(args.n):
        expr = strexpr(rng, rng.choice([1, 2, 2, 3]))
        want, ok = python_value(expr, home)
        if not ok or not isinstance(want, str):
            continue
        for mode in ("python", "compiled"):
            got, found = vetter_value(p, expr, mode, cwd, home)
            if got is not None:
                known += 1
            if got is not None and got != want:
                bad += 1
                print(f"VALUE {mode}: {expr}\n      python {want!r}, vetter {got!r}")
            branches = vetter_branch(p, expr, mode, cwd, home)
            taken = "T" if want else "F"
            if branches and taken not in branches:
                bad += 1
                print(f"TRUTH {mode}: if {expr}: python {taken}, vetter {sorted(branches)}")
        if args.v:
            print(f"ok {expr}")
    print(f"\n{args.n} expressions, {known} values vetter knew, {bad} wrong")
    return 1 if bad else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    sys.exit(main(sys.argv[1:]))
