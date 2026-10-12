"""What a PowerShell command runs, in the same terms as bash's (Executions,
Unknowns), so one policy covers both: cmdlets (an alias resolved: rm, del,
ri are Remove-Item) with their parameters bound as PowerShell binds them
and their roles from specs/powershell.toml; code in strings read again
(Invoke-Expression, powershell -Command, -EncodedCommand); native programs
through bash's specs and wrappers. The walker is a record (PW) and module
functions, given rt first.

    r = resolve(rt, "Remove-Item -Rec C:\\x", "C:/Users/u/p", "C:/Users/u")
"""

from dataclasses import dataclass

import zgram

from ... import paths
from ...glob import match
from ...specs import DOWNLOADERS as BASH_DOWNLOADERS
from ...specs import Role, strip
from ..bash.expand import Dynamic, Field, Variables, field_known, field_static, field_text
from ..bash.resolve import (
    Ctx,
    Execution,
    Redirect,
    Resolution,
    Stdin,
    W,
    downloaded,
    exec_name,
    execution,
    offset,
    run,
    unknown,
)
from ..bash.syntax import nodes_of
from ..cmd.resolve import LAUNCHERS, default_env, launch
from .cmdlets import (
    ALIASES,
    CMDLETS,
    COMMON_ALIASES,
    COMMON_PARAMS,
    DOWNLOADING,
    FILE_BOTH,
    FILE_READERS,
    FILE_WRITERS,
    MAX_DEPTH,
    POWERSHELLS,
    PS_ALIASES,
    PS_OPTIONS,
    PS_VALUED,
    CAPABLE_TYPES,
    RISKY_METHODS,
    RISKY_TYPES,
)
from . import values
from .syntax import bareword_value, dq_value, fold, fold_upper, here_value, literal_word, parse, sq_value, unquote


@dataclass
class PW:
    """The walker: what it found (r), the home, how deep in code read
    again, known variables (a str, or None: not known) and $env:X set,
    where it runs, the commands found by where they start (by_command),
    the text read (source)."""

    r: object
    bash: object
    home: object
    depth: int
    vars: dict
    env: dict
    cwd: object
    via: tuple
    by_command: dict
    source: str
    # (Set-Alias's: folded alias -> the command's name)
    aliases: dict
    # ($PSDefaultParameterValues['Cmdlet:Param'] = v: folded key -> v; "?":
    # changed in a way only running tells)
    defaults: dict
    # (Push-Location's, by the stack's name (folded; "" the default):
    # where Pop-Location goes back to)
    locations: dict
    # (the stack Push-Location and Pop-Location use: Set-Location
    # -StackName's; "?": one only running tells)
    stack: str = ""


def walker(r, home, depth):
    return PW(r, W(r), home, depth, {}, {}, None, (), {}, "", {}, {}, {})


@dataclass
class Word:
    """A command's element: kind (param, arg, verbatim, dashdash), the
    parameter's name, its fields (None: no value), verbatim's words."""

    kind: str
    name: str
    fields: object
    texts: list


def resolve(rt, command, cwd, home):
    """The command's executions (zgram.ParseError / ValueError("unreadable:
    ...") when it isn't PowerShell vetter can read)."""
    tree = parse(rt, command)
    r = Resolution([], [], set(), set())
    script(rt, walker(r, home, 0), tree, cwd, (), command)
    return r


def children(node, rule):
    out = []
    for k in node.children:
        if k.rule == rule:
            out.append(k)
    return out


def first_child(node, rule):
    for k in node.children:
        if k.rule == rule:
            return k
    return None


def lstrip_chars(s, chars):
    i = 0
    while i < len(s) and s[i] in chars:
        i += 1
    return s[i:]


def strip_chars(s, chars):
    i = 0
    j = len(s)
    while i < j and s[i] in chars:
        i += 1
    while j > i and s[j - 1] in chars:
        j -= 1
    return s[i:j]


def replace_first(s, old, new):
    k = s.find(old)
    if k < 0:
        return s
    return s[:k] + new + s[k + len(old) :]


def span_of(pw, node):
    """Where a node is in the text read, in characters."""
    s = offset(pw.source, node)
    return (s, s + len(node.text))


def ctx_of(pw):
    ctx = Ctx(pw.cwd, Variables({"HOME": pw.home}), pw.home, pw.via, pw.depth, None, None, 0, "", {}, None)
    ctx.exported = {k: v for k, v in pw.env.items()}
    return ctx


def note(rt, pw, reason, span, kind, given):
    """An Unknown, as bash's walker records it."""
    unknown(rt, pw.bash, reason, span, ctx_of(pw), kind, given)


def script(rt, pw, tree, cwd, via, source):
    pw.cwd = cwd
    pw.via = via
    pw.source = source
    pw.by_command = {}
    body = tree.children[0]
    for stmt in body.children:
        if stmt.rule != "statement":
            continue
        for cmd in nodes_of(stmt, "command", []):
            first = len(pw.r.executions)
            command(rt, pw, cmd)
            if len(pw.r.executions) > first:
                pw.by_command[cmd.start] = pw.r.executions[first]
        expression_redirects(rt, pw, stmt)
        effects(rt, pw, stmt)
        method_effects(rt, pw, stmt)
        defaults_reached(pw, stmt)
        forget_changed(pw, stmt)
    for pipe in nodes_of(tree, "pipe", []):
        pipeline(rt, pw, pipe)
    dotnet(rt, pw, tree)


def expression_redirects(rt, pw, stmt):
    """A value's redirections ('text' > $PROFILE): the files written, with
    no command to carry them."""
    of_commands = set()
    for cmd in nodes_of(stmt, "command", []):
        for r in nodes_of(cmd, "redirection", []):
            of_commands.add(r.start)
    for node in nodes_of(stmt, "redirection", []):
        if node.start in of_commands:
            continue
        red = redirect(rt, pw, node)
        if red is not None:
            pw.r.executions.append(execution([Field(["("], False, False)], {}, [red], pw.cwd, span_of(pw, node), pw.via,
                                             None, "group"))


