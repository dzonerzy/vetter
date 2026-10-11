"""Fuzzing vetter's bash reading against bash (bashdiff.check on generated
commands):

- soup: random sequences of bash-significant fragments, mostly not bash:
  vetter must reject what bash rejects, accept what it accepts;
- trees: random valid commands built from bash's grammar (lists,
  pipelines, compound commands, every kind of word): read as bash reads
  them.

    python -m tools.bash.bashfuzz [N] [SEED] [--bash PATH]
"""

import argparse
import random
import sys

from tools.bash import bashdiff

FRAGMENTS = [
    "a", "b", "echo", "x=1", "y+=2", "'q r'", '"d $x"', "$'\\x41\\''", "$(b)", "`c`",
    "${x:-$(d)}", "$((1+2))", "$x", "$", ";", "&", "&&", "||", "|", "|&", "\n", " ",
    "#c", "!", "{", "}", "(", ")", "if", "then", "elif", "else", "fi", "do", "done",
    "for", "in", "case", "esac", ";;", ";&", "<", ">", "2>&1", ">>", ">|", "&>", "<<<",
    "<<E\nbody\nE\n", "\\", "\\\n", "*", "~", "=", "[[", "]]", "-f", "<(x)", ">(y)",
    "time", "while", "until", "function", "f()", "((", "))", "'", '"', "`", "\t", "a#b",
    "{a,b}", "\\;", "\\|", "==", "=~", "-n", "-eq", "@(", "|", "$[", "]", "`", "<(", "2>", "{fd}>",
]


def soup(rng):
    n = rng.randint(1, 10)
    return "".join(rng.choice(FRAGMENTS) + rng.choice(["", " "]) for _ in range(n))


WORDS = ["a", "b1", "-n", "--x=y", "~/p", "*.py", "{a,b}", "a#b", "x\\ y", "\\$z"]


def word(rng, depth):
    parts = []
    for _ in range(rng.randint(1, 3)):
        k = rng.randrange(10 if depth > 0 else 7)
        if k == 0:
            parts.append("'" + rng.choice(["s", "a b", "$x", "\"", ";|&"]) + "'")
        elif k == 1:
            parts.append('"' + rng.choice(["d", "a b", "$x", "${y}", "\\$", "\\\"", "'"]) + '"')
        elif k == 2:
            parts.append("$'" + rng.choice(["\\x72", "\\n", "\\'", "a\\tb", "\\101"]) + "'")
        elif k == 3:
            parts.append(rng.choice(["$x", "${x}", "${x:-d}", "${#x}", "${x%%/*}", "$1", "$@", "$?"]))
        elif k == 4:
            parts.append("$((" + rng.choice(["1+2", "x*3", "(1+2)*3"]) + "))")
        elif k in (5, 6):
            parts.append(rng.choice(WORDS))
        elif k == 7:
            parts.append("$(" + command_list(rng, depth - 1) + ")")
        elif k == 8:
            parts.append('"$(' + command_list(rng, depth - 1) + ')"')
        else:
            parts.append("`" + rng.choice(["b", "c d", "e | f"]) + "`")
    w = "".join(parts)
    # (a word starting with # would be a comment)
    return w if not w.startswith("#") else "x" + w


def simple(rng, depth):
    items = []
    for _ in range(rng.randint(0, 2)):
        items.append(rng.choice(["X=1", "Y=" + word(rng, depth), "Z+=a"]))
    items.append(rng.choice(["echo", "ls", "git", "cat", "rm", "env", "printf"]))
    for _ in range(rng.randint(0, 3)):
        items.append(word(rng, depth))
    if rng.random() < 0.3:
        items.append(rng.choice([">out", "2>&1", "<in", ">>log", "&>/dev/null", "2>err", "<<<" + word(rng, 0),
                                 "{fd}>x", "3<>rw", ">&2", "2>&-", "&>>all", ">|f", "<(" + simple(rng, 0) + ")"]))
    if rng.random() < 0.1:
        items.insert(0, "arr=(" + word(rng, 0) + " " + word(rng, 0) + ")")
    return " ".join(items)


def command(rng, depth):
    if depth <= 0 or rng.random() < 0.5:
        return simple(rng, depth)
    k = rng.randrange(14)
    body = command_list(rng, depth - 1)
    if k == 8:
        return "for ((i = 0; i < 3; i++)); do " + body + "; done"
    if k == 9:
        return "select v in " + word(rng, 0) + "; do " + body + "; done"
    if k == 10:
        return "function g { " + body + "; }"
    if k == 11:
        return "case " + word(rng, 0) + " in (a) " + body + rng.choice([" ;& ", " ;;& ", ";;\n"]) + "*) b;; esac"
    if k == 12:
        return "coproc C { " + body + "; }"
    if k == 13:
        return "until " + body + "; do " + simple(rng, 0) + "; done" + rng.choice(["", " >out", " 2>&1 <in"])
    if k == 0:
        return "{ " + body + "; }"
    if k == 1:
        return "(" + body + ")"
    if k == 2:
        return "if " + body + "; then " + command_list(rng, depth - 1) + "; fi"
    if k == 3:
        return "while " + body + "; do " + command_list(rng, depth - 1) + "; done"
    if k == 4:
        return "for v in " + word(rng, 0) + " " + word(rng, 0) + "; do " + body + "; done"
    if k == 5:
        return "case " + word(rng, 0) + " in a|b) " + body + ";; *) " + simple(rng, 0) + ";; esac"
    if k == 6:
        return "f() { " + body + "; }"
    return "[[ " + cond(rng, 2) + " ]]"


