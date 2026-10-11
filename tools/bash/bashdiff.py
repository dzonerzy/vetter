"""Differential testing of vetter's bash reading against bash itself.

For each command:
1. acceptance: `bash -n` and vetter's grammar accept (or reject) it alike;
2. structure: bash prints the command in its canonical form (`declare -f`
   of a function holding it); vetter reads both the original and bash's
   form, and their commands (words' values, redirections, operators) must
   be the same.

    python -m tools.bash.bashdiff              # the corpus and the built-in cases
    python -m tools.bash.bashdiff -c 'cmd'     # one command, its signatures shown
    python -m tools.bash.bashdiff --bash PATH  # the bash to compare with
"""

import argparse
import subprocess
import sys

import zgram

from tools.corpus import corpus
from vetter import engine
from vetter.shells.bash import scan, syntax

# Commands beyond the corpus: syntax that has to be read right
EXTRA = [
    "a; b & c && d || e | f |& g",
    "! a | b",
    "a && ! b",
    "x=1 y+=2 z[3]=4 env cmd arg",
    "arr=(a 'b c' $(d))",
    "cmd 2>&1 >out <in 3<>rw 4>>app 5>|clob &>both &>>both2 {fd}>x",
    "cmd >&2 2>&- <&0",
    "echo 'single' \"double $x ${y:-z} $(w)\" $'a\\tb\\x41' $\"loc\" \\$lit",
    "echo a\\ b c\\\nd",
    "echo $((1 + (2 * 3))) $(( $(echo 4) ))",
    'echo `date` "`whoami`"',
    "diff <(sort a) <(sort b) >(tee c)",
    "{ a; b; } > out",
    "(cd x && make) || echo fail",
    "if a; then b; elif c; then d; else e; fi",
    'while read -r l; do echo "$l"; done < file',
    "until false; do break; done",
    "for x in a b c; do echo $x; done",
    "for x; do echo $x; done",
    "for ((i = 0; i < 3; i++)); do echo $i; done",
    "select o in a b; do break; done",
    "case $1 in start|go) run;; stop) halt;& *) other;;& esac",
    "case x in (a) b ;; esac",
    "f() { echo hi; }",
    "function g { echo hi; }",
    "function h() ( echo sub )",
    "(( x = 1 + 2 ))",
    "[[ -n $x && ( $y == z* || $w =~ ^a.b$ ) ]]",
    "time sleep 1",
    "coproc cat",
    "echo a # comment\necho b",
    "echo a#b #c",
    "echo ${#x} ${x%%/*} ${x//a/b} ${!ref} ${x:0:2} $# $? $$ $! $@ $* $0 $1",
    "cat <<EOF\nline $x\nEOF",
    "cat <<'EOF'\nline $x\nEOF",
    "cat <<-EOF\n\tindented\n\tEOF",
    "cat <<A <<B\na\nA\nb\nB",
    "cat <<EOF | grep x && echo y\nbody\nEOF",
    "x=$(cat <<EOF\ninner\nEOF\n)",
    "bash <<< 'echo hi'",
    'echo "a\nb"',
    "a &&\nb ||\nc",
    "a |\nb",
    "echo }; echo {",
    "{ echo; }",
    "echo -- -n --foo=bar",
    "echo ~ ~/x ~user/y a~b",
    "echo *.py ?.txt [ab]c",
    "echo {a,b}{1..3}",
    'echo \\"quoted\\"',
    "echo $'it\\'s'",
    "true; false",
    "exit 0",
    "fori in a; casey x; selectv in b; iffy; donex; functionf; timex; coprocs",
    "forv in x; do b; done",
    "x= done; >f in; y=1 then",
    "time; ! ; time -p -- a; ! time ! b",
    "echo $[1 + 2] $() <() n[a b] x",
    "cat <<EOF\nEO\\\nF\necho after",
    "cat <<EOF\na \\\nEOF\nEOF",
    'x=`echo \\`echo in\\`` "`echo \\"q\\"`"',
    "((rm -rf x)); ( (a) )",
]


# The bash compared with (--bash): 5.2 or later, which parses what's in
# $(...) when it reads the command (5.1's `-n` doesn't look inside)
BASH = "bash"


def bash_accepts(command):
    r = subprocess.run(
        [BASH, "-n"], input=command, capture_output=True, text=True, errors="replace"
    )
    return r.returncode == 0


def bash_canonical(command):
    """bash's own printing of the command (the body of a function holding
    it), or None if bash can't define the function."""
    script = "__vetter_f() {\n" + command + "\n}\ndeclare -f __vetter_f\n"
    r = subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, errors="replace"
    )
    if r.returncode != 0:
        return None
    lines = r.stdout.splitlines()
    # (`__vetter_f () `, `{ `, the body, `}`)
    body = lines[2:-1]
    return "\n".join(body)


# bash prints these as other forms that mean the same: compared as bash's
# forms (`|&` is `2>&1 |`; a redirection's fd defaults to 1 for output, 0
# for input)
DEFAULT_FD = {
    "<<": "0",
    "<<-": "0",
    "<": "0",
    "<&": "0",
    "<>": "0",
    "<<<": "0",
    ">": "1",
    ">>": "1",
    ">|": "1",
    ">&": "1",
}

