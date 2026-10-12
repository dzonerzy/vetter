"""Arithmetic as bash evaluates it, and what in it runs commands: `let`,
`(( ))`, `$(( ))`, `for (( ))`, `[[ -eq ]]`, an integer variable's values,
indexed arrays' subscripts, `${s:offset}`.

bash expands arithmetic's text once, then evaluates it; evaluating, it
expands each subscript again (`a[$(cmd)]` runs cmd, quoted or not) and
evaluates a variable's value as arithmetic too (x='a[$(cmd)]'; (( x )) runs
cmd). So what's in arithmetic is found here: each subscript with a `$` or a
backtick, as code; each value only running tells (read, a command's output),
an Unknown, unless it's surely a number (a counter, `$(wc -l < f)`).

    a = from_node(body, variables, 0, 0)       # $(( ... )): its arith_body
    out = []
    check(a, 0, len(a.text), variables, home, out)   # Findings: ("code", text), ("unknown", reason)
    names = assigned(a)                         # numbers after
"""

from dataclasses import dataclass

from .expand import UNKNOWN, Dynamic, Number, dynamic_text, expand_word, field_known, field_static, param

# (what in an arithmetic text is a value only running tells)
HOLE = "\x00"

# (values naming values: as far as they're followed)
MAX_DEPTH = 8

EXPANSIONS = ("param", "cmdsub", "arith_sub", "arith_old", "backtick", "procsub")

# (parameters whose value is a number: $#, $?, $$, $!)
NUMERIC_SPECIALS = "#?$!"


@dataclass
class Arith:
    """An arithmetic text after bash's first expansion: the values known
    put in, each other expansion a HOLE (its Dynamic in holes, in order)."""

    text: str
    holes: list


@dataclass
class Finding:
    """"code": a subscript's text, its substitutions run (expanded again);
    "unknown": why what's evaluated only running tells."""

    kind: str
    text: str


def from_node(node, variables, start, end):
    """node's text but its first `start` and last `end` characters, as
    bash's first expansion leaves it."""
    t = node.text
    t = t[start : len(t) - end]
    text = ""
    holes = []
    cursor = 0
    for e in expansions_in(node, []):
        at = t.find(e.text, cursor)
        if at < 0:
            continue
        text += t[cursor:at]
        cursor = at + len(e.text)
        if e.rule == "param":
            v = param(e, variables)
            if isinstance(v, str):
                text += v
                continue
            if isinstance(v, list):
                text += " ".join(v)
                continue
            if v is None:
                continue
        text += HOLE
        holes.append(Dynamic(e, ""))
    text += t[cursor:]
    return Arith(text, holes)


def expansions_in(node, out):
    for k in node.children:
        if k.rule in EXPANSIONS:
            out.append(k)
        else:
            expansions_in(k, out)
    return out


def from_parts(parts):
    """A field's parts (strs, Dynamic pieces): an expanded word."""
    text = ""
    holes = []
    for p in parts:
        if isinstance(p, Dynamic):
            text += HOLE
            holes.append(p)
        else:
            text += p
    return Arith(text, holes)


def raw(a, lo, hi):
    """a.text[lo:hi] with its holes' own text: as bash expands it again."""
    out = ""
    n = a.text.count(HOLE, 0, lo)
    for i in range(lo, hi):
        c = a.text[i]
        if c == HOLE:
            out += dynamic_text(a.holes[n])
            n += 1
        else:
            out += c
    return out


def check(a, lo, hi, variables, home, out):
    """Findings of evaluating a.text[lo:hi] (added to out, each once)."""
    scan(a, lo, hi, variables, home, 0, out)


def check_subscript(a, lo, hi, variables, home, out):
    """a.text[lo:hi], a subscript (`${a[...]}`, `a[...]=`, `unset
    'a[...]'`): expanded again, then evaluated."""
    subscript(a, lo, hi, variables, home, 0, out)


def add(out, kind, text):
    for f in out:
        if f.kind == kind and f.text == text:
            return
    out.append(Finding(kind, text))


def is_ident_start(c):
    return ("a" <= c <= "z") or ("A" <= c <= "Z") or c == "_"


def is_ident_char(c):
    return is_ident_start(c) or ("0" <= c <= "9")


def is_name(s):
    if s == "" or not is_ident_start(s[0]):
        return False
    for c in s:
        if not is_ident_char(c):
            return False
    return True


