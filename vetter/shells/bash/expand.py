"""Word expansion as bash does it: brace expansion, tilde, parameters (the
variables whose values are known), word splitting, pathname patterns,
quote removal, in bash's order.

A variable's value: a str, a list (an array; "@" the positional
parameters), None (known unset), UNKNOWN (an Unknown record) or NUMBER (an
integer only running tells: unknown too, harmless in arithmetic). The items a
word is made of are Item records of a kind (CH, DYN, EXP, QUOTE, BREAK);
a field's parts are strs and Dynamic records (node None: a home directory
not known).

    fields = expand_word(word_node, variables, home, True)
"""

from dataclasses import dataclass, field

from ...glob import match
from .scan import ansi_decode


@dataclass
class Unknown:
    """A variable's value that only running tells (set outside, by `read`...)."""


UNKNOWN = Unknown()


@dataclass
class Number:
    """An integer only running tells (arithmetic set it, a count): unknown
    as text, harmless as arithmetic."""


NUMBER = Number()

DEFAULT_IFS = " \t\n"

MAX_FIELDS = 1024


@dataclass
class Variables:
    """What's known of the shell's variables at a point of the command.
    Not set here: UNKNOWN (it may come from outside), IFS aside (bash sets
    it)."""

    values: dict
    # (declare's: "i" an integer, its values evaluated as arithmetic; "A"
    # an associative array)
    attrs: dict = field(default_factory=dict)


def var_copy(variables):
    return Variables({k: v for k, v in variables.values.items()}, {k: v for k, v in variables.attrs.items()})


def var_forget(variables, names):
    """These became unknown (set where vetter can't follow: a loop, a
    condition, `read`)."""
    for n in names:
        variables.values[n] = UNKNOWN


def changed_since(variables, before):
    """The variables whose values differ from before's (one set to what it
    was is that either way)."""
    out = []
    for n, v in variables.values.items():
        if n not in before.values or before.values[n] != v:
            out.append(n)
    return out


def var_get(variables, name):
    if name in variables.values:
        return variables.values[name]
    if name == "IFS":
        return DEFAULT_IFS
    return UNKNOWN


def is_unknown(v):
    return isinstance(v, Unknown) or isinstance(v, Number)


@dataclass
class Dynamic:
    """A part of a word only known when the command runs: its node, or
    None and its text (a home directory not known, `~`; `{}` of find
    -exec...)."""

    node: object
    text: str


def dynamic_text(d):
    if d.node is None:
        return d.text
    return d.node.text


@dataclass
class Field:
    """One word after expansion: known text and Dynamic pieces; `glob`: it's
    a pathname pattern (an unquoted * ? or [); `splits`: an unquoted dynamic
    piece may make it any number of fields."""

    parts: list
    glob: bool
    splits: bool


def field_static(f):
    """The text if all of it is known (a pattern's text too), else None."""
    for p in f.parts:
        if isinstance(p, Dynamic):
            return None
    return "".join(f.parts)


def field_known(f):
    """Known, and one field for sure (not a pattern, no splitting)."""
    return not f.glob and not f.splits and field_static(f) is not None


def field_text(f):
    out = ""
    for p in f.parts:
        if isinstance(p, Dynamic):
            out += dynamic_text(p)
        else:
            out += p
    return out


# The items of a word before splitting: characters (quoted or not, from an
# expansion or the text), dynamic pieces, expansions still to do, where
# quotes were (`''` keeps an empty field), field boundaries inside quotes
# ("$@", "${a[@]}")
CH = 0
DYN = 1
EXP = 2
QUOTE = 3
BREAK = 4


@dataclass
class Item:
    kind: int
    c: str
    quoted: bool
    from_exp: bool
    node: object


def ch(c, quoted, from_exp):
    return Item(CH, c, quoted, from_exp, None)


def chars(out, text, quoted, from_exp):
    for c in text:
        out.append(Item(CH, c, quoted, from_exp, None))


def is_ch(item, c):
    return item.kind == CH and not item.quoted and item.c == c


# ----------------------------------------------------------------------
# Small readers (what expand.py does with re)
# ----------------------------------------------------------------------


def is_digit(c):
    return c >= "0" and c <= "9" and len(c) == 1


