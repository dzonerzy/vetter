"""Fuzzing vetter's PowerShell reading against PowerShell's parser
(pwshdiff.check_all on generated commands, in batches):

- soup: random sequences of PowerShell-significant fragments, mostly not
  PowerShell: vetter must reject what PowerShell rejects;
- trees: random valid commands built from PowerShell's grammar: read as
  PowerShell reads them.

Each disagreement is shrunk to a small command (whole chunks removed while
the problem stays the same kind).

    python -m tools.powershell.pwshfuzz [N] [SEED]
"""

import argparse
import random
import sys

from tools.powershell.oracle import Oracle
from tools.powershell.pwshdiff import check_all

FRAGMENTS = [
    "gci", "rm", "Remove-Item", "echo", "-r", "-Recurse", "-Force:$true", "-x:", "$x", "$env:A", "${a b}", "$_",
    '"a $b"', '"$(id)"', "'q'", "''", '""', "`n", "`", "|", ";", "&", ". ", "(", ")", "{", "}", "@(", "$(", "@{",
    "[int]", "[IO.File]::", "::", ".Name", "()", ",", "#c", "<#c#>", "--%", "--", "2>&1", ">x", ">>y", "*>z",
    "if", "else", "elseif", "foreach", "in", "while", "do", "until", "for", "switch", "try", "catch", "finally",
    "function", "param", "return", "throw", "\n", " ", " ", "–", "—", "“", "”", "‘", "’", "=", "+=", "-eq", "-not",
    "!", "5", "0x1f", "1kb", 'a"b"', '"a"b', "`\n", "@'\nx\n'@", '@"\ny $z\n"@', "a,b", "@args", "1..3", "%",
    "?", "$true", "[", "]", "-", "+", "*", "/", "<",
]


def soup(rng):
    return "".join(rng.choice(FRAGMENTS) + rng.choice(["", " "]) for _ in range(rng.randint(1, 10)))


NAMES = ["Get-ChildItem", "gci", "rm", "Remove-Item", "Copy-Item", "echo", "Write-Output", "iex", "iwr",
         "Invoke-WebRequest", "Set-Content", "git", "npm", "python", "cmd", "C:\\tools\\x.exe", ".\\run.ps1"]
PARAMS = ["-Recurse", "-Force", "-Path", "-r", "-LiteralPath", "-Uri", "-OutFile", "-Value", "-Filter", "-WhatIf"]


def word(rng, depth):
    k = rng.randrange(12 if depth > 0 else 9)
    if k == 0:
        return "'" + rng.choice(["s", "a b", "$x", "it''s", '"']) + "'"
    if k == 1:
        return '"' + rng.choice(["d", "a b", "$x", "${y}", "`$z", "`n", "$($x.Name)", "a""b"]) + '"'
    if k == 2:
        return rng.choice(["$x", "$env:TEMP", "$_", "$_.FullName", "$x[0]", "$x.Length", "${a b}", "@args"])
    if k == 3:
        return rng.choice(["5", "0x10", "1kb", "2.5", "-1"])
    if k in (4, 5, 6):
        return rng.choice(["a", "C:\\x\\y", "*.tmp", "a-b", "x.txt", "a\"b\"", "a'b'", "~", "./f", "a#b", "a=b"])
    if k == 7:
        return rng.choice(["a,b", "a, 'b'", "1,2,3"])
    if k == 8:
        return rng.choice(["@{a=1}", "@(1, 2)", "(1+2)", "[int]5"])
    if k == 9:
        return "$(" + pipeline(rng, depth - 1) + ")"
    if k == 10:
        return "(" + pipeline(rng, depth - 1) + ")"
    return "{ " + statements(rng, depth - 1) + " }"


def command(rng, depth):
    parts = []
    k = rng.randrange(10)
    if k == 0:
        parts.append("& " + rng.choice(["'C:\\a b\\x.exe'", "$p", "{ rm x }", "(gcm rm)"]))
    elif k == 1:
        parts.append(". " + rng.choice([".\\x.ps1", "$p"]))
    else:
        parts.append(rng.choice(NAMES))
    for _ in range(rng.randint(0, 4)):
        r = rng.random()
        if r < 0.3:
            p = rng.choice(PARAMS)
            if rng.random() < 0.3:
                p += ":" + word(rng, depth)
            parts.append(p)
        elif r < 0.9:
            parts.append(word(rng, depth))
        else:
            parts.append(rng.choice(["2>&1", "> out.txt", ">> log", "*> $null"]))
    if rng.random() < 0.05:
        parts.append("--% " + rng.choice(["/c dir & del x", "a b"]))
    return " ".join(parts)


