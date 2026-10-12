"""What a bash command runs: every program, builtin and function call,
with its arguments as far as they're known, its environment, its
redirections, its standard input and its working directory; wrappers
unwrapped, `bash -c`, `eval` and here-documents fed to a shell read again.

The walker is a record (W: the Resolution) and module functions, given rt
first; the context a record (Ctx). The specs' roles are vetter/specs'; the
Windows shells started from bash are windows_shell()'s.

    r = resolve(rt, "cd src && rm -rf build", "/home/u/p", "/home/u")
"""

from dataclasses import dataclass, field

import zgram

from ... import paths
from ...specs import Role, apply_specs
from . import arith
from .expand import (
    NUMBER,
    UNKNOWN,
    Dynamic,
    Number,
    Field,
    Variables,
    changed_since,
    expand_assignment,
    expand_heredoc,
    expand_word,
    field_known,
    field_static,
    field_text,
    var_copy,
    var_forget,
    var_get,
)
from .syntax import parse

MAX_DEPTH = 8
MAX_ITEMS = 16      # a for loop's items walked one by one

SHELLS = {"bash", "sh", "dash", "zsh", "ksh", "mksh", "ash", "busybox"}

# Builtins that only change the shell's state (no program runs)
BUILTINS = {
    "cd", "pushd", "popd", "dirs", "export", "declare", "typeset", "local", "readonly", "unset",
    "set", "shift", "read", "mapfile", "readarray", "printf", "echo", "true", "false", ":", "test",
    "[", "type", "hash", "alias", "unalias", "shopt", "umask", "ulimit", "wait", "jobs", "fg", "bg",
    "disown", "kill", "trap", "return", "exit", "break", "continue", "let", "getopts", "times",
    "enable", "help", "history", "fc", "caller", "complete", "compgen", "compopt", "suspend", "logout",
}

# Builtins that run code: theirs is read where it's known (trap's action,
# mapfile's -C callback: builtin_effects)
CODE_BUILTINS = {"eval", "source", ".", "exec", "command", "builtin", "coproc"}

# Variables bash expands again where it uses them (expanded_later)
EXPANDED_LATER = {"PS4"}

WRAPPERS = {"env", "command", "builtin", "exec", "sudo", "doas", "nice", "nohup", "setsid", "stdbuf", "time",
            "timeout", "chroot", "ionice", "taskset", "chrt", "flock", "unbuffer", "xargs", "find", "watch", "su",
            "ssh"}

SUBSTITUTIONS = {"cmdsub": "$(...)", "procsub": "<(...)", "backtick": "`...`"}


@dataclass
class Redirect:
    """A redirection: fd (None: the default), operator, target (a Field; a
    here-document: None, and its Doc)."""

    fd: object
    op: str
    target: object
    heredoc: object


def writes(r):
    return r.op == ">" or r.op == ">>" or r.op == ">|" or r.op == "&>" or r.op == "&>>" or r.op == "<>"


def reads(r):
    return r.op == "<" or r.op == "<>"


@dataclass
class Stdin:
    """What a command reads on its standard input when vetter knows it: the
    text, or None with the producer when it's another command's output."""

    text: object
    producer: object


@dataclass
class Execution:
    """One program, builtin or function call."""

    argv: list
    env: dict
    redirects: list
    cwd: object
    span: tuple
    via: tuple
    stdin: object
    kind: str
    roles: list
    # (each word as written, and what it became: for traces)
    words: list
    # (a PowerShell cmdlet vetter knows; one that only reads)
    cmdlet: bool
    readonly: bool
    # (what it reads another command's output through, not on its stdin:
    # bash <(curl ...), the curl)
    fed: object = None


def execution(argv, env, redirects, cwd, span, via, stdin, kind):
    return Execution(argv, env, redirects, cwd, span, via, stdin, kind, [], [], False, False)


def exec_name(e):
    """The command's name if known (a path's last part), else None."""
    if len(e.argv) == 0 or not field_known(e.argv[0]):
        return None
    return paths.program_name(field_static(e.argv[0]))


@dataclass
class Unknown:
    """Something that runs but that vetter can't see (resolve.py's kinds)."""

    reason: str
    span: tuple
    via: tuple
    kind: str
    paths: list
    cwd: object


@dataclass
class Resolution:
    executions: list
    unknowns: list
    functions: set
    downloads: set


@dataclass
class Ctx:
    cwd: object
    vars: object
    home: object
    via: tuple
    depth: int
    span: object
    parsed: object
    # (the nodes walked: of `source`'s tree, which starts at `base` in the
    # command's text)
    base: int
    source: str
    # (exported variables: every command after gets them)
    exported: dict
    # (stdin when nothing else says: inside >(...), the outer command's output)
    stdin: object


@dataclass
class W:
    """The walker: what it found so far. (rt is every function's first
    parameter: rt.parse() is compiled as zrun's when rt is known as rt.)"""

    r: object
    # (each process substitution, by where it starts in the text: <(cmd)'s
    # last execution, the one whose output is read; >(cmd)'s Stdin, its
    # producer the command it's given to, set when that one runs)
    procs: dict = field(default_factory=dict)


def copy(ctx):
    return Ctx(ctx.cwd, var_copy(ctx.vars), ctx.home, ctx.via, ctx.depth, ctx.span, ctx.parsed, ctx.base,
               ctx.source, {k: v for k, v in ctx.exported.items()}, ctx.stdin)


def merge_uncertain(ctx, branch):
    """What the branch changed might or might not have happened (an export
    that might have: kept, the stricter)."""
    if branch.cwd != ctx.cwd:
        ctx.cwd = None
    for n in changed_since(branch.vars, ctx.vars):
        # (a number either way, a counter: still a number)
        old = ctx.vars.values[n] if n in ctx.vars.values else None
        number = isinstance(old, Number) or (isinstance(old, str) and arith.is_number_text(old)) or old is None
        ctx.vars.values[n] = NUMBER if number and isinstance(branch.vars.values[n], Number) else UNKNOWN
    for k, v in branch.vars.attrs.items():
        ctx.vars.attrs[k] = v
    for k, v in branch.exported.items():
        ctx.exported[k] = v


def offset(text, node):
    """Where a node of text's tree starts in it, in characters."""
    b = node.start
    if len(text.encode()) == len(text):
        return b
    n = 0
    i = 0
    while n < b:
        c = ord(text[i])
        n += 1 if c < 0x80 else (2 if c < 0x800 else (3 if c < 0x10000 else 4))
        i += 1
    return i


def node_span(ctx, node):
    if ctx.span is not None:
        return ctx.span
    s = ctx.base + offset(ctx.source, node)
    return (s, s + len(node.text))


def resolve(rt, command, cwd, home):
    """The command's executions (a Resolution). cwd: where it runs (None:
    unknown); home: the user's home (for ~). zgram.ParseError when it isn't
    bash, ValueError("unreadable: ...") when its reading isn't certain."""
    parsed = parse(rt, command)
    r = Resolution([], [], set(), set())
    ctx = Ctx(cwd, Variables({"HOME": home}), home, (), 0, None, parsed, 0, parsed.source, {}, None)
    seq(rt, W(r), parsed.tree, ctx)
    return r


