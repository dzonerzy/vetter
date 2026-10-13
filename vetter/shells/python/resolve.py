"""What Python code given to an interpreter does (python -c CODE, a
here-document on python's stdin): read with python.zgram and followed the
way it runs, its values as far as they're known: the files it reads,
writes and deletes, the commands it runs (resolved as commands are), where
it connects, the folder it moves to, the environment it gives what it runs.

Values (V) are known (a str, a number, a list of values, a module, a
function of the code's own) or not: `data`, plain data (str, numbers,
lists of them: what a computation gives), or `opaque`, anything at all.
What it does with a value vetter doesn't follow is an Unknown: asked.
Where the code branches (if, loops, try, a function returning early),
each way is followed and what each gives joined: a value that may be
either is data or opaque. Lists and dicts are shared as Python shares
them; changed where vetter can't say for sure how, they're widened, in
place: their items no longer known.

    python_code(rt, w, e, ctx, text, label, args, isolated)
"""

from dataclasses import dataclass, field

import zgram

from ... import paths
from ...specs import Role
from ..bash.expand import Dynamic, Field, Variables, field_known, field_static
from ...policy.actions import DOWNLOADERS, SOCKETS
from ..bash.resolve import Ctx, Resolution, Stdin, W, code, exec_name, run, unknown
from .stdlib import (
    BUILTINS,
    CONSTS,
    DATA_ATTRS,
    DATA_METHODS,
    FOLLOWED_PACKAGES,
    FUNCS,
    IMPORT_EFFECTS,
    ITEMS_OF,
    MODULES,
    NEVER_CALLS,
    NOT_PURE,
    PATH_METHODS,
    PRELOADED,
    PURE_CLASSES,
    PURE_MODULES,
    STDLIB,
    STREAM_METHODS,
    STREAMS,
)
from .syntax import parse

MAX_STEPS = 4000        # statements and calls followed
MAX_CALLS = 12          # calls nested
MAX_ITEMS = 16          # a loop over a known list: walked item by item
MAX_PASSES = 3          # a loop's body walked again until its values settle
MAX_TEXT = 4096         # a str computed: longer, data

# Names Python's builtins module has that aren't in BUILTINS (the ones
# vetter doesn't follow, open's and the like's)
OTHER_BUILTINS = {
    "eval", "exec", "compile", "__import__", "globals", "locals", "vars", "setattr", "delattr", "getattr",
    "breakpoint", "help", "super", "open", "exit", "quit", "staticmethod", "classmethod", "property",
    "copyright", "credits", "license", "__build_class__", "__loader__", "__spec__", "__builtins__",
}
# The types whose methods a builtins.str.strip names
TYPES = {"str", "bytes", "int", "float", "list", "dict", "set", "tuple", "frozenset", "bytearray"}
# Path's properties (not methods)
PATH_PROPS = {"parent", "name", "stem", "suffix", "suffixes", "parts", "parents", "anchor", "drive", "root"}
CONTAINERS = ("list", "tuple", "set", "dict", "seq")


@dataclass
class V:
    """A value: kind (str, bytes, int, bool, none, list, tuple, set, dict,
    seq, data, opaque, module, attr, path, file, tempdir, method, fn,
    class, identity, decorator, suppress, request, socket, etree: an
    ElementTree; file: a stream too, stdin's, a StringIO's); text (a str's,
    bytes', a path's, a module's or attribute's qualified name, a method's
    name); num (an int's); items (a list's, tuple's, set's; a dict's keys)
    and vals (a dict's values); glob: the text is a pattern (a name a
    listing found); obj: a method's receiver, a seq's item, a request's
    URL; fn: a function's Fn."""

    kind: str
    text: object = None
    num: object = None
    items: list = field(default_factory=list)
    vals: list = field(default_factory=list)
    glob: bool = False
    obj: object = None
    fn: object = None


@dataclass
class Fn:
    """A function the code defines (a lambda's body an expression)."""

    name: str
    params: object
    body: object
    lam: bool
    scope: object
    defaults: dict


@dataclass
class Scope:
    """Names and their values: the module's, a function call's, a class
    body's, a comprehension's (kind); parent: the enclosing scope."""

    vars: dict
    parent: object
    kind: str
    declared: dict = field(default_factory=dict)


@dataclass
class State:
    """What each scope holds at a point (for joining ways)."""

    scopes: list
    dicts: list


@dataclass
class Frame:
    """A function call's or a loop's: the states (and values) at its
    returns, breaks, continues; a generator's yields."""

    states: list
    values: list
    others: list


@dataclass
class Args:
    pos: list
    kw: dict
    # (a *x or **x vetter can't spread: what's given isn't known)
    rest: bool


@dataclass
class Py:
    w: object
    pw: object
    ctx: object
    e: object
    label: str
    home: object
    module: object
    scope: object
    argv: object
    isolated: bool
    # (what the commands it runs read on their stdin when not given:
    # python's own)
    stdin: object = None
    # (python's stdin is a download)
    fetched: bool = False
    dead: bool = False
    uncertain: int = 0
    depth: int = 0
    steps: int = 0
    stopped: bool = False
    # (a value not plain data was put where vetter lost track of it: data
    # may hold it, its methods no longer known to only compute)
    leaked: bool = False
    logs: list = field(default_factory=list)
    loops: list = field(default_factory=list)
    funcs: list = field(default_factory=list)
    stack: list = field(default_factory=list)
    star: list = field(default_factory=list)
    said: set = field(default_factory=set)
    # (folders the code put on its module path, absolute)
    folders: list = field(default_factory=list)
    ran: set = field(default_factory=set)
    roles: set = field(default_factory=set)


def python_code(rt, w, e, ctx, text, label, args, isolated):
    """The code's effects, added to w (executions, Unknowns) and e (its
    roles). args: sys.argv (Fields: -c or -, then what follows);
    isolated: the current folder isn't on its module path (-I, -P)."""
    try:
        tree = parse(rt, text)
    except zgram.ParseError as ex:
        unknown(rt, w, label + ": Python vetter can't read (" + first_line(str(ex)) + ")", e.span, ctx,
                "inline_code", [])
        return
    except ValueError as ex:
        why = str(ex)
        if why.startswith("unreadable: "):
            why = why[12:]
        unknown(rt, w, label + ": Python vetter can't read (" + why + ")", e.span, ctx, "inline_code", [])
        return
    module = Scope({}, None, "module")
    pw = W(Resolution(w.r.executions, w.r.unknowns, set(), w.r.downloads))
    argv = V("list")
    for a in args:
        argv.items.append(V("str", field_static(a)) if field_known(a) else V("data"))
    py = Py(w, pw, ctx, e, label, ctx.home, module, module, argv, isolated)
    module.vars["\x00cwd"] = V("str", e.cwd) if e.cwd is not None else V("data")
    for n in tree.find("name"):
        if not is_ascii(n.text):
            # (Python's names are NFKC's: ｃｍｄ is cmd)
            cant(rt, py, "a name not in ASCII (" + n.text + ")")
            return
    module.vars["__name__"] = V("str", "__main__")
    from_stdin = len(args) > 0 and field_known(args[0]) and field_static(args[0]) == "-"
    py.stdin = None if from_stdin else e.stdin
    py.fetched = not from_stdin and fetched(e)
    statements(rt, py, tree)
    if py.stopped:
        say(rt, py, label + ": more code than vetter follows", "inline_code")


def first_line(s):
    return s.partition("\n")[0]


def fetched(e):
    """Is what's piped into e a download (curl ... | tee | python)?"""
    st = e.stdin
    depth = 0
    while st is not None and st.producer is not None and depth < 16:
        name = exec_name(st.producer)
        if name is not None and (name in DOWNLOADERS or name in SOCKETS):
            return True
        st = st.producer.stdin
        depth += 1
    return False


def say(rt, py, reason, kind):
    """What vetter can't follow (once each)."""
    key = kind + ":" + reason
    if key in py.said:
        return
    py.said.add(key)
    unknown(rt, py.w, reason, py.e.span, sub_ctx(py), kind, [])


def cant(rt, py, what):
    say(rt, py, py.label + ": " + what + ", which vetter doesn't follow", "inline_code")


def kids(node):
    return [c for c in node.children if c.rule != "comment"]


def step(rt, py):
    py.steps += 1
    if py.steps > MAX_STEPS:
        py.stopped = True
    return not py.stopped


def statements(rt, py, node):
    """A file's, a block's statements, in order, until one ends the way."""
    for c in node.children:
        if py.dead or py.stopped:
            return
        r = c.rule
        if r == "statement" or r == "simple_stmts" or r == "block":
            statements(rt, py, c)
        elif r != "comment":
            statement(rt, py, c)


def statement(rt, py, node):
    if not step(rt, py):
        return
    r = node.rule
    if r == "expr_stmt":
        ev(rt, py, kids(node)[0])
    elif r == "assign":
        k = kids(node)
        v = ev(rt, py, k[len(k) - 1])
        for t in k[: len(k) - 1]:
            assign(rt, py, t, v)
    elif r == "aug_assign":
        aug_assign(rt, py, node)
    elif r == "ann_assign":
        k = kids(node)
        ev(rt, py, k[1])
        if len(k) > 2:
            assign(rt, py, k[0], ev(rt, py, k[2]))
    elif r == "import_stmt":
        for d in kids(node):
            import_as(rt, py, d)
    elif r == "from_stmt":
        from_import(rt, py, node)
    elif r == "if_stmt":
        if_stmt(rt, py, node)
    elif r == "for_stmt":
        for_stmt(rt, py, node)
    elif r == "while_stmt":
        while_stmt(rt, py, node)
    elif r == "try_stmt":
        try_stmt(rt, py, node)
    elif r == "with_stmt":
        with_stmt(rt, py, node)
    elif r == "funcdef":
        bind(py, kids(node)[0].text, define(rt, py, node))
    elif r == "classdef":
        bind(py, kids(node)[0].text, classdef(rt, py, node))
    elif r == "decorated":
        decorated(rt, py, node)
    elif r == "async_stmt":
        statement(rt, py, kids(node)[0])
    elif r == "return_stmt":
        k = kids(node)
        v = ev(rt, py, k[0]) if len(k) > 0 else V("none")
        if len(py.funcs) > 0:
            f = py.funcs[len(py.funcs) - 1]
            f.states.append(snapshot(py))
            f.values.append(v)
        py.dead = True
    elif r == "raise_stmt":
        for k in kids(node):
            ev(rt, py, k)
        py.dead = True
    elif r == "break_stmt" or r == "continue_stmt":
        if len(py.loops) > 0:
            f = py.loops[len(py.loops) - 1]
            if r == "break_stmt":
                f.states.append(snapshot(py))
            else:
                f.others.append(snapshot(py))
        py.dead = True
    elif r == "global_stmt" or r == "nonlocal_stmt":
        for k in kids(node):
            py.scope.declared[k.text] = "global" if r == "global_stmt" else "nonlocal"
    elif r == "del_stmt":
        delete(rt, py, kids(node)[0])
    elif r == "assert_stmt":
        k = kids(node)
        ev(rt, py, k[0])
        if len(k) > 1:
            dead = py.dead
            py.uncertain += 1
            ev(rt, py, k[1])
            py.uncertain -= 1
            py.dead = dead


# Names and states


def scope_for(py, name):
    """The scope an assignment to name binds in."""
    s = py.scope
    while s.kind == "comp" and s.parent is not None:
        s = s.parent
    d = s.declared[name] if name in s.declared else ""
    if d == "global":
        return py.module
    if d == "nonlocal":
        p = s.parent
        while p is not None and p.parent is not None:
            if name in p.vars:
                return p
            p = p.parent
    return s


def bind(py, name, v):
    s = scope_for(py, name) if py.scope.kind != "comp" else py.scope
    s.vars[name] = v
    for log in py.logs:
        log.append((s, name, v))


def bind_walrus(py, name, v):
    s = scope_for(py, name)
    if s is not py.scope:
        old = s.vars[name] if name in s.vars else None
        # (in a comprehension: as many times as it runs, maybe none)
        v = join(py, old, v) if old is not None else v
    s.vars[name] = v
    for log in py.logs:
        log.append((s, name, v))


def lookup(rt, py, name):
    s = py.scope
    first = True
    while s is not None:
        # (a class body's names aren't its methods')
        if (first or s.kind != "class") and name in s.vars:
            return s.vars[name]
        first = False
        s = s.parent
    if name in BUILTINS or name in OTHER_BUILTINS:
        return V("attr", "builtins." + name)
    if len(py.star) > 0:
        return attribute_of(rt, py, V("module", py.star[0]), name)
    # (not defined: a NameError)
    return V("opaque")


def chain(py):
    out = []
    s = py.scope
    while s is not None:
        out.append(s)
        s = s.parent
    return out


def snapshot(py):
    scopes = chain(py)
    return State(scopes, [{k: v for k, v in s.vars.items()} for s in scopes])


def restore(st):
    for k in range(len(st.scopes)):
        st.scopes[k].vars = {n: v for n, v in st.dicts[k].items()}


def merge(py, states):
    """The states joined (each from the same scopes, or the first's
    scopes the others have)."""
    first = states[0]
    dicts = []
    for k in range(len(first.scopes)):
        s = first.scopes[k]
        out = {n: v for n, v in first.dicts[k].items()}
        for st in states[1:]:
            d = None
            for j in range(len(st.scopes)):
                if st.scopes[j] is s:
                    d = st.dicts[j]
            if d is None:
                continue
            for n, v in d.items():
                out[n] = join(py, out[n], v) if n in out else v
        dicts.append(out)
    return State(first.scopes, dicts)