def is_alpha(c):
    return (c >= "a" and c <= "z") or (c >= "A" and c <= "Z")


def is_word_char(c):
    return is_alpha(c) or is_digit(c) or c == "_"


def is_int(s):
    """-?[0-9]+"""
    i = 0
    if s[:1] == "-":
        i = 1
    if i >= len(s):
        return False
    while i < len(s):
        if not is_digit(s[i]):
            return False
        i += 1
    return True


def ident_end(s, i):
    """The end of [A-Za-z_][A-Za-z0-9_]* at i, or -1."""
    if i >= len(s) or not (is_alpha(s[i]) or s[i] == "_"):
        return -1
    i += 1
    while i < len(s) and is_word_char(s[i]):
        i += 1
    return i


def digits_end(s, i):
    """The end of [0-9]+ at i, or -1."""
    j = i
    while j < len(s) and is_digit(s[j]):
        j += 1
    return j if j > i else -1


def is_name(s):
    """[A-Za-z_]\\w*|[0-9]+, all of s"""
    k = ident_end(s, 0)
    if k < 0:
        k = digits_end(s, 0)
    return k == len(s)


def name_end(s, i, specials):
    """The end of a parameter's name at i: an identifier, digits, or one
    of specials; -1 when there's none."""
    k = ident_end(s, i)
    if k < 0:
        k = digits_end(s, i)
    if k < 0 and i < len(s) and s[i] in specials:
        k = i + 1
    return k


def skip_space(s, i):
    while i < len(s) and s[i] in " \t\n\r\f\v":
        i += 1
    return i


def int_end(s, i):
    """The end of -?[0-9]+ at i, or -1."""
    j = i
    if j < len(s) and s[j] == "-":
        j += 1
    k = digits_end(s, j)
    return k


def zfill(s, width):
    sign = ""
    if s[:1] == "-":
        sign = "-"
        s = s[1:]
    while len(sign) + len(s) < width:
        s = "0" + s
    return sign + s


# ----------------------------------------------------------------------
# The word's items, before any expansion
# ----------------------------------------------------------------------


def items_of(node):
    """The word's characters and expansions, quoting kept."""
    if node.rule == "cmd_name":
        first = node.children[0]
        if first.rule == "word":
            node = first
    out = []
    for part in node.children:
        rule = part.rule
        t = part.text
        if rule == "lit":
            chars(out, t, False, False)
        elif rule == "dollar":
            out.append(ch("$", False, False))
        elif rule == "escape":
            out.append(ch(t[1:], True, False))
        elif rule == "sq":
            out.append(Item(QUOTE, "", False, False, None))
            chars(out, t[1 : len(t) - 1], True, False)
        elif rule == "ansi":
            out.append(Item(QUOTE, "", False, False, None))
            chars(out, ansi_decode(t[2 : len(t) - 1]), True, False)
        elif rule == "dq" or rule == "locale":
            out.append(Item(QUOTE, "", False, False, None))
            dq_items(part, False, out)
        elif (rule == "param" or rule == "cmdsub" or rule == "arith_sub" or rule == "arith_old"
              or rule == "backtick" or rule == "procsub"):
            out.append(Item(EXP, "", False, False, part))
        elif rule == "subscripted":
            out.append(Item(DYN, "", False, False, part))
        else:
            chars(out, t, False, False)
    return out


def dq_items(node, heredoc, out):
    # (a backslash escapes only $ ` \ newline, and " in double quotes)
    special = "$`\\\n" if heredoc else '$`"\\\n'
    for p in node.children:
        r = p.rule
        if r == "dq_text" or r == "hd_text" or r == "dq_dollar":
            chars(out, p.text, True, False)
        elif r == "dq_escape" or r == "hd_escape":
            t = p.text
            if len(t) == 2 and t[1] in special:
                if t[1] != "\n":
                    out.append(ch(t[1], True, False))
            else:
                chars(out, t, True, False)
        else:
            out.append(Item(EXP, "", True, False, p))
    return out


# ----------------------------------------------------------------------
# Brace expansion
# ----------------------------------------------------------------------