def file_type(type_literal):
    """"read", "write", "both": what an object of the type does to the
    file it's made with; None: not such a type."""
    t = fold(strip_chars(type_literal, "[]"))
    if t.startswith("system."):
        t = t[7:]
    if t in FILE_READERS:
        return "read"
    if t in FILE_WRITERS:
        return "write"
    if t in FILE_BOTH:
        return "both"
    return None


def file_object(rt, pw, node, does, invoke):
    """[IO.StreamReader]::new(path): the file read (written: a writer's;
    both: a FileStream's); a path only running tells, an Unknown."""
    args = [k for k in invoke.children if k.rule == "expression"]
    path = values.value(rt, pw, args[0]) if len(args) > 0 else None
    if isinstance(path, list) and len(path) > 0:
        path = path[0]
    span = span_of(pw, node)
    if not isinstance(path, str):
        note(rt, pw, "a file object on a path only running tells: " + node.text, span, "code", [])
        return
    f = Field([path], False, False)
    e = execution([Field(["("], False, False)], {}, [], pw.cwd, span, pw.via, None, "group")
    if does == "read" or does == "both":
        e.roles.append(Role("read", f, None))
    if does == "write" or does == "both":
        e.roles.append(Role("write", f, None))
    pw.r.executions.append(e)


def risky_type(type_literal):
    t = fold(strip_chars(type_literal, "[]"))
    if t.startswith("system."):
        t = t[7:]
    for r in RISKY_TYPES:
        if t == r or t.startswith(r):
            return True
    return False


def capable_type(type_literal):
    t = fold(strip_chars(type_literal, "[]"))
    if t.startswith("system."):
        t = t[7:]
    for r in CAPABLE_TYPES:
        if t == r or (r.endswith(".") and t.startswith(r)):
            return True
    return False


def dotnet(rt, pw, tree):
    """.NET calls that do what a command would: what vetter can't follow,
    an Unknown. A type that gets such objects, used at all: one too."""
    for node in nodes_of(tree, "type_literal", []):
        if capable_type(node.text):
            note(rt, pw, "a .NET type vetter doesn't follow: " + node.text, span_of(pw, node), "code", [])
    for kind in ("postfix_expr", "postfix_expr_arg", "lvalue"):
        for node in nodes_of(tree, kind, []):
            kids = node.children
            for k in range(len(kids)):
                m = kids[k]
                if m.rule != "member" or k + 1 >= len(kids) or kids[k + 1].rule != "invoke":
                    continue
                bare = lstrip_chars(m.text, ".:")
                method = fold(bare)
                on = kids[0].text if kids[0].rule == "type_literal" and m.text.startswith("::") else None
                if on is not None and method == "new" and file_type(on) is not None:
                    file_object(rt, pw, node, file_type(on), kids[k + 1])
                    continue
                risky = on is not None and risky_type(on)
                if method in RISKY_METHODS or risky:
                    what = on + "::" + bare if on is not None and on != "" else "." + bare + "()"
                    note(rt, pw, "a .NET call vetter doesn't follow: " + what, span_of(pw, node), "code", [])


def piped_shell(rt, pw, e, span):
    """powershell -NoExit, cmd /k, given a pipe: the commands in it run
    too."""
    from ..cmd.resolve import cmd_stdin, reads_stdin
    from ..cmd.resolve import walker as cmd_walker

    if len(e.argv) == 0 or not field_known(e.argv[0]):
        return
    base = fold(paths.program_name(field_static(e.argv[0])))
    if base.endswith(".exe"):
        base = base[: len(base) - 4]
    if base in POWERSHELLS and ps_reads_stdin(e.argv[1:]):
        ps_stdin(rt, pw, e, span)
    elif base == "cmd" and len([a for a in e.argv[1:] if not field_known(a)]) == 0:
        if reads_stdin(" ".join([field_static(a) for a in e.argv[1:]])):
            cw = cmd_walker(pw.r, pw.home, pw.depth + 1, pw.via, False)
            cw.cwd = pw.cwd
            cw.piped = True
            cw.stdin_text = e.stdin.text
            cw.piped_from = e.stdin.producer
            cmd_stdin(rt, cw, span, False)


def pipeline(rt, pw, pipe):
    """Each command reads what the one before writes: a download piped into
    Invoke-Expression runs it."""
    parts = []
    for k in pipe.children:
        if k.rule == "command" or k.rule == "expression":
            parts.append(k)
    for i in range(len(parts) - 1):
        prev = parts[i]
        cur = parts[i + 1]
        if cur.rule != "command" or cur.start not in pw.by_command:
            continue
        e = pw.by_command[cur.start]
        producer = None
        if prev.rule == "command" and prev.start in pw.by_command:
            producer = pw.by_command[prev.start]
        text = None
        if prev.rule == "expression":
            text = constant_text(rt, prev)
            # ((Invoke-WebRequest ...).Content | ...: what it downloads)
            if text is None and downloader_under(prev) is not None:
                for c in nodes_of(prev, "command", []):
                    if c.start in pw.by_command and producer is None:
                        e0 = pw.by_command[c.start]
                        if exec_name(e0) in DOWNLOADING:
                            producer = e0
        e.stdin = Stdin(text, producer)
        piped_shell(rt, pw, e, span_of(pw, cur))
        pwsh = False
        for r in e.roles:
            if r.role == "pwsh":
                pwsh = True
        if exec_name(e) == "Invoke-Expression" and not pwsh and len(e.argv) == 1:
            if text is not None:
                code(rt, pw, text, e.span, "Invoke-Expression")
            elif producer is not None and exec_name(producer) in DOWNLOADING:
                note(rt, pw, "Invoke-Expression runs what " + str(exec_name(producer)) + " downloads", e.span,
                     "downloaded_code", [])
            else:
                note(rt, pw, "Invoke-Expression runs what the pipeline gives it", e.span, "code", [])


def string_atoms(t):
    """The sq_strings, then the dq_strings, under t."""
    return nodes_of(t, "sq_string", []) + nodes_of(t, "dq_string", [])


def constant_text(rt, expr):
    try:
        t = parse(rt, expr.text)
    except zgram.ParseError:
        return None
    except ValueError:
        return None
    for kind in ("sq_string", "dq_string"):
        atoms = nodes_of(t, kind, [])
        if len(atoms) == 1 and atoms[0].text == strip(expr.text):
            return sq_value(atoms[0].text) if kind == "sq_string" else dq_value(atoms[0])
    return None