def same_state(a, b):
    if len(a.dicts) != len(b.dicts):
        return False
    for k in range(len(a.dicts)):
        if len(a.dicts[k]) != len(b.dicts[k]):
            return False
        for n, v in a.dicts[k].items():
            if n not in b.dicts[k] or b.dicts[k][n] is not v:
                return False
    return True


def with_log(py, st, log):
    """st, each value its names took in log joined in (an exception's
    handler: the body stopped anywhere)."""
    out = State(st.scopes, [{n: v for n, v in d.items()} for d in st.dicts])
    for s, n, v in log:
        for k in range(len(out.scopes)):
            if out.scopes[k] is s:
                d = out.dicts[k]
                d[n] = join(py, d[n], v) if n in d else v
    return out


# Values


def data():
    return V("data")


def opaque():
    return V("opaque")


def datalike(v, depth):
    """Plain data, all of it: no module, function, path, opaque."""
    if depth > 6:
        return False
    k = v.kind
    if k == "str" or k == "bytes" or k == "int" or k == "bool" or k == "none" or k == "data" or k == "file" \
            or k == "request" or k == "socket" or k == "etree":
        return True
    if k == "list" or k == "tuple" or k == "set":
        for x in v.items:
            if not datalike(x, depth + 1):
                return False
        return True
    if k == "dict":
        for x in v.items:
            if not datalike(x, depth + 1):
                return False
        for x in v.vals:
            if not datalike(x, depth + 1):
                return False
        return True
    if k == "seq":
        return datalike(v.obj, depth + 1)
    return False


def same_value(a, b):
    if a.kind != b.kind:
        return False
    k = a.kind
    if k == "str" or k == "bytes" or k == "module" or k == "attr" or k == "path":
        return a.text == b.text and a.glob == b.glob and a.text is not None
    if k == "int" or k == "bool":
        return a.num == b.num and a.num is not None
    if k == "none":
        return True
    if k == "fn":
        return a.fn is b.fn
    return False


def widen(py, v, depth):
    """A list, dict, set, seq vetter can no longer follow: data, or opaque
    if what it holds isn't all data; in place, as Python shares it (what
    it holds widened too: still shared)."""
    k = v.kind
    if k != "list" and k != "tuple" and k != "set" and k != "dict" and k != "seq":
        return
    plain = datalike(v, 0)
    if depth < 6:
        for x in v.items:
            widen(py, x, depth + 1)
        for x in v.vals:
            widen(py, x, depth + 1)
        if v.obj is not None:
            widen(py, v.obj, depth + 1)
    v.kind = "data" if plain else "opaque"
    v.items = []
    v.vals = []
    v.obj = None


def join(py, a, b):
    """A value that's a or b."""
    if a is b:
        return a
    if same_value(a, b):
        return a
    if a.kind in CONTAINERS:
        widen(py, a, 0)
    if b.kind in CONTAINERS:
        widen(py, b, 0)
    if a.kind == "data" and datalike(b, 0):
        return a
    if b.kind == "data" and datalike(a, 0):
        return b
    if datalike(a, 0) and datalike(b, 0):
        return data()
    if a.kind == "opaque":
        return a
    if b.kind == "opaque":
        return b
    return opaque()


def join_all(py, values):
    if len(values) == 0:
        return data()
    out = values[0]
    for v in values[1:]:
        out = join(py, out, v)
    return out


def store_into(py, target, v):
    """target (data, widened) given v: holding what isn't data, nothing
    vetter knows of it is plain any longer."""
    if target.kind == "seq":
        target.obj = join(py, target.obj, v) if target.obj is not None else v
        return
    if target.kind == "data" and not datalike(v, 0):
        target.kind = "opaque"
        py.leaked = True


def text_of(v):
    """A str's, bytes', path's text (None: not known) and whether it's a
    pattern."""
    if (v.kind == "str" or v.kind == "bytes" or v.kind == "path") and v.text is not None:
        return v.text, v.glob
    return None, False


def known_str(v):
    return v.kind == "str" and v.text is not None and not v.glob


def to_text(v):
    """str(v) when known (a pattern's: its pattern), else None."""
    if v.kind == "str" or v.kind == "path":
        return v.text
    if v.kind == "int":
        return str(v.num)
    if v.kind == "bool":
        return "True" if v.num == 1 else "False"
    if v.kind == "none":
        return "None"
    return None


def make_str(text, glob):
    if text is None or len(text) > MAX_TEXT:
        return data()
    return V("str", text, None, [], [], glob)


def seq_of(v):
    s = V("seq")
    s.obj = v
    return s


def elem(py, v):
    """What iterating v gives."""
    k = v.kind
    if k == "list" or k == "tuple" or k == "set" or k == "dict":
        return join_all(py, v.items)
    if k == "seq":
        return v.obj if v.obj is not None else data()
    if k == "str" or k == "bytes" or k == "file" or k == "int" or k == "bool" or k == "none":
        return data()
    if k == "data":
        return opaque() if py.leaked else data()
    if k == "attr" and v.text == "os.environ":
        return data()
    return opaque()


def norm_path(p):
    """pathlib's normal form: no //, no ., no trailing /."""
    if p == "":
        return "."
    lead = "/" if p.startswith("/") else ""
    if p.startswith("//") and not p.startswith("///"):
        lead = "//"
    parts = [x for x in p.split("/") if x != "" and x != "."]
    out = lead + "/".join(parts)
    return out if out != "" else "."


def make_path(text, glob):
    if text is None:
        return V("path")
    return V("path", norm_path(text), None, [], [], glob)


def path_join(a, b):
    """os.path.join's"""
    if b.startswith("/"):
        return b
    if a == "" or a.endswith("/"):
        return a + b
    return a + "/" + b


def joined_glob(a_glob, b_glob, b):
    """Joining onto a pattern: still one only if what's added doesn't
    climb out of it."""
    if not a_glob:
        return b_glob, True
    return True, ".." not in b.split("/")


# Effects


def sub_ctx(py):
    """The bash context what the code runs is resolved in: its folder,
    no shell functions, aliases or variables of the shell's."""
    cwd = cwd_now(py)
    c = py.ctx
    return Ctx(cwd, Variables({"HOME": py.home}), py.home, c.via + (py.label,), c.depth + 1, py.e.span, c.parsed, 0,
               c.source, {}, None)


def cwd_now(py):
    v = py.module.vars["\x00cwd"]
    return v.text if known_str(v) else None


def path_field(py, v, what):
    """A path argument as a Field: absolute where known; None: no file (an
    fd, None, "")."""
    if v.kind == "int" or v.kind == "none" or v.kind == "bool":
        return None
    t, g = text_of(v)
    if t is None:
        if v.kind == "file" and v.text is not None:
            t = v.text
            g = v.glob
        else:
            return Field([Dynamic(None, what)], False, False)
    if t == "":
        return None
    p = paths.join(cwd_now(py), t) if not paths.is_windows(t) else None
    if p is None:
        return Field([Dynamic(None, t)], False, False)
    return Field([p], g, False)


def effect(py, verb, v, what):
    f = path_field(py, v, what)
    if f is None:
        return
    key = verb + ":" + (field_static(f) if field_static(f) is not None else "?" + what)
    if key in py.roles:
        return
    py.roles.add(key)
    py.e.roles.append(Role(verb, f, py.label))
    if verb == "write" and py.fetched and field_static(f) is not None:
        # (what it writes may be what was downloaded: running it later,
        # running downloaded code)
        py.w.r.downloads.add(field_static(f))


def linked(py, target, link, symbolic, what):
    """A link made at `link` to `target`: the link written; and what's
    done through it later is done to the target, so the target read and
    written too (as ln's spec has it). A symbolic link's relative target is
    from the link's folder."""
    effect(py, "write", link, what)
    t, g = text_of(target)
    if t is not None and symbolic and not t.startswith("/"):
        lt, lg = text_of(link)
        if lt is None:
            t = None
        else:
            head = lt.rpartition("/")[0] if "/" in lt else "."
            t = path_join(head if head != "" else "/", t)
            g = g or lg
    to = make_str(t, g) if t is not None else data()
    effect(py, "read", to, what)
    effect(py, "write", to, what)


def env_fields(rt, py, given):
    """The environment what the code runs gets: the shell's, the code's
    changes, given (subprocess's env=: a dict, None: not given)."""
    out = {k: v for k, v in py.e.env.items()}
    for n, v in py.module.vars.items():
        if n.startswith("\x00env:"):
            name = n[5:]
            t = to_text(v) if v.kind == "str" and not v.glob else None
            out[name] = Field([t], False, False) if t is not None else Field([Dynamic(None, "?")], False, False)
    if "\x00envany" in py.module.vars:
        cant(rt, py, "an environment variable named only when it runs")
    if given is not None and not (given.kind == "attr" and given.text == "os.environ") and given.kind != "none":
        if given.kind != "dict":
            cant(rt, py, "an environment only running tells")
            return out
        for k in range(len(given.items)):
            key = given.items[k]
            v = given.vals[k]
            if not known_str(key):
                cant(rt, py, "an environment variable named only when it runs")
                continue
            t = to_text(v) if v.kind == "str" and not v.glob else None
            out[key.text] = Field([t], False, False) if t is not None else Field([Dynamic(None, "?")], False, False)
    return out


def child_stdin(py, a):
    """What a command the code runs reads on its stdin: input=TEXT, its
    text; stdin= anything else, what only running tells; not given,
    python's own (none left if python read its program there)."""
    if a is not None and "input" in a.kw:
        v = a.kw["input"]
        if (v.kind == "str" or v.kind == "bytes") and v.text is not None and not v.glob:
            return Stdin(v.text, None)
        if v.kind != "none":
            return Stdin(None, None)
    if a is not None and "stdin" in a.kw and a.kw["stdin"].kind != "none":
        return Stdin(None, None)
    return py.stdin


def run_words(rt, py, words, env, what, stdin):
    """A program and its arguments (V each)."""
    fields = []
    key = "" if stdin is None else ("<" + stdin.text if stdin.text is not None else "<?")
    for x in words:
        t, g = text_of(x)
        if t is None:
            if x.kind == "int":
                t = str(x.num)
            else:
                fields.append(Field([Dynamic(None, "?")], False, False))
                key += "\x00?"
                continue
        fields.append(Field([t], g, False))
        key += "\x00" + t
    if len(fields) == 0:
        return
    c = sub_ctx(py)
    key += "\x00" + (c.cwd if c.cwd is not None else "?")
    if key in py.ran:
        return
    py.ran.add(key)
    run(rt, py.pw, fields, env_fields(rt, py, env), [], c, py.e.span, stdin, c.via)


def run_line(rt, py, v, env, what, stdin):
    """A command line /bin/sh runs."""
    if not known_str(v):
        cant(rt, py, what + " with a command only running tells")
        return
    c = sub_ctx(py)
    key = "sh\x00" + v.text + "\x00" + (c.cwd if c.cwd is not None else "?")
    if stdin is not None:
        key += "\x00<" + (stdin.text if stdin.text is not None else "?")
    if key in py.ran:
        return
    py.ran.add(key)
    c.exported = env_fields(rt, py, env)
    c.stdin = stdin
    code(rt, py.pw, v.text, c, py.e.span, what, False, None)


def network(rt, py, url, sends, what):
    """A connection to url (a V: str known, else only running tells)."""
    if known_str(url):
        f = Field([url.text], False, False)
    else:
        f = Field([Dynamic(None, what)], False, False)
    py.e.roles.append(Role("code_url", f, py.label))
    if sends:
        py.e.roles.append(Role("code_send", f, py.label))


# Statements


def assign(rt, py, node, v):
    """node: targets, target, starred_target, name, primary."""
    r = node.rule
    if r == "targets":
        k = kids(node)
        if len(k) == 1 and not node.text.rstrip().endswith(","):
            assign(rt, py, k[0], v)
        else:
            unpack(rt, py, k, v)
    elif r == "target":
        k = kids(node)
        assign(rt, py, k[0], v)
    elif r == "starred_target":
        assign(rt, py, kids(node)[0], v)
    elif r == "name":
        bind(py, node.text, v)
    elif r == "primary":
        k = kids(node)
        if len(k) == 1 and k[0].rule == "name":
            bind(py, k[0].text, v)
            return
        obj = primary_upto(rt, py, node, len(k) - 1)
        last = k[len(k) - 1]
        if last.rule == "attribute":
            set_attribute(rt, py, obj, kids(last)[0].text, v)
        elif last.rule == "subscript":
            set_item(rt, py, obj, subscript_key(rt, py, last), v)
    else:
        # ((a, b) parenthesized: a target's children)
        for c in kids(node):
            assign(rt, py, c, v)


def unpack(rt, py, targets, v):
    star = -1
    for k in range(len(targets)):
        if targets[k].rule == "starred_target":
            star = k
    items = None
    if v.kind == "list" or v.kind == "tuple":
        items = v.items
    elif known_str(v):
        items = [V("str", c) for c in v.text]
    if items is not None and star < 0 and len(items) == len(targets):
        for k in range(len(targets)):
            assign(rt, py, targets[k], items[k])
        return
    if items is not None and star >= 0 and len(items) >= len(targets) - 1:
        after = len(targets) - star - 1
        for k in range(star):
            assign(rt, py, targets[k], items[k])
        middle = V("list")
        middle.items = items[star : len(items) - after]
        assign(rt, py, targets[star], middle)
        for k in range(after):
            assign(rt, py, targets[star + 1 + k], items[len(items) - after + k])
        return
    x = elem(py, v)
    for k in range(len(targets)):
        assign(rt, py, targets[k], seq_of(x) if k == star else x)


