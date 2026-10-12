"""PowerShell values vetter can compute while reading a command: what a
command name built from pieces is (`$v + '-Item'`, `-join ('Inv','oke-
Expression')`, `[char[]](105,101,120)`, `'R3move-Item' -replace '3','e'`,
`@("$env:TEMP\\p.exe")[0]`, `[scriptblock]::Create('...')`, `Get-Command
I*e-E*n`), as PowerShell computes it. A value is a str, an int, a list, a
Command (Get-Command's) or a Block (a script block's text); None: only
running tells.

    v = value(rt, pw, node)
"""

from dataclasses import dataclass

from ...glob import match
from .cmdlets import ALIASES, CMDLETS
from .syntax import dq_value, fold, here_value, sq_value

# (values made, at most: a range, a repeat)
MAX_ITEMS = 256
MAX_DEPTH = 32

# (how tightly each operator binds: higher first)
PRECEDENCE = {",": 5, "..": 6, "*": 4, "/": 4, "%": 4, "+": 3, "-": 3}


@dataclass
class Command:
    """Get-Command's result: the command it names."""

    name: str


@dataclass
class Block:
    """A script block: its code."""

    text: str


@dataclass
class TypeName:
    """[T] before :: (a static call's type)."""

    name: str


def text_of(v):
    """A value as a string, as PowerShell makes one (an array: its items
    joined with blanks)."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        parts = []
        for x in v:
            t = text_of(x)
            if t is None:
                return None
            parts.append(t)
        return " ".join(parts)
    if isinstance(v, Command):
        return v.name
    return None


def value(rt, pw, n):
    return node_value(rt, pw, n, 0)


def node_value(rt, pw, n, depth):
    if n is None or depth > MAX_DEPTH:
        return None
    r = n.rule
    if r == "statement" or r == "pipeline" or r == "paren":
        kids = [k for k in n.children if k.rule != "comment"]
        return node_value(rt, pw, kids[0], depth + 1) if len(kids) == 1 else None
    if r == "statements" or r == "subexpr":
        kids = [k for k in n.children if k.rule == "statement" or k.rule == "statements"]
        return node_value(rt, pw, kids[0], depth + 1) if len(kids) == 1 else None
    if r == "array_expr":
        kids = [k for k in n.children if k.rule == "statement" or k.rule == "statements"]
        if len(kids) != 1:
            return None
        v = node_value(rt, pw, kids[0], depth + 1)
        if v is None:
            return None
        return v if isinstance(v, list) else [v]
    if r == "pipe":
        kids = [k for k in n.children if k.rule != "comment"]
        if len(kids) != 1:
            return None
        if kids[0].rule == "command":
            return command_value(rt, pw, kids[0])
        return node_value(rt, pw, kids[0], depth + 1)
    if r == "expression":
        return expression_value(rt, pw, n, depth)
    if r == "unary":
        return unary_value(rt, pw, n, depth)
    if r == "postfix_expr" or r == "postfix_expr_arg":
        return postfix_value(rt, pw, n, depth)
    return primary_value(rt, pw, n, depth)


def primary_value(rt, pw, n, depth):
    from .resolve import variable_value

    r = n.rule
    if r == "number":
        t = n.text
        if t.isdigit() and len(t) < 18:
            return int(t)
        return None
    if r == "sq_string":
        return sq_value(n.text)
    if r == "dq_string":
        v = dq_value(n)
        return v if v is not None else dq_parts(rt, pw, n, depth)
    if r == "here_sq":
        return here_value(n)
    if r == "here_dq":
        return here_value(n)
    if r == "variable":
        return variable_value(pw, n.text)
    if r == "paren" or r == "subexpr" or r == "array_expr" or r == "statement":
        return node_value(rt, pw, n, depth + 1)
    if r == "scriptblock":
        t = n.text
        return Block(t[1 : len(t) - 1])
    if r == "type_literal":
        return TypeName(fold(n.text[1 : len(n.text) - 1]))
    if r == "bareword" or r == "bareword_any":
        return None
    return None


def dq_parts(rt, pw, n, depth):
    """A "string" with $variables and $(...): each part's value."""
    from .resolve import variable_value

    out = ""
    for k in n.children:
        r = k.rule
        if r == "dq_text":
            out += k.text
        elif r == "dq_escape":
            c = k.text[1:]
            out += {"n": "\n", "t": "\t", "r": "\r", "0": "\x00", "a": "\x07", "b": "\x08", "e": "\x1b",
                    "f": "\x0c", "v": "\x0b"}.get(c, c)
        elif r == "variable":
            t = text_of(variable_value(pw, k.text))
            if t is None:
                return None
            out += t
        elif r == "subexpr":
            t = text_of(node_value(rt, pw, k, depth + 1))
            if t is None:
                return None
            out += t
        elif k.text == "$":
            out += "$"
        else:
            # ("" inside: one ")
            out += k.text[:1]
    return out