def pipeline(rng, depth):
    k = rng.randrange(6)
    if k == 0:
        head = rng.choice(["$x = ", "$y += ", "[int]$z = "]) + command(rng, depth)
        return head
    if k == 1:
        head = rng.choice(['"a"', "1..3", "$x", "@(1,2)", "[IO.File]::ReadAllText('x')"])
    else:
        head = command(rng, depth)
    for _ in range(rng.randint(0, 2)):
        head += rng.choice([" | ", " |\n "]) + command(rng, depth)
    return head


def statement(rng, depth):
    if depth <= 0 or rng.random() < 0.5:
        return pipeline(rng, depth)
    k = rng.randrange(9)
    body = statements(rng, depth - 1)
    if k == 0:
        return f"if ({pipeline(rng, 0)}) {{ {body} }}" + rng.choice(["", f" else {{ {pipeline(rng, 0)} }}"])
    if k == 1:
        return f"foreach ($i in {pipeline(rng, 0)}) {{ {body} }}"
    if k == 2:
        return f"while ($true) {{ {body}; break }}"
    if k == 3:
        return f"try {{ {body} }} catch {{ {pipeline(rng, 0)} }}" + rng.choice(["", " finally { a }"])
    if k == 4:
        return f"function f($a) {{ {body} }}"
    if k == 5:
        return f"switch ($x) {{ 'a' {{ {body} }} default {{ b }} }}"
    if k == 6:
        return f"for ($i = 0; $i -lt 3; $i++) {{ {body} }}"
    if k == 7:
        return f"do {{ {body} }} while ($x)"
    return f"$r = {pipeline(rng, 0)}"


def statements(rng, depth):
    out = statement(rng, depth)
    for _ in range(rng.randint(0, 2)):
        out += rng.choice(["; ", "\n"]) + statement(rng, depth)
    if rng.random() < 0.15:
        out += " # note"
    return out


MAX_SHOWN = 15     # failures shrunk and shown per run (the rest counted)


def kind(problems):
    return problems[0].split(":")[0].split("(")[0].strip() if problems else None


def shrink(oracle, cmd, k):
    """The command made smaller while its problem stays the same kind:
    every one-chunk cut of a size checked in one batch."""
    size = len(cmd) // 2
    while size >= 1:
        while True:
            cands = [cmd[:i] + cmd[i + size:] for i in range(0, len(cmd) - size + 1, size)]
            cands = [c for c in cands if c.strip()]
            if not cands:
                break
            hit = next((c for c, p in zip(cands, check_all(cands, oracle)) if kind(p) == k), None)
            if hit is None:
                break
            cmd = hit
        size //= 2
    return cmd


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("n", type=int, nargs="?", default=500)
    ap.add_argument("seed", type=int, nargs="?", default=1)
    args = ap.parse_args(argv)
    rng = random.Random(args.seed)
    oracle = Oracle()
    cmds = [soup(rng) if i % 2 == 0 else statements(rng, 2) for i in range(args.n)]
    kinds = {}
    seen = set()
    for cmd, problems in zip(cmds, check_all(cmds, oracle)):
        if not problems:
            continue
        k = kind(problems)
        kinds[k] = kinds.get(k, 0) + 1
        if len(seen) >= MAX_SHOWN:
            continue
        small = shrink(oracle, cmd, k)
        if small in seen:
            continue
        seen.add(small)
        print(f"--- {small!r}")
        for p in check_all([small], oracle)[0]:
            print("   ", p[:400])
    bad = sum(kinds.values())
    print(f"{args.n - bad}/{args.n} agree with PowerShell (seed {args.seed})")
    for k, n in sorted(kinds.items()):
        print(f"  {n:4d}  {k}" + ("  (safe: vetter asks)" if k.startswith("PowerShell accepts") else ""))
    return 1 if bad - sum(n for k, n in kinds.items() if k.startswith("PowerShell accepts")) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