def aug_assign(rt, py, node):
    k = kids(node)
    target = k[0]
    op = k[1].text
    rhs = ev(rt, py, k[2])
    cur = ev(rt, py, target)
    if op == "+=" and cur.kind == "list":
        # (a list's += extends it: shared)
        extend(rt, py, cur, rhs)
        return
    if op == "|=" and cur.kind == "dict":
        update(rt, py, cur, rhs)
        return
    assign(rt, py, target, binop(rt, py, op[: len(op) - 1], cur, rhs))


def delete(rt, py, node):
    r = node.rule
    if r == "targets" or r == "target":
        for c in kids(node):
            delete(rt, py, c)
    elif r == "primary":
        k = kids(node)
        if len(k) == 1 and k[0].rule == "name":
            s = scope_for(py, k[0].text)
            if k[0].text in s.vars:
                s.vars.pop(k[0].text)
            return
        obj = primary_upto(rt, py, node, len(k) - 1)
        last = k[len(k) - 1]
        if last.rule == "subscript":
            # (the key evaluated: what it calls, followed)
            subscript_key(rt, py, last)
            if obj.kind == "attr" and obj.text == "os.environ":
                return
            if obj.kind == "list" or obj.kind == "dict" or obj.kind == "set":
                widen(py, obj, 0)
            elif obj.kind == "module" or obj.kind == "attr":
                cant(rt, py, "deleting from " + obj.text)
        elif obj.kind == "module" or obj.kind == "attr":
            cant(rt, py, "deleting " + obj.text + "." + kids(last)[0].text)
    elif r == "name":
        s = scope_for(py, node.text)
        if node.text in s.vars:
            s.vars.pop(node.text)


def set_attribute(rt, py, obj, name, v):
    k = obj.kind
    if k == "module" or k == "attr":
        # (os.system = ..., sys.path = ...: Python's own, changed)
        cant(rt, py, "changing " + obj.text + "." + name)
    elif k == "data" or k == "fn":
        if not datalike(v, 0):
            if k == "data":
                obj.kind = "opaque"
            py.leaked = True
    elif k in CONTAINERS or k == "str" or k == "path":
        if not datalike(v, 0):
            py.leaked = True


def set_item(rt, py, obj, key, v):
    k = obj.kind
    if k == "attr" and obj.text == "os.environ":
        set_env(rt, py, key, v)
        return
    if k == "module" or k == "attr":
        # (sys.modules[...], sys.path[0] = ...)
        cant(rt, py, "changing " + obj.text)
        return
    if py.uncertain > 0 and (k == "list" or k == "dict"):
        widen(py, obj, 0)
        k = obj.kind
    if k == "list":
        if key.kind == "int" and key.num is not None and in_range(key.num, len(obj.items)):
            i = key.num if key.num >= 0 else len(obj.items) + key.num
            obj.items[i] = v
        else:
            widen(py, obj, 0)
            store_into(py, obj, v)
    elif k == "dict":
        if dict_key(key):
            i = dict_index(obj, key)
            if i >= 0:
                obj.vals[i] = v
            else:
                obj.items.append(key)
                obj.vals.append(v)
        else:
            widen(py, obj, 0)
            store_into(py, obj, v)
    elif k == "data" or k == "seq":
        store_into(py, obj, v)


def set_env(rt, py, key, v):
    if known_str(key):
        name = "\x00env:" + key.text
        old = py.module.vars[name] if name in py.module.vars else None
        nv = join(py, old, v) if py.uncertain > 0 and old is not None else v
        py.module.vars[name] = nv
        for log in py.logs:
            log.append((py.module, name, nv))
    else:
        py.module.vars["\x00envany"] = V("bool", None, 1)


def in_range(i, n):
    """An index of n items (from the end too)."""
    return i >= 0 - n and i < n


def dict_key(k):
    return (k.kind == "str" and k.text is not None and not k.glob) or (k.kind == "int" and k.num is not None) \
        or k.kind == "none" or (k.kind == "bool" and k.num is not None)


def dict_index(d, key):
    for i in range(len(d.items)):
        x = d.items[i]
        if x.kind == key.kind and x.text == key.text and x.num == key.num:
            return i
    return -1


def if_stmt(rt, py, node):
    k = kids(node)
    branches = [k[1]]
    tests = [k[0]]
    has_else = False
    for c in k[2:]:
        if c.rule == "elif_part":
            ck = kids(c)
            tests.append(ck[0])
            branches.append(ck[1])
        elif c.rule == "else_part":
            tests.append(None)
            branches.append(kids(c)[0])
            has_else = True
    # (tests whose truth is known: the branch they take, for sure)
    first = 0
    while first < len(branches):
        if tests[first] is None:
            statements(rt, py, branches[first])
            return
        t = truth(ev(rt, py, tests[first]))
        if t == 1:
            statements(rt, py, branches[first])
            return
        if t < 0:
            break
        first += 1
    if first >= len(branches):
        return
    pre = snapshot(py)
    ends = []
    for i in range(first, len(branches)):
        restore(pre)
        py.dead = False
        py.uncertain += 1
        if tests[i] is not None and i > first:
            ev(rt, py, tests[i])
        statements(rt, py, branches[i])
        py.uncertain -= 1
        if not py.dead:
            ends.append(snapshot(py))
    if not has_else:
        ends.append(pre)
    finish(py, pre, ends)


def finish(py, pre, ends):
    """After ways that may each have ended: the ones that go on, joined."""
    if len(ends) == 0:
        restore(pre)
        py.dead = True
        return
    restore(merge(py, ends))
    py.dead = False


def known_items(v):
    """A known list's, tuple's, str's items, walked one by one."""
    if (v.kind == "list" or v.kind == "tuple") and len(v.items) <= MAX_ITEMS:
        return [x for x in v.items]
    if v.kind == "dict" and len(v.items) <= MAX_ITEMS:
        return [x for x in v.items]
    return None


def for_stmt(rt, py, node):
    k = kids(node)
    target = k[0]
    it = ev(rt, py, k[1])
    body = k[2]
    other = k[3] if len(k) > 3 else None
    items = known_items(it)
    if items is not None:
        unrolled(rt, py, target, items, body, other)
        return
    loop(rt, py, target, elem(py, it), None, body, other)


def unrolled(rt, py, target, items, body, other):
    frame = Frame([], [], [])
    py.loops.append(frame)
    for x in items:
        if py.dead:
            break
        assign(rt, py, target, x)
        statements(rt, py, body)
        ends = frame.others
        frame.others = []
        if not py.dead:
            ends.append(snapshot(py))
        if len(ends) == 0:
            py.dead = True
            break
        restore(merge(py, ends))
        py.dead = False
    py.loops.pop()
    exits = frame.states
    if not py.dead:
        if other is not None:
            statements(rt, py, kids(other)[0])
        if not py.dead:
            exits = exits + [snapshot(py)]
    if len(exits) == 0:
        py.dead = True
        return
    restore(merge(py, exits))
    py.dead = False


def while_stmt(rt, py, node):
    k = kids(node)
    ev(rt, py, k[0])
    loop(rt, py, None, None, k[0], k[1], k[2] if len(k) > 2 else None)


def loop(rt, py, target, x, test, body, other):
    """A loop whose number of times isn't known: its body walked until
    what it changes settles (each time maybe the last, maybe never)."""
    frame = Frame([], [], [])
    py.loops.append(frame)
    py.uncertain += 1
    cur = snapshot(py)
    for n in range(MAX_PASSES + 1):
        restore(cur)
        py.dead = False
        if test is not None and n > 0:
            ev(rt, py, test)
        if target is not None:
            assign(rt, py, target, x)
        statements(rt, py, body)
        ends = [cur] + frame.others
        frame.others = []
        if not py.dead:
            ends.append(snapshot(py))
        nxt = merge(py, ends)
        if same_state(nxt, cur):
            break
        if n == MAX_PASSES - 1:
            nxt = widened(py, nxt, cur)
        cur = nxt
    py.uncertain -= 1
    py.loops.pop()
    restore(cur)
    py.dead = False
    if other is not None:
        py.uncertain += 1
        statements(rt, py, kids(other)[0])
        py.uncertain -= 1
    finish(py, cur, [snapshot(py)] + frame.states if not py.dead else frame.states + [cur])


def widened(py, st, before):
    """A loop's values that still change: data or opaque."""
    out = State(st.scopes, [{n: v for n, v in d.items()} for d in st.dicts])
    for k in range(len(out.dicts)):
        d = out.dicts[k]
        for n, v in d.items():
            if k < len(before.dicts) and n in before.dicts[k] and before.dicts[k][n] is v:
                continue
            if v.kind == "data" or v.kind == "opaque":
                continue
            d[n] = data() if datalike(v, 0) else opaque()
    return out


def try_stmt(rt, py, node):
    k = kids(node)
    pre = snapshot(py)
    log = []
    py.logs.append(log)
    py.uncertain += 1
    statements(rt, py, k[0])
    py.uncertain -= 1
    py.logs.pop()
    for outer in py.logs:
        for x in log:
            outer.append(x)
    handler_in = with_log(py, pre, log)
    ends = []
    if not py.dead:
        for c in k[1:]:
            if c.rule == "else_part":
                statements(rt, py, kids(c)[0])
        if not py.dead:
            ends.append(snapshot(py))
    final = None
    for c in k[1:]:
        if c.rule == "except_part":
            restore(handler_in)
            py.dead = False
            py.uncertain += 1
            ck = kids(c)
            for x in ck:
                if x.rule == "expr":
                    ev(rt, py, x)
                elif x.rule == "name":
                    bind(py, x.text, data())
                elif x.rule == "block":
                    statements(rt, py, x)
            py.uncertain -= 1
            if not py.dead:
                ends.append(snapshot(py))
        elif c.rule == "finally_part":
            final = kids(c)[0]
    if final is not None:
        # (run whichever way: after each, and as an exception passes)
        restore(merge(py, ends + [handler_in]))
        py.dead = False
        statements(rt, py, final)
        if py.dead:
            return
        if len(ends) == 0:
            py.dead = True
            return
        restore(merge(py, [snapshot(py)]))
        return
    finish(py, pre, ends)


def with_stmt(rt, py, node):
    k = kids(node)
    suppressing = False
    for c in k:
        if c.rule == "with_item":
            ck = kids(c)
            cm = ev(rt, py, ck[0])
            entered = enter(rt, py, cm)
            if cm.kind != "file" and cm.kind != "socket" and cm.kind != "tempdir":
                # (a context manager may swallow the body's exception:
                # contextlib.suppress, one of the code's own)
                suppressing = True
            if len(ck) > 1:
                assign(rt, py, ck[1], entered)
    body = k[len(k) - 1]
    if not suppressing:
        statements(rt, py, body)
        return
    pre = snapshot(py)
    log = []
    py.logs.append(log)
    py.uncertain += 1
    statements(rt, py, body)
    py.uncertain -= 1
    py.logs.pop()
    for outer in py.logs:
        for x in log:
            outer.append(x)
    ends = [with_log(py, pre, log)]
    if not py.dead:
        ends.append(snapshot(py))
    finish(py, pre, ends)


def enter(rt, py, cm):
    """What `with cm as x` gives x."""
    k = cm.kind
    if k == "file" or k == "socket" or k == "suppress":
        return cm
    if k == "tempdir":
        return make_str(cm.text, True)
    if k == "opaque" or k == "class" or k == "module" or k == "attr":
        return opaque()
    if datalike(cm, 0):
        return opaque() if py.leaked else data()
    return opaque()


def define(rt, py, node):
    """def: its parameters' defaults and annotations evaluated now."""
    k = kids(node)
    params = None
    body = None
    for c in k[1:]:
        if c.rule == "params":
            params = c
        elif c.rule == "expr":
            ev(rt, py, c)
        elif c.rule == "block":
            body = c
    fn = Fn(k[0].text, params, body, False, py.scope if py.scope.kind != "class" else py.scope.parent,
            defaults(rt, py, params))
    v = V("fn")
    v.fn = fn
    return v


def defaults(rt, py, params):
    out = {}
    if params is None:
        return out
    for p in kids(params):
        pk = kids(p)
        name = pk[0].text if len(pk) > 0 and pk[0].rule == "name" else ""
        for x in pk[1:]:
            v = ev(rt, py, x)
            # (name: annotation = default; the default is the last)
            out[name] = v
        if p.rule == "param" and len(pk) == 2 and "=" not in p.text:
            out.pop(name)
    return out


def classdef(rt, py, node):
    k = kids(node)
    for c in k[1:]:
        if c.rule == "args":
            a = args_of(rt, py, c)
            if len(a.kw) > 0 or a.rest:
                cant(rt, py, "a class with a metaclass")
            for b in a.pos:
                if not (b.kind == "attr" and b.text.startswith("builtins.")):
                    cant(rt, py, "a class built on another")
                    break
        elif c.rule == "block":
            outer = py.scope
            py.scope = Scope({}, outer, "class")
            statements(rt, py, c)
            py.scope = outer
            py.dead = False
    return V("class", k[0].text)


def decorated(rt, py, node):
    k = kids(node)
    decs = [ev(rt, py, kids(d)[0]) for d in k if d.rule == "decorator"]
    target = k[len(k) - 1]
    if target.rule == "async_stmt":
        target = kids(target)[0]
    if target.rule == "classdef":
        v = classdef(rt, py, target)
    else:
        v = define(rt, py, target)
    i = len(decs) - 1
    while i >= 0:
        v = call(rt, py, decs[i], Args([v], {}, False), target.text)
        i -= 1
    bind(py, kids(target)[0].text, v)