def effects(rt, pw, stmt):
    """What a top-level statement changes for the ones after: a known
    string in a variable; $env:X."""
    if len(stmt.children) == 0:
        return
    first = stmt.children[0]
    if first.rule != "pipeline" or len(first.children) == 0:
        return
    a = first.children[0]
    if a.rule != "assignment":
        return
    lv = first_child(a, "lvalue")
    var = lv.children[0] if lv is not None and len(lv.children) > 0 else None
    name = fold(var.text[1:]) if var is not None and var.text.startswith("$") else None
    value = constant(rt, a)
    computed = None
    rhs = first_child(a, "statement")
    op = first_child(a, "assign_op")
    if op is not None and op.text != "=":
        # ($p += 'x': added to what it was, a string's, else forgotten)
        if name is not None and is_plain_name(name):
            old = pw.vars[name] if name in pw.vars else variable(pw, var.text)
            added = values.value(rt, pw, rhs) if rhs is not None else None
            if op.text == "+=" and old is not None and added is not None:
                pw.vars[name] = values.binary("+", old, added)
            else:
                pw.vars[name] = None
        elif name is not None and name.startswith("psdefaultparametervalues"):
            pw.defaults["?"] = True
        return
    if name == "psdefaultparametervalues":
        # (the whole table replaced: what's in it only running tells)
        pw.defaults["?"] = True
        return
    if value is None and rhs is not None and op is not None and op.text == "=":
        # (a value built from pieces: $a + '-Item', -join (...), ...)
        computed = values.value(rt, pw, rhs)
        if isinstance(computed, str):
            value = computed
    if name is not None and name.startswith("psdefaultparametervalues["):
        # ($PSDefaultParameterValues['Set-Alias:Name'] = 'x': what a
        # cmdlet's parameter is when it isn't given; a key or value only
        # running tells: any)
        key = default_key(var)
        if key is not None and value is not None:
            pw.defaults[key] = value
        else:
            pw.defaults["?"] = True
        return
    if name is not None and name != "" and name.startswith("env:"):
        pw.env[fold_upper(name[4:])] = Field([value], False, False) if value is not None else env_value(rt, pw, a)
    if name is not None and is_plain_name(name):
        if computed is not None and not isinstance(computed, str):
            pw.vars[name] = computed
        else:
            pw.vars[name] = value if value is not None else field_static(value_of(pw, a))


def env_value(rt, pw, assignment):
    """$env:X = "...": a "string" with what's known in it known, the rest
    dynamic ("$env:TEMP;$env:PATH": the temp directory, then what only
    running tells)."""
    rhs = first_child(assignment, "statement")
    atoms = string_atoms(rhs) if rhs is not None else []
    if len(atoms) != 1 or atoms[0].rule != "dq_string" or atoms[0].text != strip(rhs.text):
        return value_of(pw, assignment)
    parts = []
    for k in atoms[0].children:
        if k.rule == "dq_text":
            parts.append(k.text)
        elif k.rule == "variable":
            v = variable(pw, k.text)
            parts.append(v.replace("/", "\\") if v is not None else Dynamic(k, ""))
        elif k.rule == "dq_escape":
            parts.append(k.text[1:])
        else:
            parts.append(Dynamic(k, ""))
    return Field(parts, False, False)


def method_effects(rt, pw, stmt):
    """Calls that change what's after them: $PSDefaultParameterValues.Add(k,
    v) (Remove, Clear...), ...SessionState.Path.SetLocation(p) (its
    PushCurrentLocation, PopLocation)."""
    for kind in ("postfix_expr", "postfix_expr_arg"):
        for node in nodes_of(stmt, kind, []):
            kids = node.children
            for k in range(1, len(kids)):
                m = kids[k]
                if m.rule != "member" or k + 1 >= len(kids) or kids[k + 1].rule != "invoke":
                    continue
                method = fold(m.text.lstrip(".:"))
                args = [values.value(rt, pw, x) for x in kids[k + 1].children if x.rule == "expression"]
                if len(args) == 1 and isinstance(args[0], list):
                    args = args[0]
                receiver = fold(kids[0].text)
                if receiver == "$psdefaultparametervalues" and k == 1:
                    if method == "add" and len(args) == 2 and isinstance(args[0], str) \
                            and isinstance(args[1], str):
                        pw.defaults[fold(args[0])] = args[1]
                    elif method == "remove" and len(args) == 1 and isinstance(args[0], str):
                        pw.defaults.pop(fold(args[0]), None)
                    elif method != "containskey" and method != "containsvalue" and method != "tostring":
                        pw.defaults["?"] = True
                elif method == "setlocation" or method == "pushcurrentlocation" or method == "poplocation":
                    if method == "setlocation" and len(args) >= 1 and isinstance(args[0], str):
                        pw.cwd = paths.join(pw.cwd, args[0]) if pw.cwd is not None else None
                    else:
                        pw.cwd = None


# (the variable cmdlets and their aliases: a variable by its name)
VARIABLE_CMDLETS = {"get-variable", "gv", "set-variable", "sv", "set", "new-variable", "nv", "remove-variable", "rv",
                    "clear-variable", "clv"}


def has_param(bound, name):
    for b in bound:
        if b.name == name:
            return True
    return False


def location_stack(pw, bound):
    """The location stack -StackName names (folded), else the current one;
    "?": one only running tells."""
    for b in bound:
        if b.name == "StackName":
            if len(b.vals) == 1 and field_known(b.vals[0]):
                return fold(field_static(b.vals[0]))
            return "?"
    return pw.stack