def closing(text, i, hi):
    """The `]` closing the `[` at i (nested ones skipped), or hi."""
    depth = 0
    k = i
    while k < hi:
        if text[k] == "[":
            depth += 1
        elif text[k] == "]":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return hi


def assigns_plainly(text, j, hi):
    """Whether what follows a name at j is `=` (not `==`): its value set,
    not read."""
    while j < hi and (text[j] == " " or text[j] == "\t"):
        j += 1
    return j < hi and text[j] == "=" and not (j + 1 < hi and text[j + 1] == "=")


def subscript(a, lo, hi, variables, home, depth, out):
    s = raw(a, lo, hi)
    if "$" in s or "`" in s:
        add(out, "code", s)
    scan(a, lo, hi, variables, home, depth, out)


def scan(a, lo, hi, variables, home, depth, out):
    text = a.text
    i = lo
    while i < hi:
        c = text[i]
        if c == HOLE:
            d = a.holes[text.count(HOLE, 0, i)]
            if not hole_is_number(d, variables, home):
                add(out, "unknown", "arithmetic on " + dynamic_text(d) + ", a value only running tells (bash "
                    "evaluates it: a[$(...)] in it runs commands)")
            i += 1
        elif "0" <= c <= "9":
            # (a number: 10, 0x1f, 16#ff, 64#_@)
            while i < hi and (is_ident_char(text[i]) or text[i] == "#" or text[i] == "@"):
                i += 1
        elif is_ident_start(c):
            j = i
            while j < hi and is_ident_char(text[j]):
                j += 1
            name = text[i:j]
            k = j
            if j < hi and text[j] == "[":
                k = closing(text, j, hi)
                subscript(a, j + 1, k, variables, home, depth, out)
                k += 1
            if not assigns_plainly(text, k, hi):
                value(name, variables, home, depth, out)
            i = k
        else:
            i += 1


def value(name, variables, home, depth, out):
    """A variable named in arithmetic: its value evaluated as arithmetic."""
    if name not in variables.values:
        # (set outside the command: the environment's)
        return
    v = variables.values[name] if name not in variables.refs else UNKNOWN
    if v is None or isinstance(v, Number):
        return
    if isinstance(v, str) or isinstance(v, list):
        if depth >= MAX_DEPTH:
            add(out, "unknown", "arithmetic on " + name + ": values naming values, deeper than vetter follows")
            return
        items = v if isinstance(v, list) else [v]
        for s in items:
            scan(Arith(s, []), 0, len(s), variables, home, depth + 1, out)
        return
    add(out, "unknown", "arithmetic on $" + name + ", a value only running tells (bash evaluates it: a[$(...)] "
        "in it runs commands)")


def assigned(a):
    """The variables arithmetic sets (x=, x+=, x++, ++x): numbers after."""
    out = []
    text = a.text
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if "0" <= c <= "9":
            while i < n and (is_ident_char(text[i]) or text[i] == "#" or text[i] == "@"):
                i += 1
            continue
        if not is_ident_start(c):
            i += 1
            continue
        j = i
        while j < n and is_ident_char(text[j]):
            j += 1
        name = text[i:j]
        k = j
        if k < n and text[k] == "[":
            k = closing(text, k, n) + 1
        m = k
        while m < n and (text[m] == " " or text[m] == "\t"):
            m += 1
        after = text[m : m + 3]
        before = text[max(0, i - 2) : i]
        sets = (assigns_plainly(text, k, n) or after.startswith("++") or after.startswith("--")
                or before == "++" or before == "--" or after.startswith("<<=") or after.startswith(">>="))
        if not sets and len(after) >= 2 and after[1] == "=" and after[0] in "+-*/%&^|":
            sets = True
        if sets and name not in out:
            out.append(name)
        i = k
    return out


def hole_is_number(d, variables, home):
    """Whether an expansion's value is surely a number (harmless evaluated)."""
    node = d.node
    if node is None:
        return False
    rule = node.rule
    if rule == "arith_sub" or rule == "arith_old":
        return True
    if rule == "cmdsub":
        return numeric_output(node, variables, home)
    if rule != "param":
        return False
    t = node.text
    body = t[2 : len(t) - 1] if t.startswith("${") else t[1:]
    if body.startswith("#") and len(body) > 1:
        # (a length)
        return True
    if body.startswith("!"):
        return False
    if len(body) > 0 and body[0] in NUMERIC_SPECIALS:
        return True
    k = 0
    while k < len(body) and is_ident_char(body[k]):
        k += 1
    name = body[:k]
    if name == "":
        name = "@"
    elif "0" <= name[0] <= "9":
        # (a positional parameter: the command's, unless a function's or
        # a `bash -c`'s)
        name = "@"
    if name not in variables.values:
        return True
    v = variables.values[name]
    if isinstance(v, Number):
        return True
    return isinstance(v, str) and is_number_text(v)