# Imports


def import_as(rt, py, node):
    """import a.b.c [as x]"""
    k = kids(node)
    qual = dotted(k[0])
    v = import_module(rt, py, qual)
    if len(k) > 1:
        bind(py, k[1].text, v)
        return
    top = qual.partition(".")[0]
    bind(py, top, V("module", top) if v.kind == "module" else v)


def dotted(node):
    return ".".join([n.text for n in kids(node) if n.rule == "name"])


def import_module(rt, py, qual):
    top = qual.partition(".")[0]
    if top in IMPORT_EFFECTS:
        cant(rt, py, "importing " + top)
        return opaque()
    if top not in STDLIB:
        say(rt, py, py.label + ": imports " + qual + ", the project's own module or an installed one",
            "project_code")
        return V("module", qual) if top in FOLLOWED_PACKAGES else opaque()
    if not py.isolated and top not in PRELOADED and qual not in PRELOADED:
        # (the current folder comes first on its module path: a json.py
        # there is what `import json` runs)
        say(rt, py, py.label + ": imports " + top + ", which a " + top + ".py in the folder it runs in would be",
            "project_code")
    if top not in PRELOADED and qual not in PRELOADED:
        # (sys.path.insert(0, "src"): what that folder has comes first)
        for d in py.folders:
            key = "project_code:" + d + ":" + top
            if key not in py.said:
                py.said.add(key)
                unknown(rt, py.w, py.label + ": imports " + top + ", which " + d + " may have", py.e.span,
                        sub_ctx(py), "project_code", [Field([d], False, False)])
    return V("module", qual)


def from_import(rt, py, node):
    k = kids(node)
    rel = len(k) > 0 and k[0].rule == "dots"
    names = [c for c in k if c.rule == "dotted"]
    base = dotted(names[0]) if len(names) > 0 else ""
    if rel:
        say(rt, py, py.label + ": imports from the project's own package", "project_code")
        for c in k:
            if c.rule == "import_as":
                ck = kids(c)
                bind(py, ck[len(ck) - 1].text, opaque())
        return
    if base == "__future__":
        return
    m = import_module(rt, py, base)
    for c in k:
        if c.rule == "star_import":
            if m.kind == "module":
                py.star.append(base)
        elif c.rule == "import_as":
            ck = kids(c)
            name = ck[0].text
            v = attribute_of(rt, py, m, name) if m.kind == "module" else opaque()
            bind(py, ck[len(ck) - 1].text, v)


# Expressions


def ev(rt, py, node):
    """The node's value (its effects followed)."""
    r = node.rule
    k = kids(node)
    if len(k) == 1 and (r == "named_expr" or r == "expr" or r == "disjunction" or r == "conjunction"
                        or r == "inversion" or r == "comparison" or r == "bitor" or r == "bitxor"
                        or r == "bitand" or r == "shift" or r == "sum" or r == "term" or r == "factor"
                        or r == "power" or r == "star_exprs" or r == "rhs" or r == "slice"):
        if r == "star_exprs" and node.text.rstrip().endswith(","):
            return sequence(rt, py, k, "tuple")
        return ev(rt, py, k[0])
    if r == "name":
        return lookup(rt, py, node.text)
    if r == "primary":
        return primary_upto(rt, py, node, len(k))
    if r == "strings":
        return strings(rt, py, k)
    if r == "number":
        return number(node.text)
    if r == "constant":
        if node.text == "None":
            return V("none")
        return V("bool", None, 1 if node.text == "True" else 0)
    if r == "ellipsis":
        return data()
    if r == "star_exprs":
        return sequence(rt, py, k, "tuple")
    if r == "paren":
        return paren(rt, py, node, k)
    if r == "list_display":
        if len(k) == 2:
            return comprehension(rt, py, k[0], None, k[1], "list")
        if len(k) == 0:
            return V("list")
        return sequence(rt, py, kids(k[0]) if k[0].rule == "star_exprs" else k, "list")
    if r == "brace_display":
        return braces(rt, py, k)
    if r == "walrus":
        v = ev(rt, py, k[1])
        bind_walrus(py, k[0].text, v)
        return v
    if r == "ternary":
        t = truth(ev(rt, py, k[1]))
        if t >= 0:
            return ev(rt, py, k[0] if t == 1 else k[2])
        dead = py.dead
        py.uncertain += 1
        a = ev(rt, py, k[0])
        b = ev(rt, py, k[2])
        py.uncertain -= 1
        py.dead = dead
        return join(py, a, b)
    if r == "lambdef":
        params = k[0] if len(k) > 1 else None
        v = V("fn")
        v.fn = Fn("<lambda>", params, k[len(k) - 1], True, py.scope if py.scope.kind != "class" else py.scope.parent,
                  defaults(rt, py, params))
        return v
    if r == "yield_expr":
        v = ev(rt, py, k[0]) if len(k) > 0 else V("none")
        if len(py.funcs) > 0:
            py.funcs[len(py.funcs) - 1].others.append(v)
        return opaque()
    if r == "disjunction" or r == "conjunction":
        # (a value whose truth is known decides, as Python's does)
        out = ev(rt, py, k[0])
        i = 1
        while i < len(k):
            t = truth(out)
            if (r == "disjunction" and t == 1) or (r == "conjunction" and t == 0):
                return out
            if t < 0:
                break
            out = ev(rt, py, k[i])
            i += 1
        dead = py.dead
        py.uncertain += 1
        for c in k[i:]:
            out = join(py, out, ev(rt, py, c))
        py.uncertain -= 1
        py.dead = dead
        return out
    if r == "not_op":
        ev(rt, py, k[0])
        return data()
    if r == "comparison":
        vals = [ev(rt, py, c) for c in k if c.rule != "comp_op"]
        return compare(py, vals)
    if r == "bitor" or r == "bitxor" or r == "bitand":
        vals = [ev(rt, py, c) for c in k]
        op = "|" if r == "bitor" else ("^" if r == "bitxor" else "&")
        out = vals[0]
        for v in vals[1:]:
            out = binop(rt, py, op, out, v)
        return out
    if r == "shift" or r == "sum" or r == "term":
        out = ev(rt, py, k[0])
        i = 1
        while i + 1 < len(k):
            out = binop(rt, py, k[i].text.strip(), out, ev(rt, py, k[i + 1]))
            i += 2
        return out
    if r == "unary":
        v = ev(rt, py, k[1])
        if k[0].text == "-" and v.kind == "int" and v.num is not None:
            return make_int(0 - v.num)
        if k[0].text == "+" and v.kind == "int":
            return v
        return data() if datalike(v, 0) else opaque()
    if r == "power":
        a = ev(rt, py, k[0])
        b = ev(rt, py, k[1])
        return data() if datalike(a, 0) and datalike(b, 0) else opaque()
    if r == "await":
        v = ev(rt, py, k[0])
        return data() if datalike(v, 0) else opaque()
    if r == "starred":
        return ev(rt, py, k[0])
    if r == "target" or r == "targets":
        return ev(rt, py, k[0]) if len(k) == 1 else sequence(rt, py, k, "tuple")
    if r == "range_slice":
        for c in k:
            ev(rt, py, c)
        return data()
    if len(k) == 1:
        return ev(rt, py, k[0])
    for c in k:
        ev(rt, py, c)
    return opaque()


def truth(v):
    """bool(v) when known: 1, 0; -1 not known."""
    k = v.kind
    if (k == "str" or k == "bytes") and v.text is not None and not v.glob:
        return 1 if v.text != "" else 0
    if (k == "int" or k == "bool") and v.num is not None:
        return 1 if v.num != 0 else 0
    if k == "none":
        return 0
    if k == "list" or k == "tuple" or k == "set" or k == "dict":
        return 1 if len(v.items) > 0 else 0
    if k == "module" or k == "fn" or k == "path":
        return 1
    return -1


def compare(py, vals):
    for v in vals:
        if not datalike(v, 0) and v.kind != "module" and v.kind != "attr" and v.kind != "path" and v.kind != "fn":
            return opaque()
    return data()


def sequence(rt, py, nodes, kind):
    """a, *b, c: a tuple's (list's, set's) items."""
    out = V(kind)
    for n in nodes:
        if n.rule == "starred":
            v = ev(rt, py, kids(n)[0])
            items = known_items(v) if v.kind != "dict" else [x for x in v.items]
            if items is None:
                x = elem(py, v)
                widen(py, out, 0)
                if out.kind == "data" and not datalike(x, 0):
                    out.kind = "opaque"
                continue
            if out.kind == kind:
                for x in items:
                    out.items.append(x)
        else:
            v = ev(rt, py, n)
            if out.kind == kind:
                out.items.append(v)
            elif out.kind == "data" and not datalike(v, 0):
                out.kind = "opaque"
    return out


def paren(rt, py, node, k):
    if len(k) == 0:
        return V("tuple")
    if len(k) == 2:
        return comprehension(rt, py, k[0], None, k[1], "seq")
    c = k[0]
    if c.rule == "star_exprs":
        ck = kids(c)
        if len(ck) == 1 and not c.text.rstrip().endswith(",") and ck[0].rule != "starred":
            return ev(rt, py, ck[0])
        return sequence(rt, py, ck, "tuple")
    return ev(rt, py, c)


def braces(rt, py, k):
    if len(k) == 0:
        return V("dict")
    c = k[0]
    if c.rule == "dict_items":
        out = V("dict")
        for item in kids(c):
            ik = kids(item)
            if len(ik) == 1:
                # (**other)
                other = ev(rt, py, ik[0])
                if other.kind == "attr" and other.text == "os.environ":
                    continue
                if other.kind == "dict" and out.kind == "dict":
                    for j in range(len(other.items)):
                        put(py, out, other.items[j], other.vals[j])
                else:
                    widen(py, out, 0)
                    store_into(py, out, elem(py, other))
                continue
            key = ev(rt, py, ik[0])
            v = ev(rt, py, ik[1])
            if out.kind == "dict" and dict_key(key):
                put(py, out, key, v)
            else:
                widen(py, out, 0)
                store_into(py, out, v)
        return out
    if c.rule == "dict_comp":
        ck = kids(c)
        return comprehension(rt, py, ck[0], ck[1], ck[2], "dict")
    if c.rule == "set_comp":
        ck = kids(c)
        return comprehension(rt, py, ck[0], None, ck[1], "seq")
    return sequence(rt, py, kids(c) if c.rule == "star_exprs" else [c], "set")


def put(py, d, key, v):
    i = dict_index(d, key)
    if i >= 0:
        d.vals[i] = v
    else:
        d.items.append(key)
        d.vals.append(v)


def comprehension(rt, py, expr, value, comp, kind):
    """[expr for ...], {expr: value for ...}, (expr for ...): what each
    gives, its loops' names in a scope of its own."""
    outer = py.scope
    dead = py.dead
    py.scope = Scope({}, outer, "comp")
    py.uncertain += 1
    comp_for(rt, py, comp, outer)
    a = ev(rt, py, expr)
    b = ev(rt, py, value) if value is not None else None
    py.uncertain -= 1
    py.scope = outer
    py.dead = dead
    if kind == "dict":
        out = V("data")
        if not datalike(a, 0) or (b is not None and not datalike(b, 0)):
            out.kind = "opaque"
        return out
    if kind == "list":
        out = V("seq")
        out.obj = a
        return out
    return seq_of(a)


def comp_for(rt, py, node, outer):
    k = kids(node)
    targets = k[0]
    # (the first iterable is evaluated where the comprehension is)
    if py.scope.parent is outer and len(py.scope.vars) == 0:
        saved = py.scope
        py.scope = outer
        it = ev(rt, py, k[1])
        py.scope = saved
    else:
        it = ev(rt, py, k[1])
    assign(rt, py, targets, elem(py, it))
    for c in k[2:]:
        if c.rule == "comp_if":
            ev(rt, py, kids(c)[0])
        elif c.rule == "comp_for":
            comp_for(rt, py, c, outer)


def number(text):
    t = text.replace("_", "").lower()
    if t.endswith("j") or "." in t or ("e" in t and not t.startswith("0x")):
        return data()
    base = 10
    if t.startswith("0x"):
        base = 16
        t = t[2:]
    elif t.startswith("0o"):
        base = 8
        t = t[2:]
    elif t.startswith("0b"):
        base = 2
        t = t[2:]
    n = 0
    for c in t:
        d = "0123456789abcdef".find(c)
        if d < 0 or d >= base:
            return data()
        n = n * base + d
        if n > LIMIT:
            return data()
    return V("int", None, n)


# Strings


def strings(rt, py, nodes):
    """Adjacent strings: one."""
    text = ""
    known = True
    glob = False
    is_bytes = False
    for n in nodes:
        if n.rule == "plain":
            t, b = plain(n.text)
            is_bytes = b
        else:
            t, g = fstring(rt, py, n)
            glob = glob or g
        if t is None:
            known = False
        elif known:
            text += t
    if not known:
        return data()
    if is_bytes:
        return V("bytes", text)
    return make_str(text, glob)


def plain(s):
    """A string literal's value (None: not known: \\N{...}), and whether
    it's bytes."""
    i = 0
    raw = False
    is_bytes = False
    while i < len(s) and s[i] != "'" and s[i] != '"':
        c = s[i].lower()
        if c == "r":
            raw = True
        elif c == "b":
            is_bytes = True
        i += 1
    q = s[i]
    n = 3 if s[i : i + 3] == q * 3 else 1
    body = s[i + n : len(s) - n]
    if raw:
        return body, is_bytes
    return unescape(body, is_bytes), is_bytes