def defaults_reached(pw, stmt):
    """$PSDefaultParameterValues reached other than by `$PSDefault...[k] =
    v` or its .Add / .Remove (as another variable, $d = it; through the
    variable: provider, $ExecutionContext...PSVariable): what's in it, only
    running tells."""
    text = fold(stmt.text)
    k = text.find("psdefaultparametervalues")
    if k >= 0 and text.find("psdefaultparametervalues", k + 1) < 0:
        lead = strip(text)
        if lead.startswith("$psdefaultparametervalues[") or lead.startswith("$psdefaultparametervalues.add(") \
                or lead.startswith("$psdefaultparametervalues.remove("):
            return
    if k >= 0 or "psvariable" in text:
        pw.defaults["?"] = True
        return
    for c in nodes_of(stmt, "command", []):
        # (Get-Variable PSDefault*, ('PSDefault' + ...): which variable,
        # maybe the table)
        words = fold(c.text).split()
        if len(words) > 1 and words[0] in VARIABLE_CMDLETS:
            rest = " ".join(words[1:])
            if "$" in rest or "(" in rest or "*" in rest or "?" in rest or "[" in rest:
                pw.defaults["?"] = True


def forget_changed(pw, stmt):
    """A variable a method is called on or given to ([Array]::Reverse($a),
    $list.Add(1)) may be changed in place: its value forgotten (one
    computed would be wrong)."""
    for kind in ("postfix_expr", "postfix_expr_arg"):
        for node in nodes_of(stmt, kind, []):
            calls = False
            for k in node.children:
                if k.rule == "invoke":
                    calls = True
            if not calls:
                continue
            for v in nodes_of(node, "variable", []):
                name = fold(strip_chars(v.text[1:], "{}"))
                if name in pw.vars:
                    pw.vars[name] = None


def default_key(var):
    """$PSDefaultParameterValues['Cmdlet:Param']'s key, folded."""
    for k in var.children:
        if k.rule == "index" and len(k.children) > 0:
            atoms = string_atoms(k)
            if len(atoms) == 1 and atoms[0].rule == "sq_string":
                return fold(sq_value(atoms[0].text))
            if len(atoms) == 1:
                v = dq_value(atoms[0])
                return fold(v) if v is not None else None
    return None


def is_plain_name(name):
    """ASCII letters and digits, _ and :, at least one letter or digit"""
    seen = False
    for c in name:
        if c == ":" or c == "_":
            continue
        if not ((c >= "a" and c <= "z") or (c >= "A" and c <= "Z") or (c >= "0" and c <= "9")):
            return False
        seen = True
    return seen


def value_of(pw, assignment):
    """The value assigned as a Field: a string with known variables
    expanded, else dynamic."""
    rhs = first_child(assignment, "statement")
    if rhs is None:
        return Field([Dynamic(assignment, "")], False, False)
    atoms = string_atoms(rhs)
    if len(atoms) == 1 and atoms[0].text == strip(rhs.text):
        return atom(pw, atoms[0])
    return Field([Dynamic(rhs, "")], False, False)


def constant(rt, assignment):
    """The value assigned if it's a plain string."""
    rhs = first_child(assignment, "statement")
    text = strip(rhs.text) if rhs is not None else ""
    try:
        t = parse(rt, text)
    except zgram.ParseError:
        return None
    except ValueError:
        return None
    atoms = string_atoms(t)
    if len(atoms) == 1 and atoms[0].text == text:
        n = atoms[0]
        return sq_value(text) if n.rule == "sq_string" else dq_value(n)
    return None


def command(rt, pw, node):
    span = span_of(pw, node)
    invocation = None
    name_field = None
    words = []
    reds = []
    verbatim_text = None
    for k in node.children:
        r = k.rule
        if r == "invocation":
            invocation = k.text
        elif r == "cmd_name" or r == "dash_cmd_name":
            name_field = Field([literal_word(k.text)], False, False)
        elif r == "redirection":
            red = redirect(rt, pw, k)
            if red is not None:
                reds.append(red)
        elif r == "stop_parsing":
            # (the rest of the line goes to the program as it is: split as
            # Windows programs split their command line)
            verbatim_text = k.children[0].text if len(k.children) > 0 else ""
            words.append(Word("verbatim", "", None, windows_argv(verbatim_text)))
        elif r == "parameter":
            pname = first_child(k, "pname").text
            arg = None
            for c in k.children:
                if c.rule == "argument" or c.rule == "argument_any":
                    arg = c
                    break
            words.append(Word("param", pname, fields(pw, arg) if arg is not None else None, []))
        elif r == "end_of_params":
            words.append(Word("dashdash", "", None, []))
        elif r == "argument" or r == "argument_any":
            words.append(Word("arg", "", fields(pw, k), []))
        elif name_field is None and invocation is not None:
            # (& and . call what follows)
            if r == "scriptblock":
                # (its commands are found where they are)
                return
            v = values.value(rt, pw, k)
            if isinstance(v, list) and len(v) == 1:
                v = v[0]
            if isinstance(v, values.Block):
                # (& $block, [scriptblock]::Create('...'): its code runs)
                code(rt, pw, v.text, span, "script block")
                return
            t = values.text_of(v) if v is not None else None
            name_field = Field([t], False, False) if t is not None and t != "" else atom(pw, k)
    if name_field is None:
        return
    argv_tail = []
    for w in words:
        if w.kind == "param":
            argv_tail.append(Field(["-" + w.name], False, False))
            if w.fields is not None and len(w.fields) > 0:
                argv_tail += w.fields
        elif w.kind == "arg":
            argv_tail += w.fields
        elif w.kind == "verbatim":
            for t in w.texts:
                argv_tail.append(Field([t], False, False))
        else:
            argv_tail.append(Field(["--"], False, False))
    if not field_known(name_field):
        pw.r.executions.append(execution([name_field] + argv_tail, {}, reds, pw.cwd, span, pw.via, None, "program"))
        return
    name = field_static(name_field)
    base = fold(paths.program_name(name))
    if base in pw.aliases and "/" not in name and "\\" not in name:
        # (an alias Set-Alias made: the command it names)
        if pw.aliases[base] is None:
            pw.r.executions.append(execution([name_field] + argv_tail, {}, reds, pw.cwd, span, pw.via, None, "program"))
            note(rt, pw, name + ": an alias for what only running tells", span, "code", [])
            return
        name = pw.aliases[base]
        name_field = Field([name], False, False)
        base = fold(paths.program_name(name))
    if base == "set-alias" or base == "sal" or base == "new-alias" or base == "nal":
        record_alias(pw, words)
    if fold(name).endswith(".ps1"):
        pw.r.executions.append(execution([name_field] + argv_tail, {}, reds, pw.cwd, span, pw.via, None, "program"))
        note(rt, pw, "runs the PowerShell script " + name, span, "code_file", [name_field])
        return
    if "\\" in name and "/" not in name and ":" not in name and "." in name.partition("\\")[0]:
        # (a module's cmdlet: Microsoft.PowerShell.Management\New-Item)
        name = name.rpartition("\\")[2]
        base = fold(name)
        name_field = Field([name], False, False)
    canonical = base
    if "/" not in name and "\\" not in name and base in ALIASES:
        canonical = ALIASES[base]
    if canonical in CMDLETS:
        cmdlet(rt, pw, CMDLETS[canonical], words, reds, span)
        return
    native(rt, pw, name_field, argv_tail, command_line(words, verbatim_text), reds, span, pw.via)