def cond(rng, depth):
    k = rng.randrange(8 if depth > 0 else 5)
    if k == 0:
        return rng.choice(["-n", "-z", "-f", "-d", "-v"]) + " " + word(rng, 0)
    if k == 1:
        return word(rng, 0) + " " + rng.choice(["==", "!=", "=", "<", ">"]) + " " + \
            rng.choice(["z*", "@(a|b)", "!(x)", "+(y)z", '"q"', word(rng, 0)])
    if k == 2:
        return word(rng, 0) + " =~ " + rng.choice(["^a.b$", "(x|y z)", "x|y", "a\\ b", "$re", "'lit'"])
    if k == 3:
        return word(rng, 0) + " " + rng.choice(["-eq", "-lt", "-nt", "-ef"]) + " " + word(rng, 0)
    if k == 4:
        return word(rng, 0)
    if k == 5:
        return "! " + cond(rng, depth - 1)
    if k == 6:
        return "( " + cond(rng, depth - 1) + " )"
    return cond(rng, depth - 1) + rng.choice([" && ", " || ", " &&\n"]) + cond(rng, depth - 1)


def pipeline(rng, depth):
    cmds = [command(rng, depth) for _ in range(rng.randint(1, 3))]
    p = rng.choice([" | ", " |& "]).join(cmds)
    return ("! " if rng.random() < 0.1 else "") + p


def command_list(rng, depth):
    out = pipeline(rng, depth)
    for _ in range(rng.randint(0, 2)):
        out += rng.choice([" && ", " || ", "; ", " & ", "\n"]) + pipeline(rng, depth)
    if rng.random() < 0.2:
        out += " # note"
    return out


def heredoc(rng):
    """A command with here-documents, and what follows their bodies."""
    docs = []
    line = []
    for _ in range(rng.randint(1, 2)):
        delim = rng.choice(["E", "EOF", "x_1"])
        quoted = rng.choice(["{}", "'{}'", '"{}"', "\\{}", "{}''"]).format(delim)
        dash = rng.random() < 0.3
        line.append(simple(rng, 0) + " <<" + ("-" if dash else "") + quoted)
        body = [rng.choice(["text", "$x and $(cmd)", "\tindented", "a \\", "'q' \"d\"", delim + "x", " " + delim,
                            delim[:1] + "\\\n" + delim[1:], "`b`", "a \\\\"])
                for _ in range(rng.randint(0, 3))]
        docs.append("\n".join(body + [("\t" if dash and rng.random() < 0.5 else "") + delim]))
    head = rng.choice([" | ", " && ", "; "]).join(line)
    if rng.random() < 0.3:
        head = "x=$(" + head + "\n" + "\n".join(docs) + "\n)"
        return head + rng.choice(["", "\n" + command_list(rng, 1)])
    return head + "\n" + "\n".join(docs) + rng.choice(["", "\n" + command_list(rng, 1)])


STRICTER = "bash accepts it, vetter doesn't"


def kind(problems):
    return problems[0].split(":")[0] if problems else None


def shrink(cmd, k):
    """The command made as short as it goes while its problem stays the
    same kind (whole chunks removed, halving their size)."""
    size = len(cmd) // 2
    while size >= 1:
        i = 0
        while i < len(cmd):
            shorter = cmd[:i] + cmd[i + size:]
            if shorter.strip() and kind(bashdiff.check(shorter)) == k:
                cmd = shorter
            else:
                i += size
        size //= 2
    return cmd


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("n", type=int, nargs="?", default=500)
    ap.add_argument("seed", type=int, nargs="?", default=1)
    ap.add_argument("--bash", default=bashdiff.BASH)
    args = ap.parse_args(argv)
    bashdiff.BASH = args.bash
    n, seed = args.n, args.seed
    rng = random.Random(seed)
    kinds = {}
    seen = set()
    for i in range(n):
        cmd = (soup, lambda r: command_list(r, 2), heredoc)[i % 3](rng)
        problems = bashdiff.check(cmd)
        if problems:
            kinds[kind(problems)] = kinds.get(kind(problems), 0) + 1
            small = shrink(cmd, kind(problems))
            if small in seen:
                continue
            seen.add(small)
            print(f"--- {small!r}")
            for p in bashdiff.check(small):
                print("   ", p.splitlines()[0][:300])
    bad = sum(kinds.values())
    print(f"{n - bad}/{n} agree with bash (seed {seed})")
    # (vetter stricter than bash: it asks; the others could let a command
    # through as something it isn't)
    for k, count in sorted(kinds.items()):
        print(f"  {count:4d}  {k}" + ("  (safe: vetter asks)" if k == STRICTER else ""))
    return 1 if bad - kinds.get(STRICTER, 0) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