def braces(items, budget):
    """Every word the first brace expression makes, expanded in turn
    (ValueError: more than budget)."""
    i = 0
    while i < len(items):
        if not is_ch(items[i], "{"):
            i += 1
            continue
        # (a `${` is a parameter, already an item)
        depth = 0
        commas = []
        j = i
        closed = False
        while j < len(items):
            if is_ch(items[j], "{"):
                depth += 1
            elif is_ch(items[j], "}"):
                depth -= 1
                if depth == 0:
                    closed = True
                    break
            elif is_ch(items[j], ",") and depth == 1:
                commas.append(j)
            j += 1
        if not closed:
            return [items]
        prefix = items[:i]
        suffix = items[j + 1 :]
        alts = []
        if len(commas) > 0:
            cuts = [i] + commas + [j]
            for k in range(len(cuts) - 1):
                alts.append(items[cuts[k] + 1 : cuts[k + 1]])
        else:
            alts = sequence(items[i + 1 : j])
            if alts is None:
                # (not a brace expression: look further)
                head = items[: i + 1]
                out = []
                for r in braces(items[i + 1 :], budget):
                    out.append(head + r)
                return out
        out = []
        for alt in alts:
            out += braces(prefix + alt + suffix, budget)
            if len(out) > budget:
                raise ValueError("too many fields")
        return out
    return [items]


def sequence(body):
    """`{1..5}`, `{a..e}`, `{1..10..2}`: its items, or None."""
    text = ""
    for it in body:
        if it.kind != CH or it.quoted:
            return None
        text += it.c
    parts = text.split("..")
    if len(parts) != 2 and len(parts) != 3:
        return None
    if len(parts) == 3 and not is_int(parts[2]):
        return None
    step = 1
    if len(parts) == 3:
        step = abs(int(parts[2]))
    out = []
    if is_int(parts[0]) and is_int(parts[1]):
        a = int(parts[0])
        b = int(parts[1])
        if step == 0 or abs(b - a) // step > MAX_FIELDS:
            return None
        width = 0
        if unsigned(parts[0])[:1] == "0" or unsigned(parts[1])[:1] == "0":
            width = max(len(parts[0]), len(parts[1]))
        for v in steps(a, b, step):
            item = []
            chars(item, zfill(str(v), width), False, False)
            out.append(item)
        return out
    if len(parts[0]) == 1 and len(parts[1]) == 1 and is_alpha(parts[0]) and is_alpha(parts[1]):
        if step == 0:
            return None
        a = ord(parts[0])
        b = ord(parts[1])
        for v in steps(a, b, step):
            out.append([ch(chr(v), False, False)])
        return out
    return None


def steps(a, b, step):
    """a to b (b too, if a step lands on it), by step, up or down."""
    out = []
    v = a
    if a <= b:
        while v <= b:
            out.append(v)
            v += step
    else:
        while v >= b:
            out.append(v)
            v -= step
    return out


def unsigned(s):
    return s[1:] if s[:1] == "-" else s


# ----------------------------------------------------------------------
# Parameters
# ----------------------------------------------------------------------

OPS = [":-", ":=", ":+", ":?", "-", "=", "+", "?", "##", "#", "%%", "%", "//", "/#", "/%", "/",
       "^^", "^", ",,", ","]


def literal(text):
    """A parameter operation's word, if it's plain text (quotes removed):
    None when it has expansions."""
    out = ""
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            out += text[i + 1]
            i += 2
        elif c == "'":
            j = i + 1
            while j < n and text[j] != "'":
                j += 1
            if j >= n:
                return None
            out += text[i + 1 : j]
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "$" or text[j] == "`":
                    return None
                if text[j] == "\\" and j + 1 < n and text[j + 1] in '$`"\\':
                    j += 1
                out += text[j]
                j += 1
            i = j + 1
        elif c == "$" or c == "`":
            return None
        else:
            out += c
            i += 1
    return out