def record_alias(pw, words):
    """Set-Alias [-Name] N [-Value] V: N names V from here (a parameter
    not given: $PSDefaultParameterValues' 'Set-Alias:Name' and the like)."""
    given = {}
    positional = []
    pending = None
    for w in words:
        if w.kind == "param":
            p = fold(w.name)
            key = "name" if "name".startswith(p) else ("value" if "value".startswith(p) else None)
            if w.fields is not None and len(w.fields) > 0:
                if key is not None:
                    given[key] = w.fields[0]
            else:
                pending = key
        elif w.kind == "arg" and len(w.fields) > 0:
            if pending is not None:
                given[pending] = w.fields[0]
                pending = None
            else:
                positional.append(w.fields[0])
    for key in ("name", "value"):
        if key not in given and len(positional) > 0:
            given[key] = positional.pop(0)
    out = {}
    for key in ("name", "value"):
        if key in given:
            if not field_known(given[key]):
                if key == "value" and "name" in out:
                    # (an alias for what only running tells)
                    pw.aliases[fold(out["name"])] = None
                return
            out[key] = field_static(given[key])
        else:
            found = None
            for prefix in ("set-alias:", "new-alias:", "*:"):
                if prefix + key in pw.defaults:
                    found = pw.defaults[prefix + key]
                    break
            if found is None:
                return
            out[key] = found
    pw.aliases[fold(out["name"])] = out["value"]


def quote_arg(s):
    if (s == "" or " " in s or "\t" in s) and not s.startswith('"'):
        return '"' + s + '"'
    return s


def command_line(words, verbatim_text):
    """The command line PowerShell 5.1 gives a native program: the
    arguments, quoted when they have blanks, then what --% left as it is
    (None: some only running tells)."""
    out = []
    for w in words:
        if w.kind == "verbatim":
            out.append(verbatim_text if verbatim_text is not None else "")
            continue
        if w.kind == "dashdash":
            out.append("--")
            continue
        given = w.fields if w.kind == "arg" else [Field(["-" + w.name], False, False)] + (
            w.fields if w.fields is not None else [])
        for f in given:
            if not field_known(f):
                return None
            out.append(quote_arg(field_static(f)))
    return " ".join(out)


def native(rt, pw, name_field, argv_tail, line, reds, span, via):
    """A program: cmd.exe and powershell.exe read their command line; the
    others through bash's specs and wrappers."""
    base = fold(paths.program_name(field_static(name_field)))
    if base in POWERSHELLS:
        if line is not None:
            argv_tail = [Field([w], False, False) for w in windows_argv(line)]
        e = execution([name_field] + argv_tail, {}, reds, pw.cwd, span, via, None, "program")
        pw.r.executions.append(e)
        powershell(rt, pw, e, argv_tail, span)
        return
    if base in LAUNCHERS:
        # (cmd /c, forfiles, wmic, rundll32...: read as cmd reads them)
        if line is None:
            pw.r.executions.append(execution([name_field] + argv_tail, {}, reds, pw.cwd, span, via, None, "program"))
            note(rt, pw, base + " with arguments only running tells", span, "code", [])
            return
        launch(rt, pw.r, pw.home, pw.depth + 1, via, pw.cwd, field_static(name_field), line, reds, span)
        return
    # (a native program: bash's specs and wrappers know it)
    run(rt, pw.bash, [name_field] + argv_tail, {}, reds, ctx_of(pw), span, None, via)


def redirect(rt, pw, node):
    inner = node.children[0]
    t = strip(node.text)
    if inner.rule == "merging":
        return None
    fd = t[0] if t[0] in "*123456" else None
    op = ">>" if ">>" in t else ">"
    if len(inner.children) == 0:
        return None
    target = inner.children[0]
    if fold(target.text) == "$null":
        return None
    return Redirect(fd, op, atom(pw, target), None)


def fields(pw, node):
    """An argument's values (an array a,b: each)."""
    out = []
    for a in node.children:
        out.append(atom(pw, a))
    return out


def atom(pw, n):
    r = n.rule
    if r == "bareword" or r == "bareword_any":
        v = bareword_value(n)
        if v is not None:
            return Field([home_path(pw, v)], False, False)
        return expandable(pw, n)
    if r == "sq_string":
        return Field([sq_value(n.text)], False, False)
    if r == "dq_string":
        v = dq_value(n)
        return Field([v], False, False) if v is not None else expandable(pw, n)
    if r == "here_sq" or r == "here_dq":
        v = here_value(n)
        return Field([v], False, False) if v is not None else Field([Dynamic(n, "")], False, False)
    if r == "number":
        return Field([n.text], False, False)
    if r == "postfix_expr_arg" and len(n.children) > 0:
        first = n.children[0]
        if first.rule == "variable" and first.text == n.text:
            v = variable(pw, first.text)
            if v is not None:
                return Field([v], False, False)
        # (a value built from pieces: ('C:\Users\x\'+'project'); an array,
        # several values for one argument: not one path)
        v = values.value(None, pw, n)
        if isinstance(v, str) or isinstance(v, int):
            return Field([values.text_of(v)], False, False)
    return Field([Dynamic(n, "")], False, False)


def home_path(pw, v):
    # (~ at a path's start: the home)
    if pw.home is not None and pw.home != "" and (v == "~" or v.startswith("~/") or v.startswith("~\\")):
        return pw.home + v[1:]
    return v