SIMPLE_ESCAPES = {"\\": "\\", "'": "'", '"': '"', "a": "\x07", "b": "\x08", "f": "\x0c", "n": "\n", "r": "\r",
                  "t": "\t", "v": "\x0b", "\n": ""}


def unescape(body, is_bytes):
    out = ""
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c != "\\" or i + 1 >= n:
            out += c
            i += 1
            continue
        d = body[i + 1]
        if d in SIMPLE_ESCAPES:
            out += SIMPLE_ESCAPES[d]
            i += 2
        elif d >= "0" and d <= "7":
            j = i + 1
            v = 0
            while j < n and j < i + 4 and body[j] >= "0" and body[j] <= "7":
                v = v * 8 + ord(body[j]) - 48
                j += 1
            out += chr(v)
            i = j
        elif d == "x" or (not is_bytes and (d == "u" or d == "U")):
            width = 2 if d == "x" else (4 if d == "u" else 8)
            h = body[i + 2 : i + 2 + width]
            v = hex_value(h)
            if len(h) != width or v < 0 or v > 0x10FFFF:
                return None
            out += chr(v)
            i += 2 + width
        elif d == "N" and not is_bytes:
            return None
        else:
            out += "\\" + d
            i += 2
    return out


def hex_value(h):
    v = 0
    for c in h.lower():
        d = "0123456789abcdef".find(c)
        if d < 0:
            return -1
        v = v * 16 + d
    return v


def fstring(rt, py, node):
    """An f-string's value (None: not known), and whether it's a pattern;
    its fields evaluated."""
    raw = False
    out = ""
    known = True
    glob = False
    for c in node.children:
        r = c.rule
        if r == "fprefix":
            raw = "r" in c.text.lower()
        elif r == "fbrace":
            out += c.text[0]
        elif r == "fescape":
            if raw:
                out += c.text
            else:
                t = unescape(c.text, False)
                if t is None:
                    known = False
                else:
                    out += t
        elif r == "field":
            ck = kids(c)
            v = ev(rt, py, ck[0])
            for x in ck[1:]:
                ev(rt, py, x)
            inner = c.text[1 : len(c.text) - 1].strip()
            t = to_text(v) if inner == ck[0].text.strip() else None
            if t is None:
                known = False
            else:
                out += t
                glob = glob or v.glob
        elif r.startswith("ftext"):
            out += c.text
    return (out if known else None), glob


# Primaries: names, attributes, calls, subscripts


def primary_upto(rt, py, node, n):
    """The value of the primary's first n parts (its atom, trailers)."""
    k = kids(node)
    v = ev(rt, py, k[0])
    i = 1
    while i < n:
        t = k[i]
        if t.rule == "attribute":
            name = kids(t)[0].text
            if i + 1 < n and k[i + 1].rule == "call" and v.kind != "module" and v.kind != "attr":
                a = args_of(rt, py, k[i + 1])
                v = method(rt, py, v, name, a, node.text)
                i += 2
                continue
            v = attribute_of(rt, py, v, name)
        elif t.rule == "call":
            v = call(rt, py, v, args_of(rt, py, t), node.text)
        elif t.rule == "subscript":
            v = item_of(rt, py, v, subscript_key(rt, py, t))
        i += 1
    return v


def subscript_key(rt, py, node):
    k = kids(node)
    sl = kids(k[0])
    if len(sl) == 1 and kids(sl[0])[0].rule != "range_slice" and not k[0].text.rstrip().endswith(","):
        return ev(rt, py, sl[0])
    for s in sl:
        ev(rt, py, s)
    return V("slice")


def args_of(rt, py, node):
    """A call's arguments."""
    a = Args([], {}, False)
    k = kids(node)
    if len(k) == 0:
        return a
    for c in kids(k[0]):
        r = c.rule
        if r == "keyword_arg":
            ck = kids(c)
            a.kw[ck[0].text] = ev(rt, py, ck[1])
        elif r == "kwsplat":
            v = ev(rt, py, kids(c)[0])
            if v.kind == "dict":
                for j in range(len(v.items)):
                    if known_str(v.items[j]):
                        a.kw[v.items[j].text] = v.vals[j]
            else:
                a.rest = True
                a.pos.append(v)
        elif r == "starred":
            v = ev(rt, py, kids(c)[0])
            items = known_items(v)
            if items is None:
                a.rest = True
                a.pos.append(elem(py, v))
            else:
                for x in items:
                    a.pos.append(x)
        elif r == "genexp_arg":
            ck = kids(c)
            a.pos.append(comprehension(rt, py, ck[0], None, ck[1], "seq"))
        else:
            a.pos.append(ev(rt, py, c))
    return a


def arg(a, i, name):
    """The argument at i, or by name; None: not given."""
    if name != "" and name in a.kw:
        return a.kw[name]
    if i >= 0 and i < len(a.pos) and not (a.rest and i >= len(a.pos) - 1):
        return a.pos[i]
    return None


def all_args(a):
    return a.pos + [v for v in a.kw.values()]


def attribute_of(rt, py, v, name):
    if name.startswith("__") and name.endswith("__") and name != "__name__" and name != "__doc__" \
            and name != "__version__" and name != "__file__":
        cant(rt, py, "reaching Python's internals (" + name + ")")
        return opaque()
    k = v.kind
    if k == "module" or k == "attr":
        qual = v.text + "." + name
        if qual in MODULES:
            return V("module", qual)
        if qual in CONSTS:
            # (Windows' differ: os.sep \\, os.name nt)
            if py.e.cwd is not None and paths.is_windows(py.e.cwd):
                return data()
            c = CONSTS[qual]
            return V("none") if c is None else V("str", c)
        if qual in DATA_ATTRS:
            return data()
        if qual in STREAMS:
            return V("file")
        if qual == "sys.argv":
            return py.argv
        return V("attr", qual)
    if k == "path":
        return path_property(py, v, name)
    if k == "tempdir" and name == "name":
        return make_str(v.text, True)
    if k == "file" and name == "buffer":
        # (sys.stdout.buffer: the same stream, as bytes)
        return V("file")
    if k == "fn" or k == "str" or k == "bytes" or k == "int" or k == "bool" or k == "none" or k == "file" \
            or k == "request" or k == "socket" or k == "etree":
        return data()
    if k in CONTAINERS:
        return data() if datalike(v, 0) else opaque()
    if k == "data":
        return opaque() if py.leaked else data()
    return opaque()


def item_of(rt, py, v, key):
    k = v.kind
    if k == "attr" and v.text == "os.environ":
        return env_value(py, key)
    if (k == "list" or k == "tuple") and key.kind == "int" and key.num is not None:
        n = len(v.items)
        if in_range(key.num, n):
            return v.items[key.num if key.num >= 0 else n + key.num]
        return data()
    if (k == "list" or k == "tuple") and key.kind == "slice":
        return seq_of(join_all(py, v.items))
    if k == "list" or k == "tuple":
        return join_all(py, v.items)
    if k == "dict":
        if dict_key(key):
            i = dict_index(v, key)
            if i >= 0:
                return v.vals[i]
            return data()
        return join_all(py, v.vals)
    if k == "seq":
        return v if key.kind == "slice" else (v.obj if v.obj is not None else data())
    if known_str(v) and key.kind == "int" and key.num is not None:
        n = len(v.text)
        if in_range(key.num, n):
            return V("str", v.text[key.num if key.num >= 0 else n + key.num])
        return data()
    if k == "str" or k == "bytes" or k == "data" or k == "file":
        return opaque() if k == "data" and py.leaked else data()
    if k == "path":
        return data()
    return opaque()


def env_value(py, key):
    if not known_str(key):
        return data()
    name = "\x00env:" + key.text
    if name in py.module.vars:
        return py.module.vars[name]
    if key.text in py.e.env and field_known(py.e.env[key.text]):
        return V("str", field_static(py.e.env[key.text]))
    if key.text == "HOME" and py.home is not None:
        return V("str", py.home)
    return data()


def home_of(py):
    """$HOME as the code sees it (~, Path.home()); None: not known."""
    v = env_value(py, V("str", "HOME"))
    return v.text if known_str(v) and v.text != "" else None


def path_property(py, v, name):
    if name not in PATH_PROPS:
        m = V("method", name)
        m.obj = v
        return m
    t = v.text
    if t is None:
        return V("path") if name == "parent" else data()
    if name == "parent":
        if v.glob and "*" in t.rpartition("/")[0]:
            return V("path", t.rpartition("/")[0], None, [], [], True)
        head = t.rpartition("/")[0] if "/" in t else "."
        return make_path(head if head != "" else "/", v.glob)
    # (Path("."): no name)
    base = t.rpartition("/")[2] if t != "." else ""
    if name == "name":
        return make_str(base, v.glob)
    if v.glob:
        return data()
    if name == "stem" or name == "suffix":
        dot = base.rfind(".")
        if dot <= 0:
            return V("str", base if name == "stem" else "")
        return V("str", base[:dot] if name == "stem" else base[dot:])
    return data()


# Calls


def call(rt, py, f, a, what):
    """f(a): what f is decides."""
    if not step(rt, py):
        return opaque()
    k = f.kind
    if k == "attr" or k == "module":
        return call_qual(rt, py, f.text, a, what)
    if k == "fn":
        return call_fn(rt, py, f.fn, a)
    if k == "method":
        return method(rt, py, f.obj, f.text, a, what)
    if k == "identity":
        return a.pos[0] if len(a.pos) > 0 else opaque()
    if k == "class":
        cant(rt, py, "creating a " + str(f.text) + " (a class of the code's own)")
        return opaque()
    cant(rt, py, "calling a value only running tells")
    return opaque()


def invoke_args(rt, py, a, skip_positional):
    """The callables given to a function vetter knows: maybe called,
    with what it would give them."""
    vals = [v for v in a.kw.values()] if skip_positional else all_args(a)
    for v in vals:
        if callable_value(v):
            maybe_call(rt, py, v, Args([data(), data()], {}, False), "")


def maybe_call(rt, py, f, a, what):
    """A call that may or may not happen (its exit doesn't end the code)."""
    dead = py.dead
    py.uncertain += 1
    v = call(rt, py, f, a, what)
    py.uncertain -= 1
    py.dead = dead
    return v


def callable_value(v):
    k = v.kind
    return k == "fn" or k == "method" or k == "class" or k == "opaque" \
        or (k == "attr" and v.text not in DATA_ATTRS and v.text != "os.environ")


def module_of(qual):
    """The longest module qual is in."""
    m = qual
    while "." in m:
        m = m.rpartition(".")[0]
        if m in MODULES:
            return m
    return ""


def pure_name(qual):
    """A function of a pure module: its own (re.sub), or a class's of it
    (datetime.datetime.now); not what it reached of another module's
    (shlex.os.system)."""
    m = module_of(qual)
    if m not in PURE_MODULES:
        return False
    rest = qual[len(m) + 1 :]
    last = rest.rpartition(".")[2]
    if last == "main" or last.startswith("_"):
        # (base64.main(), quopri.main(): sys.argv's files read; a private
        # name: anything)
        return False
    if "." not in rest:
        return True
    return m + "." + rest.partition(".")[0] in PURE_CLASSES and "." not in rest.partition(".")[2]


def pure_result(py, a):
    for v in all_args(a):
        # (defaultdict(list): what list() makes, data)
        if v.kind == "attr" and v.text.startswith("builtins.") and v.text[9:] in TYPES:
            continue
        if not datalike(v, 0):
            return opaque()
    return data()


def call_qual(rt, py, qual, a, what):
    """A function named by where it's from: builtins.open, os.remove."""
    special = call_special(rt, py, qual, a, what)
    if special is not None:
        return special
    kind = FUNCS[qual] if qual in FUNCS else ""
    if kind == "":
        if qual.startswith("builtins."):
            rest = qual[9:]
            if rest in BUILTINS:
                kind = "pure"
            elif rest.partition(".")[0] in TYPES and rest.partition(".")[2] in DATA_METHODS:
                kind = "pure"
        elif qual not in NOT_PURE and pure_name(qual):
            kind = "pure"
    if kind == "":
        if qual in MODULES:
            return data()
        cant(rt, py, qual + "()")
        return opaque()
    return call_kind(rt, py, qual, kind, a, what)