def is_number_text(s):
    s = s.strip()
    if s.startswith("-") or s.startswith("+"):
        s = s[1:]
    if s == "":
        return False
    for c in s:
        if not ("0" <= c <= "9"):
            return False
    return True


def numeric_output(node, variables, home):
    """A command substitution printing only a number (`$(wc -l < f)`, `$(date
    +%s)`): its one pipeline's last command, all its words known."""
    lists = [k for k in node.children if k.rule == "compound_list"]
    if len(lists) != 1:
        return False
    and_ors = [k for k in lists[0].children if k.rule == "and_or"]
    if len(and_ors) != 1:
        return False
    pipes = [k for k in and_ors[0].children if k.rule == "pipeline"]
    if len(pipes) != 1:
        return False
    cmds = [k for k in pipes[0].children if k.rule == "command"]
    if len(cmds) == 0 or cmds[len(cmds) - 1].children[0].rule != "simple":
        return False
    argv = []
    for k in cmds[len(cmds) - 1].children[0].children:
        if k.rule == "cmd_name" or k.rule == "word":
            for f in expand_word(k, variables, home, True):
                if not field_known(f):
                    return False
                argv.append(field_static(f))
    if len(argv) == 0:
        return False
    return numeric_command(argv)


DIGIT_SETS = ("0-9", "[:digit:]", "[0-9]", "0-9\\n", "0-9\n", "[:digit:]\\n", "[:digit:]\n")


def numeric_command(argv):
    """Whether this command prints only numbers (and the names it was given)."""
    name = argv[0]
    slash = name.rfind("/")
    if slash >= 0:
        name = name[slash + 1 :]
    args = argv[1:]
    if name == "tr":
        complement = False
        delete = False
        sets = []
        for x in args:
            if x.startswith("-") and len(x) > 1 and not x.startswith("--"):
                complement = complement or "c" in x or "C" in x
                delete = delete or "d" in x
            elif x == "--complement":
                complement = True
            elif x == "--delete":
                delete = True
            else:
                sets.append(x)
        return complement and delete and len(sets) == 1 and sets[0] in DIGIT_SETS
    for x in args:
        if "$" in x or "`" in x or "[" in x:
            return False
    if name == "wc":
        for x in args:
            if x.startswith("--files0"):
                return False
        return True
    if name == "nproc" or name == "date" or name == "stat":
        return True
    if name == "id":
        for x in args:
            if x == "-u" or x == "-g" or x == "--user" or x == "--group" or x == "-ur" or x == "-gr":
                return True
        return False
    if name == "grep" or name == "egrep" or name == "fgrep":
        count = False
        for x in args:
            if x == "--count" or (x.startswith("-") and not x.startswith("--") and "c" in x):
                count = True
            if x == "-r" or x == "-R" or x.startswith("--recursive") or x.startswith("--dereference-recursive") \
                    or (x.startswith("-") and not x.startswith("--") and ("r" in x or "R" in x)):
                return False
        return count
    if name == "seq":
        for x in args:
            if x.startswith("-f") or x.startswith("--format") or x.startswith("-s") or x.startswith("--separator"):
                return False
        return True
    if name == "echo":
        for x in args:
            if x != "-n" and not is_number_text(x):
                return False
        return True
    if name == "printf":
        if len(args) == 0:
            return False
        fmt = args[0].replace("\\n", "").replace("\n", "")
        i = 0
        while i < len(fmt):
            if fmt[i] == "%":
                if i + 1 >= len(fmt) or fmt[i + 1] not in "diuxXo":
                    return False
                i += 2
            elif fmt[i] == " " or ("0" <= fmt[i] <= "9"):
                i += 1
            else:
                return False
        return True
    if name == "git":
        return "rev-list" in args and "--count" in args
    if name == "tput":
        return len(args) == 1 and (args[0] == "cols" or args[0] == "lines" or args[0] == "colors")
    return False