def postfix_value(rt, pw, n, depth):
    kids = n.children
    if len(kids) == 0:
        return None
    v = primary_value(rt, pw, kids[0], depth + 1)
    k = 1
    while k < len(kids):
        op = kids[k]
        if v is None:
            return None
        if op.rule == "index":
            i = node_value(rt, pw, op.children[0] if len(op.children) > 0 else None, depth + 1)
            v = indexed(v, i)
            k += 1
            continue
        if op.rule != "member":
            return None
        name = fold(op.text.lstrip(".:"))
        static = op.text.startswith("::")
        args = []
        called = k + 1 < len(kids) and kids[k + 1].rule == "invoke"
        if called:
            exprs = [a for a in kids[k + 1].children if a.rule == "expression"]
            for a in exprs:
                args.append(node_value(rt, pw, a, depth + 1))
            # (M('a','b'): one expression with commas, its items the
            # arguments)
            if len(exprs) == 1 and isinstance(args[0], list) and has_comma(exprs[0]):
                args = args[0]
            k += 1
        v = member(v, name, static, called, args)
        k += 1
    return v


def has_comma(expr):
    for k in expr.children:
        if k.rule == "binop" and k.text == ",":
            return True
    return False


def indexed(v, i):
    if not isinstance(i, int):
        return None
    if isinstance(v, list) or isinstance(v, str):
        n = len(v)
        if -n <= i < n:
            return v[i]
        return None
    return None


def member(v, name, static, called, args):
    """A method or property of a value vetter knows."""
    for a in args:
        if a is None:
            return None
    if isinstance(v, TypeName):
        if not static or not called:
            return None
        if (v.name == "scriptblock" or v.name == "system.management.automation.scriptblock") and name == "create" \
                and len(args) == 1 and isinstance(args[0], str):
            return Block(args[0])
        if (v.name == "string" or v.name == "system.string") and name == "join" and len(args) == 2:
            items = args[1] if isinstance(args[1], list) else [args[1]]
            parts = [text_of(x) for x in items]
            sep = text_of(args[0])
            if sep is None or None in parts:
                return None
            return sep.join(parts)
        if (v.name == "string" or v.name == "system.string") and name == "concat":
            parts = [text_of(x) for x in args]
            return None if None in parts else "".join(parts)
        if (v.name == "io.path" or v.name == "system.io.path") and name == "combine" and len(args) >= 1:
            parts = [text_of(x) for x in args]
            if None in parts:
                return None
            return windows_join(parts)
        return None
    if isinstance(v, str):
        if name == "length" and not called:
            return len(v)
        if not called:
            return None
        if name == "tolower" or name == "tolowerinvariant":
            return v.lower()
        if name == "toupper" or name == "toupperinvariant":
            return v.upper()
        if name == "trim" and len(args) == 0:
            return v.strip()
        if name == "replace" and len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], str):
            return v.replace(args[0], args[1])
        if name == "substring" and len(args) >= 1 and isinstance(args[0], int):
            if len(args) == 2 and isinstance(args[1], int):
                return v[args[0] : args[0] + args[1]]
            return v[args[0] :]
        return None
    if isinstance(v, Command) and not called and (name == "name" or name == "source" or name == "definition"):
        return v.name
    return None