def children(node, rule):
    out = []
    for k in node.children:
        if k.rule == rule:
            out.append(k)
    return out


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------


def seq(rt, w,node, ctx):
    """A list: its and-or lists in order; a backgrounded one runs in a
    subshell."""
    kids = node.children
    for i in range(len(kids)):
        k = kids[i]
        if k.rule != "and_or":
            if k.rule != "sep" and k.rule != "op_semi" and k.rule != "op_amp":
                walk(rt, w,k, ctx)
            continue
        background = (i + 1 < len(kids) and kids[i + 1].rule == "sep"
                      and kids[i + 1].children[0].rule == "op_amp")
        if background:
            and_or(rt, w,k, copy(ctx))
        else:
            and_or(rt, w,k, ctx)


def and_or(rt, w,node, ctx):
    kids = children(node, "pipeline")
    if len(kids) == 0:
        return
    pipeline(rt, w,kids[0], ctx)
    if len(kids) > 1:
        # (after && or ||: maybe)
        branch = copy(ctx)
        for p in kids[1:]:
            pipeline(rt, w,p, branch)
        merge_uncertain(ctx, branch)


def pipeline(rt, w,node, ctx):
    cmds = children(node, "command")
    if len(cmds) == 1:
        command(rt, w,cmds[0], ctx, None)
        return
    # (each in a subshell; each reads the one before)
    producer = None
    for c in cmds:
        first = len(w.r.executions)
        command(rt, w,c, copy(ctx), Stdin(None, producer) if producer is not None else None)
        n = len(w.r.executions)
        producer = w.r.executions[n - 1] if n > first else None


def command(rt, w,node, ctx, stdin):
    first = node.children[0]
    rule = first.rule
    if rule == "simple":
        simple(rt, w,first, ctx, stdin)
    elif rule == "function_def":
        function_def(rt, w,first, ctx)
    elif rule == "compound":
        redirects = []
        for r in node.children:
            if r.rule == "redirect":
                redirects.append(redirect(rt, w,r, ctx))
        compound(rt, w,first.children[0], ctx)
        for r in redirects:
            if writes(r) or reads(r):
                # (the compound's redirections: a pseudo execution so the
                # policy sees the files)
                w.r.executions.append(execution([Field(["{"], False, False)], {}, redirects, ctx.cwd,
                                                node_span(ctx, node), ctx.via, None, "group"))
                break
    else:
        walk(rt, w,first, ctx)


def compound(rt, w,node, ctx):
    rule = node.rule
    if rule == "brace_group":
        for k in children(node, "compound_list"):
            seq(rt, w,k, ctx)
    elif rule == "subshell":
        for k in children(node, "compound_list"):
            seq(rt, w,k, copy(ctx))
    elif rule == "if_clause":
        lists = children(node, "compound_list")
        seq(rt, w,lists[0], ctx)
        branch = copy(ctx)
        skipped = False
        for k in node.children:
            if not skipped and k.rule == "compound_list":
                skipped = True
                continue
            walk(rt, w,k, branch)
        merge_uncertain(ctx, branch)
    elif rule == "for_clause" and for_each(rt, w,node, ctx):
        pass
    elif rule == "while_clause" or rule == "until_clause" or rule == "for_clause" or rule == "select_clause":
        branch = copy(ctx)
        if rule == "for_clause" or rule == "select_clause":
            # (`for i in $(seq 5)`: numbers)
            numbers = True
            for k in node.children:
                if k.rule == "word":
                    substitutions(rt, w,k, ctx)
                    for f in expand_word(k, ctx.vars, ctx.home, True):
                        if not numeric_field(f, ctx.vars, ctx.home):
                            numbers = False
            for k in node.children:
                if k.rule == "name":
                    branch.vars.values[k.text] = NUMBER if numbers and len(children(node, "word")) > 0 else UNKNOWN
        for k in node.children:
            if k.rule == "for_arith":
                # (each part evaluated, the first once: in the loop's)
                for x in children(k, "for_expr"):
                    substitutions(rt, w, x, branch)
                    arithmetic_node(rt, w, x, branch, 0, 0)
            elif k.rule == "compound_list" or k.rule == "do_group":
                walk(rt, w,k, branch)
        merge_uncertain(ctx, branch)
    elif rule == "case_clause":
        for k in children(node, "word"):
            substitutions(rt, w,k, ctx)
        branch = copy(ctx)
        for k in children(node, "case_item"):
            walk(rt, w,k, branch)
        merge_uncertain(ctx, branch)
    elif rule == "coproc":
        for k in children(node, "command"):
            command(rt, w,k, copy(ctx), None)
    else:
        # ((...)), [[ ... ]]: their substitutions run, then what's
        # arithmetic in them is evaluated
        substitutions(rt, w,node, ctx)
        if rule == "arith_cmd":
            arithmetic_node(rt, w, children(node, "arith_body")[0], ctx, 0, 0)
        elif rule == "cond_cmd":
            cond_arithmetic(rt, w, node, ctx)


# [[ ]]'s operators comparing numbers: their operands arithmetic
ARITH_TESTS = ("-eq", "-ne", "-lt", "-le", "-gt", "-ge")


def cond_arithmetic(rt, w, node, ctx):
    """[[ a -eq b ]]: a and b evaluated; [[ -v a[i] ]]: i."""
    for k in node.children:
        if k.rule != "cond_prim":
            cond_arithmetic(rt, w, k, ctx)
            continue
        ops = children(k, "cond_binary")
        unary = children(k, "cond_unary")
        operands = children(k, "word") + children(k, "cond_pattern")
        span = node_span(ctx, k)
        if len(ops) > 0 and ops[0].text in ARITH_TESTS:
            for x in operands:
                for f in expand_word(x, ctx.vars, ctx.home, False):
                    a = arith.from_parts(f.parts)
                    arithmetic(rt, w, ctx, span, a, 0, len(a.text), False)
        elif len(unary) > 0 and unary[0].text == "-v":
            for x in operands:
                for f in expand_word(x, ctx.vars, ctx.home, False):
                    named_subscript(rt, w, ctx, span, f)


def for_each(rt, w,node, ctx):
    """`for v in a b c`: the body once for each item when the items are
    known and few. False: not that kind of loop."""
    names = children(node, "name")
    words = children(node, "word")
    body = children(node, "do_group")
    if len(names) == 0 or len(words) == 0 or len(body) == 0:
        return False
    items = []
    for x in words:
        items += expand_word(x, ctx.vars, ctx.home, True)
    if len(items) == 0 or len(items) > MAX_ITEMS:
        return False
    for f in items:
        if field_static(f) is None or f.splits:
            return False
    var = names[0].text
    merged = copy(ctx)
    for f in items:
        branch = copy(ctx)
        branch.vars.values[var] = field_static(f)
        walk(rt, w,body[0], branch)
        merge_uncertain(merged, branch)
    ctx.cwd = merged.cwd
    ctx.vars = merged.vars
    var_forget(ctx.vars, [var])
    ctx.exported = merged.exported
    return True