# bash's printing that doesn't read back as the original: `coproc cat` is
# printed `coproc COPROC cat`, which runs `COPROC` (the name goes only
# before a compound command), and the redirections of `coproc { ...; } |&`
# move inside
PRINTER_QUIRKS = ("coproc ",)


RESERVED = {
    "if",
    "then",
    "elif",
    "else",
    "fi",
    "do",
    "done",
    "case",
    "esac",
    "while",
    "until",
    "for",
    "select",
    "function",
    "time",
    "coproc",
    "in",
    "{",
    "}",
    "!",
    "[[",
    "]]",
}


def _reserved_after_prefix(parsed):
    """A command named by a reserved word after an assignment or a
    redirection (`>n !` runs `!`): bash prints the name first, where it's
    the reserved word (`! > n`)."""
    for node in _walk(parsed.tree):
        if node.rule() == "simple":
            kids = list(node)
            if kids[0].rule() != "cmd_name":
                if any(k.rule() == "cmd_name" and k.text() in RESERVED for k in kids):
                    return True
    return False


def signature(parsed):
    """What vetter read, without positions or layout: each simple command's
    assignments, words and redirections (values after quote removal;
    dynamic parts by their text), and the operators between commands."""
    out = []
    # (commands before a `|&`: their stderr goes to the pipe too)
    stderr_piped = set()
    for node in _walk(parsed.tree):
        rule = node.rule()
        if rule == "pipeline":
            kids = list(node)
            # (`! ! a` is `a`)
            if sum(1 for c in kids if c.rule() == "bang") % 2:
                out.append(("bang", "!"))
            for a, b in zip(kids, kids[1:]):
                if a.rule() == "command" and b.rule() == "pipe_op" and b.text() == "|&":
                    stderr_piped.add(_key(a))
        elif rule == "command":
            first = next(iter(node))
            if first.rule() == "simple":
                items = [_item(c) for c in first]
                kind = "simple"
            elif first.rule() == "compound":
                items = [_item(c) for c in node if c.rule() == "redirect"]
                kind = "redirects"
            else:
                continue
            # (bash prints the redirections last: their order among
            # themselves is what counts)
            items = [i for i in items if i[0] not in ("redirect", "heredoc")] + [
                i for i in items if i[0] in ("redirect", "heredoc")
            ]
            if _key(node) in stderr_piped:
                items.append(("redirect", ("2", ">&", ("1",))))
            if items or kind == "simple":
                out.append((kind, tuple(items)))
        elif rule == "compound":
            out.append(("compound", next(iter(node)).rule()))
        elif rule == "elif_part":
            # (printed `else if ... fi`)
            out.append(("compound", "if_clause"))
        elif rule == "function_def":
            # (a body other than { ... } is printed in one)
            body = [c for c in node if c.rule() == "compound"][0]
            if next(iter(body)).rule() != "brace_group":
                out.append(("compound", "brace_group"))
        elif rule == "pipe_op":
            out.append((rule, "|"))
        elif rule == "case_end":
            # (only ;& and ;;& change the flow: bash prints the last
            # item's optional ;;)
            if node.text() != ";;":
                out.append((rule, node.text()))
        elif rule in ("op_and", "op_or", "op_amp"):
            out.append((rule, node.text()))
    out.append(
        (
            "heredocs",
            tuple(
                _body(parsed.text[d.body_start : d.body_end], d)
                for d in parsed.heredocs
            ),
        )
    )
    return out


def _body(body, doc):
    # (as bash keeps it: tabs stripped for <<-, an expanded body's
    # `\`-newlines gone)
    if doc.strip_tabs:
        body = body.replace("\t", "")
    if not doc.expanded:
        return body
    out = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            if body[i + 1] != "\n":
                out.append(body[i : i + 2])
            i += 2
            continue
        out.append(body[i])
        i += 1
    return "".join(out)


def _key(node):
    return node.start(), len(node.text())


def _walk(node):
    yield node
    kids = list(node)
    if node.rule() == "simple":
        # (bash prints the redirections last: their commands come after)
        kids = [c for c in kids if c.rule() != "redirect"] + [
            c for c in kids if c.rule() == "redirect"
        ]
    for c in kids:
        yield from _walk(c)


def _item(node):
    rule = node.rule()
    if rule in ("cmd_name", "word"):
        return ("word", _value(node))
    if rule == "assignment":
        parts = []
        for c in node:
            if c.rule() == "word":
                parts.append(_value(c))
            elif c.rule() == "array":
                parts.append(
                    ("array",) + tuple(_value(w) for w in c if w.rule() == "word")
                )
            else:
                parts.append(c.text())
        return ("assign", tuple(parts))
    if rule == "redirect" and next(iter(node)).rule() == "heredoc":
        return _item(next(iter(node)))
    if rule == "redirect" or rule == "heredoc":
        parts = []
        for c in node:
            if c.rule() == "word":
                parts.append(_value(c))
            elif c.rule() == "fd_target":
                parts.append((c.text(),))
            else:
                parts.append(c.text())
        # (no fd: the default one, as bash prints it)
        if parts and parts[0] in DEFAULT_FD:
            parts.insert(0, DEFAULT_FD[parts[0]])
        if rule == "heredoc":
            # (any quoting in the delimiter: the body isn't expanded)
            parts.append(
                ("quoted", any(q in node.text().replace("\\\n", "") for q in "'\"\\"))
            )
        return (rule, tuple(parts))
    return (rule, node.text())