def call_kind(rt, py, qual, kind, a, what):
    short = qual.rpartition(".")[2]
    if kind != "pure" and kind != "invoke" and kind != "thread" and kind != "identity" and kind != "decorator":
        # (shutil.rmtree(p, onerror=f), copytree(copy_function=f): f
        # called with what it works on)
        invoke_args(rt, py, a, False)
    if kind == "pure":
        invoke_args(rt, py, a, qual in NEVER_CALLS)
        if qual in ITEMS_OF:
            first = arg(a, 0, "")
            if first is None:
                return V("list")
            # (sorted: in another order, its items no longer by place)
            if qual == "builtins.list" or qual == "builtins.tuple":
                items = known_items(first)
                if items is not None and first.kind != "dict":
                    out = V("list" if qual != "builtins.tuple" else "tuple")
                    out.items = items
                    return out
            x = elem(py, first)
            if qual == "builtins.min" or qual == "builtins.max" or qual == "builtins.next":
                return x if len(a.pos) == 1 else join(py, x, pure_result(py, a))
            return seq_of(x)
        if qual in NEVER_CALLS or qual == "builtins.int" or qual == "builtins.float" or qual == "builtins.input":
            return data()
        return pure_result(py, a)
    if kind == "read":
        p = arg(a, 0, "path")
        if p is None:
            p = arg(a, 0, "source")
        if p is not None:
            effect(py, "read", p, what)
        if qual == "xml.etree.ElementTree.parse":
            # (an ElementTree: its write() writes a path)
            return V("etree")
        return data()
    if kind == "list":
        p = arg(a, 0, "path")
        if p is None:
            p = arg(a, 0, "top")
        if qual == "glob.glob" or qual == "glob.iglob":
            p = arg(a, 0, "pathname")
            if p is None or "root_dir" in a.kw or "dir_fd" in a.kw:
                cant(rt, py, qual + " with arguments only running tells")
                return seq_of(data())
            t, g = text_of(p)
            effect(py, "read", make_str(t, True) if t is not None else p, what)
            return seq_of(make_str(t, True) if t is not None else data())
        if p is None:
            p = V("str", ".")
        effect(py, "read", p, what)
        t, g = text_of(p)
        if qual == "os.walk" or qual == "os.fwalk":
            under = make_str(path_join(t, "*") if t is not None else None, True)
            names = seq_of(make_str("*", True))
            item = V("tuple")
            item.items = [under, names, names]
            if qual == "os.fwalk":
                item.items.append(data())
            return seq_of(item)
        if qual == "os.scandir":
            return seq_of(data())
        return seq_of(make_str("*", True))
    if kind == "write" or kind == "delete":
        p = arg(a, 0, "path")
        if p is None:
            p = arg(a, 0, "name")
        if p is None:
            cant(rt, py, qual + " with arguments only running tells")
            return data()
        effect(py, kind, p, what)
        if qual == "os.removedirs" or qual == "os.makedirs":
            t, g = text_of(p)
            if t is not None and qual == "os.removedirs":
                # (and each empty folder above it)
                effect(py, "delete", make_str(t.rpartition("/")[0] + "/*", True) if "/" in t else p, what)
        return data()
    if kind == "copy" or kind == "move" or kind == "link":
        src = arg(a, 0, "src")
        dst = arg(a, 1, "dst")
        if src is None or dst is None:
            cant(rt, py, qual + " with arguments only running tells")
            return data()
        if kind == "link":
            linked(py, src, dst, qual == "os.symlink", what)
            return V("none")
        effect(py, "read", src, what)
        if kind == "move":
            effect(py, "delete", src, what)
        effect(py, "write", dst, what)
        return dst if dst.kind == "str" else data()
    if kind == "open":
        return open_file(rt, py, qual, a, what)
    if kind == "shell":
        # (os.popen(cmd, "w"): what the code writes, cmd's stdin)
        m = arg(a, 1, "mode")
        writing = qual == "os.popen" and m is not None and not (known_str(m) and "w" not in m.text)
        run_line(rt, py, arg(a, 0, "cmd") if arg(a, 0, "cmd") is not None else data(), None, qual,
                 Stdin(None, None) if writing else py.stdin)
        return data()
    if kind == "argv":
        return subprocess(rt, py, qual, a, what)
    if kind == "exec" or kind == "execl":
        return exec_call(rt, py, qual, kind, a, what)
    if kind == "chdir":
        p = arg(a, 0, "path")
        t, g = text_of(p) if p is not None else (None, False)
        cwd = paths.join(cwd_now(py), t) if t is not None and not g else None
        nv = V("str", cwd) if cwd is not None else data()
        py.module.vars["\x00cwd"] = nv
        for log in py.logs:
            log.append((py.module, "\x00cwd", nv))
        return V("none")
    if kind == "url":
        url = arg(a, 0, "url")
        if url is not None and url.kind == "request":
            network(rt, py, url.obj if url.obj is not None else data(), url.num == 1, what)
            return data()
        # (urlopen(url, data); requests.get(url, params): data only by name)
        sends = "data" in a.kw or "json" in a.kw or "files" in a.kw or "content" in a.kw
        if qual.startswith("urllib.") and len(a.pos) > 1:
            sends = True
        if qual.startswith("urllib.request.urlretrieve"):
            sends = arg(a, 2, "data") is not None
            dst = arg(a, 1, "filename")
            if dst is not None:
                effect(py, "write", dst, what)
                f = path_field(py, dst, what)
                if f is not None and field_static(f) is not None:
                    # (running it later: running what was downloaded)
                    py.w.r.downloads.add(field_static(f))
            else:
                effect(py, "write", temp_place(py), what)
        network(rt, py, url if url is not None else data(), sends, what)
        return data()
    if kind == "send":
        url = arg(a, 1 if short == "request" else 0, "url")
        network(rt, py, url if url is not None else data(), True, what)
        return data()
    if kind == "request":
        r = V("request")
        r.obj = arg(a, 0, "url")
        m = arg(a, 3, "method")
        sends = arg(a, 1, "data") is not None or (m is not None and not (known_str(m) and (m.text == "GET"
                                                                                       or m.text == "HEAD")))
        r.num = 1 if sends else 0
        return r
    if kind == "exit":
        for v in all_args(a):
            if not datalike(v, 0):
                cant(rt, py, "exiting with a value only running tells")
        py.dead = True
        return V("none")
    if kind == "temp":
        return temp_file(rt, py, qual, a, what)
    if kind == "invoke":
        f = arg(a, 0, "func")
        if f is not None:
            maybe_call(rt, py, f, Args(a.pos[1:], {n: v for n, v in a.kw.items()}, a.rest), what)
            return f
        return data()
    if kind == "thread":
        f = arg(a, -1, "target")
        if f is not None:
            given = arg(a, -1, "args")
            items = known_items(given) if given is not None else []
            maybe_call(rt, py, f, Args(items if items is not None else [data()], {}, items is None), what)
        return data()
    if kind == "socket":
        return V("socket")
    if kind == "connect":
        socket_method(rt, py, V("socket"), "connect", a, what)
        return V("socket")
    if kind == "host":
        host = arg(a, 0, "host")
        network(rt, py, make_str("tcp://" + host.text, False) if host is not None and known_str(host) else data(),
                True, what)
        return data()
    if kind == "stream":
        # (io.StringIO(), io.BytesIO(): a stream in memory, read and written)
        return V("file")
    if kind == "suppress":
        return V("suppress")
    if kind == "identity":
        return a.pos[0] if len(a.pos) > 0 else opaque()
    if kind == "decorator":
        # (@lru_cache(maxsize=None), @wraps(f): what they decorate, back)
        if len(a.pos) == 1 and a.pos[0].kind == "fn" and len(a.kw) == 0 and qual != "functools.wraps":
            return a.pos[0]
        return V("identity")
    cant(rt, py, qual + "()")
    return opaque()


def temp_place(py):
    """A new file in the temporary folder."""
    d = "/tmp"
    if "TMPDIR" in py.e.env and field_known(py.e.env["TMPDIR"]) and field_static(py.e.env["TMPDIR"]) != "":
        d = field_static(py.e.env["TMPDIR"])
    return make_str(path_join(d, "*"), True)


def temp_file(rt, py, qual, a, what):
    where = arg(a, -1, "dir")
    if where is not None and where.kind != "none":
        t, g = text_of(where)
        place = make_str(path_join(t, "*") if t is not None else None, True)
    else:
        place = temp_place(py)
    effect(py, "write", place, what)
    if qual == "tempfile.mkstemp":
        out = V("tuple")
        out.items = [data(), place]
        return out
    if qual == "tempfile.mkdtemp":
        return place
    if qual == "tempfile.TemporaryDirectory":
        effect(py, "delete", place, what)
        return V("tempdir", place.text if place.kind == "str" else None)
    f = V("file", place.text if place.kind == "str" else None, None, [], [], True)
    return f


def open_file(rt, py, qual, a, what):
    p = arg(a, 0, "file")
    if p is None:
        p = arg(a, 0, "filename")
    m = arg(a, 1, "mode")
    if "opener" in a.kw:
        cant(rt, py, "open with an opener")
    if p is None:
        cant(rt, py, qual + " with arguments only running tells")
        return V("file")
    mode = "rb" if qual != "builtins.open" and qual != "io.open" and qual != "codecs.open" else "r"
    if m is not None:
        mode = m.text if known_str(m) else "w+"
    if "r" in mode and "+" not in mode:
        effect(py, "read", p, what)
    else:
        if "+" in mode or "a" in mode:
            effect(py, "read", p, what)
        effect(py, "write", p, what)
    t, g = text_of(p)
    return V("file", t, None, [], [], g)


def subprocess(rt, py, qual, a, what):
    cmd = arg(a, 0, "args")
    if qual == "pty.spawn":
        cmd = arg(a, 0, "argv")
    if cmd is None:
        cant(rt, py, qual + " with arguments only running tells")
        return data()
    shell = arg(a, -1, "shell")
    env = arg(a, -1, "env")
    if arg(a, -1, "executable") is not None:
        cant(rt, py, qual + " with executable=")
    if "preexec_fn" in a.kw:
        maybe_call(rt, py, a.kw["preexec_fn"], Args([], {}, False), what)
    saved = py.module.vars["\x00cwd"]
    where = arg(a, -1, "cwd")
    if where is not None and where.kind != "none":
        t, g = text_of(where)
        c = paths.join(cwd_now(py), t) if t is not None and not g else None
        py.module.vars["\x00cwd"] = V("str", c) if c is not None else data()
    on = shell is not None and not (shell.kind == "bool" and shell.num == 0) and shell.kind != "none"
    if on and not (shell.kind == "bool" and shell.num == 1):
        cant(rt, py, qual + " with shell= only running tells")
        on = False
    # (pty.spawn: its callbacks feed the program)
    stdin = child_stdin(py, a) if qual != "pty.spawn" else Stdin(None, None)
    if on:
        line = cmd
        if cmd.kind == "list" or cmd.kind == "tuple":
            line = cmd.items[0] if len(cmd.items) > 0 else data()
        run_line(rt, py, line, env, short_name(qual), stdin)
    elif cmd.kind == "list" or cmd.kind == "tuple":
        run_words(rt, py, cmd.items, env, short_name(qual), stdin)
    elif cmd.kind == "str" or cmd.kind == "path" or cmd.kind == "bytes":
        run_words(rt, py, [cmd], env, short_name(qual), stdin)
    else:
        cant(rt, py, short_name(qual) + " with a command only running tells")
    py.module.vars["\x00cwd"] = saved
    return data()


def short_name(qual):
    return qual.rpartition(".")[2] if qual.startswith("builtins.") else qual


def exec_call(rt, py, qual, kind, a, what):
    """os.execv(path, args), os.execl(path, arg0, ...), os.spawnv(mode,
    path, args), asyncio.create_subprocess_exec(prog, *args)."""
    words = a.pos
    if a.rest:
        cant(rt, py, qual + " with arguments only running tells")
        return data()
    if ".spawn" in qual:
        words = words[1:]
    if "file_actions" in a.kw or "setsid" in a.kw:
        cant(rt, py, qual + " with file actions")
    if qual == "asyncio.create_subprocess_exec":
        run_words(rt, py, words, arg(a, -1, "env"), qual, child_stdin(py, a))
        return data()
    if len(words) < 1:
        cant(rt, py, qual + " with arguments only running tells")
        return data()
    prog = words[0]
    env = None
    if qual.endswith("e") or "posix_spawn" in qual:
        env = arg(a, -1, "env")
        if env is None and len(words) > 2:
            env = words[len(words) - 1]
            words = words[: len(words) - 1]
    if kind == "exec":
        given = words[1] if len(words) > 1 else None
        if given is None or (given.kind != "list" and given.kind != "tuple"):
            cant(rt, py, qual + " with arguments only running tells")
            return data()
        rest = given.items[1:]
    else:
        rest = words[2:]
    run_words(rt, py, [prog] + rest, env, qual, py.stdin)
    if qual.startswith("os.exec"):
        py.dead = True
    return data()