def walk(rt, w,node, ctx):
    """Anything else: lists in order, substitutions found."""
    rule = node.rule
    if rule == "list" or rule == "compound_list":
        seq(rt, w,node, ctx)
    elif rule == "and_or":
        and_or(rt, w,node, ctx)
    elif rule == "pipeline":
        pipeline(rt, w,node, ctx)
    elif rule == "command":
        command(rt, w,node, ctx, None)
    elif rule == "compound":
        compound(rt, w,node.children[0], ctx)
    elif rule == "cmdsub" or rule == "procsub" or rule == "backtick":
        substitution(rt, w,node, ctx)
    else:
        for k in node.children:
            walk(rt, w,k, ctx)


def function_def(rt, w,node, ctx):
    name = children(node, "func_name")[0].text
    w.r.functions.add(name)
    body = children(node, "compound")[0]
    inner = copy(ctx)
    inner.via = ctx.via + ("function " + name,)
    inner.vars.values["@"] = UNKNOWN
    compound(rt, w,body.children[0], inner)


# ----------------------------------------------------------------------
# Substitutions
# ----------------------------------------------------------------------


def substitutions(rt, w,node, ctx):
    """The substitutions in a node (not nested in others: theirs are
    theirs), each run in a subshell."""
    for k in node.children:
        if k.rule == "cmdsub" or k.rule == "procsub" or k.rule == "backtick":
            substitution(rt, w,k, ctx)
            continue
        substitutions(rt, w,k, ctx)
        # (after the substitutions in it, what bash evaluates)
        if k.rule == "arith_sub":
            arithmetic_node(rt, w, children(k, "arith_body")[0], ctx, 0, 0)
        elif k.rule == "arith_old":
            arithmetic_node(rt, w, k, ctx, 2, 1)
        elif k.rule == "param":
            param_arithmetic(rt, w, k, ctx)


def substitution(rt, w,node, ctx):
    inner = copy(ctx)
    inner.via = ctx.via + (SUBSTITUTIONS[node.rule],)
    if node.rule == "backtick":
        tick = backtick(node, ctx)
        if tick is None:
            unknown(rt, w,"a backtick substitution vetter couldn't read", node_span(ctx, node), ctx, "code", [])
            return
        inner.span = node_span(ctx, node)
        inner.parsed = tick.command
        inner.base = 0
        inner.source = tick.command.source
        seq(rt, w,tick.command.tree, inner)
        return
    key = ctx.base + offset(ctx.source, node)
    if node.rule == "procsub" and node.text.startswith(">"):
        # (what it reads: the output of the command it's given to)
        inner.stdin = Stdin(None, None)
        w.procs[key] = inner.stdin
    first = len(w.r.executions)
    for k in children(node, "compound_list"):
        seq(rt, w,k, inner)
    if node.rule == "procsub" and node.text.startswith("<") and len(w.r.executions) > first:
        w.procs[key] = w.r.executions[len(w.r.executions) - 1]


def link_procsubs(w, ctx, e, fields):
    """The command e given <(cmd) (as a word or a redirection's target):
    fed by cmd; given >(cmd): cmd's producer."""
    for f in fields:
        for p in f.parts:
            if not isinstance(p, Dynamic) or p.node is None or p.node.rule != "procsub":
                continue
            key = ctx.base + offset(ctx.source, p.node)
            if key not in w.procs:
                continue
            v = w.procs[key]
            if isinstance(v, Stdin):
                v.producer = e
            elif e.fed is None:
                e.fed = v


def backtick(node, ctx):
    parsed = ctx.parsed
    if parsed is None:
        return None
    start = ctx.base + offset(ctx.source, node) + 1
    for t in parsed.backticks:
        if t.start == start:
            return t
    return None


# ----------------------------------------------------------------------
# Simple commands
# ----------------------------------------------------------------------


def simple(rt, w,node, ctx, stdin):
    assigns = []
    words = []
    redirects = []
    for k in node.children:
        rule = k.rule
        if rule == "assignment":
            assigns.append(k)
        elif rule == "cmd_name" or rule == "word":
            words.append(k)
        elif rule == "redirect":
            redirects.append(k)
    # (substitutions run first, in their order)
    substitutions(rt, w,node, ctx)
    reds = []
    for r in redirects:
        reds.append(redirect(rt, w,r, ctx))
    for r in reds:
        # (an expanded here-document's substitutions run too)
        if r.heredoc is not None and r.heredoc.body is not None:
            h = r.heredoc.heredoc
            body = copy(ctx)
            body.base = ctx.base + h.body_start
            body.source = ctx.parsed.text[h.body_start : h.body_end]
            substitutions(rt, w,r.heredoc.body, body)
    given = stdin_of(reds, ctx)
    if given is None:
        given = stdin
    if given is None:
        given = ctx.stdin
    span = node_span(ctx, node)
    if len(words) == 0:
        # (assignments only: they set the shell's variables)
        for a in assigns:
            assignment_arithmetic(rt, w, a, ctx, ctx.vars, span)
            name, _ = assign(a, ctx, ctx.vars)
            expanded_later(rt, w, ctx, span, name, var_get(ctx.vars, name))
        for r in reds:
            if writes(r) or reads(r):
                w.r.executions.append(execution([Field([""], False, False)], {}, reds, ctx.cwd, span, ctx.via, None,
                                                "redirect"))
                break
        return
    env = {}
    written = []
    scratch = var_copy(ctx.vars)
    for a in assigns:
        assignment_arithmetic(rt, w, a, ctx, scratch, span)
        name, shown = assign(a, ctx, scratch)
        env[name] = shown
        written.append((a.text, [name + "=" + field_text(shown)]))
    argv = []
    for x in words:
        fields = expand_word(x, scratch, ctx.home, True)
        texts = []
        for f in fields:
            texts.append(field_text(f))
        written.append((x.text, texts))
        argv += fields
    if len(argv) == 0:
        return
    # (a wrapper's inner executions come after its own)
    first = len(w.r.executions)
    run(rt, w,argv, env, reds, ctx, span, given, None)
    w.r.executions[first].words = written
    link_procsubs(w, ctx, w.r.executions[first], argv + [r.target for r in reds if r.target is not None])


def expanded_later(rt, w, ctx, span, name, value):
    """A variable bash expands again when it uses it (PS4: before each
    command `set -x` traces): its value's substitutions run then, read now
    as bash expands it (a here-document's body: as in double quotes, `"`
    plain). Whether tracing is on isn't followed: set, it's decided."""
    if name not in EXPANDED_LATER or not isinstance(value, str) or ("$" not in value and "`" not in value):
        return
    delimiter = "__vetter_" + name + "__"
    code(rt, w, ": <<" + delimiter + "\n" + value + "\n" + delimiter + "\n", ctx, span, name, False, None)


def arithmetic(rt, w, ctx, span, a, lo, hi, subscript):
    """What evaluating a.text[lo:hi] runs (an arithmetic text, or a
    subscript: expanded again first): its subscripts' substitutions, and an
    Unknown for each value only running tells. All of it arithmetic: the
    variables it sets are numbers after."""
    out = []
    if subscript:
        arith.check_subscript(a, lo, hi, ctx.vars, ctx.home, out)
    else:
        arith.check(a, lo, hi, ctx.vars, ctx.home, out)
    for f in out:
        if f.kind == "code":
            code(rt, w, ": <<__vetter_arith__\n" + f.text + "\n__vetter_arith__\n", ctx, span, "arithmetic", False,
                 None)
        else:
            unknown(rt, w, f.text, span, ctx, "code", [])
    if not subscript and lo == 0 and hi == len(a.text):
        for n in arith.assigned(a):
            ctx.vars.values[n] = NUMBER


