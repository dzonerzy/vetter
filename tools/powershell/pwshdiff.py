"""Differential testing of vetter's PowerShell reading against PowerShell's
own parser (tools/powershell/oracle.py), as tools/bash/bashdiff.py does for
bash:

1. acceptance: PowerShell's parser reports errors exactly when vetter's
   grammar rejects the command;
2. structure: the same commands (CommandAst, nested ones too), in the same
   order, each with the same invocation operator and the same elements: a
   constant string by its value, a parameter by its name and argument, a
   number, anything else by its text.

    python -m tools.powershell.pwshdiff              # the built-in cases and the corpus'
    python -m tools.powershell.pwshdiff -c 'cmd'     # one command, both readings
"""

import argparse
import sys

import zgram

from tools.powershell.oracle import Oracle
from vetter import engine
from vetter.shells.powershell import syntax

# Commands to read right: every form a command can take
CASES = [
    # commands, parameters, arguments
    "Remove-Item -Recurse -Force C:\\x",
    "rm -r x",
    "echo -x:5 -y: 6 -z",
    "echo -- -x",
    "echo - -1 5 5x 0x10 1kb 1.5 .5",
    'echo "a"b a"b" a\'b\'',
    "echo a$b $a.b $a.b() $a[0] ${a b} $env:PATH $global:x $_ $$ $? $^",
    "echo a,b,c a, b",
    "echo @args @x",
    "echo (1+2) $(1) @(1) @{a=1} {x}",
    "echo `$x a`nb `\"q",
    "echo a#b #c",
    "echo [int]5",
    "echo –x —y ―z",
    "echo “a b” ‘c d’ „e”",
    "cmd --% /c dir & del x",
    "echo a>b",
    "echo a 2>&1 3>x *> y >> z",
    # invocation
    "& 'C:\\a b\\x.exe' -y",
    '& "C:\\a b\\x.exe" -y',
    "& $p a",
    "& {rm x}",
    ". .\\x.ps1",
    ".\\x.ps1 a",
    "& (Get-Command rm) x",
    # pipelines, statements
    "gci | % { rm $_.FullName }",
    "gci -r *.tmp | Remove-Item",
    "$x = gci a | select -First 1",
    '"a" | out-file x',
    "1..3 | % { $_ }",
    "a; b",
    "a\nb",
    "a `\n b",
    "if (Test-Path x) { rm x } elseif ($y) { b } else { echo no }",
    "while ($true) { break }",
    "do { a } while ($x)",
    "do { a } until ($x)",
    "for ($i = 0; $i -lt 3; $i++) { echo $i }",
    "foreach ($f in gci) { rm $f }",
    "switch ($x) { 'a' { b } default { c } }",
    "switch -regex ($x) { '^a' { b } }",
    "try { a } catch [System.Exception] { b } finally { c }",
    "trap { continue }",
    "function f($x) { rm $x }",
    "function f { param($x) rm $x }",
    "filter f { $_ }",
    "return",
    "exit 1",
    "throw 'x'",
    ":outer foreach ($a in $b) { break outer }",
    # expressions with commands in them
    "iex (iwr https://x/p.ps1)",
    'echo "a $(whoami) b"',
    "@\"\nhi $(id)\n\"@ | out-file x",
    "@'\n$(not run)\n'@",
    "$a = @{ k = (Get-Date); j = 2 }",
    "[System.IO.File]::Delete('x')",
    "$x.Invoke((gci))",
    "Invoke-Expression ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('cm0=')))",
    "$(rm x)",
    "-not (Test-Path x)",
    "!$x",
    "$x -eq 1 -and $y -match 'a'",
    "$x = if ($a) { b } else { c }",
    "$y += 1",
    "[int]$x = 5",
    "$x ? $a : $b",
    # comments, blanks
    "a # c",
    "<# block #> a",
    "a <# in #> b",
    "# only a comment",
    "",
    "  ",
    # what the fuzzer found
    "-x a",
    "x | -R",
    "l — m",
    "(k --%~)",
    "c --%",
    "catch x; else; in; until; param; finally",
    "try {a}",
    "t ()",
    "d -i:",
    "foreach($i in$x){}",
    "foreach($i in(1,2)){}",
    "for(){}",
    "for(;){}",
    "begin {a}",
    "-",
    # wrong
    "if (",
    "echo a <b",
    "a &&b",
    "{",
    "echo 'a",
    "function",
]