def param(node, variables):
    """The parameter's value: a str, a list (several fields in quotes:
    "$@", "${a[@]}"), None or UNKNOWN."""
    text = node.text
    if not text.startswith("${"):
        return lookup(text[1:], None, variables)
    body = text[2 : len(text) - 1]
    if body.startswith("#") and len(body) > 1:
        k = name_end(body, 1, "@*")
        if k < 0:
            return UNKNOWN
        index = None
        if k < len(body):
            if body[k] != "[" or body[len(body) - 1] != "]":
                return UNKNOWN
            index = body[k + 1 : len(body) - 1]
            if index != "@" and index != "*" and digits_end(index, 0) != len(index):
                return UNKNOWN
        v = lookup(body[1:k], index, variables)
        if is_unknown(v):
            return UNKNOWN
        if v is None:
            return "0"
        return str(len(v))
    if body.startswith("!"):
        if ident_end(body, 1) != len(body):
            return UNKNOWN
        ref = var_get(variables, body[1:])
        if not isinstance(ref, str) or not is_name(ref):
            return UNKNOWN
        return lookup(ref, None, variables)
    k = name_end(body, 0, "@*#?$!-")
    if k < 0:
        return UNKNOWN
    name = body[:k]
    index = None
    if k < len(body) and body[k] == "[":
        close = k + 1
        while close < len(body) and body[close] != "]":
            close += 1
        if close < len(body):
            index = body[k + 1 : close]
            k = close + 1
    rest = body[k:]
    v = lookup(name, index, variables)
    if rest == "":
        return v
    if rest.startswith(":") and not (rest.startswith(":-") or rest.startswith(":=") or rest.startswith(":+")
                                     or rest.startswith(":?")):
        return substring(v, rest[1:])
    for op in OPS:
        if rest.startswith(op):
            return operate(name, index, v, op, rest[len(op) :], variables)
    return UNKNOWN


def lookup(name, index, variables):
    if name == "@" or name == "*":
        return var_get(variables, "@")
    if name.isdigit():
        pos = var_get(variables, "@")
        if name == "0" or not isinstance(pos, list):
            return UNKNOWN
        i = int(name) - 1
        return pos[i] if i < len(pos) else None
    if name == "#":
        pos = var_get(variables, "@")
        return str(len(pos)) if isinstance(pos, list) else UNKNOWN
    if name == "?" or name == "$" or name == "!" or name == "-":
        return UNKNOWN
    v = var_get(variables, name)
    if index is None:
        if isinstance(v, list):
            return v[0] if len(v) > 0 else None
        return v
    if is_unknown(v):
        return UNKNOWN
    arr = v if isinstance(v, list) else ([] if v is None else [v])
    if index == "@" or index == "*":
        return arr
    if not is_int(index):
        return UNKNOWN
    i = int(index)
    if i >= len(arr) or i < -len(arr):
        return None
    return arr[i]


def scalar(v):
    if isinstance(v, list):
        return " ".join(v)
    return v


def operate(name, index, v, op, word_text, variables):
    word = literal(word_text)
    sv = scalar(v)
    if op == ":-" or op == "-" or op == ":=" or op == "=":
        if is_unknown(v):
            return UNKNOWN
        empty = v is None or ((op == ":-" or op == ":=") and sv == "")
        if not empty:
            return v
        if word is None:
            return UNKNOWN
        if (op == ":=" or op == "=") and index is None:
            variables.values[name] = word
        return word
    if op == ":+" or op == "+":
        if is_unknown(v):
            return UNKNOWN
        empty = v is None or (op == ":+" and sv == "")
        if empty:
            return ""
        return word if word is not None else UNKNOWN
    if op == ":?" or op == "?":
        return v if v is not None else UNKNOWN
    if is_unknown(v) or word is None:
        return UNKNOWN
    if v is None:
        return ""
    each = v if isinstance(v, list) else [v]
    out = []
    if op == "#" or op == "##" or op == "%" or op == "%%":
        for s in each:
            out.append(trim(s, word, op))
    elif op == "/" or op == "//" or op == "/#" or op == "/%":
        cut = split_replacement(word_text)
        pat = literal(word_text[:cut])
        rep = literal(word_text[cut + 1 :]) if cut < len(word_text) else ""
        if pat is None or rep is None:
            return UNKNOWN
        for s in each:
            out.append(replace(s, pat, rep, op))
    else:
        # (^^ ^ ,, ,)
        if word != "" and word != "?":
            return UNKNOWN
        # (beyond ASCII, the locale says: in C, nothing changes)
        for s in each:
            for c in s:
                if ord(c) > 127:
                    return UNKNOWN
        for s in each:
            if op == "^^":
                out.append(s.upper())
            elif op == "^":
                out.append(s[:1].upper() + s[1:])
            elif op == ",,":
                out.append(s.lower())
            else:
                out.append(s[:1].lower() + s[1:])
    if isinstance(v, list):
        return out
    return out[0]