def arithmetic_node(rt, w, node, ctx, start, end):
    """An arithmetic text in the command ((( )), $(( )), for (( ))'s)."""
    a = arith.from_node(node, ctx.vars, start, end)
    arithmetic(rt, w, ctx, node_span(ctx, node), a, 0, len(a.text), False)


def named_subscript(rt, w, ctx, span, f):
    """`a[...]` a builtin names (unset, read, printf -v, -v, declare): an
    indexed array's subscript, evaluated."""
    a = arith.from_parts(f.parts)
    t = a.text
    k = 0
    while k < len(t) and arith.is_ident_char(t[k]):
        k += 1
    if k == 0 or k >= len(t) or t[k] != "[":
        return
    name = t[:k]
    if name in ctx.vars.attrs and ctx.vars.attrs[name] == "A":
        return
    end = arith.closing(t, k, len(t))
    inside = t[k + 1 : end]
    if inside != "@" and inside != "*":
        arithmetic(rt, w, ctx, span, a, k + 1, end, True)


def param_arithmetic(rt, w, node, ctx):
    """${a[...]}, ${s:offset:length}: what bash evaluates as arithmetic (an
    associative array's subscript aside)."""
    bodies = children(node, "param_body")
    if len(bodies) == 0:
        return
    a = arith.from_node(bodies[0], ctx.vars, 0, 0)
    t = a.text
    span = node_span(ctx, node)
    p = 0
    if p < len(t) and (t[p] == "#" or t[p] == "!"):
        p += 1
    q = p
    while q < len(t) and arith.is_ident_char(t[q]):
        q += 1
    if q == p and q < len(t) and t[q] in "@*#?$!-":
        q += 1
    name = t[p:q]
    if q < len(t) and t[q] == "[" and name != "":
        end = arith.closing(t, q, len(t))
        inside = t[q + 1 : end]
        if inside != "@" and inside != "*" and not (name in ctx.vars.attrs and ctx.vars.attrs[name] == "A"):
            arithmetic(rt, w, ctx, span, a, q + 1, end, True)
        q = end + 1
    if q < len(t) and t[q] == ":" and (q + 1 >= len(t) or t[q + 1] not in "-=+?"):
        arithmetic(rt, w, ctx, span, a, q + 1, len(t), False)


def assignment_arithmetic(rt, w, node, ctx, variables, span):
    """An assignment's arithmetic: `a[...]=`'s subscript, `a=([...]=x)`'s,
    an integer variable's value (declare -i)."""
    name = children(node, "name")[0].text
    indexed = not (name in variables.attrs and variables.attrs[name] == "A")
    for s in children(node, "subscript"):
        if indexed:
            a = arith.from_node(s, variables, 0, 0)
            arithmetic(rt, w, ctx, span, a, 0, len(a.text), True)
    for arr in children(node, "array"):
        for x in children(arr, "word"):
            if indexed and x.text.startswith("["):
                a = arith.from_node(x, variables, 0, 0)
                end = arith.closing(a.text, 0, len(a.text))
                arithmetic(rt, w, ctx, span, a, 1, end, True)
    if name in variables.attrs and variables.attrs[name] == "i":
        for x in children(node, "word"):
            f = expand_assignment(x, variables, ctx.home)
            a = arith.from_parts(f.parts)
            arithmetic(rt, w, ctx, span, a, 0, len(a.text), False)


def numeric_field(f, variables, home):
    """A field surely a number (`$((...))`, `$(wc -l < f)`, 12)."""
    if len(f.parts) == 0:
        return False
    for p in f.parts:
        if isinstance(p, Dynamic):
            if not arith.hole_is_number(p, variables, home):
                return False
        elif not arith.is_number_text(p):
            return False
    return True


def assign(node, ctx, variables):
    """(name, the value shown): the variable set in variables."""
    name = children(node, "name")[0].text
    op = children(node, "assign_op")[0].text
    index = children(node, "subscript")
    arr = children(node, "array")
    val = children(node, "word")
    value = UNKNOWN
    expanded = None
    if len(arr) > 0:
        fields = []
        for x in children(arr[0], "word"):
            fields += expand_word(x, variables, ctx.home, True)
        statics = []
        for f in fields:
            if not field_known(f):
                statics = None
                break
            statics.append(field_static(f))
        if statics is not None:
            value = statics
    else:
        f = expand_assignment(val[0] if len(val) > 0 else None, variables, ctx.home)
        expanded = f
        s = field_static(f)
        if s is not None:
            value = s
        elif numeric_field(f, variables, ctx.home):
            value = NUMBER
    integer = name in variables.attrs and variables.attrs[name] == "i"
    if len(index) > 0:
        variables.values[name] = NUMBER if integer else UNKNOWN
        return name, Field([""], False, False)
    old = var_get(variables, name)
    if op == "+=":
        if isinstance(old, list) and isinstance(value, list):
            value = old + value
        elif isinstance(old, str) and isinstance(value, str):
            value = old + value
        elif old is None:
            pass
        else:
            value = UNKNOWN
    if integer and not (isinstance(value, str) and arith.is_number_text(value)):
        # (its value evaluated as arithmetic: a number)
        value = NUMBER
    variables.values[name] = value
    if isinstance(value, str):
        return name, Field([value], False, False)
    if isinstance(value, list):
        return name, Field([" ".join(value)], False, False)
    if expanded is not None and op == "=":
        # (what's known of it kept: PATH=/tmp/x:$PATH, /tmp/x)
        return name, expanded
    return name, Field([Dynamic(node, "")], False, False)


def redirect(rt, w,node, ctx):
    first = node.children[0]
    if first.rule == "heredoc":
        kids = first.children
        fd = kids[0].text if kids[0].rule == "io_number" or kids[0].rule == "io_var" else None
        opnode = children(first, "heredoc_op")[0]
        doc = None
        parsed = ctx.parsed
        if parsed is not None:
            pos = offset(ctx.source, opnode)
            for d in parsed.docs:
                if d.heredoc.op_start == pos:
                    doc = d
        return Redirect(fd, opnode.text, None, doc)
    kids = node.children
    fd = kids[0].text if kids[0].rule == "io_number" or kids[0].rule == "io_var" else None
    op = ""
    target = None
    for k in kids:
        if op == "" and (k.rule == "redir_op" or k.rule == "dup_op"):
            op = k.text
        if target is None and (k.rule == "word" or k.rule == "fd_target"):
            target = k
    if target.rule == "fd_target":
        return Redirect(fd, op, Field([target.text], False, False), None)
    fields = expand_word(target, ctx.vars, ctx.home, op != "<<<")
    t = fields[0] if len(fields) == 1 else Field([Dynamic(target, "")], False, True)
    return Redirect(fd, op, t, None)


def strip_tabs(text):
    lines = []
    for line in text.split("\n"):
        i = 0
        while i < len(line) and line[i] == "\t":
            i += 1
        lines.append(line[i:])
    return "\n".join(lines)