def call_special(rt, py, qual, a, what):
    """The functions whose value vetter computes, or that act on its own
    records (os.environ, sys.argv)."""
    if py.fetched and (qual == "builtins.exec" or qual == "builtins.eval" or qual == "builtins.compile"):
        # (curl ... | python -c 'exec(sys.stdin.read())')
        say(rt, py, py.label + ": " + qual[9:] + " of what may be the download piped in", "downloaded_code")
        return opaque()
    if qual == "sys.path.insert" or qual == "sys.path.append":
        d = arg(a, 1 if qual == "sys.path.insert" else 0, "")
        t, g = text_of(d) if d is not None else (None, False)
        p = paths.join(cwd_now(py), t) if t is not None and not g else None
        if p is None:
            cant(rt, py, "a module path only running tells")
        else:
            py.folders.append(p)
        return V("none")
    if qual == "builtins.getattr":
        obj = arg(a, 0, "")
        name = arg(a, 1, "")
        if obj is None or name is None or not known_str(name):
            cant(rt, py, "getattr of a name only running tells")
            return opaque()
        v = attribute_of(rt, py, obj, name.text)
        if len(a.pos) > 2:
            return join(py, v, a.pos[2])
        return v
    if qual == "builtins.type" and len(a.pos) > 1:
        cant(rt, py, "type() making a class")
        return opaque()
    if qual == "builtins.str":
        v = arg(a, 0, "object")
        if v is None:
            return V("str", "")
        if len(a.pos) > 1 or len(a.kw) > 0:
            return data()
        t = to_text(v)
        if t is not None:
            return make_str(t, v.glob)
        return data()
    if qual == "builtins.len" or qual == "builtins.range" or qual == "builtins.repr":
        return data()
    if qual == "os.getcwd":
        return V("str", cwd_now(py)) if cwd_now(py) is not None else data()
    if qual == "os.getenv" or qual == "os.environ.get":
        key = arg(a, 0, "key")
        v = env_value(py, key) if key is not None else data()
        if len(a.pos) > 1:
            return join(py, v, a.pos[1])
        return v
    if qual == "os.putenv":
        k = arg(a, 0, "")
        v = arg(a, 1, "")
        if k is not None and v is not None:
            set_env(rt, py, k, v)
        return V("none")
    if qual == "os.unsetenv" or qual == "os.environ.pop" or qual == "os.environ.keys" \
            or qual == "os.environ.items" or qual == "os.environ.values" or qual == "os.environ.__contains__":
        return data()
    if qual == "os.environ.copy" or (qual == "builtins.dict" and len(a.pos) == 1 and a.pos[0].kind == "attr"
                                     and a.pos[0].text == "os.environ"):
        return V("dict")
    if qual == "builtins.dict" and len(a.pos) == 0 and not a.rest:
        out = V("dict")
        for n, v in a.kw.items():
            put(py, out, V("str", n), v)
        return out
    if qual == "os.environ.setdefault":
        k = arg(a, 0, "")
        v = arg(a, 1, "")
        if k is not None and v is not None:
            set_env(rt, py, k, join(py, env_value(py, k), v))
        return data()
    if qual == "os.environ.update":
        d = arg(a, 0, "")
        if d is not None and d.kind == "dict":
            for j in range(len(d.items)):
                set_env(rt, py, d.items[j], d.vals[j])
        elif d is not None:
            py.module.vars["\x00envany"] = V("bool", None, 1)
        for n, v in a.kw.items():
            set_env(rt, py, V("str", n), v)
        return V("none")
    if qual == "os.environ.clear":
        return V("none")
    if qual == "os.kill" or qual == "os.killpg":
        pid = arg(a, 0, "")
        run_words(rt, py, [V("str", "kill"), pid if pid is not None else data()], None, qual, None)
        return V("none")
    if qual == "os.path.join":
        if a.rest or len(a.pos) == 0:
            return pure_result(py, a)
        out = ""
        glob = False
        for v in a.pos:
            t, g = text_of(v)
            if t is None:
                return data() if datalike(v, 0) or v.kind == "path" else opaque()
            glob, ok = joined_glob(glob, g, t)
            if not ok:
                return data()
            out = path_join(out, t) if out != "" else t
        return make_str(out, glob)
    if qual == "os.path.expanduser":
        v = arg(a, 0, "path")
        t, g = text_of(v) if v is not None else (None, False)
        home = home_of(py)
        if t is None:
            return data()
        if t == "~" or t.startswith("~/"):
            return make_str(home + t[1:], g) if home is not None else data()
        return make_str(t, g) if not t.startswith("~") else data()
    if qual == "os.path.abspath" or qual == "os.path.realpath" or qual == "os.path.normpath":
        v = arg(a, 0, "path")
        t, g = text_of(v) if v is not None else (None, False)
        if t is None:
            return data()
        if qual == "os.path.normpath":
            return make_str(paths.normpath(t), g) if not g else data()
        p = paths.join(cwd_now(py), t)
        return make_str(p, g) if p is not None and not g else data()
    if qual == "os.path.dirname" or qual == "os.path.basename":
        v = arg(a, 0, "p")
        t, g = text_of(v) if v is not None else (None, False)
        if t is None:
            return data()
        # (posixpath's: the head keeps its slashes if it's only slashes)
        i = t.rfind("/") + 1
        head = t[:i]
        if qual == "os.path.basename":
            return make_str(t[i:], g)
        if head != "" and head != "/" * len(head):
            head = head.rstrip("/")
        if g and "*" not in head and "?" not in head and "[" not in head:
            g = False
        return make_str(head, g)
    if qual == "os.fspath":
        v = arg(a, 0, "path")
        t, g = text_of(v) if v is not None else (None, False)
        return make_str(t, g) if t is not None else data()
    if qual.startswith("pathlib.") and qual.rpartition(".")[2] in ("Path", "PurePath", "PosixPath",
                                                                     "PurePosixPath"):
        if len(a.pos) == 0:
            return make_path(".", False)
        out = ""
        glob = False
        for v in a.pos:
            t, g = text_of(v)
            if t is None:
                return V("path") if datalike(v, 0) or v.kind == "path" else opaque()
            glob, ok = joined_glob(glob, g, t)
            if not ok:
                return V("path")
            out = path_join(out, t) if out != "" else t
        return make_path(out, glob)
    if qual.startswith("pathlib.") and (qual.endswith(".home") or qual.endswith(".cwd")):
        if qual.endswith(".home"):
            return make_path(home_of(py), False) if home_of(py) is not None else V("path")
        return make_path(cwd_now(py), False) if cwd_now(py) is not None else V("path")
    if qual == "shlex.quote":
        v = arg(a, 0, "s")
        if known_str(v):
            return V("str", shell_quote(v.text))
        return data()
    if qual == "shlex.join":
        v = arg(a, 0, "split_command")
        items = known_items(v) if v is not None else None
        if items is None:
            return data()
        words = []
        for x in items:
            if not known_str(x):
                return data()
            words.append(shell_quote(x.text))
        return make_str(" ".join(words), False)
    if qual == "shlex.split":
        v = arg(a, 0, "s")
        if not known_str(v) or len(a.pos) > 1 or len(a.kw) > 0:
            return seq_of(data())
        words = plain_words(v.text)
        if words is None:
            return seq_of(data())
        out = V("list")
        out.items = [V("str", w) for w in words]
        return out
    return None


SAFE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@%+=:,./-_"


def shell_quote(s):
    """shlex.quote"""
    if s == "":
        return "''"
    for c in s:
        if c not in SAFE_CHARS:
            return "'" + s.replace("'", "'\"'\"'") + "'"
    return s


def plain_words(s):
    """shlex.split of text with no quotes, escapes or comments: its words;
    None: other text."""
    if not plain_text(s):
        return None
    for c in s:
        if c == "'" or c == '"' or c == "\\" or c == "#":
            return None
    return [w for w in s.replace("\t", " ").replace("\n", " ").replace("\r", " ").split(" ") if w != ""]


def call_fn(rt, py, fn, a):
    """A function of the code's own, called: its body followed with what
    it's given. Called again inside itself: followed with anything given,
    again until what it changes settles; no deeper."""
    count = 0
    for f in py.stack:
        if f is fn:
            count += 1
    if count >= 2:
        return opaque()
    if py.depth >= MAX_CALLS:
        cant(rt, py, "calls nested this deep")
        return opaque()
    if count == 0:
        return run_fn(rt, py, fn, a)
    anything = Args([opaque() for x in a.pos], {n: opaque() for n in a.kw}, True)
    cur = snapshot(py)
    for n in range(MAX_PASSES):
        run_fn(rt, py, fn, anything)
        nxt = merge(py, [cur, snapshot(py)])
        if same_state(nxt, cur):
            break
        restore(nxt)
        cur = nxt
    return opaque()


def run_fn(rt, py, fn, a):
    scope = Scope({}, fn.scope, "function")
    bind_params(rt, py, fn, a, scope)
    frame = Frame([], [], [])
    saved_scope = py.scope
    saved_dead = py.dead
    saved_loops = py.loops
    py.scope = scope
    py.loops = []
    py.funcs.append(frame)
    py.stack.append(fn)
    py.depth += 1
    py.dead = False
    if fn.lam:
        result = ev(rt, py, fn.body)
    else:
        statements(rt, py, fn.body)
        ends = frame.states + ([snapshot(py)] if not py.dead else [])
        values = frame.values + ([V("none")] if not py.dead else [])
        if len(ends) > 0:
            restore(merge(py, ends))
        result = join_all(py, values) if len(values) > 0 else opaque()
        if len(frame.others) > 0:
            # (a generator: what it yields)
            result = seq_of(join_all(py, frame.others))
    py.depth -= 1
    py.stack.pop()
    py.funcs.pop()
    py.loops = saved_loops
    py.scope = saved_scope
    py.dead = saved_dead
    return result


def bind_params(rt, py, fn, a, scope):
    params = [] if fn.params is None else kids(fn.params)
    i = 0
    used = set()
    star = False
    for p in params:
        t = p.text.strip()
        pk = kids(p)
        name = pk[0].text if len(pk) > 0 and pk[0].rule == "name" else ""
        if t.startswith("**"):
            d = V("dict")
            for n, v in a.kw.items():
                if n not in used:
                    d.items.append(V("str", n))
                    d.vals.append(v)
            if a.rest:
                widen(py, d, 0)
            scope.vars[name] = d
        elif t.startswith("*"):
            star = True
            if name != "":
                rest = V("tuple")
                rest.items = a.pos[i:]
                if a.rest:
                    widen(py, rest, 0)
                scope.vars[name] = rest
                i = len(a.pos)
        elif t == "/":
            continue
        else:
            if not star and i < len(a.pos) and not (a.rest and i >= len(a.pos) - 1):
                scope.vars[name] = a.pos[i]
                i += 1
            elif name in a.kw:
                scope.vars[name] = a.kw[name]
                used.add(name)
            elif a.rest:
                scope.vars[name] = join_all(py, a.pos[i:] + [opaque()])
            elif name in fn.defaults:
                scope.vars[name] = fn.defaults[name]
            else:
                scope.vars[name] = opaque()


# Methods


def method(rt, py, recv, name, a, what):
    """recv.name(a)"""
    if not step(rt, py):
        return opaque()
    if name.startswith("__") and name.endswith("__"):
        cant(rt, py, "reaching Python's internals (" + name + ")")
        return opaque()
    k = recv.kind
    if k == "module" or k == "attr":
        return call_qual(rt, py, recv.text + "." + name, a, what)
    if k == "str":
        return str_method(rt, py, recv, name, a)
    if k == "bytes":
        if name == "decode" and recv.text is not None and len(a.pos) == 0 and is_ascii(recv.text):
            return V("str", recv.text)
        return data_method(rt, py, recv, name, a)
    if k == "list" or k == "dict" or k == "set" or k == "tuple" or k == "seq":
        return container_method(rt, py, recv, name, a)
    if k == "path":
        return path_method(rt, py, recv, name, a, what)
    if k == "socket":
        return socket_method(rt, py, recv, name, a, what)
    if k == "etree":
        # (an ElementTree: write(path) writes it, parse(path) reads it;
        # its other methods are its elements')
        if name == "write" or name == "parse":
            p = arg(a, 0, "file" if name == "write" else "source")
            if p is None:
                cant(rt, py, "ElementTree." + name + " with arguments only running tells")
            elif p.kind != "file":
                effect(py, "write" if name == "write" else "read", p, what)
            return V("none") if name == "write" else data()
        return data_method(rt, py, V("data"), name, a)
    if k == "tempdir":
        if name == "cleanup":
            effect(py, "delete", make_str(recv.text, True), what)
            return V("none")
        return data_method(rt, py, recv, name, a)
    if k == "file" or k == "data" or k == "int" or k == "bool" or k == "none" or k == "request":
        return data_method(rt, py, recv, name, a)
    if k == "fn" or k == "method":
        cant(rt, py, "a function's " + name + "()")
        return opaque()
    cant(rt, py, "calling ." + name + "() on a value only running tells")
    return opaque()


def is_ascii(s):
    for c in s:
        if ord(c) > 127:
            return False
    return True


def data_method(rt, py, recv, name, a):
    # (a stream's read and write: an open file's, stdin's and stdout's, a
    # StringIO's, what they touch decided when they were opened; anything
    # else's .read(), .write() may open a path of its own (a ConfigParser's,
    # an ElementTree's): not followed)
    known = name in DATA_METHODS or (recv.kind == "file" and name in STREAM_METHODS)
    if not known or (py.leaked and recv.kind == "data"):
        cant(rt, py, "calling ." + name + "() on a value only running tells")
        return opaque()
    invoke_args(rt, py, a, False)
    if recv.kind == "data":
        return data() if datalike(recv, 0) and not py.leaked else opaque()
    return pure_result(py, a)