def expandable(pw, n):
    """A word or "string" with $variables: its value when they're known."""
    text = n.text
    found = nodes_of(n, "variable", [])
    if len(found) == 0 or "$(" in text or "@(" in text or "`" in text:
        # (a subexpression: what it gives only running tells; escapes next
        # to variables: not worth guessing)
        return Field([Dynamic(n, "")], False, False)
    value = text
    for k in found:
        v = variable(pw, k.text)
        if v is None:
            return Field([Dynamic(n, "")], False, False)
        value = replace_first(value, k.text, v)
    if n.rule == "dq_string":
        value = unquote(value)
    return Field([value], False, False)


def variable(pw, text):
    """A variable's value if known: one assigned a string before; the home;
    $env:USERPROFILE, $env:HOME; Windows' own."""
    name = fold(strip_chars(text[1:], "{}"))
    known_home = pw.home is not None and pw.home != ""
    if (name == "home" or name == "env:userprofile" or name == "env:home") and known_home:
        return pw.home
    if name == "profile" and known_home:
        return pw.home + "/Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1"
    if (name == "env:temp" or name == "env:tmp") and known_home and paths.is_windows(pw.home):
        return pw.home + "/AppData/Local/Temp"
    if name in pw.vars:
        v = pw.vars[name]
        return v if isinstance(v, str) else None
    if name.startswith("env:") and known_home and paths.is_windows(pw.home):
        env = default_env(pw.home, None)
        key = fold_upper(name[4:])
        return env[key].replace("\\", "/") if key in env else None
    return None


def default_value(pw, cmdlet_name, param):
    """$PSDefaultParameterValues' value for Cmdlet:Param (a key with
    wildcards, *:Param, too), or None."""
    want = fold(cmdlet_name) + ":" + fold(param)
    if want in pw.defaults:
        return pw.defaults[want]
    for key, v in pw.defaults.items():
        name, _, p = key.partition(":")
        if ("*" in name or "?" in name or "*" in p) and match(fold(cmdlet_name), name) and match(fold(param), p):
            return v
    return None


def downloads_in(f):
    """The downloading command a value only running tells comes from
    ((Invoke-WebRequest ...).Content, $(iwr ...)), or None."""
    for p in f.parts:
        if isinstance(p, Dynamic) and p.node is not None:
            found = downloader_under(p.node)
            if found is not None:
                return found
    return None


def downloader_under(node):
    """The first downloading command in a node (a cmdlet's alias too)."""
    for c in nodes_of(node, "command", []):
        for k in c.children:
            if k.rule == "cmd_name":
                n = fold(literal_word(k.text))
                n = ALIASES[n] if n in ALIASES else n
                for d in DOWNLOADING:
                    if fold(d) == n:
                        return d
    return None


def variable_value(pw, text):
    """A variable's value as values.py has them (a list, a script block, a
    command...), else as variable() knows it."""
    name = fold(strip_chars(text[1:], "{}"))
    if name in pw.vars and not isinstance(pw.vars[name], str):
        return pw.vars[name]
    return variable(pw, text)


@dataclass
class Bound:
    name: object
    role: object
    vals: list


def cmdlet(rt, pw, c, words, reds, span):
    """A cmdlet's parameters bound: by name (a prefix naming only one), then
    the rest by position."""
    bound = []
    positional = []
    argv = [Field([c.name], False, False)]
    pending = None
    for w in words:
        if w.kind == "param":
            full = param_name(c, w.name)
            argv.append(Field(["-" + (full if full is not None else w.name)], False, False))
            prole = None
            if full is not None:
                prole = c.params[full] if full in c.params else (COMMON_PARAMS[full] if full in COMMON_PARAMS else None)
            if w.fields is not None and len(w.fields) > 0:
                argv += w.fields
                bound.append(Bound(full, prole, w.fields))
            elif prole is not None and prole != "flag":
                pending = Bound(full, prole, [])
            continue
        vals = w.fields if w.kind == "arg" else [Field([t], False, False) for t in w.texts]
        argv += vals
        if pending is not None:
            bound.append(Bound(pending.name, pending.role, vals))
            pending = None
        else:
            positional.append(vals)
    named = []
    for b in bound:
        named.append(b.name)
    free = []
    for p in c.positional:
        if p not in named:
            free.append(p)
    for k in range(min(len(free), len(positional))):
        bound.append(Bound(free[k], c.params[free[k]] if free[k] in c.params else None, positional[k]))
    # ($PSDefaultParameterValues: what a parameter not given is)
    named = [b.name for b in bound]
    if "?" in pw.defaults:
        note(rt, pw, c.name + ": default parameter values set in a way only running tells", span, "code", [])
    for p in c.params:
        if p not in named:
            v = default_value(pw, c.name, p)
            if v is not None:
                bound.append(Bound(p, c.params[p], [Field([v], False, False)]))
    stack =location_stack(pw, bound) if c.name == "Push-Location" or c.name == "Pop-Location" \
        or c.name == "Set-Location" else ""
    if c.name == "Push-Location":
        if stack not in pw.locations:
            pw.locations[stack] = []
        pw.locations[stack].append(pw.cwd)
    e = Execution(argv, {}, reds, pw.cwd, span, pw.via, None, "program", [], [], True, c.readonly)
    pw.r.executions.append(e)
    if c.name == "Pop-Location":
        # (back where the last Push-Location on its stack was; none: only
        # running tells)
        if stack in pw.locations and len(pw.locations[stack]) > 0:
            pw.cwd = pw.locations[stack].pop()
        else:
            pw.cwd = None
    if c.name == "Set-Location" and has_param(bound, "StackName"):
        # (Set-Location -StackName S: S the stack Push-Location and
        # Pop-Location use from then on)
        pw.stack = stack
    if c.name == "New-Item":
        kind = None
        for b in bound:
            if b.name == "ItemType" and len(b.vals) > 0 and field_known(b.vals[0]):
                kind = fold(field_static(b.vals[0]))
        if kind == "symboliclink" or kind == "junction" or kind == "hardlink":
            # (a link: what's done through it is done to its target)
            for b in bound:
                if b.name == "Value" or b.name == "Target":
                    for f in b.vals:
                        e.roles.append(Role("read", f, "-" + b.name))
                        e.roles.append(Role("write", f, "-" + b.name))
    if len(positional) > len(free) or (pending is not None and pending.role != "plain"):
        # (arguments vetter can't bind: what they are only running tells)
        note(rt, pw, c.name + ": arguments vetter can't bind to its parameters", span, "code", [])
    program = None
    for b in bound:
        if b.role == "program":
            program = b.vals
            break
    if program is not None and len(program) > 0:
        # (Start-Process: the program with its -ArgumentList, joined with
        # blanks into its command line)
        given = []
        for b in bound:
            if b.role == "program_args":
                given += b.vals
        line = None
        all_known = True
        texts = []
        for f in given:
            if not field_known(f):
                all_known = False
                break
            texts.append(field_static(f))
        if all_known:
            line = " ".join(texts)
        args = [Field([t], False, False) for t in windows_argv(line)] if line is not None else given
        elevated = False
        for b in bound:
            if b.role == "elevates":
                for f in b.vals:
                    if field_known(f) and fold(field_static(f)) == "runas":
                        elevated = True
        name = exec_name(e)
        if elevated:
            # (-Verb RunAs: what it starts runs elevated)
            pw.r.executions.append(execution([Field(["runas"], False, False)], {}, [], pw.cwd, span, pw.via + (name,),
                                             None, "program"))
        if field_known(program[0]):
            native(rt, pw, program[0], args, line, [], span, pw.via + (name,))
        else:
            note(rt, pw, str(name) + ": a program only running tells", span, "code", [])
    for b in bound:
        if b.role == "program" or b.role == "program_args":
            continue
        for f in b.vals:
            role(rt, pw, e, b.name, b.role, f, span)