def split_replacement(text):
    """Where the `/` between a replacement's pattern and its string is
    (len(text): none)."""
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "/":
            return i
        i += 1
    return len(text)


def trim(s, pat, op):
    n = len(s)
    if op == "#":
        for i in range(0, n + 1):
            if match(s[:i], pat):
                return s[i:]
        return s
    if op == "##":
        for i in range(n, -1, -1):
            if match(s[:i], pat):
                return s[i:]
        return s
    if op == "%":
        for i in range(n, -1, -1):
            if match(s[i:], pat):
                return s[:i]
        return s
    for i in range(0, n + 1):
        if match(s[i:], pat):
            return s[:i]
    return s


def replace(s, pat, rep, op):
    if pat == "":
        return s
    n = len(s)
    if op == "/#":
        for j in range(n, -1, -1):
            if match(s[:j], pat):
                return rep + s[j:]
        return s
    if op == "/%":
        for i in range(0, n + 1):
            if match(s[i:], pat):
                return s[:i] + rep
        return s
    out = ""
    i = 0
    replaced = False
    while i <= n:
        if replaced and op == "/":
            out += s[i:]
            break
        found = False
        j = n
        while j > i:
            if match(s[i:j], pat):
                out += rep
                i = j
                replaced = True
                found = True
                break
            j -= 1
        if not found:
            if i < n:
                out += s[i]
            i += 1
    return out


def substring(v, spec):
    if is_unknown(v):
        return UNKNOWN
    # (\s*(-?\d+)\s*(?::\s*(-?\d+)\s*)?)
    i = skip_space(spec, 0)
    k = int_end(spec, i)
    if k < 0:
        return UNKNOWN
    off = int(spec[i:k])
    i = skip_space(spec, k)
    length = None
    if i < len(spec):
        if spec[i] != ":":
            return UNKNOWN
        i = skip_space(spec, i + 1)
        k = int_end(spec, i)
        if k < 0:
            return UNKNOWN
        length = int(spec[i:k])
        if skip_space(spec, k) != len(spec):
            return UNKNOWN
    if isinstance(v, list):
        seq = v[off:]
        if length is None:
            return seq
        return seq[:length] if length >= 0 else UNKNOWN
    s = v if v is not None else ""
    if off < 0:
        off = max(0, len(s) + off)
    t = s[off:]
    if length is None:
        return t
    return t[:length] if length >= 0 else t[: max(0, len(t) + length)]


# ----------------------------------------------------------------------
# Expanding
# ----------------------------------------------------------------------


def is_user(s):
    """[A-Za-z_][\\w.-]*"""
    if len(s) == 0 or not (is_alpha(s[0]) or s[0] == "_"):
        return False
    for c in s:
        if not (is_word_char(c) or c == "." or c == "-"):
            return False
    return True


def expand_items(items, variables, home, tilde):
    """Tilde and expansions done: characters (from_exp marks what may
    split), DYN pieces, BREAK boundaries."""
    out = []
    if tilde and len(items) > 0 and is_ch(items[0], "~"):
        j = 1
        while j < len(items) and items[j].kind == CH and not items[j].quoted and items[j].c != "/":
            j += 1
        user = ""
        for k in range(1, j):
            user += items[k].c
        if user == "":
            if home is not None:
                chars(out, home, True, False)
            else:
                out.append(Item(DYN, "", True, False, None))
            items = items[j:]
        elif is_user(user):
            # (another user's home: not known here)
            out.append(Item(DYN, "", True, False, None))
            items = items[j:]
    for it in items:
        if it.kind != EXP:
            out.append(it)
            continue
        if it.node.rule != "param":
            out.append(Item(DYN, "", it.quoted, False, it.node))
            continue
        v = param(it.node, variables)
        if is_unknown(v):
            out.append(Item(DYN, "", it.quoted, False, it.node))
        elif v is None:
            continue
        elif isinstance(v, list):
            if it.quoted and "*" in it.node.text:
                ifs = var_get(variables, "IFS")
                sep = ifs[:1] if isinstance(ifs, str) else " "
                chars(out, sep.join(v), True, True)
            else:
                for k in range(len(v)):
                    if k > 0:
                        if it.quoted:
                            out.append(Item(BREAK, "", False, False, None))
                        else:
                            out.append(ch(" ", False, True))
                    chars(out, v[k], it.quoted, True)
        else:
            chars(out, v, it.quoted, True)
    return out