def str_method(rt, py, s, name, a):
    if s.text is None or s.glob:
        if name == "replace" or name == "split" or name == "rsplit" or name == "strip" or name == "lstrip" \
                or name == "rstrip":
            # (a name found by listing: changed, any name)
            return data() if name != "split" and name != "rsplit" else seq_of(data())
        return data_method(rt, py, V("data"), name, a)
    t = s.text
    a0 = arg(a, 0, "")
    a1 = arg(a, 1, "")
    if name == "format" or name == "format_map":
        invoke_args(rt, py, a, False)
        return format_str(t, a) if name == "format" else data()
    if name == "join":
        items = known_items(a0) if a0 is not None else None
        if items is None:
            return data() if a0 is not None and datalike(elem(py, a0), 0) else opaque()
        parts = []
        glob = False
        for x in items:
            if x.kind != "str" or x.text is None:
                return data()
            glob = glob or x.glob
            parts.append(x.text)
        return make_str(t.join(parts), glob)
    if len(a.kw) > 0 or a.rest:
        return data_method(rt, py, V("data"), name, a)
    if not plain_text(t) and name != "replace" and name != "removeprefix" and name != "removesuffix" \
            and name != "encode":
        # (Unicode's spaces, line breaks and cases: Python's tables)
        return data_method(rt, py, V("data"), name, a)
    if name == "strip" or name == "lstrip" or name == "rstrip":
        if a0 is not None and not known_str(a0) and a0.kind != "none":
            return data()
        chars = a0.text if a0 is not None and a0.kind == "str" else None
        if name == "strip":
            return V("str", t.strip(chars) if chars is not None else t.strip())
        if name == "lstrip":
            return V("str", t.lstrip(chars) if chars is not None else t.lstrip())
        return V("str", t.rstrip(chars) if chars is not None else t.rstrip())
    if name == "lower":
        return V("str", t.lower())
    if name == "upper":
        return V("str", t.upper())
    if name == "replace":
        if known_str(a0) and known_str(a1) and len(a.pos) == 2 and a0.text != "":
            return make_str(t.replace(a0.text, a1.text), False)
        return data()
    if name == "removeprefix" and known_str(a0):
        return V("str", t[len(a0.text) :] if t.startswith(a0.text) else t)
    if name == "removesuffix" and known_str(a0):
        return V("str", t[: len(t) - len(a0.text)] if t.endswith(a0.text) and a0.text != "" else t)
    if name == "split" and len(a.pos) <= 1:
        if a0 is None or a0.kind == "none":
            parts = [x for x in t.replace("\t", " ").replace("\n", " ").replace("\r", " ").split(" ") if x != ""]
        elif known_str(a0) and a0.text != "":
            parts = t.split(a0.text)
        else:
            return seq_of(data())
        out = V("list")
        out.items = [V("str", x) for x in parts]
        return out
    if name == "splitlines" and len(a.pos) == 0:
        out = V("list")
        out.items = [V("str", x) for x in t.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        if t.endswith("\n") and len(out.items) > 0:
            out.items = out.items[: len(out.items) - 1]
        return out
    if name == "encode" and is_ascii(t):
        return V("bytes", t)
    return data_method(rt, py, V("data"), name, a)


def plain_text(t):
    """Printable ASCII, tabs, line breaks: what strip, split, lower work on
    the same everywhere."""
    for c in t:
        o = ord(c)
        if (o < 0x20 and c != "\t" and c != "\n" and c != "\r") or o > 0x7E:
            return False
    return True


def format_str(t, a):
    """str.format with {} {0} {name} fields only; else data."""
    out = ""
    i = 0
    auto = 0
    n = len(t)
    while i < n:
        c = t[i]
        if c == "{" and t[i + 1 : i + 2] == "{":
            out += "{"
            i += 2
            continue
        if c == "}" and t[i + 1 : i + 2] == "}":
            out += "}"
            i += 2
            continue
        if c == "{":
            j = t.find("}", i)
            if j < 0:
                return data()
            key = t[i + 1 : j]
            if key == "":
                v = arg(a, auto, "")
                auto += 1
            elif key.isdigit():
                v = arg(a, int(key), "")
            elif key in a.kw:
                v = a.kw[key]
            else:
                return data()
            s = to_text(v) if v is not None else None
            if s is None or (v.glob):
                return data()
            out += s
            i = j + 1
            continue
        out += c
        i += 1
    return make_str(out, False)


def container_method(rt, py, c, name, a):
    k = c.kind
    a0 = arg(a, 0, "")
    if name == "append" or name == "add" or name == "appendleft":
        if a0 is None:
            return V("none")
        if k == "seq":
            store_into(py, c, a0)
        elif py.uncertain > 0 or k == "set":
            widen(py, c, 0)
            store_into(py, c, a0)
        elif k == "list":
            c.items.append(a0)
        return V("none")
    if name == "extend" or name == "update" and k != "dict":
        if a0 is not None:
            extend(rt, py, c, a0)
        return V("none")
    if name == "update" and k == "dict":
        if a0 is not None:
            update(rt, py, c, a0)
        for n, v in a.kw.items():
            if py.uncertain > 0:
                widen(py, c, 0)
                store_into(py, c, v)
            elif c.kind == "dict":
                put(py, c, V("str", n), v)
        return V("none")
    if name == "get" and k == "dict":
        if a0 is not None and dict_key(a0):
            i = dict_index(c, a0)
            if i >= 0:
                return c.vals[i]
            a1 = arg(a, 1, "")
            return a1 if a1 is not None else V("none")
        return join_all(py, c.vals + [V("none")])
    if name == "keys" and k == "dict":
        out = V("list")
        out.items = [x for x in c.items]
        return out
    if name == "values" and k == "dict":
        out = V("list")
        out.items = [x for x in c.vals]
        return out
    if name == "items" and k == "dict":
        out = V("list")
        for i in range(len(c.items)):
            t = V("tuple")
            t.items = [c.items[i], c.vals[i]]
            out.items.append(t)
        return out
    if name == "copy" and k == "list":
        out = V("list")
        out.items = [x for x in c.items]
        return out
    if name == "setdefault" and k == "dict" and a0 is not None and dict_key(a0) and py.uncertain == 0:
        i = dict_index(c, a0)
        if i >= 0:
            return c.vals[i]
        v = arg(a, 1, "")
        put(py, c, a0, v if v is not None else V("none"))
        return v if v is not None else V("none")
    if name == "pop" and k == "list" and len(a.pos) == 0 and py.uncertain == 0 and len(c.items) > 0:
        x = c.items[len(c.items) - 1]
        c.items = c.items[: len(c.items) - 1]
        return x
    if name == "index" or name == "count" or name == "get" or name == "copy" or name == "most_common" \
            or name == "union" or name == "intersection" or name == "difference" or name == "issubset" \
            or name == "issuperset" or name == "isdisjoint" or name == "symmetric_difference":
        x = join_all(py, c.items + c.vals) if k != "seq" else (c.obj if c.obj is not None else data())
        if name == "get" or name == "copy":
            return x if name == "get" else seq_of(x)
        return data()
    if name in DATA_METHODS:
        # (insert, pop, remove, sort, reverse, clear...: changed, no longer
        # known item by item)
        invoke_args(rt, py, a, False)
        x = elem(py, c) if k != "dict" else join_all(py, c.vals)
        widen(py, c, 0)
        if a0 is not None and (name == "insert" or name == "setdefault"):
            store_into(py, c, arg(a, 1, "") if arg(a, 1, "") is not None else a0)
        if name == "pop" or name == "popleft" or name == "popitem":
            return x
        return data() if datalike(x, 0) else opaque()
    cant(rt, py, "calling ." + name + "() on a value only running tells")
    return opaque()


def extend(rt, py, c, other):
    items = known_items(other)
    if c.kind == "list" and py.uncertain == 0 and items is not None and other.kind != "dict":
        for x in items:
            c.items.append(x)
        return
    widen(py, c, 0)
    store_into(py, c, elem(py, other))


def update(rt, py, c, other):
    if c.kind == "dict" and other.kind == "dict" and py.uncertain == 0:
        for j in range(len(other.items)):
            put(py, c, other.items[j], other.vals[j])
        return
    widen(py, c, 0)
    if other.kind == "dict":
        for v in other.vals:
            store_into(py, c, v)
    else:
        store_into(py, c, elem(py, other))


def binop(rt, py, op, a, b):
    ka = a.kind
    kb = b.kind
    if op == "+":
        if ka == "str" and kb == "str":
            if a.text is None or b.text is None:
                return data()
            if a.glob and ".." in b.text:
                return data()
            return make_str(a.text + b.text, a.glob or b.glob)
        if ka == "bytes" and kb == "bytes" and a.text is not None and b.text is not None:
            return V("bytes", a.text + b.text)
        if (ka == "list" and kb == "list") or (ka == "tuple" and kb == "tuple"):
            out = V(ka)
            out.items = a.items + b.items
            return out
    if op == "/" and ka == "path":
        t, g = text_of(b)
        if a.text is None or t is None:
            return V("path") if datalike(b, 0) or kb == "path" else opaque()
        glob, ok = joined_glob(a.glob, g, t)
        if not ok:
            return V("path")
        return make_path(path_join(a.text, t), glob)
    if op == "/" and kb == "path" and ka == "str" and a.text is not None and b.text is not None and not a.glob:
        return make_path(path_join(a.text, b.text), b.glob)
    if op == "%" and ka == "str" and a.text is not None and not a.glob:
        return percent(a.text, b)
    if ka == "int" and kb == "int" and a.num is not None and b.num is not None:
        x = a.num
        y = b.num
        if op == "+":
            return make_int(x + y)
        if op == "-":
            return make_int(x - y)
        if op == "*" and in_range(x, 1000000) and in_range(y, 1000000):
            return make_int(x * y)
        if op == "//" and y != 0:
            return make_int(x // y)
        if op == "%" and y != 0:
            return make_int(x % y)
    if op == "*" and ka == "str" and kb == "int" and a.text is not None and b.num is not None \
            and 0 <= b.num and len(a.text) * b.num <= MAX_TEXT and not a.glob:
        return V("str", a.text * b.num)
    if datalike(a, 0) and datalike(b, 0):
        return data()
    if ka == "path" or kb == "path":
        return data() if (datalike(a, 0) or ka == "path") and (datalike(b, 0) or kb == "path") else opaque()
    return opaque()


LIMIT = 1 << 52


def make_int(n):
    """An int vetter keeps (Python's are any size: larger, data)."""
    if n > LIMIT or n < 0 - LIMIT:
        return data()
    return V("int", None, n)


def percent(t, b):
    """printf-style: %s %d %% only."""
    items = b.items if b.kind == "tuple" else [b]
    out = ""
    i = 0
    j = 0
    n = len(t)
    while i < n:
        c = t[i]
        if c != "%":
            out += c
            i += 1
            continue
        d = t[i + 1 : i + 2]
        if d == "%":
            out += "%"
        elif (d == "s" or d == "d") and j < len(items):
            s = to_text(items[j])
            if s is None or items[j].glob or (d == "d" and items[j].kind != "int"):
                return data()
            out += s
            j += 1
        else:
            return data()
        i += 2
    if j != len(items):
        return data()
    return make_str(out, False)


def path_method(rt, py, p, name, a, what):
    kind = PATH_METHODS[name] if name in PATH_METHODS else ""
    a0 = arg(a, 0, "")
    if kind == "path":
        if name == "joinpath":
            out = p
            for x in a.pos:
                out = binop(rt, py, "/", out, x)
            return out
        if p.text is None:
            return V("path")
        if name == "expanduser":
            if p.text == "~" or p.text.startswith("~/"):
                home = home_of(py)
                return make_path(home + p.text[1:], p.glob) if home is not None else V("path")
            return p
        if name == "absolute" or name == "resolve":
            j = paths.join(cwd_now(py), p.text) if not p.glob else None
            return make_path(j, False) if j is not None else V("path")
        if name == "with_name" or name == "with_suffix" or name == "with_stem":
            if not known_str(a0) or p.glob:
                return V("path")
            head = p.text.rpartition("/")[0]
            base = p.text.rpartition("/")[2]
            dot = base.rfind(".")
            stem = base[:dot] if dot > 0 else base
            suffix = base[dot:] if dot > 0 else ""
            if name == "with_name":
                base = a0.text
            elif name == "with_suffix":
                base = stem + a0.text
            else:
                base = a0.text + suffix
            return make_path(path_join(head, base) if head != "" else base, False)
        if name == "parent":
            return path_property(py, p, "parent")
        return V("path")
    if kind == "data":
        return data()
    if kind == "read":
        effect(py, "read", p, what)
        return data()
    if kind == "list":
        effect(py, "read", p, what)
        if name == "walk":
            item = V("tuple")
            item.items = [make_path(path_join(p.text, "*") if p.text is not None else None, True),
                          seq_of(make_str("*", True)), seq_of(make_str("*", True))]
            return seq_of(item)
        pattern = "*"
        if (name == "glob" or name == "rglob") and a0 is not None:
            pattern = a0.text if known_str(a0) else "*"
        if name == "rglob":
            pattern = "**/" + pattern
        if ".." in pattern.split("/"):
            return seq_of(V("path"))
        return seq_of(make_path(path_join(p.text, pattern) if p.text is not None else None, True))
    if kind == "write" or kind == "delete":
        effect(py, kind, p, what)
        return V("none")
    if kind == "link":
        # (p.symlink_to(target): p a link to target)
        if a0 is None:
            cant(rt, py, "Path." + name + " with arguments only running tells")
            return V("none")
        linked(py, a0, p, name == "symlink_to", what)
        return V("none")
    if kind == "move" or kind == "copy":
        if a0 is None:
            cant(rt, py, "Path." + name + " with arguments only running tells")
            return V("path")
        effect(py, "read", p, what)
        if kind == "move":
            effect(py, "delete", p, what)
        dst = a0
        if name == "move_into" or name == "copy_into":
            t, g = text_of(a0)
            base = p.text.rpartition("/")[2] if p.text is not None else None
            dst = make_path(path_join(t, base) if t is not None and base is not None else None, g or p.glob)
        effect(py, "write", dst, what)
        return dst if dst.kind == "path" else make_path(text_of(dst)[0], text_of(dst)[1])
    if kind == "open":
        return open_file(rt, py, "builtins.open", Args([p] + a.pos, {n: v for n, v in a.kw.items()}, a.rest), what)
    cant(rt, py, "Path." + name + "()")
    return opaque()


def socket_method(rt, py, s, name, a, what):
    if name == "connect" or name == "connect_ex":
        addr = arg(a, 0, "")
        host = addr.items[0] if addr is not None and addr.kind == "tuple" and len(addr.items) > 0 else None
        url = make_str("tcp://" + host.text, False) if host is not None and known_str(host) else data()
        network(rt, py, url, True, what)
        return data()
    if name == "bind" or name == "listen" or name == "accept":
        say(rt, py, py.label + ": listens for connections", "inline_code")
        return data()
    return data_method(rt, py, s, name, a)