def stdin_of(reds, ctx):
    """The text read on stdin when it's known (the last redirection of fd
    0 wins)."""
    out = None
    for r in reds:
        if r.fd is not None and r.fd != "0":
            continue
        if (r.op == "<<" or r.op == "<<-") and r.heredoc is None:
            # (a here-document not found: its text unknown, not none)
            out = Stdin(None, None)
        elif r.heredoc is not None:
            d = r.heredoc.heredoc
            if ctx.parsed is None:
                out = Stdin(None, None)
                continue
            text = ctx.parsed.text[d.body_start : d.body_end]
            if d.strip_tabs:
                text = strip_tabs(text)
            if d.expanded:
                if r.heredoc.body is not None:
                    out = Stdin(field_static(expand_heredoc(r.heredoc.body, ctx.vars)), None)
                else:
                    out = Stdin("", None)
            else:
                out = Stdin(text, None)
        elif r.op == "<<<":
            s = field_static(r.target)
            out = Stdin(s + "\n" if s is not None else None, None)
        elif r.op == "<" or r.op == "<>" or r.op == "<&":
            out = Stdin(None, None)
    return out


# ----------------------------------------------------------------------
# Running
# ----------------------------------------------------------------------


def ascii_lower(s):
    out = ""
    for c in s:
        if c >= "A" and c <= "Z":
            out += chr(ord(c) + 32)
        else:
            out += c
    return out


def run(rt, w,argv, env, reds, ctx, span, stdin, via):
    if via is None:
        via = ctx.via
    name0 = argv[0]
    static0 = field_static(name0)
    known0 = field_known(name0)
    name = paths.program_name(static0) if known0 else None
    kind = "program"
    if name is not None and name in w.r.functions and "/" not in (static0 if static0 is not None else ""):
        kind = "function"
    elif name is not None and (name in BUILTINS or name in CODE_BUILTINS):
        kind = "builtin"
    # (what the shell exported reaches it too)
    merged = {k: v for k, v in ctx.exported.items()}
    for k, v in env.items():
        merged[k] = v
    e = execution(argv, merged, reds, ctx.cwd, span, via, stdin, kind)
    w.r.executions.append(e)
    if known0 and "/" in static0 and paths.join(ctx.cwd, static0) in w.r.downloads:
        unknown(rt, w,"runs " + static0 + ", downloaded by this command", span, ctx, "downloaded_code", [name0])
    if name is None or kind == "function":
        return
    if name in WRAPPERS:
        wrapper(rt, w,e, ctx, name)
    elif name in SHELLS:
        shell(rt, w,e, ctx)
    else:
        low = ascii_lower(name)
        if low == "powershell" or low == "pwsh" or low == "cmd":
            windows_shell(rt, w,e, ctx, low)
    apply_specs(rt, w,e, ctx)
    builtin_effects(rt, w,e, ctx)



def windows_shell(rt, w, e, ctx, name):
    """powershell / cmd started from here (Git Bash, WSL,
    GIT_SSH_COMMAND): their command line read by their rules."""
    from ..cmd.resolve import cmd
    from ..cmd.resolve import walker as cmd_walker
    from ..powershell.resolve import powershell, walker

    if not all_known(e.argv[1:]):
        unknown(rt, w, name + " with arguments only running tells", e.span, ctx, "code", [])
        return
    if name == "cmd":
        words = []
        for a in e.argv[1:]:
            s = field_static(a)
            words.append('"' + s + '"' if " " in s else s)
        cw = cmd_walker(w.r, ctx.home, ctx.depth + 1, e.via, False)
        cw.cwd = ctx.cwd
        cmd(rt, cw, " ".join(words), e.span)
        return
    pw = walker(w.r, ctx.home, ctx.depth + 1)
    pw.cwd = ctx.cwd
    pw.via = e.via
    powershell(rt, pw, e, e.argv[1:], e.span)


def inner(rt, w,e, argv, ctx, label, env):
    """A command another runs (a wrapper's): resolved like one."""
    if len(argv) == 0:
        return
    merged = {k: v for k, v in e.env.items()}
    for k, v in env.items():
        merged[k] = v
    run(rt, w,argv, merged, [], ctx, e.span, e.stdin, e.via + (label,))


def unknown(rt, w,reason, span, ctx, kind, given):
    if kind == "code_file":
        for p in given:
            if field_known(p) and paths.join(ctx.cwd, field_static(p)) in w.r.downloads:
                # (code the command itself downloaded)
                kind = "downloaded_code"
                reason += " (downloaded by this command)"
                break
    w.r.unknowns.append(Unknown(reason, span, ctx.via, kind, [p for p in given], ctx.cwd))


def downloaded(rt, w,e, value):
    """A file a download writes: running it later in the command is running
    downloaded code."""
    if field_known(value):
        p = paths.join(e.cwd, field_static(value))
        if p is not None:
            w.r.downloads.add(p)


def code(rt, w,text, ctx, span, label, same_shell, positional):
    """Code run from a string: read and resolved (a new shell: fresh
    variables, the positional parameters given; None: none given)."""
    if ctx.depth >= MAX_DEPTH:
        unknown(rt, w,label + ": nested too deep", span, ctx, "code", [])
        return
    try:
        parsed = parse(rt, text)
    except zgram.ParseError as e:
        unknown(rt, w,label + ": not bash vetter can read (" + str(e) + ")", span, ctx, "code", [])
        return
    except ValueError as e:
        why = str(e)
        if why.startswith("unreadable: "):
            why = why[12:]
        unknown(rt, w,label + ": not bash vetter can read (" + why + ")", span, ctx, "code", [])
        return
    target = ctx if same_shell else copy(ctx)
    if not same_shell:
        target.vars = Variables({})
        if positional is not None:
            target.vars.values["@"] = positional
    # (the same shell's: where its own text is read, given back after:
    # `eval true; bash <<E` finds its here-document in its text)
    saved = (target.depth, target.span, target.parsed, target.base, target.source, target.via)
    target.depth = ctx.depth + 1
    target.span = span
    target.parsed = parsed
    target.base = 0
    target.source = parsed.source
    target.via = ctx.via + (label,)
    seq(rt, w,parsed.tree, target)
    target.depth, target.span, target.parsed, target.base, target.source, target.via = saved


def all_known(fields):
    for f in fields:
        if not field_known(f):
            return False
    return True


def statics(fields):
    out = []
    for f in fields:
        out.append(field_static(f))
    return out