def _param_names(c):
    """A cmdlet's parameters, then the common ones it doesn't have: each
    (folded, name), in that order"""
    names = list(c.params) + [n for n in COMMON_PARAMS if n not in c.params]
    return tuple((fold(n), n) for n in names)


# (each cmdlet's, folded once: param_name compares with them)
PARAM_NAMES = {c.name: _param_names(c) for c in CMDLETS.values()}


def param_name(c, given):
    given = fold(given)
    if given in COMMON_ALIASES:
        return COMMON_ALIASES[given]
    if given in c.param_aliases:
        return c.param_aliases[given]
    names = PARAM_NAMES[c.name]
    for folded, n in names:
        if folded == given:
            return n
    # (a prefix naming only one)
    hit = None
    count = 0
    for folded, n in names:
        if folded.startswith(given):
            hit = n
            count += 1
    return hit if count == 1 else None


def role(rt, pw, e, pname, r, f, span):
    name = exec_name(e)
    if r == "write" or r == "read" or r == "delete" or r == "url":
        e.roles.append(Role(r, f, "-" + str(pname)))
        if r == "write" and (name == "Invoke-WebRequest" or name == "Invoke-RestMethod" or name == "Start-BitsTransfer"):
            downloaded(rt, pw.bash, e, f)
    elif r == "send_data":
        e.roles.append(Role("send", f, "-" + str(pname)))
    elif r == "cwd":
        pw.cwd = paths.join(pw.cwd, field_static(f)) if field_known(f) else None
    elif r == "pwsh":
        if field_known(f):
            code(rt, pw, field_static(f), span, str(name))
        elif downloads_in(f) is not None:
            # (iex (Invoke-WebRequest ...).Content: what it downloads)
            note(rt, pw, str(name) + " runs what " + str(downloads_in(f)) + " downloads", span, "downloaded_code", [])
        else:
            note(rt, pw, str(name) + ": PowerShell code only running tells", span, "code", [])
    elif r == "code_file":
        note(rt, pw, str(name) + ": runs the code in " + field_text(f), span, "code_file", [f])
    elif r == "package":
        note(rt, pw, str(name) + ": loads the module " + field_text(f), span, "package", [])
    elif r == "configures":
        note(rt, pw, str(name) + " -" + str(pname) + ": changes what Windows lets run", span, "persistent", [])


def code(rt, pw, text, span, label):
    if pw.depth >= MAX_DEPTH:
        note(rt, pw, label + ": nested too deep", span, "code", [])
        return
    try:
        inner = walker(pw.r, pw.home, pw.depth + 1)
        inner.vars = {k: v for k, v in pw.vars.items()}
        inner.env = {k: v for k, v in pw.env.items()}
        inner.aliases = pw.aliases
        inner.defaults = pw.defaults
        tree = parse(rt, text)
        # (what runs inside is pointed at where the outer command is)
        executions = len(pw.r.executions)
        unknowns = len(pw.r.unknowns)
        script(rt, inner, tree, pw.cwd, pw.via + (label,), text)
        for e in pw.r.executions[executions:]:
            e.span = span
        for u in pw.r.unknowns[unknowns:]:
            u.span = span
    except zgram.ParseError as ex:
        note(rt, pw, label + ": not PowerShell vetter can read (" + str(ex) + ")", span, "code", [])
    except ValueError as ex:
        why = str(ex)
        if why.startswith("unreadable: "):
            why = why[12:]
        note(rt, pw, label + ": not PowerShell vetter can read (" + why + ")", span, "code", [])


def ps_option(opt):
    """powershell.exe's option a word names (an alias, or a prefix naming
    only one), else None."""
    opt = fold(opt)
    if opt in PS_ALIASES:
        return PS_ALIASES[opt]
    hits = []
    for o in PS_OPTIONS:
        if o.startswith(opt):
            hits.append(o)
    return hits[0] if len(hits) == 1 else None


def powershell(rt, pw, e, args, span):
    """powershell -Command TEXT / -EncodedCommand B64 / -File F / TEXT;
    then, with -NoExit, `-Command -` or none, the commands on its stdin."""
    launched(rt, pw, args, span)
    if e.stdin is not None and ps_reads_stdin(args):
        ps_stdin(rt, pw, e, span)


