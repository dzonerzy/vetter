"""PowerShell's syntax, read as PowerShell reads it (Windows PowerShell
5.1): its grammar (grammar.py's) parsed with rt.parse, and the words'
values (quotes, escapes, here-strings). Nodes are zrun's.

Names compare as .NET's OrdinalIgnoreCase compares them, and Windows' file
names: by each character's uppercase (paths.case_key); outside ASCII two
letters uppercase into it, ſ to S and ı to I: `Remove-ıtem` is
Remove-Item. The Kelvin sign's uppercase is itself: not K."""

import zgram

from ...paths import case_key as fold_upper  # noqa: F401  (resolve.py's)
from ...paths import fold  # noqa: F401
from ...specs import strip
from ..bash.syntax import nodes_of
from .grammar import GRAMMAR

PS = zgram.compile(GRAMMAR)

# (PowerShell 5.1's escapes: `e is PowerShell 6's, in 5.1 it's an e)
BACKTICK = {"0": "\0", "a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
SQ = "'‘’‚‛"
DQ = '"“”„'


def parse(rt, text):
    """The command's tree (zgram.ParseError when it isn't PowerShell,
    ValueError("unreadable: ...") for what PowerShell rejects after reading
    it)."""
    tree = rt.parse(PS, text)
    for cmd in nodes_of(tree, "command", []):
        streams = []
        for r in cmd.children:
            if r.rule == "redirection":
                t = strip(r.text)
                s = t[0] if t[0] in "*123456" else "1"
                if s in streams:
                    raise ValueError("unreadable: a stream redirected twice")
                streams.append(s)
    return tree


def unquote(text):
    """text[1:-1]"""
    return text[1 : len(text) - 1]


def sq_value(text):
    body = unquote(text)
    out = ""
    i = 0
    while i < len(body):
        if body[i] in SQ and i + 1 < len(body) and body[i + 1] in SQ:
            out += body[i]
            i += 2
        else:
            out += body[i]
            i += 1
    return out


def escaped(c):
    return BACKTICK[c] if c in BACKTICK else c


def bareword_value(node):
    """A bareword's value if it's constant (no $ expansions), else None."""
    out = ""
    for p in node.children:
        r = p.rule
        if r == "bw_text":
            out += p.text
        elif r == "bw_escape":
            out += escaped(p.text[1:])
        elif r == "bw_sq":
            out += sq_value(p.text)
        elif r == "bw_dq":
            v = dq_value(p.children[0])
            if v is None:
                return None
            out += v
        else:
            return None
    return out


def literal_word(text):
    """A command's name as PowerShell takes it: quotes and escapes removed,
    nothing expanded ($x stays $x)."""
    out = ""
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "`" and i + 1 < n:
            out += escaped(text[i + 1])
            i += 2
        elif c in SQ:
            j = i + 1
            while j < n:
                if text[j] in SQ:
                    if j + 1 < n and text[j + 1] in SQ:
                        out += text[j]
                        j += 2
                        continue
                    break
                out += text[j]
                j += 1
            i = j + 1
        elif c in DQ:
            j = i + 1
            while j < n and text[j] not in DQ:
                if text[j] == "`" and j + 1 < n:
                    out += escaped(text[j + 1])
                    j += 2
                    continue
                out += text[j]
                j += 1
            i = j + 1
        else:
            out += c
            i += 1
    return out


def here_value(node):
    """A here-string's body if it's constant (an @' or an @" without
    expansions), else None."""
    body = None
    for k in node.children:
        if k.rule == "here_sq_body" or k.rule == "here_dq_body":
            body = k
            break
    if body is None:
        return ""
    if node.rule == "here_dq":
        for k in body.children:
            if k.rule == "variable" or k.rule == "subexpr":
                return None
    return body.text


def dq_value(node):
    """A double-quoted string's value if it's constant, else None."""
    for k in node.children:
        if k.rule == "variable" or k.rule == "subexpr":
            return None
    return dq_plain(unquote(node.text))


def dq_plain(body):
    out = ""
    i = 0
    while i < len(body):
        c = body[i]
        if c == "`" and i + 1 < len(body):
            out += escaped(body[i + 1])
            i += 2
            continue
        if c in DQ and i + 1 < len(body) and body[i + 1] in DQ:
            out += c
            i += 2
            continue
        out += c
        i += 1
    return out