def shell(rt, w,e, ctx):
    """bash/sh -c SCRIPT, a script file, or the commands on stdin."""
    args = e.argv[1:]
    name = exec_name(e)
    if name == "busybox":
        if len(args) == 0 or not field_known(args[0]):
            return
        s0 = field_static(args[0])
        if s0 != "sh" and s0 != "ash" and s0 != "bash":
            return
        args = args[1:]
    i = 0
    script = None
    dynamic_opts = False
    while i < len(args):
        a = args[i]
        if not field_known(a):
            dynamic_opts = True
            break
        s = field_static(a)
        if s == "--":
            i += 1
            break
        if (s.startswith("-") and len(s) > 1) or (s.startswith("+") and len(s) > 1):
            if "c" in s[1:] and not s.startswith("--"):
                script = i + 1
            if s == "-o" or s == "+o" or s == "-O" or s == "+O" or s == "--rcfile" or s == "--init-file":
                i += 1
            i += 1
            continue
        break
    if dynamic_opts:
        unknown(rt, w,name + " with options only running tells", e.span, ctx, "code", [])
        return
    if script is not None:
        if script >= len(args):
            return
        body = args[script]
        rest = args[script + 1 :]
        if not field_known(body):
            unknown(rt, w,name + " -c with a script only running tells", e.span, ctx, "code", [])
            return
        positional = statics(rest[1:]) if all_known(rest) else UNKNOWN
        code(rt, w,field_static(body), ctx, e.span, name + " -c", False, positional)
        return
    if i < len(args):
        target = args[i]
        what = field_static(target) if field_known(target) else field_text(target)
        unknown(rt, w,name + " runs a script file: " + what, e.span, ctx, "code_file", [target])
        return
    stdin_code(rt, w,e, ctx, name)


def stdin_code(rt, w,e, ctx, label):
    """A shell (or source) reading its commands from stdin."""
    st = e.stdin
    if st is None:
        # (the terminal's input, or the agent's: no command known)
        return
    if st.text is not None:
        code(rt, w,st.text, ctx, e.span, label + " <<<stdin", False, None)
        return
    p = st.producer
    if p is not None:
        pname = exec_name(p)
        if (pname == "echo" or pname == "printf") and all_known(p.argv[1:]):
            text = echo_output(pname, statics(p.argv[1:]))
            if text is not None:
                code(rt, w,text, ctx, e.span, pname + " | " + label, False, None)
                return
        unknown(rt, w,label + " runs what " + (pname if pname is not None else "a command") + " outputs", e.span, ctx,
                "code", [])
    else:
        unknown(rt, w,label + " runs input only running tells (a here-document's substitutions, "
                "a process substitution)", e.span, ctx, "code", [])


def unknown_all(ctx):
    ctx.vars.values = {k: UNKNOWN for k in ctx.vars.values}


def builtin_effects(rt, w,e, ctx):
    """What a builtin changes in the shell (the variables, the working
    directory), and the code eval and source run."""
    name = exec_name(e)
    args = e.argv[1:]
    if name == "cd" or name == "pushd":
        ops = []
        for a in args:
            s = field_static(a)
            if not (field_known(a) and s.startswith("-") and s != "-"):
                ops.append(a)
        if len(ops) == 0:
            ctx.cwd = ctx.home
        elif field_known(ops[0]) and field_static(ops[0]) != "-":
            ctx.cwd = paths.join(ctx.cwd, field_static(ops[0]))
        else:
            ctx.cwd = None
    elif name == "popd":
        ctx.cwd = None
    elif name == "let":
        # (each argument an arithmetic expression)
        for a in args:
            x = arith.from_parts(a.parts)
            arithmetic(rt, w, ctx, e.span, x, 0, len(x.text), False)
    elif name == "unset":
        for a in args:
            named_subscript(rt, w, ctx, e.span, a)
            if field_known(a) and not field_static(a).startswith("-"):
                ctx.vars.values[field_static(a)] = None
            elif not field_known(a):
                unknown_all(ctx)
    elif name == "test" or name == "[":
        for k in range(len(args) - 1):
            if field_known(args[k]) and field_static(args[k]) == "-v":
                named_subscript(rt, w, ctx, e.span, args[k + 1])
    elif name == "export" or name == "declare" or name == "typeset" or name == "local" or name == "readonly":
        exported_flag = name == "export"
        array_flag = False
        integer_flag = False
        assoc_flag = False
        for x in args:
            s = field_static(x)
            if field_known(x) and s.startswith("-"):
                if "x" in s:
                    exported_flag = True
                if "a" in s or "A" in s:
                    array_flag = True
                if "i" in s and name != "export":
                    integer_flag = True
                if "A" in s:
                    assoc_flag = True
        for a in args:
            s = field_static(a)
            if s is not None and s.startswith("-"):
                continue
            if name != "export":
                named_subscript(rt, w, ctx, e.span, a)
            if integer_flag:
                # (n=value: the value evaluated, as arithmetic)
                x = arith.from_parts(a.parts)
                arithmetic(rt, w, ctx, e.span, x, 0, len(x.text), False)
            if not field_known(a):
                unknown_all(ctx)
                continue
            n = s.partition("=")[0]
            if n.endswith("+"):
                n = n[: len(n) - 1]
            if integer_flag and arith.is_name(n.partition("[")[0]):
                ctx.vars.attrs[n.partition("[")[0]] = "i"
            elif assoc_flag and arith.is_name(n.partition("[")[0]):
                ctx.vars.attrs[n.partition("[")[0]] = "A"
            if "=" in s:
                n, _, v = s.partition("=")
                if n.endswith("+"):
                    n = n[: len(n) - 1]
                    old = var_get(ctx.vars, n)
                    v = old + v if isinstance(old, str) else UNKNOWN
                if integer_flag and not arith.is_number_text(v if isinstance(v, str) else ""):
                    v = NUMBER
                if "[" in n:
                    ctx.vars.values[n.partition("[")[0]] = UNKNOWN
                else:
                    ctx.vars.values[n] = v
                    expanded_later(rt, w, ctx, e.span, n, v)
                    if exported_flag:
                        if isinstance(v, str):
                            ctx.exported[n] = Field([v], False, False)
                        else:
                            ctx.exported[n] = Field([Dynamic(None, "$" + n)], False, False)
            elif (name == "declare" or name == "typeset" or name == "local") and array_flag:
                ctx.vars.values[s] = []
    elif name == "set":
        for k in range(len(args)):
            if field_known(args[k]) and field_static(args[k]) == "--":
                rest = args[k + 1 :]
                ctx.vars.values["@"] = statics(rest) if all_known(rest) else UNKNOWN
                break
    elif name == "shift":
        pos = var_get(ctx.vars, "@")
        n = None
        if len(args) == 0:
            n = "1"
        elif field_known(args[0]):
            n = field_static(args[0])
        if isinstance(pos, list) and n is not None and is_digits(n):
            ctx.vars.values["@"] = pos[int(n) :]
        else:
            ctx.vars.values["@"] = UNKNOWN
    elif name == "read" or name == "mapfile" or name == "readarray" or name == "getopts":
        named = False
        for a in args:
            if name == "read":
                named_subscript(rt, w, ctx, e.span, a)
            if field_known(a) and is_name(field_static(a)):
                ctx.vars.values[field_static(a)] = UNKNOWN
                named = True
        if name == "read" and not named:
            ctx.vars.values["REPLY"] = UNKNOWN
        if name == "mapfile" or name == "readarray":
            ctx.vars.values["MAPFILE"] = UNKNOWN
            mapfile_callback(rt, w, e, ctx, name, args)
    elif name == "trap":
        trap_action(rt, w, e, ctx, args)
    elif name == "printf":
        for k in range(len(args)):
            if field_known(args[k]) and field_static(args[k]) == "-v" and k + 1 < len(args):
                named_subscript(rt, w, ctx, e.span, args[k + 1])
                out = None
                target = None
                if field_known(args[k + 1]):
                    target = field_static(args[k + 1])
                    rest = args[k + 2 :]
                    if len(rest) > 0 and all_known(rest):
                        out = echo_output("printf", statics(rest))
                if target is not None and target != "" and is_name(target):
                    ctx.vars.values[target] = out if out is not None else UNKNOWN
    elif name == "eval":
        if all_known(args):
            code(rt, w," ".join(statics(args)), ctx, e.span, "eval", True, None)
        else:
            unknown(rt, w,"eval of a string only running tells", e.span, ctx, "code", [])
    elif name == "source" or name == ".":
        if len(args) > 0 and field_known(args[0]):
            unknown(rt, w,name + " runs a script file: " + field_static(args[0]), e.span, ctx, "code_file", [args[0]])
        elif len(args) > 0:
            unknown(rt, w,name + " runs a script only running tells", e.span, ctx, "code", [])
        unknown_all(ctx)
        ctx.cwd = None


