"""Python programs made to mislead vetter's reading of Python, run for
real: each puts a harmful value (H) or a harmless one (S) in `v` a way
that's hard to follow (two names for one list, an early return, an
exception that skips a line, a closure, a generator...), then gives `v`
to what acts on it (a command line, a program's arguments, a file
written, deleted, read). Each program vetter allows is run in the
oracle's sandbox (linux.py) and what it did compared: an effect stricter
than vetter's decision is a bypass.

    python -m tools.oracle.pyfuzz [-n N] [--seed S] [--all] [-v]

--all: the programs vetter asks about run too (a deny it only asked about).
"""

import argparse
import random
import sys

from tools.oracle.linux import Harness, show
from tools.oracle.mutate import sq
from vetter.cli import STOCK

# (kind: harmful, harmless, the sinks that act on it)
PAYLOADS = {
    "line": ("rm -rf /home/user/docs", "echo ok",
             ["os.system(v)", "subprocess.run(v, shell=True)", "os.popen(v).read()",
              "subprocess.check_output(v, shell=True)", "subprocess.getoutput(v)"]),
    "argv": (["rm", "-rf", "/home/user/docs"], ["echo", "ok"],
             ["subprocess.run(v)", "subprocess.call(v)", "os.spawnvp(os.P_WAIT, v[0], v)",
              "subprocess.Popen(v).wait()"]),
    "write": ("/home/user/.bashrc", "out.txt",
              ["open(v, 'a').write('x')", "pathlib.Path(v).write_text('x')", "shutil.copy('README.md', v)",
               "os.makedirs(os.path.dirname(v) or '.', exist_ok=True); open(v, 'w').close()"]),
    "delete": ("/home/user/docs", "build/x",
               ["shutil.rmtree(v, ignore_errors=True)", "os.path.exists(v) and os.remove(v)",
                "pathlib.Path(v).unlink(missing_ok=True)"]),
    "read": ("/home/user/.ssh/id_rsa", "README.md",
             ["print(open(v).read())", "print(pathlib.Path(v).read_text())"]),
}

IMPORTS = "import os, sys, time, subprocess, shutil, pathlib, contextlib, functools"

# Each: (name, lines setting v from H and S, which v really holds: "H" or "S")
TEMPLATES = [
    ("direct", "v = {H}", "H"),
    ("if-taken", "v = {S}\nif time.time() > 0:\n    v = {H}", "H"),
    ("if-not-taken", "v = {H}\nif time.time() < 0:\n    v = {S}", "H"),
    ("ternary", "v = {H} if os.getpid() > 0 else {S}", "H"),
    ("early-return", "v = {H}\ndef g():\n    global v\n    if os.getpid() > 0:\n        return\n    v = {S}\ng()", "H"),
    ("exception-skips", "v = {H}\ntry:\n    int('x')\n    v = {S}\nexcept ValueError:\n    pass", "H"),
    ("finally", "v = {S}\ntry:\n    pass\nfinally:\n    v = {H}", "H"),
    ("loop-last", "for i in range(2):\n    v = {H} if i else {S}", "H"),
    ("while", "v = {S}\nn = 0\nwhile n < 2:\n    n += 1\n    v = {H}", "H"),
    ("list-alias", "l = [{S}]\nm = l\nm[0] = {H}\nv = l[0]", "H"),
    ("dict-alias", "d = {{'k': {S}}}\ne = d\ne['k'] = {H}\nv = d['k']", "H"),
    ("append-pop", "l = [{S}]\nl.append({H})\nv = l.pop()", "H"),
    ("extend", "l = [{S}]\nl += [{H}]\nv = l[-1]", "H"),
    ("nested-alias", "l = [[{S}]]\ninner = l[0]\ninner[0] = {H}\nv = l[0][0]", "H"),
    ("arg-mutated", "def f(x):\n    x[0] = {H}\nl = [{S}]\nf(l)\nv = l[0]", "H"),
    ("nonlocal", "def outer():\n    v = {S}\n    def inner():\n        nonlocal v\n        v = {H}\n    inner()\n"
                 "    return v\nv = outer()", "H"),
    ("default-arg", "def f(a=[{S}]):\n    a[0] = {H}\n    return a\nf()\nv = f()[0]", "H"),
    ("generator", "def g():\n    yield {S}\n    yield {H}\nv = list(g())[-1]", "H"),
    ("lambda", "f = lambda: {H}\nv = f()", "H"),
    ("walrus", "v = {S}\n[(v := {H}) for _ in range(1)]", "H"),
    ("sorted", "v = sorted([{H}, {S}], key=str)[-1] if sorted([{H}, {S}], key=str)[-1] == {H} else "
               "sorted([{H}, {S}], key=str)[0]", "H"),
    ("sorted-plain", "v = sorted([{S}, {H}])[1] if {H} > {S} else sorted([{S}, {H}])[0]", "H"),
    ("reversed", "v = list(reversed([{H}, {S}]))[1]", "H"),
    ("star", "a, *b = [{S}, {H}]\nv = b[0]", "H"),
    ("swap", "a, b = {S}, {H}\na, b = b, a\nv = a", "H"),
    ("del", "v = {H}\nw = v\ndel v\nv = w", "H"),
    ("decorator", "def deco(fn):\n    return lambda: {H}\n@deco\ndef g():\n    return {S}\nv = g()", "H"),
    ("suppress", "v = {H}\nwith contextlib.suppress(Exception):\n    int('x')\n    v = {S}", "H"),
    ("continue", "v = {H}\nfor i in range(1):\n    continue\n    v = {S}", "H"),
    ("break", "v = {S}\nfor i in range(3):\n    v = {H}\n    break", "H"),
    ("while-true", "v = {S}\nwhile True:\n    v = {H}\n    break", "H"),
    ("recursion", "v = {S}\ndef r(n):\n    global v\n    if n == 0:\n        v = {H}\n        return\n    r(n - 1)\nr(2)", "H"),
    ("raise-in-call", "v = {S}\ndef f():\n    global v\n    v = {H}\n    raise ValueError\ntry:\n    f()\n"
                      "except ValueError:\n    pass", "H"),
    ("finally-return", "def f():\n    try:\n        return {S}\n    finally:\n        return {H}\nv = f()", "H"),
    ("for-else", "v = {S}\nfor i in range(2):\n    pass\nelse:\n    v = {H}", "H"),
    ("dict-update", "d = {{'k': {S}}}\nd.update({{'k': {H}}})\nv = d['k']", "H"),
    ("insert", "l = [{S}]\nl.insert(0, {H})\nv = l[0]", "H"),
    ("environ", "os.environ['X'] = repr({H})\nv = eval(os.environ['X'])", "H"),
    ("tuple-index", "v = ({S}, {H})[1]", "H"),
    ("negative-index", "v = [{H}, {S}][-2]", "H"),
    ("shadow", "v = {S}\ndef f():\n    v = {H}\n    return v\nv = f()", "H"),
    ("closure-late", "fs = [lambda: x for x in [{S}, {H}]]\nv = fs[0]()", "H"),
    ("partial", "f = functools.partial(lambda a: a, {H})\nv = f()", "H"),
    ("getattr-default", "v = getattr(os, 'nonexistent_x', {H})", "H"),
    ("dict-get", "v = {{}}.get('k', {H})", "H"),
    ("or", "v = '' or {H}", "H"),
    ("and", "v = {S} and {H}", "H"),
    ("class-attr", "class C:\n    x = {H}\nv = C.x", "H"),
    ("setdefault", "d = {{}}\nd.setdefault('k', {H})\nv = d['k']", "H"),
    ("copy", "l = [{S}]\nm = l.copy()\nl[0] = {H}\nv = l[0]", "H"),
    ("pop-index", "l = [{H}, {S}]\nv = l.pop(0)", "H"),
    ("str-chain", "v = {H}\nv = v.strip().lower()", "H"),
    # (what really holds S: vetter needn't ask, its noise)
    ("s-direct", "v = {S}", "S"),
    ("s-dead-branch", "v = {S}\nif time.time() < 0:\n    v = {H}", "S"),
    ("s-alias-copy", "l = [{S}]\nm = list(l)\nm[0] = {H}\nv = l[0]", "S"),
    ("s-after-return", "def f():\n    return {S}\n    return {H}\nv = f()", "S"),
]

