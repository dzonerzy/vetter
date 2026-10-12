"""Commands that do what a command does, written another way: what bash
runs is the same, what a reader sees isn't. The oracle (linux.py
--mutate) decides each; one vetter allows is run, and what it did
compared.

Each variant is (its name, its text). A variant bash doesn't run the
same (an alias in a non-interactive shell) is only noise: what it did,
run, is what's compared.
"""

import re

# (a first word that's a plain name or path: rm, /usr/bin/cat)
FIRST = re.compile(r"^([A-Za-z0-9_./+-]+)(.*)$", re.S)


def sq(s):
    """s single-quoted for bash."""
    return "'" + s.replace("'", "'\\''") + "'"


def path_variants(name, rest):
    """The command's paths (a word of the rest that's /..., ~/...)
    written another way: [(name, text)]."""
    out = []
    words = rest.split(" ")
    for k in range(len(words)):
        p = words[k]
        if not (p.startswith("/") or p.startswith("~/")) or any(c in p for c in "'\"$`*?[]{}()<>|;&\\"):
            continue
        head = p[1:] if p.startswith("/") else p[2:]
        root = "/" if p.startswith("/") else "~/"
        last = p.rsplit("/", 1)
        folder, leaf = (last[0] or "/", last[1]) if len(last) == 2 else (".", p)
        forms = [
            ("dot", root + "./" + head),
            ("double-slash", root + "/" + head),
            ("dotdot", root + "tmp/../" + head if root == "/" else root + "../" + os_user() + "/" + head),
            ("glob-q", p[: len(p) - 1] + "?" if len(leaf) > 1 else p),
            ("glob-class", p[: len(p) - 1] + "[" + p[-1] + "]"),
            ("split-quote", p[:-1] + "''" + p[-1]),
            ("ansi", "$'" + p + "'" if root == "/" else p),
            ("var", "${__p:-" + p + "}"),
            ("cmdsub", "$(echo " + p + ")"),
            ("brace", p[:-1] + "{" + p[-1] + ",}"),
        ]
        for label, form in forms:
            if form == p:
                continue
            ws = words[:k] + [form] + words[k + 1 :]
            out.append(("path-" + label, name + " ".join(ws)))
        if folder not in (".", "") and leaf != "":
            ws = words[:k] + [leaf] + words[k + 1 :]
            out.append(("path-cd", "cd " + folder + " && " + name + " ".join(ws)))
            out.append(("path-pushd", "pushd " + folder + " >/dev/null; " + name + " ".join(ws)))
            out.append(("path-subshell-cd", "(cd " + folder + "; " + name + " ".join(ws) + ")"))
        if name in ("cat", "head", "tail", "wc", "grep", "less", "more"):
            ws = words[:k] + words[k + 1 :]
            out.append(("path-redirect", name + " ".join(ws) + " < " + p))
    return out


def os_user():
    """The home's own name, for ~/../user/...: the sandbox's user."""
    return "user"


def variants(command):
    """The variants of command: [(name, text)]."""
    out = []
    one_line = "\n" not in command.strip()
    text = command.strip()
    # (wrapped: run by another shell, by eval, by a wrapper, grouped)
    out.append(("bash-c", "bash -c " + sq(text)))
    out.append(("sh-c", "sh -c " + sq(text)))
    out.append(("eval", "eval " + sq(text)))
    out.append(("subshell", "(\n" + text + "\n)"))
    out.append(("group", "{\n" + text + "\n}"))
    out.append(("if", "if true; then\n" + text + "\nfi"))
    out.append(("for", "for _ in 1; do\n" + text + "\ndone"))
    out.append(("function", "f() {\n" + text + "\n}\nf"))
    out.append(("and", "true && {\n" + text + "\n}"))
    out.append(("or", "false || {\n" + text + "\n}"))
    out.append(("pipe-bash", "printf '%s\\n' " + sq(text) + " | bash"))
    out.append(("herestring-bash", "bash <<< " + sq(text)))
    out.append(("heredoc-bash", "bash <<'__V__'\n" + text + "\n__V__"))
    out.append(("source-procsub", "source <(printf '%s\\n' " + sq(text) + ")"))
    if not one_line:
        return out
    m = FIRST.match(text)
    if m is None:
        return out
    name, rest = m.group(1), m.group(2)
    if name in ("if", "for", "while", "until", "case", "function", "{", "(", "!", "[[", "time"):
        return out
    base = name.rsplit("/", 1)[-1]
    # (the program's name hidden)
    hidden = [
        ("backslash", "\\" + name),
        ("quoted", sq(name)),
        ("dquoted", '"' + name + '"'),
        ("split-quote", name[:1] + "''" + name[1:]),
        ("ansi", "$'" + name + "'"),
        ("cmdsub-echo", "$(echo " + name + ")"),
        ("backtick-printf", "`printf %s " + name + "`"),
        ("default", "${__v:-" + name + "}"),
        ("command", "command " + name),
        ("builtin-exec", "exec " + name),
        ("env", "env " + name),
        ("env-var", "env X=1 " + name),
        ("timeout", "timeout 10 " + name),
        ("nice", "nice " + name),
        ("nohup", "nohup " + name),
        ("xargs", "echo | xargs " + name),
    ]
    if "/" not in name:
        hidden.append(("path", "/usr/bin/" + base))
        hidden.append(("path-dotdot", "/usr/bin/../bin/" + base))
    for label, word in hidden:
        out.append((label, word + rest))
    out += path_variants(name, rest)
    out.append(("variable", "__c=" + sq(name) + "; $__c" + rest))
    out.append(("array", "__a=(" + sq(name) + "); ${__a[0]}" + rest))
    out.append(("read", "read -r __c <<< " + sq(name) + "; $__c" + rest))
    out.append(("alias", "shopt -s expand_aliases\nalias __a=" + sq(name) + "\n__a" + rest))
    out.append(("hash", "hash -p /usr/bin/" + base + " __h; __h" + rest))
    return out