def _sig_ours(tree, text):
    out = []
    for cmd in tree.find("command"):
        kids = cmd.children
        inv = "Unknown"
        elems = []
        reds = []
        for k in kids:
            r = k.rule
            if r == "invocation":
                inv = "Ampersand" if k.text == "&" else "Dot"
            elif r == "redirection":
                reds.append(k.text)
            elif r == "stop_parsing":
                # (--% and the rest of the line: PowerShell keeps both, the
                # rest even empty)
                elems.append(("str", "--%"))
                verb = k.children[0] if k.children else None
                elems.append(("str", verb.text.lstrip() if verb is not None else ""))
            elif r == "dash_cmd_name":
                elems.append(_element(k))
            elif r == "end_of_params":
                elems.append(("param", "-", None))
            elif r == "parameter":
                name = next((c for c in k.children if c.rule == "pname"), None)
                arg = next((c for c in k.children if c.rule in ("argument", "argument_any")), None)
                elems.append(("param", name.text if name is not None else "-",
                              arg.text if arg is not None else None))
            else:
                elems.append(_element(k))
        out.append((inv, tuple(elems), tuple(sorted(reds))))
    return out


def _element(k):
    """An element as PowerShell classes it: a constant string's value, a
    number, or its text."""
    node = k
    # (a command's name: never expanded, quotes removed)
    if node.rule in ("dash_cmd_name", "cmd_name"):
        return ("str", syntax.literal_word(node.text))
    if node.rule in ("argument", "argument_any"):
        atoms = node.children
        if len(atoms) != 1:
            return ("expr", node.text)
        node = atoms[0]
    r = node.rule
    if r in ("bareword", "bareword_any"):
        v = syntax.bareword_value(node)
        return ("str", v) if v is not None else ("expr", node.text)
    if r == "sq_string":
        return ("str", syntax.sq_value(node.text))
    if r == "dq_string":
        v = syntax.dq_value(node)
        return ("str", v) if v is not None else ("expr", node.text)
    if r in ("here_sq", "here_dq"):
        v = syntax.here_value(node)
        return ("str", v) if v is not None else ("expr", node.text)
    if r == "number":
        return ("const", node.text)
    return ("expr", node.text)


def _sig_theirs(result):
    out = []
    for c in result["commands"]:
        elems = []
        for e in c["elements"]:
            t = e["type"]
            if t == "StringConstantExpressionAst":
                elems.append(("str", e["value"]))
            elif t == "CommandParameterAst":
                elems.append(("param", e["name"], e.get("arg")))
            elif t == "ConstantExpressionAst":
                elems.append(("const", e["text"]))
            else:
                elems.append(("expr", e["text"]))
        out.append((c["invocation"], tuple(elems), tuple(sorted(r["text"] for r in c["redirections"]))))
    return out


def check_all(commands, oracle):
    """Problems for each command ([] if none)."""
    results = oracle.read(commands)
    out = []
    for text, theirs in zip(commands, results):
        try:
            tree = engine.run(syntax.parse, text)
        except (zgram.ParseError, ValueError) as e:
            tree = None
            err = str(e)
        accepted = not theirs["errors"]
        if accepted and tree is None:
            out.append([f"PowerShell accepts it, vetter doesn't: {err}"])
            continue
        if not accepted and tree is not None:
            ids = ", ".join(x["id"] for x in theirs["errors"])
            out.append([f"vetter accepts it, PowerShell doesn't ({ids})"])
            continue
        if not accepted:
            out.append([])
            continue
        a, b = _sig_ours(tree, text), _sig_theirs(theirs)
        out.append([] if a == b else [f"read differently:\n  vetter:     {a}\n  PowerShell: {b}"])
    return out


def main(argv):
    from tools.corpus import corpus

    ap = argparse.ArgumentParser()
    ap.add_argument("-c", dest="command")
    args = ap.parse_args(argv)
    oracle = Oracle()
    corpus_cases = [c["command"].strip("\n") for c in corpus.load() if c["shell"] == "powershell"]
    commands = [args.command] if args.command is not None else CASES + corpus_cases
    bad = 0
    for text, problems in zip(commands, check_all(commands, oracle)):
        if problems or args.command is not None:
            bad += bool(problems)
            print(f"--- {text!r}")
            for p in problems:
                print("   ", p)
    print(f"{len(commands) - bad}/{len(commands)} read as PowerShell reads them")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