def _value(word):
    return tuple(p if isinstance(p, str) else _dynamic(p[1]) for p in word_value(word))


# (the parts of a word only running tells; a command name `n[...]` too)
DYNAMIC_PARTS = {"param", "cmdsub", "arith_sub", "arith_old", "backtick", "procsub", "subscripted"}


def word_value(node):
    """A word's value after quote removal, as pieces: strs (known text) and
    ("dynamic", node) (what only running tells)."""
    if node.rule() == "cmd_name":
        first = next(iter(node))
        if first.rule() == "word":
            node = first
    pieces = []

    def add(x):
        if isinstance(x, str) and pieces and isinstance(pieces[-1], str):
            pieces[-1] += x
        elif x != "":
            pieces.append(x)

    for part in node:
        rule = part.rule()
        if rule == "lit" or rule == "dollar":
            add(part.text())
        elif rule == "sq":
            add(part.text()[1:-1])
        elif rule == "ansi":
            add(scan.ansi_decode(part.text()[2:-1]))
        elif rule in ("dq", "locale"):
            for p in part:
                r = p.rule()
                if r == "dq_text" or r == "dq_dollar":
                    add(p.text())
                elif r == "dq_escape":
                    t = p.text()
                    # (in double quotes a backslash escapes only $ ` " \ and newline)
                    add(t[1:] if t[1] in '$`"\\\n' else t)
                else:
                    add(("dynamic", p))
        elif rule == "escape":
            add(part.text()[1:])
        elif rule in DYNAMIC_PARTS:
            add(("dynamic", part))
        else:
            add(part.text())
    return pieces


class Read:
    """A command as vetter reads it: its tree (zgram's Python nodes: the
    text with here-document bodies blanked, as vetter parses it), its
    here-documents (scan.Heredoc), its text."""

    def __init__(self, text):
        # (whether vetter reads it: its own reading, through the engine)
        engine.run(syntax.parse, text)
        self.text = text
        self.heredocs = scan.heredocs(text) if "<<" in text else []
        self.tree = syntax.BASH.parse(scan.mask(text, self.heredocs))


def _dynamic(node):
    # (the commands of $(...), <(...) and $((...)) are compared on their
    # own, and bash reprints their text: `$(($'1'))` as `$(('1'))`)
    if node.rule() in ("cmdsub", "procsub", "arith_sub", "arith_old"):
        return ("$", node.rule())
    return ("$", node.text())


def check(command):
    """Problems found with one command ([] if none)."""
    problems = []
    ours = None
    try:
        ours = Read(command)
    except (zgram.ParseError, ValueError) as e:
        ours_err = str(e)
    accepted = bash_accepts(command)
    if accepted and ours is None:
        return [f"bash accepts it, vetter doesn't: {ours_err}"]
    if not accepted and ours is not None:
        return ["vetter accepts it, bash doesn't"]
    if not accepted:
        return []
    canon = bash_canonical(command)
    # (bash's printing can be wrong: `>1 in` printed `in > 1`, which bash
    # rejects; nothing to compare with)
    if (
        canon is None
        or not bash_accepts(canon)
        or any(q in canon for q in PRINTER_QUIRKS)
    ):
        return []
    if _reserved_after_prefix(ours):
        return []
    try:
        theirs = Read(canon)
    except (zgram.ParseError, ValueError) as e:
        return [f"vetter can't read bash's canonical form: {e}\n{canon}"]
    a, b = signature(ours), signature(theirs)
    if a != b:
        problems.append(
            "read differently from bash:\n  vetter: "
            + repr(a)
            + "\n  bash:   "
            + repr(b)
            + "\n  bash's form:\n"
            + canon
        )
    return problems


def main(argv):
    global BASH
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", dest="command")
    ap.add_argument("--bash", default=BASH)
    args = ap.parse_args(argv)
    BASH = args.bash
    if args.command is not None:
        cmd = args.command
        print("bash -n:", bash_accepts(cmd))
        print("canonical:\n" + str(bash_canonical(cmd)))
        try:
            print("signature:", signature(Read(cmd)))
        except Exception as e:
            print("vetter:", e)
        print("problems:", check(cmd))
        return 0
    commands = [(c["id"], c["command"]) for c in corpus.load() if c["shell"] == "bash"]
    commands += [(f"extra-{i}", c) for i, c in enumerate(EXTRA)]
    bad = 0
    for cid, cmd in commands:
        problems = check(cmd)
        if problems:
            bad += 1
            print(f"--- {cid}: {cmd!r}")
            for p in problems:
                print("   ", p)
    print(f"{len(commands) - bad}/{len(commands)} read as bash reads them")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