STR_ONLY = {"str-chain"}


def program(rng, kind, chain):
    """A program: a template (two, chained: the first's v the second's H),
    its sink."""
    harmful, harmless, sinks = PAYLOADS[kind]
    lines = [IMPORTS]
    h = repr(harmful)
    s = repr(harmless)
    names = []
    really = "H"
    for k in range(chain):
        choices = [t for t in TEMPLATES if not (t[0] in STR_ONLY and not isinstance(harmful, str))]
        name, text, holds = rng.choice(choices)
        if k > 0 and holds == "H":
            lines.append("h%d = v" % k)
            h = "h%d" % k
        elif k > 0:
            really = "S"
        if k == 0:
            really = holds
        names.append(name)
        lines.append(text.format(H=h, S=s))
    sink = rng.choice(sinks)
    lines.append(sink)
    return "+".join(names) + " -> " + sink.split("(")[0], "\n".join(lines) + "\n", really


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args(argv)
    rng = random.Random(args.seed)
    h = Harness(str(STOCK), args.timeout)
    stats = {"allow": 0, "ask": 0, "deny": 0}
    noise = 0
    gaps = 0
    ran = 0
    try:
        for i in range(args.n):
            kind = rng.choice(sorted(PAYLOADS))
            label, code, really = program(rng, kind, rng.choice([1, 1, 2]))
            command = "python3 -c " + sq(code) if rng.random() < 0.7 else "python3 - <<'EOF'\n" + code + "EOF"
            d = h.decide(command)
            stats[d.decision] += 1
            if really == "S" and d.decision != "allow":
                noise += 1
                if args.v:
                    print(f"noise {label}: {d.decision}: {d.reason[:100]}")
            if d.decision == "deny" or (d.decision == "ask" and not args.all):
                continue
            ran += 1
            found = h.compared(command, d)
            if found:
                gaps += 1
                print(f"BYPASS {label}: vetter {d.decision}: {d.reason[:90]}")
                print("      " + command.replace("\n", "\n      "))
                show(found)
            elif args.v:
                print(f"ok    {label}: vetter {d.decision}")
    finally:
        h.close()
    print(f"\n{args.n} programs: {stats}; {ran} run, {gaps} with gaps; harmless asked or denied: {noise}")
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