def split_fields(items, ifs):
    """Fields after word splitting (only characters from unquoted
    expansions split)."""
    fields = [[]]
    ifs_known = isinstance(ifs, str)
    ws = ""
    other = ""
    if ifs_known:
        for c in ifs:
            if c in " \t\n":
                ws += c
            else:
                other += c
    pending_ws = False
    for it in items:
        if it.kind == BREAK:
            fields.append([])
            continue
        if it.kind == CH and it.from_exp and not it.quoted:
            if not ifs_known:
                fields[len(fields) - 1].append(Item(DYN, "", False, False, None))
                continue
            if it.c in ws:
                pending_ws = True
                continue
            if it.c in other:
                fields.append([])
                pending_ws = False
                continue
        if pending_ws:
            if len(fields[len(fields) - 1]) > 0:
                fields.append([])
            pending_ws = False
        fields[len(fields) - 1].append(it)
    return fields


def make_field(items):
    """The field of items, or None (nothing, no quotes: no field)."""
    f = Field([], False, False)
    text = ""
    quoted_any = False
    for it in items:
        if it.kind == QUOTE:
            quoted_any = True
            continue
        if it.kind == CH:
            text += it.c
            if it.quoted:
                quoted_any = True
            elif it.c in "*?[":
                f.glob = True
            continue
        if text != "":
            f.parts.append(text)
            text = ""
        f.parts.append(Dynamic(it.node, "~"))
        if it.quoted:
            quoted_any = True
        else:
            f.splits = True
    if text != "":
        f.parts.append(text)
    if len(f.parts) == 0 and not quoted_any:
        return None
    return f


def expand_word(node, variables, home, split):
    """The fields a word becomes (an empty list: none, e.g. `$empty`)."""
    words = []
    if split:
        try:
            words = braces(items_of(node), MAX_FIELDS)
        except ValueError:
            return [Field([Dynamic(node, "")], False, True)]
    else:
        words = [items_of(node)]
    out = []
    for items in words:
        expanded = expand_items(items, variables, home, True)
        # (not split, "$@" is one field: `<<< "$@"` joins with spaces)
        groups = [joined(expanded)]
        if split:
            groups = split_fields(expanded, var_get(variables, "IFS"))
        for g in groups:
            f = make_field(g)
            if f is not None:
                if not split:
                    f.splits = False
                    f.glob = False
                out.append(f)
    return out


def joined(items):
    out = []
    for it in items:
        if it.kind == BREAK:
            out.append(ch(" ", True, True))
        else:
            out.append(it)
    return out


def quoted(items):
    out = []
    for it in items:
        if it.kind == CH:
            out.append(Item(CH, it.c, True, it.from_exp, None))
        else:
            out.append(it)
    return out


def expand_assignment(node, variables, home):
    """An assignment's value (no splitting, no globs, no braces; `~` after
    `=` and `:` expands)."""
    if node is None:
        return Field([""], False, False)
    # (tilde after each unquoted ':' too)
    segments = [[]]
    for it in items_of(node):
        if is_ch(it, ":"):
            segments.append([])
        else:
            segments[len(segments) - 1].append(it)
    expanded = []
    for k in range(len(segments)):
        if k > 0:
            expanded.append(ch(":", True, False))
        expanded += expand_items(segments[k], variables, home, True)
    # ("$@" joins with spaces: `x="$@"`)
    f = make_field(quoted(joined(expanded)))
    if f is None:
        f = Field([""], False, False)
    f.glob = False
    f.splits = False
    return f


def expand_heredoc(body, variables):
    """An expanded here-document's text."""
    items = expand_items(dq_items(body, True, []), variables, None, False)
    f = make_field(joined(items))
    if f is None:
        f = Field([""], False, False)
    f.glob = False
    f.splits = False
    return f