def ps_reads_stdin(args):
    """Does powershell read commands from its stdin: -NoExit, -Command -,
    -File -, or no command given?"""
    i = 0
    while i < len(args):
        s = fold(field_static(args[i])) if field_known(args[i]) else None
        nxt = field_static(args[i + 1]) if i + 1 < len(args) and field_known(args[i + 1]) else None
        if s is None:
            return True
        if not ((s.startswith("-") or s.startswith("/")) and len(s) > 1):
            return False
        opt = ps_option(s[1:])
        if opt == "noexit":
            return True
        if opt == "command" or opt == "file":
            return nxt == "-" or nxt is None
        if opt == "encodedcommand":
            return False
        i += 2 if opt in PS_VALUED else 1
    return True


def ps_stdin(rt, pw, e, span):
    if e.stdin.text is not None:
        code(rt, pw, e.stdin.text, span, "powershell (its stdin)")
    elif downloads_into(e):
        note(rt, pw, "powershell runs what " + str(exec_name(e.stdin.producer)) + " downloads, on its stdin", span,
             "downloaded_code", [])
    else:
        note(rt, pw, "powershell reads more commands from its stdin, which only running tells", span, "inline_code",
             [])


def downloads_into(e):
    """Is what's piped into it a download's?"""
    p = e.stdin.producer if e.stdin is not None else None
    return p is not None and (exec_name(p) in DOWNLOADING or exec_name(p) in BASH_DOWNLOADERS)


def launched(rt, pw, args, span):
    i = 0
    while i < len(args):
        a = args[i]
        s = fold(field_static(a)) if field_known(a) else None
        nxt = args[i + 1] if i + 1 < len(args) else None
        if s is None:
            note(rt, pw, "powershell with arguments only running tells", span, "code", [])
            return
        if (s.startswith("-") or s.startswith("/")) and len(s) > 1:
            opt = ps_option(s[1:])
            if opt is None:
                note(rt, pw, "powershell " + field_static(a) + ": an option vetter doesn't know", span, "code", [])
                return
            if opt == "encodedcommand":
                if nxt is None or not field_known(nxt):
                    note(rt, pw, "powershell -EncodedCommand only running tells", span, "code", [])
                    return
                text = None
                data = b64decode(field_static(nxt))
                if data is not None:
                    text = utf16le(data)
                if text is None:
                    note(rt, pw, "powershell -EncodedCommand: not base64 of UTF-16", span, "code", [])
                    return
                code(rt, pw, text, span, "powershell -EncodedCommand")
                return
            if opt == "command":
                rest = args[i + 1 :]
                texts = []
                known = True
                for f in rest:
                    if not field_known(f):
                        known = False
                        break
                    texts.append(field_static(f))
                if texts == ["-"]:
                    # (-Command -: its stdin's, ps_stdin)
                    return
                if len(rest) > 0 and known:
                    code(rt, pw, " ".join(texts), span, "powershell -Command")
                elif len(rest) > 0:
                    note(rt, pw, "powershell -Command: code only running tells", span, "code", [])
                return
            if opt == "file":
                if nxt is not None and not (field_known(nxt) and field_static(nxt) == "-"):
                    note(rt, pw, "powershell -File: runs the code in " + field_text(nxt), span, "code_file", [nxt])
                return
            i += 2 if opt in PS_VALUED else 1
            continue
        # (the rest is the command)
        rest = args[i:]
        texts = []
        for f in rest:
            if not field_known(f):
                note(rt, pw, "powershell: code only running tells", span, "code", [])
                return
            texts.append(field_static(f))
        code(rt, pw, " ".join(texts), span, "powershell")
        return


def windows_argv(line):
    """A command line split as Windows programs split it
    (CommandLineToArgvW): quotes group, backslashes before a quote escape
    it, "" in quotes is a quote."""
    out = []
    cur = ""
    has = False
    quoted = False
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c == "\\":
            j = i
            while j < n and line[j] == "\\":
                j += 1
            k = j - i
            if j < n and line[j] == '"':
                cur += "\\" * (k // 2)
                if k % 2 == 1:
                    cur += '"'
                    i = j + 1
                else:
                    i = j
                has = True
                continue
            cur += "\\" * k
            i = j
            has = True
            continue
        if c == '"':
            if quoted and i + 1 < n and line[i + 1] == '"':
                cur += '"'
                i += 2
                continue
            quoted = not quoted
            has = True
            i += 1
            continue
        if (c == " " or c == "\t") and not quoted:
            if has:
                out.append(cur)
                cur = ""
                has = False
            i += 1
            continue
        cur += c
        has = True
        i += 1
    if has:
        out.append(cur)
    return out


B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def b64decode(s):
    """base64.b64decode(s, validate=False) (binascii's a2b_base64, not
    strict): the bytes (a list of ints), or None where it raises."""
    out = []
    quad = 0
    left = 0
    pads = 0
    for c in s:
        if ord(c) > 127:
            # (a str of more than ASCII: ValueError)
            return None
        if c == "=":
            if quad >= 2:
                pads += 1
                if quad + pads >= 4:
                    # (a pad sequence: no more input read)
                    return out
            continue
        v = B64.find(c)
        if v < 0:
            continue
        pads = 0
        if quad == 0:
            quad = 1
            left = v
        elif quad == 1:
            quad = 2
            out.append(((left << 2) | (v >> 4)) & 0xFF)
            left = v & 0x0F
        elif quad == 2:
            quad = 3
            out.append(((left << 4) | (v >> 2)) & 0xFF)
            left = v & 0x03
        else:
            quad = 0
            out.append(((left << 6) | v) & 0xFF)
            left = 0
    if quad != 0:
        return None
    return out


def utf16le(data):
    """bytes(data).decode("utf-16-le"), or None where it raises."""
    if len(data) % 2 == 1:
        return None
    out = ""
    i = 0
    n = len(data)
    while i < n:
        u = data[i] | (data[i + 1] << 8)
        i += 2
        if u < 0xD800 or u > 0xDFFF:
            out += chr(u)
        elif u <= 0xDBFF:
            if i + 1 >= n:
                return None
            u2 = data[i] | (data[i + 1] << 8)
            if u2 < 0xDC00 or u2 > 0xDFFF:
                return None
            i += 2
            out += chr(0x10000 + ((u - 0xD800) << 10) + (u2 - 0xDC00))
        else:
            return None
    return out