def unary_value(rt, pw, n, depth):
    """Its prefixes (a cast, -join, -split, ',', '-', '!'), right to left,
    on what follows them."""
    kids = n.children
    if len(kids) == 0:
        return None
    last = kids[len(kids) - 1]
    v = node_value(rt, pw, last, depth + 1)
    text = n.text
    if len(text.encode()) != len(text):
        return None
    prefix = text[: last.start - n.start]
    ops = prefix_ops(prefix)
    if ops is None:
        return None
    k = len(ops) - 1
    while k >= 0:
        if v is None:
            return None
        v = apply_prefix(ops[k], v)
        k -= 1
    return v


def prefix_ops(s):
    """The prefixes in s, in order: "-join", "[char[]]", ","..."""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == " " or c == "\t":
            i += 1
            continue
        if c == "[":
            j = s.find("]", i)
            while j >= 0 and j + 1 < n and s[j + 1] == "]":
                j += 1
            if j < 0:
                return None
            out.append(fold(s[i : j + 1]))
            i = j + 1
            continue
        if c == "-":
            j = i + 1
            while j < n and s[j].isalpha():
                j += 1
            out.append(fold(s[i:j]))
            i = j
            continue
        if c == "!" or c == "," or c == "+":
            out.append(c)
            i += 1
            continue
        return None
    return out


def apply_prefix(op, v):
    if op == "-join":
        items = v if isinstance(v, list) else [v]
        parts = [text_of(x) for x in items]
        return None if None in parts else "".join(parts)
    if op == "-split":
        t = text_of(v)
        return None if t is None else t.split()
    if op == ",":
        return [v]
    if op == "-":
        return -v if isinstance(v, int) else None
    if op == "+":
        return v if isinstance(v, int) else None
    if op == "[char[]]" or op == "[system.char[]]":
        items = v if isinstance(v, list) else [v]
        out = []
        for x in items:
            c = to_char(x)
            if c is None:
                return None
            out.append(c)
        return out
    if op == "[char]" or op == "[system.char]":
        return to_char(v)
    if op == "[string]" or op == "[system.string]":
        return text_of(v)
    if op == "[int]" or op == "[int32]" or op == "[long]":
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        return None
    if op == "[array]" or op == "[object[]]" or op == "[string[]]":
        return v if isinstance(v, list) else [v]
    return None


def to_char(x):
    if isinstance(x, int) and 0 <= x < 0x110000:
        return chr(x)
    if isinstance(x, str) and len(x) == 1:
        return x
    return None


def expression_value(rt, pw, n, depth):
    """unary (binop unary)*: the operators by how tightly they bind
    (`'a' -replace 'b','c'`: the comma first)."""
    operands = []
    ops = []
    for k in n.children:
        if k.rule == "unary":
            operands.append(node_value(rt, pw, k, depth + 1))
        elif k.rule == "binop":
            ops.append(fold(k.text))
    if len(operands) != len(ops) + 1:
        return None
    return reduce_ops(operands, ops)


def reduce_ops(operands, ops):
    if len(ops) == 0:
        return operands[0]
    # (the loosest operator, the last of them: evaluated last, left to right)
    at = -1
    lowest = 99
    for i in range(len(ops)):
        p = PRECEDENCE[ops[i]] if ops[i] in PRECEDENCE else 1
        if p <= lowest:
            lowest = p
            at = i
    if ops[at] == ",":
        # (a, b, c: one array)
        items = []
        start = 0
        for i in range(len(ops) + 1):
            if i == len(ops) or (ops[i] == "," and (PRECEDENCE[","] == lowest)):
                part = reduce_ops(operands[start : i + 1], ops[start:i])
                if part is None:
                    return None
                items.append(part)
                start = i + 1
        return items
    left = reduce_ops(operands[: at + 1], ops[:at])
    right = reduce_ops(operands[at + 1 :], ops[at + 1 :])
    if left is None or right is None:
        return None
    return binary(ops[at], left, right)