def trap_action(rt, w, e, ctx, args):
    """trap [-lp] [[action] signal...]: the action is code the shell runs
    when a signal comes (EXIT: when it ends), read as eval's; one operand,
    or `-`, resets the signals."""
    ops = []
    k = 0
    while k < len(args):
        a = args[k]
        if len(ops) == 0 and field_known(a):
            s = field_static(a)
            if s == "--":
                k += 1
                ops = args[k:]
                break
            if s.startswith("-") and s != "-":
                # (-l, -p: listing, nothing set)
                return
        ops = args[k:]
        break
    if len(ops) < 2:
        return
    action = ops[0]
    if field_known(action) and (field_static(action) == "-" or field_static(action) == ""):
        return
    if field_known(action):
        code(rt, w, field_static(action), copy(ctx), e.span, "trap", True, None)
    else:
        unknown(rt, w, "trap of an action only running tells", e.span, ctx, "code", [])


def mapfile_callback(rt, w, e, ctx, name, args):
    """mapfile -C callback: code evaluated for every -c lines read, given
    the index and the line (read as eval's)."""
    k = 0
    while k < len(args):
        a = args[k]
        if not field_known(a):
            k += 1
            continue
        s = field_static(a)
        if s == "--" or not s.startswith("-") or s == "-":
            break
        # (its options with a value: attached, or the next word)
        j = 1
        while j < len(s):
            c = s[j]
            if c in "dnOscuC":
                value = None
                if j + 1 < len(s):
                    value = Field([s[j + 1:]], False, False)
                elif k + 1 < len(args):
                    value = args[k + 1]
                    k += 1
                if c == "C":
                    if value is not None and field_known(value):
                        code(rt, w, field_static(value), copy(ctx), e.span, name + " -C", True, None)
                    else:
                        unknown(rt, w, name + " -C: a callback only running tells", e.span, ctx, "code", [])
                break
            j += 1
        k += 1


def is_digits(s):
    if len(s) == 0:
        return False
    for c in s:
        if c < "0" or c > "9":
            return False
    return True


def is_name(s):
    """[A-Za-z_][A-Za-z0-9_]*"""
    if len(s) == 0:
        return False
    for i in range(len(s)):
        c = s[i]
        if not ((c >= "a" and c <= "z") or (c >= "A" and c <= "Z") or c == "_" or (i > 0 and c >= "0" and c <= "9")):
            return False
    return True


def echo_output(name, args):
    """What `echo ARGS` / `printf %s...` prints, when it's simple."""
    if name == "echo":
        flags = ""
        while len(args) > 0 and (args[0] == "-n" or args[0] == "-e" or args[0] == "-E" or args[0] == "-ne"
                                 or args[0] == "-en"):
            flags += args[0]
            args = args[1:]
        if "e" in flags:
            for a in args:
                if "\\" in a:
                    return None
        return " ".join(args) + ("" if "n" in flags else "\n")
    if len(args) == 0:
        return None
    fmt = args[0]
    if "%" in fmt.replace("%s", "").replace("%%", "") or "\\" in fmt:
        return None
    rest = args[1:]
    pieces = fmt.replace("%%", "\0").split("%s")
    n = len(pieces) - 1
    if n == 0:
        return fmt.replace("%%", "%")
    out = ""
    while True:
        chunk = rest[:n]
        rest = rest[n:]
        for k in range(n):
            out += pieces[k] + (chunk[k] if k < len(chunk) else "")
        out += pieces[n]
        if len(rest) == 0:
            break
    return out.replace("\0", "%")


# ----------------------------------------------------------------------
# Wrappers: programs that run another
# ----------------------------------------------------------------------


def xargs_arg_files(options):
    """xargs' -a FILE, -aFILE, -ra FILE, --arg-file[=]FILE: the files its
    arguments are read from (one only running tells: as it's written)."""
    out = []
    k = 0
    while k < len(options):
        a = options[k]
        s = field_static(a)
        nxt = options[k + 1] if k + 1 < len(options) else None
        if s == "--arg-file" and nxt is not None:
            out.append(nxt)
            k += 2
            continue
        if s.startswith("--arg-file="):
            out.append(Field([s[11:]], False, False))
        elif s.startswith("-") and not s.startswith("--"):
            # (the first option taking a value in a cluster takes the rest)
            for j in range(1, len(s)):
                if s[j] in "adEILnPs":
                    if s[j] == "a":
                        if j + 1 < len(s):
                            out.append(Field([s[j + 1 :]], False, False))
                        elif nxt is not None:
                            out.append(nxt)
                            k += 1
                    elif j + 1 == len(s):
                        k += 1
                    break
        k += 1
    return out


def skip_options(args, with_arg, long_with_arg):
    """The index of the first operand, skipping options (with_arg: the short
    options taking a value; long_with_arg: the long ones). None: an option
    vetter can't read."""
    i = 0
    while i < len(args):
        a = args[i]
        if not field_known(a):
            return None
        s = field_static(a)
        if s == "--":
            return i + 1
        if s.startswith("--"):
            n = s[2:].partition("=")[0]
            if "=" not in s and n in long_with_arg:
                i += 2
            else:
                i += 1
            continue
        if s.startswith("-") and len(s) > 1:
            # (clustered: -abc; the first taking a value takes the rest or the next)
            for k in range(len(s) - 1):
                if s[k + 1] in with_arg:
                    if k == len(s) - 2:
                        i += 1
                    break
            i += 1
            continue
        return i
    return i


def quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def wrapper(rt, w,e, ctx, name):
    args = e.argv[1:]
    if name == "env":
        wrap_env(rt, w,e, ctx)
    elif name == "command" or name == "exec":
        i = 0
        while i < len(args) and field_known(args[i]) and field_static(args[i]).startswith("-") \
                and field_static(args[i]) != "--":
            s = field_static(args[i])
            if name == "command" and ("v" in s or "V" in s):
                return
            if name == "exec" and s == "-a":
                i += 1
            i += 1
        if i < len(args) and field_known(args[i]) and field_static(args[i]) == "--":
            i += 1
        inner(rt, w,e, args[i:], ctx, name, {})
    elif name == "builtin":
        inner(rt, w,e, args, ctx, "builtin", {})
    elif name == "sudo":
        wrap_sudo(rt, w,e, ctx)
    elif name == "timeout":
        i = skip_options(args, "ks", ("kill-after", "signal"))
        if i is None:
            unknown(rt, w,"timeout with options only running tells", e.span, ctx, "code", [])
            return
        inner(rt, w,e, args[i + 1 :], ctx, "timeout", {})
    elif name == "xargs":
        # (-e, -i, -l and --eof, --replace, --max-lines take a value only
        # glued on: -i{}, --replace=X)
        i = skip_options(args, "adEILnPs", ("arg-file", "delimiter", "max-args", "max-procs", "max-chars",
                                            "process-slot-var"))
        if i is None:
            unknown(rt, w,"xargs with options only running tells", e.span, ctx, "code", [])
            return
        # (-a FILE: the arguments read from it)
        for f in xargs_arg_files(args[:i]):
            e.roles.append(Role("read", f, "-a"))
        cmd = args[i:]
        if len(cmd) == 0:
            cmd = [Field(["echo"], False, False)]
        # (its arguments come from its input: unknown, any number)
        inner(rt, w,e, cmd + [Field([Dynamic(None, "<xargs input>")], False, True)], ctx, "xargs", {})
    elif name == "find":
        i = 0
        while i < len(args):
            a = args[i]
            s = field_static(a)
            if field_known(a) and (s == "-exec" or s == "-execdir" or s == "-ok" or s == "-okdir"):
                j = i + 1
                while j < len(args) and not (field_known(args[j]) and (field_static(args[j]) == ";"
                                                                       or field_static(args[j]) == "+")):
                    j += 1
                # ({} is each file found)
                cmd = []
                for f in args[i + 1 : j]:
                    if field_known(f) and field_static(f) == "{}":
                        cmd.append(Field([Dynamic(None, "{}")], False, False))
                    else:
                        cmd.append(f)
                inner(rt, w,e, cmd, ctx, "find " + s, {})
                i = j + 1
                continue
            i += 1
    elif name == "watch":
        i = skip_options(args, "dnq", ("differences", "interval", "chgexit"))
        if i is None:
            unknown(rt, w,"watch with options only running tells", e.span, ctx, "code", [])
            return
        rest = args[i:]
        if all_known(rest):
            code(rt, w," ".join(statics(rest)), ctx, e.span, "watch", False, None)
        else:
            unknown(rt, w,"watch with a command only running tells", e.span, ctx, "code", [])
    elif name == "su":
        for k in range(len(args)):
            a = args[k]
            if field_known(a) and (field_static(a) == "-c" or field_static(a) == "--command") and k + 1 < len(args):
                if field_known(args[k + 1]):
                    code(rt, w,field_static(args[k + 1]), ctx, e.span, "su -c", False, None)
                else:
                    unknown(rt, w,"su -c with a command only running tells", e.span, ctx, "code", [])
                return
        unknown(rt, w,"su starts a shell", e.span, ctx, "code", [])
    elif name == "ssh":
        # (a command run on another machine: the policy decides about ssh)
        pass
    else:
        simple_wrapper(rt, w,e, ctx, name)


def simple_wrapper(rt, w,e, ctx, name):
    with_arg = ""
    long_with_arg = ()
    before = 0
    if name == "doas":
        with_arg = "uC"
    elif name == "nice":
        with_arg = "n"
        long_with_arg = ("adjustment",)
    elif name == "stdbuf":
        with_arg = "ioe"
        long_with_arg = ("input", "output", "error")
    elif name == "time":
        with_arg = "fo"
        long_with_arg = ("format", "output")
    elif name == "chroot":
        long_with_arg = ("userspec", "groups")
        before = 1
    elif name == "ionice":
        with_arg = "cnp"
        long_with_arg = ("class", "classdata", "pid")
    elif name == "taskset" or name == "chrt":
        before = 1
    elif name == "flock":
        with_arg = "wE"
        long_with_arg = ("timeout", "conflict-exit-code")
        before = 1
    args = e.argv[1:]
    i = skip_options(args, with_arg, long_with_arg)
    if i is None:
        unknown(rt, w,name + " with options only running tells", e.span, ctx, "code", [])
        return
    inner(rt, w,e, args[i + before :], ctx, name, {})


def wrap_env(rt, w,e, ctx):
    args = e.argv[1:]
    i = 0
    env = {}
    while i < len(args):
        a = args[i]
        if not field_known(a):
            unknown(rt, w,"env with arguments only running tells", e.span, ctx, "code", [])
            return
        s = field_static(a)
        if s == "-i" or s == "--ignore-environment" or s == "-0" or s == "--null" or s == "-v" or s == "--debug" \
                or s == "-":
            i += 1
        elif s == "-u" or s == "--unset" or s == "-C" or s == "--chdir":
            i += 2
        elif s.startswith("--unset=") or s.startswith("--chdir=") or ((s.startswith("-u") or s.startswith("-C"))
                                                                       and len(s) > 2):
            i += 1
        elif s == "-S" or s == "--split-string" or s.startswith("--split-string=") or s.startswith("-S"):
            text = None
            if s.startswith("--split-string="):
                text = s.partition("=")[2]
            elif len(s) > 2 and s.startswith("-S"):
                text = s[2:]
            if text is None:
                if i + 1 >= len(args) or not field_known(args[i + 1]):
                    unknown(rt, w,"env -S with a string only running tells", e.span, ctx, "code", [])
                    return
                text = field_static(args[i + 1])
                i += 1
            # (-S splits its string into words: a command line)
            quoted = []
            for f in args[i + 1 :]:
                if field_known(f):
                    quoted.append(quote(field_static(f)))
            code(rt, w,text + " " + " ".join(quoted), ctx, e.span, "env -S", False, None)
            return
        elif s == "--":
            i += 1
            break
        elif "=" in s and not s.startswith("-") and is_name(s.partition("=")[0]):
            n, _, v = s.partition("=")
            env[n] = Field([v], False, False)
            i += 1
        else:
            break
    inner(rt, w,e, args[i:], ctx, "env", env)


def wrap_sudo(rt, w,e, ctx):
    args = e.argv[1:]
    name = exec_name(e)
    i = skip_options(args, "CDghpRrTUu", ("chdir", "close-from", "group", "host", "prompt", "chroot", "role", "type",
                                          "command-timeout", "other-user", "user"))
    if i is None:
        unknown(rt, w,name + " with options only running tells", e.span, ctx, "code", [])
        return
    shell_opt = False
    listing = False
    for a in args[:i]:
        o = field_static(a)
        if o == "-s" or o == "--shell" or o == "-i" or o == "--login":
            shell_opt = True
        if o == "-e" or o == "--edit" or o == "-l" or o == "--list" or o == "-v" or o == "--validate" or o == "-k" \
                or o == "-K":
            listing = True
    rest = args[i:]
    if shell_opt:
        # (a shell: its arguments are a command line)
        if len(rest) > 0 and all_known(rest):
            quoted = []
            for f in rest:
                quoted.append(quote(field_static(f)))
            code(rt, w," ".join(quoted), ctx, e.span, name + " -s", False, None)
        elif len(rest) > 0:
            unknown(rt, w,name + " -s with a command only running tells", e.span, ctx, "code", [])
        return
    if listing and len(rest) == 0:
        return
    inner(rt, w,e, rest, ctx, name, {})