def binary(op, a, b):
    if op == "+":
        if isinstance(a, int) and isinstance(b, int):
            return a + b
        if isinstance(a, list):
            return a + (b if isinstance(b, list) else [b])
        ta = text_of(a)
        tb = text_of(b)
        return None if ta is None or tb is None else ta + tb
    if op == "*" and isinstance(a, int) and isinstance(b, int):
        return a * b
    if op == "*" and isinstance(a, str) and isinstance(b, int) and 0 <= b and len(a) * b <= 4096:
        return a * b
    if op == "-" and isinstance(a, int) and isinstance(b, int):
        return a - b
    if op == ".." and isinstance(a, int) and isinstance(b, int) and abs(b - a) < MAX_ITEMS:
        step = 1 if b >= a else -1
        return [x for x in range(a, b + step, step)]
    if op == "-join":
        items = a if isinstance(a, list) else [a]
        parts = [text_of(x) for x in items]
        sep = text_of(b)
        return None if sep is None or None in parts else sep.join(parts)
    if op == "-replace" or op == "-ireplace" or op == "-creplace":
        t = text_of(a)
        pat = b[0] if isinstance(b, list) and len(b) >= 1 else b
        rep = b[1] if isinstance(b, list) and len(b) >= 2 else ""
        if t is None or not isinstance(pat, str) or not isinstance(rep, str):
            return None
        for c in ".^$*+?()[]{}|\\":
            if c in pat:
                # (a regular expression: not computed here)
                return None
        if "$" in rep:
            return None
        return replace_text(t, pat, rep, op != "-creplace")
    if op == "-f":
        fmt = text_of(a)
        items = b if isinstance(b, list) else [b]
        if fmt is None:
            return None
        out = fmt
        for i in range(len(items)):
            t = text_of(items[i])
            if t is None:
                return None
            out = out.replace("{" + str(i) + "}", t)
        return None if "{" in out else out
    return None


def replace_text(s, find, rep, fold_case):
    if find == "":
        return s
    out = ""
    hay = s.lower() if fold_case else s
    needle = find.lower() if fold_case else find
    i = 0
    while True:
        j = hay.find(needle, i)
        if j < 0:
            return out + s[i:]
        out += s[i:j] + rep
        i = j + len(find)


def windows_join(parts):
    """[IO.Path]::Combine, Join-Path: the parts with one separator between
    (\\ for Windows' paths, / for others: PowerShell on Linux); a part
    that's a full path starts again."""
    windows = False
    for p in parts:
        if "\\" in p or (len(p) > 1 and p[1] == ":"):
            windows = True
    sep = "\\" if windows else "/"
    out = ""
    for p in parts:
        if (len(p) > 1 and p[1] == ":") or p.startswith("\\") or p.startswith("/"):
            out = p
        elif out == "" or out.endswith("\\") or out.endswith("/"):
            out += p.lstrip("\\/")
        else:
            out += sep + p.lstrip("\\/")
    return out


def command_value(rt, pw, cmd):
    """What a command in a value gives, when vetter knows: Get-Command
    NAME (a wildcard naming one command vetter knows); Join-Path A B."""
    words = []
    name = None
    for k in cmd.children:
        if k.rule == "cmd_name":
            name = fold(k.text)
        elif k.rule == "argument" or k.rule == "argument_any":
            words.append(k)
        elif k.rule == "parameter":
            return None
    if name == "join-path" and len(words) == 2:
        parts = []
        for w in words:
            if len(w.children) != 1:
                return None
            parts.append(text_of(node_value(rt, pw, w.children[0], 1)))
        return None if None in parts else windows_join(parts)
    if (name != "get-command" and name != "gcm") or len(words) != 1:
        return None
    w = words[0]
    if len(w.children) != 1 or w.children[0].rule not in ("bareword", "sq_string", "dq_string"):
        return None
    pattern = w.children[0].text
    if w.children[0].rule == "sq_string":
        pattern = sq_value(pattern)
    elif w.children[0].rule == "dq_string":
        pattern = dq_value(w.children[0])
        if pattern is None:
            return None
    pattern = fold(pattern)
    found = []
    for c in CMDLETS.values():
        if match(fold(c.name), pattern) and c.name not in found:
            found.append(c.name)
    for a in ALIASES:
        if match(fold(a), pattern) and ALIASES[a] in CMDLETS and CMDLETS[ALIASES[a]].name not in found:
            found.append(CMDLETS[ALIASES[a]].name)
    return Command(found[0]) if len(found) == 1 else None
