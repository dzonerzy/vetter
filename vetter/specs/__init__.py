"""The command specs (the *.toml here, see README.md): what a program's
arguments are. apply_specs reads an execution's arguments with its
program's spec: the files it writes, reads and deletes, the URLs it talks
to (Role records in its roles), what it runs read and resolved.

The tables are records made from load.py's when this module is imported
(Python's tomllib reads the files): constants of the compiled code,
carried in a standalone program's image.

    apply_specs(rt, w, e, ctx)
"""

from dataclasses import dataclass

from ..glob import match
from ..shells.bash.expand import Dynamic, Field, field_known, field_static, field_text
from . import load as py_specs


@dataclass
class Role:
    """What an argument is to the program: role (write, read, delete, url,
    cwd...), its value (a Field), the option it came with (None: an
    operand)."""

    role: str
    value: object
    option: object


@dataclass
class Flag:
    """A flag (a subcommand, the program itself) doing what vetter doesn't
    see: why, and the Unknown's kind."""

    reason: str
    kind: str


@dataclass
class Spec:
    names: list
    roles: dict
    values: set
    flags: dict
    # (a kind: plain, read, sed, git_config_set...; "pattern": by position,
    # `pattern` each operand's role, one ending in * the rest's)
    operands: str
    pattern: list
    subcommands: bool
    stop_at_operand: bool
    single_dash_long: bool
    slash_options: bool
    readonly: bool
    config: dict
    sub: dict
    commands: set
    # (an interpreter: with no program given, its program is on stdin)
    stdin_program: bool
    # (options whose value may be glued to them: -B/dir, -ofile)
    attached: list
    # (options taken wherever they are (after a subcommand too): their roles)
    anywhere: dict
    # (an operand @file: more options read from the file)
    response_files: bool
    # (options giving what the first operand is otherwise (grep -e PATTERN):
    # one given, every operand has the role after it)
    pattern_options: list


def _spec(s):
    flags = {}
    for k, v in s.flags.items():
        if isinstance(v, dict):
            flags[k] = Flag(v.get("reason", ""), v.get("kind", "configured"))
        else:
            flags[k] = Flag(v, "configured")
    pattern = list(s.operands) if isinstance(s.operands, list) else []
    return Spec(list(s.names), dict(s.roles), set(s.values), flags, "pattern" if pattern else s.operands, pattern,
                bool(s.subcommands), bool(s.stop_at_operand), bool(s.single_dash_long), bool(s.slash_options),
                bool(s.readonly), dict(s.config), {k: _spec(v) for k, v in s.sub.items()}, set(s.commands),
                bool(s.stdin_program), list(s.attached), dict(s.anywhere), bool(s.response_files),
                list(s.pattern_options))


SPECS = {name: _spec(s) for name, s in py_specs.SPECS.items()}
ENV = dict(py_specs.ENV)
EMPTY = _spec(py_specs.Spec({}))

DOWNLOADERS = {"curl", "wget", "fetch", "aria2c", "http", "xh"}

HIVES = {"hkcu": "HKCU", "hkey_current_user": "HKCU", "hklm": "HKLM", "hkey_local_machine": "HKLM",
         "hkcr": "HKCR", "hkey_classes_root": "HKCR", "hku": "HKU", "hkey_users": "HKU", "hkcc": "HKCC",
         "hkey_current_config": "HKCC"}

# (str.isspace's characters: what Python's strip() and re's \s take)
SPACES = "\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0          " \
         "      　"


# ----------------------------------------------------------------------
# Small readers (what specs/__init__.py does with re)
# ----------------------------------------------------------------------


def is_space(c):
    return c in SPACES


def strip(s):
    i = 0
    j = len(s)
    while i < j and is_space(s[i]):
        i += 1
    while j > i and is_space(s[j - 1]):
        j -= 1
    return s[i:j]


def lstrip_chars(s, chars):
    i = 0
    while i < len(s) and s[i] in chars:
        i += 1
    return s[i:]


def ascii_lower(s):
    out = ""
    for c in s:
        if c >= "A" and c <= "Z":
            out += chr(ord(c) + 32)
        else:
            out += c
    return out


def is_alpha(c):
    return (c >= "a" and c <= "z") or (c >= "A" and c <= "Z")


def is_word(c):
    return is_alpha(c) or (c >= "0" and c <= "9") or c == "_"


def is_slash_option(s):
    """/[A-Za-z?]+(:|$) at the start"""
    if s[:1] != "/":
        return False
    i = 1
    while i < len(s) and (is_alpha(s[i]) or s[i] == "?"):
        i += 1
    return i > 1 and (i == len(s) or s[i] == ":")


def is_remote(s):
    """A URL (scheme://) or a UNC share (\\\\)"""
    if s[:2] == "\\\\":
        return True
    if len(s) == 0 or not is_alpha(s[0]):
        return False
    i = 1
    while i < len(s) and (is_alpha(s[i]) or (s[i] >= "0" and s[i] <= "9") or s[i] == "+" or s[i] == "." or s[i] == "-"):
        i += 1
    return s[i : i + 3] == "://"


def last_word(s):
    words = []
    w = ""
    for c in s:
        if is_space(c):
            if w != "":
                words.append(w)
            w = ""
        else:
            w += c
    if w != "":
        words.append(w)
    return words[len(words) - 1]


def joined(a, b):
    """' '.join(filter(None, (a, b)))"""
    if a is None or a == "":
        return b if b is not None else ""
    if b is None or b == "":
        return a
    return a + " " + b


def labelled(name, option):
    """f"{name} {option or ''}".strip()"""
    return strip((name if name is not None else "None") + " " + (option if option is not None else ""))


def config_role(spec, key):
    key = ascii_lower(key)
    if key in spec.config:
        return spec.config[key]
    for pat, role in spec.config.items():
        if "*" in pat and match(key, pat):
            return role
    return None


# ----------------------------------------------------------------------
# Reading the arguments
# ----------------------------------------------------------------------


@dataclass
class Parsed:
    """options: [(name, value Field or None)], operands, the index after."""

    options: list
    operands: list
    end: int


def parse(args, spec):
    options = []
    operands = []
    i = 0
    dd = False
    while i < len(args):
        a = args[i]
        s = field_static(a) if field_known(a) else None
        if spec.slash_options and s is not None and is_slash_option(s):
            # (Windows' /i, /G:file: case doesn't matter; a value after the colon)
            name, colon, val = s.partition(":")
            name = ascii_lower(name)
            if colon != "":
                options.append((name, Field([val], False, False)))
                i += 1
            elif name in spec.values:
                options.append((name, args[i + 1] if i + 1 < len(args) else None))
                i += 2
            else:
                options.append((name, None))
                i += 1
            continue
        if dd or s is None or not s.startswith("-") or s == "-":
            operands.append(a)
            i += 1
            if spec.stop_at_operand:
                break
            continue
        if s == "--":
            dd = True
            i += 1
            continue
        # (-B/dir, -ofile: a value glued to its option)
        glued = None
        for pre in spec.attached:
            if glued is None and s.startswith(pre) and len(s) > len(pre):
                glued = pre
        if glued is not None:
            options.append((glued, Field([s[len(glued):]], False, False)))
            i += 1
            continue
        name, eq, val = s.partition("=")
        if name in spec.values and (s.startswith("--") or len(name) > 2 or eq == ""):
            # (--opt=value, --opt value, -opt value: go's single-dash long ones)
            if eq != "":
                options.append((name, Field([val], False, False)))
                i += 1
            else:
                options.append((name, args[i + 1] if i + 1 < len(args) else None))
                i += 2
            continue
        if s.startswith("--") or len(s) == 2 or spec.single_dash_long or s in spec.flags:
            # (find's and go's options are words: -delete isn't -d -e -l...)
            if eq != "":
                options.append((name, Field([val], False, False)))
            else:
                options.append((s, None))
            i += 1
            continue
        # (clustered short options: -rf, -ofile)
        consumed = False
        for k in range(1, len(s)):
            opt = "-" + s[k]
            if opt in spec.values:
                rest = s[k + 1 :]
                if rest != "":
                    options.append((opt, Field([rest], False, False)))
                    i += 1
                else:
                    options.append((opt, args[i + 1] if i + 1 < len(args) else None))
                    i += 2
                consumed = True
                break
            options.append((opt, None))
        if not consumed:
            i += 1
    return Parsed(options, operands, i)


def operand_roles(spec, operands):
    """Each operand's role from the spec's `operands`: (role, operand)."""
    if spec.operands != "pattern":
        return [(spec.operands, o) for o in operands]
    pattern = spec.pattern
    star = -1
    for k in range(len(pattern)):
        if pattern[k].endswith("*"):
            star = k
            break
    out = []
    if star < 0:
        for k in range(len(operands)):
            out.append((pattern[k] if k < len(pattern) else "plain", operands[k]))
        return out
    before = pattern[:star]
    after = pattern[star + 1 :]
    rest_role = pattern[star][: len(pattern[star]) - 1]
    n = len(operands)
    for k in range(n):
        o = operands[k]
        if k < len(before):
            out.append((before[k], o))
        elif k >= n - len(after) and n - len(after) >= len(before):
            out.append((after[k - (n - len(after))], o))
        else:
            out.append((rest_role, o))
    return out


# ----------------------------------------------------------------------
# Applying
# ----------------------------------------------------------------------


def anywhere_options(rt, w, e, ctx, spec, args):
    """The spec's options taken wherever they are (cargo's --config after
    its subcommand): `--opt value`, `--opt=value`."""
    k = 0
    while k < len(args):
        a = args[k]
        if field_known(a):
            s = field_static(a)
            if s == "--":
                return
            name, eq, val = s.partition("=")
            if name in spec.anywhere:
                if eq != "":
                    role(rt, w, e, ctx, spec.anywhere[name], Field([val], False, False), name, spec)
                elif k + 1 < len(args):
                    role(rt, w, e, ctx, spec.anywhere[name], args[k + 1], name, spec)
                    k += 1
        k += 1


# cmake -E's commands: the program each is (what it runs, deletes, writes)
CMAKE_COMMANDS = {"env": ["env"], "time": ["time"], "rm": ["rm"], "remove": ["rm", "-f"],
                  "remove_directory": ["rm", "-rf"], "copy": ["cp"], "copy_directory": ["cp", "-r"],
                  "copy_if_different": ["cp"], "rename": ["mv"], "make_directory": ["mkdir", "-p"],
                  "touch": ["touch"], "touch_nocreate": ["touch", "-c"], "cat": ["cat"], "create_symlink": ["ln", "-s"],
                  "create_hardlink": ["ln"], "tar": ["tar"], "echo": ["echo"], "echo_append": ["echo", "-n"],
                  "true": ["true"], "false": ["false"], "sleep": ["sleep"], "md5sum": ["md5sum"],
                  "sha256sum": ["sha256sum"], "compare_files": ["cmp"]}


def cmake_command(rt, w, e, ctx, args):
    """cmake -E COMMAND ARGS: its command decided as the program it is
    (env, time and chdir run what follows)."""
    from ..shells.bash.resolve import inner, unknown

    if len(args) == 0 or not field_known(args[0]):
        unknown(rt, w, "cmake -E of a command only running tells", e.span, ctx, "code", [])
        return
    cmd = field_static(args[0])
    rest = args[1:]
    if cmd == "chdir":
        if len(rest) >= 2 and field_known(rest[0]):
            inner(rt, w, e, rest[1:], ctx, "cmake -E chdir " + field_static(rest[0]), {})
        else:
            unknown(rt, w, "cmake -E chdir: a command only running tells", e.span, ctx, "code", [])
        return
    if cmd not in CMAKE_COMMANDS:
        # (the others only say things: capabilities, environment, server)
        return
    words = [Field([x], False, False) for x in CMAKE_COMMANDS[cmd]]
    inner(rt, w, e, words + rest, ctx, "cmake -E " + cmd, {})


def apply_specs(rt, w, e, ctx):
    """The execution's roles from its spec, and what its arguments and
    environment run."""
    from ..shells.bash.resolve import exec_name, unknown

    apply_env(rt, w, e, ctx)
    name = exec_name(e)
    if name is None or name not in SPECS:
        return
    spec = SPECS[name]
    args = e.argv[1:]
    if name == "cmake" and len(args) > 0 and field_known(args[0]) and field_static(args[0]) == "-E":
        cmake_command(rt, w, e, ctx, args[1:])
        return
    anywhere_options(rt, w, e, ctx, spec, args)
    if spec.response_files:
        for a in args:
            if field_known(a) and field_static(a).startswith("@") and len(field_static(a)) > 1:
                f = Field([field_static(a)[1:]], False, False)
                e.roles.append(Role("read", f, None))
                unknown(rt, w, name + " " + field_static(a) + ": options read from a file", e.span, ctx, "code_file", [f])
    p = parse(args, spec)
    rest = args[p.end :]
    if name in spec.flags:
        flag(rt, w, e, ctx, name, spec.flags[name], [])
    # (find's starting points: the operands before its expression)
    starts = []
    for a in args:
        if field_known(a):
            s = field_static(a)
            if s.startswith("-") or s.startswith("(") or s.startswith("!") or s == ")":
                break
        starts.append(a)
    apply_options(rt, w, e, ctx, spec, p.options, None, starts)
    if spec.subcommands and len(p.operands) > 0 and field_known(p.operands[0]):
        sub_name = field_static(p.operands[0])
        if sub_name in spec.sub:
            sub = spec.sub[sub_name]
            if sub_name in sub.flags:
                flag(rt, w, e, ctx, name + " " + sub_name, sub.flags[sub_name], [])
            sp = parse(rest, sub)
            apply_options(rt, w, e, ctx, sub, sp.options, spec, [])
            apply_operands(rt, w, e, ctx, sub, sp.operands + rest[sp.end :], spec)
        return
    if spec.subcommands:
        return
    if spec.stdin_program:
        stdin_program(rt, w, e, ctx, spec, p)
    apply_operands(rt, w, e, ctx, spec, p.operands + rest, None)


def stdin_program(rt, w, e, ctx, spec, p):
    """An interpreter given no program (no script, no -c, -e, -m), or `-`:
    its program is what's on its stdin. A file redirected in: code in it;
    a here-document, a here-string, a pipe: code vetter doesn't read."""
    from ..shells.bash.resolve import exec_name, unknown

    for opt, _ in p.options:
        r = spec.roles[opt] if opt in spec.roles else None
        # (the program given: code (-c, -e), python's module (-m); node's -r,
        # perl's -M only load one before it)
        if r is not None and (r.startswith("code:") or (r == "package" and opt == "-m" and spec.names[0] == "python")):
            return
    if len(p.operands) > 0 and not (field_known(p.operands[0]) and field_static(p.operands[0]) == "-"):
        return
    name = str(exec_name(e))
    path = None
    for d in e.redirects:
        if (d.fd is None or d.fd == "0") and (d.op == "<" or d.op == "<>"):
            path = d.target
    if path is not None:
        e.roles.append(Role("read", path, None))
        unknown(rt, w, name + ": runs the code in " + field_text(path) + " (its stdin)", e.span, ctx, "code_file",
                [path])
    elif e.stdin is not None:
        unknown(rt, w, name + ": runs the program on its stdin, code vetter doesn't read", e.span, ctx,
                "inline_code", [])


def flag(rt, w, e, ctx, label, value, given):
    """A flag (or a subcommand, or the program itself) that does what vetter
    doesn't see; given: what it works on."""
    from ..shells.bash.resolve import unknown

    if value.kind == "delete_starts":
        # (find -delete: deletes what's under its starting points)
        starts = given if len(given) > 0 else [Field(["."], False, False)]
        for p in starts:
            under = p
            if field_known(p):
                s = field_static(p)
                while s.endswith("/"):
                    s = s[: len(s) - 1]
                under = Field([s + "/*"], False, False)
            e.roles.append(Role("delete", under, last_word(label)))
        return
    unknown(rt, w, label + ": " + value.reason, e.span, ctx, value.kind, given)


def apply_options(rt, w, e, ctx, spec, options, parent, starts):
    from ..shells.bash.resolve import exec_name

    for name, value in options:
        if name in spec.flags:
            flag(rt, w, e, ctx, str(exec_name(e)) + " " + name, spec.flags[name], starts)
        if name not in spec.roles or value is None:
            continue
        role(rt, w, e, ctx, spec.roles[name], value, name, parent if parent is not None else spec)


def apply_operands(rt, w, e, ctx, spec, operands, parent):
    from ..shells.bash.resolve import exec_name, inner, unknown

    kind = spec.operands
    if kind == "sed" or kind == "awk":
        script_operands(rt, w, e, ctx, kind, operands)
        return
    if kind == "dd_operands":
        for o in operands:
            if field_known(o):
                s = field_static(o)
                if s.startswith("of=") or s.startswith("if="):
                    e.roles.append(Role("write" if s.startswith("of=") else "read", Field([s[3:]], False, False),
                                        None))
        return
    if kind == "git_config_set":
        keys = []
        for o in operands:
            if not (field_known(o) and field_static(o).startswith("-")):
                keys.append(o)
        if len(keys) >= 2 and field_known(keys[0]):
            r = config_role(parent if parent is not None else spec, field_static(keys[0]))
            if r is not None and r != "plain":
                unknown(rt, w, "git config " + field_static(keys[0]) + ": sets what git runs later (" + r + ")",
                        e.span, ctx, "persistent", [])
        return
    if kind == "program_args":
        inner(rt, w, e, operands, ctx, str(exec_name(e)), {})
        return
    if kind == "ln":
        link_operands(e, operands)
        return
    if kind == "make":
        for o in operands:
            if field_known(o) and "=" in field_static(o):
                var, _, val = field_static(o).partition("=")
                make_variable(rt, w, e, ctx, var, val)
        return
    remote = []
    roles = operand_roles(spec, operands)
    if pattern_given(e, spec):
        # (grep -e PATTERN FILE: no pattern operand, each one a file)
        rest = [p for p in spec.pattern if p.endswith("*")]
        r = rest[0][: len(rest[0]) - 1] if len(rest) > 0 else spec.operands
        roles = [(r, o) for o in operands]
    for r, o in roles:
        if r == "remote_command":
            remote.append(o)
        else:
            role(rt, w, e, ctx, r, o, None, parent if parent is not None else spec)
    if len(remote) > 0:
        code_words(rt, w, e, ctx, remote, str(exec_name(e)) + " (remote)")


def registry(value):
    """A key as reg.exe names it (HKCU\\Software\\..., remote \\\\host\\HKLM\\...)
    as PowerShell's drives do (HKCU:/Software/...), for the policy's places."""
    if not field_known(value):
        return value
    hive, _, rest = field_static(value).replace("/", "\\").partition("\\")
    while hive.endswith(":"):
        hive = hive[: len(hive) - 1]
    key = ascii_lower(hive)
    if key not in HIVES:
        return value
    return Field([HIVES[key] + ":/" + rest.replace("\\", "/")], False, False)


def role(rt, w, e, ctx, r, value, option, spec):
    from ..shells.bash.resolve import code, downloaded, exec_name, inner, run, unknown

    name = exec_name(e)
    if r == "source" or r == "code_source":
        # (Windows programs take a URL or UNC share where a file goes)
        remote = field_known(value) and is_remote(field_static(value))
        if r == "source":
            r = "url" if remote else "read"
        elif remote:
            e.roles.append(Role("url", value, option))
            unknown(rt, w, joined(name, option) + ": runs code from " + field_text(value), e.span, ctx,
                    "downloaded_code", [value])
            return
        else:
            r = "code_file"
    if r == "reg_write" or r == "reg_delete":
        r = r[4:]
        value = registry(value)
    if r == "write" or r == "read" or r == "delete" or r == "url" or r == "cwd" or r == "image" \
            or r == "docker_volume":
        e.roles.append(Role(r, value, option))
        if r == "write" and name in DOWNLOADERS:
            downloaded(rt, w, e, value)
    elif (r == "shell" or r == "cmdline") and field_known(value) and windows_program(field_static(value)):
        # (C:\...\p.exe: a program named by its Windows path, not sh's
        # text, its backslashes escapes; run without the variable that
        # named it, GIT_SSH_COMMAND: it would name it again)
        env = {k: v for k, v in e.env.items() if k != option}
        run(rt, w, [value], env, [], ctx, e.span, e.stdin, e.via + (labelled(name, option),))
    elif r == "shell" or r == "cmdline" or r == "remote_command":
        if field_known(value):
            text = field_static(value)
            code(rt, w, text, ctx, e.span, labelled(name, option), False, None)
            if r == "shell" and has_windows_path(text):
                # (C:\...\p.ps1 in it: sh's backslashes escapes, read too
                # as written, in case what runs it is Windows' own)
                code(rt, w, text.replace("\\", "\\\\"), ctx, e.span, labelled(name, option), False, None)
        else:
            unknown(rt, w, labelled(name, option) + ": runs a command only running tells", e.span, ctx, "code", [])
    elif r == "program":
        if field_known(value):
            inner(rt, w, e, [value], ctx, labelled(name, option), {})
        else:
            unknown(rt, w, labelled(name, option) + ": runs a program only running tells", e.span, ctx, "code", [])
    elif r == "code_file":
        e.roles.append(Role("read", value, option))
        unknown(rt, w, joined(name, option) + ": runs the code in " + field_text(value), e.span, ctx, "code_file",
                [value])
    elif r == "package" or r == "package_script":
        what = "the package's script" if r == "package_script" else "the package"
        unknown(rt, w, str(name) + ": runs " + what + " " + field_text(value), e.span, ctx, r, [])
    elif r.startswith("code:"):
        unknown(rt, w, str(name) + " " + str(option) + ": runs " + r[5:] + " code vetter doesn't read", e.span, ctx,
                "inline_code", [])
    elif r == "git_config":
        if not field_known(value):
            unknown(rt, w, str(name) + " " + str(option) + ": a setting only running tells", e.span, ctx, "code", [])
            return
        key, _, val = field_static(value).partition("=")
        cr = config_role(spec, key)
        if cr == "git_alias":
            if val.startswith("!"):
                code(rt, w, val[1:], ctx, e.span, "git alias " + key, False, None)
        elif cr == "credential_helper":
            if val.startswith("!"):
                code(rt, w, val[1:], ctx, e.span, "git " + key, False, None)
            elif val != "":
                first = last_word_first(val)
                code(rt, w, val if "/" in first else "git-credential-" + val, ctx, e.span, "git " + key, False, None)
        elif cr is not None and cr != "plain":
            role(rt, w, e, ctx, cr, Field([val], False, False), "-c " + key, spec)
    elif r == "sed_script" or r == "awk_program":
        # (read with the operands: all of a program's pieces together,
        # script_operands)
        pass
    elif r == "curl_data":
        if field_known(value):
            s = field_static(value)
            if s.startswith("@") and s != "@-":
                e.roles.append(Role("read", Field([s[1:]], False, False), option))
            elif "=@" in s:
                after = s[s.find("=@") + 2 :]
                e.roles.append(Role("read", Field([after.partition(";")[0]], False, False), option))
    elif r == "tar_checkpoint":
        if field_known(value) and field_static(value).startswith("exec="):
            code(rt, w, field_static(value)[5:], ctx, e.span, str(name) + " " + str(option), False, None)
    elif r == "ssh_option":
        if not field_known(value):
            unknown(rt, w, str(name) + " -o: an option only running tells", e.span, ctx, "code", [])
            return
        s = field_static(value)
        sp = s.find(" ")
        if sp >= 0:
            s = s[:sp] + "=" + s[sp + 1 :]
        key, _, val = s.partition("=")
        low = ascii_lower(key)
        if low == "proxycommand" or low == "localcommand" or low == "knownhostscommand" or low == "remotecommand":
            code(rt, w, val, ctx, e.span, str(name) + " -o " + key, False, None)
    elif r == "comma_program":
        # (gcc -wrapper prog,arg,...: the program and its arguments, run
        # around each of its subprocesses)
        if field_known(value):
            words = [Field([x], False, False) for x in field_static(value).split(",")]
            inner(rt, w, e, words, ctx, labelled(name, option), {})
        else:
            unknown(rt, w, labelled(name, option) + ": runs a program only running tells", e.span, ctx, "code", [])
    elif r == "program_dir":
        # (gcc -B: its own programs, cc1, as, ld, found there first)
        e.roles.append(Role("read", value, option))
        unknown(rt, w, joined(name, option) + ": runs its programs from " + field_text(value), e.span, ctx, "code_file",
                [value])
    elif r == "linker":
        # (-fuse-ld=gold names a linker; a path is the program run)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": a linker only running tells", e.span, ctx, "code", [])
        elif "/" in field_static(value) or "\\" in field_static(value):
            role(rt, w, e, ctx, "program", value, option, spec)
    elif r == "rustc_codegen":
        # (-C key=value: linker= is the program it links with)
        if field_known(value):
            key, _, val = field_static(value).partition("=")
            if key == "linker":
                role(rt, w, e, ctx, "program", Field([val], False, False), option + " linker", spec)
        else:
            unknown(rt, w, labelled(name, option) + ": a setting only running tells", e.span, ctx, "code", [])
    elif r == "agent_file":
        # (java -javaagent:path=options: the agent's code)
        f = value
        if field_known(value):
            f = Field([field_static(value).partition("=")[0]], False, False)
        e.roles.append(Role("read", f, option))
        unknown(rt, w, joined(name, option) + ": loads the code in " + field_text(f), e.span, ctx, "code_file", [f])
    elif r == "configured":
        # (a setting that changes what it runs, its effect not followed)
        unknown(rt, w, labelled(name, option) + " " + field_text(value) + ": sets what it runs", e.span, ctx,
                "configured", [])


def link_operands(e, operands):
    """ln [-s] TARGET... [LINK | DIR], ln -t DIR TARGET...: each link
    written; each target read and written too (what's done through the
    link is done to it). A symbolic link's relative target is from the
    link's directory."""
    symbolic = False
    target_dir = None
    args = e.argv[1:]
    for k in range(len(args)):
        if not field_known(args[k]):
            continue
        s = field_static(args[k])
        if s == "--symbolic" or (s.startswith("-") and not s.startswith("--") and "s" in s):
            symbolic = True
        if (s == "-t" or s == "--target-directory") and k + 1 < len(args):
            target_dir = args[k + 1]
        elif s.startswith("--target-directory="):
            target_dir = Field([s[19:]], False, False)
    if target_dir is not None:
        targets = operands
        where = target_dir
    elif len(operands) == 1:
        targets = operands
        where = None
    else:
        targets = operands[: len(operands) - 1]
        where = operands[len(operands) - 1]
        e.roles.append(Role("write", where, None))
    # (the directory links are made in, for a relative symbolic target)
    base = None
    if where is not None and field_known(where):
        w_s = field_static(where)
        if len(targets) > 1 or target_dir is not None:
            base = w_s
        elif "/" in w_s:
            base = w_s[: w_s.rfind("/")] or "/"
    for t in targets:
        target = t
        if symbolic and field_known(t) and base is not None:
            ts = field_static(t)
            if not ts.startswith("/") and not ts.startswith("~"):
                target = Field([base.rstrip("/") + "/" + ts], False, False)
        e.roles.append(Role("read", target, None))
        e.roles.append(Role("write", target, None))


# make's variables that are the shell its recipes run in; those naming a
# program (a path: that program runs)
MAKE_SHELL_VARS = {"SHELL", ".SHELLFLAGS", "MAKESHELL", "MAKEFLAGS", "MFLAGS"}
MAKE_PROGRAM_VARS = {"CC", "CXX", "CPP", "LD", "AS", "AR", "FC", "RANLIB", "STRIP", "OBJCOPY", "NM", "RUSTC", "GO",
                     "PYTHON", "INSTALL"}
SHELL_CHARS = " \t\n;|&$`()<>'\"\\"


def make_variable(rt, w, e, ctx, var, val):
    """make VAR=value: it overrides the Makefile's, and recipes use it: a
    value with shell syntax in it, or the shell itself, runs as commands;
    a program's path runs that program."""
    from ..shells.bash.resolve import unknown

    shellish = False
    for c in val:
        if c in SHELL_CHARS:
            shellish = True
    if var in MAKE_SHELL_VARS or shellish:
        unknown(rt, w, "make " + var + "=" + val + ": the Makefile's recipes run it", e.span, ctx, "configured", [])
    elif var in MAKE_PROGRAM_VARS and "/" in val:
        role(rt, w, e, ctx, "program", Field([val], False, False), var, EMPTY)


def last_word_first(s):
    """s.split()[0]"""
    i = 0
    while i < len(s) and is_space(s[i]):
        i += 1
    j = i
    while j < len(s) and not is_space(s[j]):
        j += 1
    return s[i:j]


def code_words(rt, w, e, ctx, words, label):
    """A command made of words (ssh host CMD..., docker run IMAGE CMD...):
    joined with spaces, as the remote shell reads them."""
    from ..shells.bash.resolve import code, unknown

    texts = []
    for f in words:
        if not field_known(f):
            unknown(rt, w, label + ": a command only running tells", e.span, ctx, "code", [])
            return
        texts.append(field_static(f))
    code(rt, w, " ".join(texts), ctx, e.span, label, False, None)


def path_dirs(value):
    """The directories a PATH value names, each all known (one next to what
    only running tells, $PATH, left out): split at ; when it's Windows'
    (a ; or a drive in it), else at :."""
    segments = []
    cur = ""
    cut = []
    for p in value.parts:
        if isinstance(p, Dynamic):
            segments.append(cur)
            cur = ""
        else:
            cur += p
    segments.append(cur)
    text = "".join(segments)
    windows = ";" in text or (len(text) > 1 and text[1] == ":")
    sep = ";" if windows else ":"
    out = []
    for k in range(len(segments)):
        pieces = segments[k].split(sep)
        for i in range(len(pieces)):
            # (a piece touching a dynamic part is only part of a directory)
            partial = (i == 0 and k > 0) or (i == len(pieces) - 1 and k < len(segments) - 1)
            if pieces[i] != "" and not partial:
                cut.append(pieces[i])
    for d in cut:
        if d not in out:
            out.append(d)
    return out


def has_windows_path(s):
    """A drive's path in s with a backslash in it (C:\\..., C:/...\\x)."""
    if "\\" not in s:
        return False
    for i in range(len(s) - 2):
        c = s[i]
        if s[i + 1] == ":" and (s[i + 2] == "\\" or s[i + 2] == "/") and (("a" <= c <= "z") or ("A" <= c <= "Z")) \
                and (i == 0 or not s[i - 1].isalnum()):
            return True
    return False


def windows_program(s):
    """A Windows path alone (C:\\...\\p.exe, \\\\host\\share\\x), no blanks
    or quotes: a program named, not a command line."""
    absolute = (len(s) > 2 and s[1] == ":" and s[2] == "\\") or s.startswith("\\\\")
    if not absolute:
        return False
    for c in s:
        if is_space(c) or c == '"' or c == "'":
            return False
    return True


def pattern_given(e, spec):
    """One of the spec's pattern_options given: on its own, glued
    (-epat, --regexp=pat), or last in a cluster of flags (-ie pat; earlier
    in one, its value the cluster's rest: -eix)."""
    if len(spec.pattern_options) == 0:
        return False
    for a in e.argv[1:]:
        if not field_known(a):
            continue
        s = field_static(a)
        if s == "--":
            return False
        if s.startswith("--"):
            if s.partition("=")[0] in spec.pattern_options:
                return True
        elif s.startswith("-") and len(s) > 1:
            for c in s[1:]:
                if "-" + c in spec.pattern_options:
                    return True
    return False


def option_names(e):
    out = []
    for a in e.argv[1:]:
        if field_known(a) and field_static(a).startswith("-"):
            out.append(field_static(a).partition("=")[0])
    return out


def script_operands(rt, w, e, ctx, kind, operands):
    """sed/awk: the first operand is the program unless -e/-f gave one; the
    program's pieces (each -e, --expression, --source) read together, as
    the program does (one per line: `-e '1{e cmd' -e '}'` is a block)."""
    from ..shells.bash.resolve import exec_name, unknown

    name = str(exec_name(e))
    pieces_opts = ("-e", "--expression") if kind == "sed" else ("-e", "--source")
    pieces = []
    given = False
    spec = SPECS[name] if name in SPECS else EMPTY
    for o, v in parse(e.argv[1:], spec).options:
        if o in pieces_opts and v is not None:
            pieces.append(v)
            given = True
        elif o == "-f" or o == "--file":
            given = True
    names = option_names(e)
    for o in names:
        if o in pieces_opts or o == "-f" or o == "--file":
            given = True
    files = operands if given else operands[1:]
    if not given and len(operands) > 0:
        pieces = [operands[0]]
    if len(pieces) > 0:
        texts = []
        for p in pieces:
            if not field_known(p):
                unknown(rt, w, name + ": a program only running tells", e.span, ctx, "code", [])
                texts = None
                break
            texts.append(field_static(p))
        if texts is not None:
            program = Field(["\n".join(texts)], False, False)
            if kind == "sed":
                sed(rt, w, e, ctx, program)
            else:
                awk(rt, w, e, ctx, program)
    in_place = False
    if kind == "sed":
        for o in names:
            if o == "-i" or o == "--in-place" or (o.startswith("-i") and len(o) > 2):
                in_place = True
    for f in files:
        e.roles.append(Role("write" if in_place else "read", f, None))


def sed(rt, w, e, ctx, value):
    """GNU sed: `e COMMAND` runs a command, `e` and `s///e` run the pattern
    space, `w FILE` writes."""
    from ..shells.bash.resolve import code, exec_name, unknown

    name = str(exec_name(e))
    if not field_known(value):
        unknown(rt, w, name + ": a script only running tells", e.span, ctx, "code", [])
        return
    for kind, arg in sed_commands(field_static(value)):
        if kind == "e":
            if arg != "":
                code(rt, w, arg, ctx, e.span, name + " e", False, None)
            else:
                unknown(rt, w, name + " e: runs the text it reads", e.span, ctx, "code", [])
        elif kind == "s_e":
            unknown(rt, w, name + " s///e: runs the text it substitutes", e.span, ctx, "code", [])
        elif kind == "w":
            e.roles.append(Role("write", Field([arg], False, False), None))
        elif kind == "r":
            e.roles.append(Role("read", Field([arg], False, False), None))
        elif kind == "bad":
            unknown(rt, w, name + ": a script vetter can't read (" + arg + ")", e.span, ctx, "code", [])


def sed_commands(script):
    """What a GNU sed script does that matters: ("e", command) (`e COMMAND`
    to the line's end, `e` alone: ""), ("s_e", "") (s///e), ("w", file)
    (w, W, s///w), ("r", file) (r, R), ("bad", why). Its commands as sed
    reads them: addresses (N, $, /re/I, \\%re%, first~step, addr,+N),
    `!`, blocks { }, `;` and newlines between commands; a, i, c, e, r, w
    and labels taking the rest of the line."""
    out = []
    s = script
    n = len(s)
    i = 0
    while i < n:
        c = s[i]
        if is_space(c) or c == ";" or c == "}":
            i += 1
            continue
        if c == "#":
            while i < n and s[i] != "\n":
                i += 1
            continue
        i = sed_address(s, i)
        if i < 0:
            out.append(("bad", "an address"))
            return out
        while i < n and (s[i] == " " or s[i] == "\t"):
            i += 1
        if i < n and s[i] == ",":
            i = sed_address(s, i + 1)
            if i < 0:
                out.append(("bad", "an address"))
                return out
        while i < n and (s[i] == " " or s[i] == "\t" or s[i] == "!"):
            i += 1
        if i >= n:
            break
        c = s[i]
        i += 1
        if c == "{":
            continue
        if c in "erRwWaic:btTv":
            # (the rest of the line; a, i, c: their text, a \ at a line's
            # end going on to the next)
            j = i
            while j < n and s[j] != "\n":
                if (c == "a" or c == "i" or c == "c") and s[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if c in ":btTv" and (s[j] == ";" or s[j] == "}"):
                    break
                j += 1
            arg = strip(s[i:j])
            i = j
            if c == "e":
                out.append(("e", arg))
            elif c == "r" or c == "R":
                out.append(("r", arg))
            elif c == "w" or c == "W":
                out.append(("w", arg))
            continue
        if c == "s" or c == "y":
            if i >= n or s[i] == "\n" or s[i] == "\\":
                out.append(("bad", c + " with no delimiter"))
                return out
            d = s[i]
            i += 1
            for _ in range(2):
                while i < n and s[i] != d:
                    i += 2 if s[i] == "\\" else 1
                if i >= n:
                    out.append(("bad", "an unclosed " + c))
                    return out
                i += 1
            if c == "y":
                continue
            # (its flags: g, p, i, m, e, a number; w FILE to the line's end)
            while i < n and s[i] != ";" and s[i] != "\n" and s[i] != "}":
                f = s[i]
                if f == "w":
                    j = i + 1
                    while j < n and s[j] != "\n":
                        j += 1
                    out.append(("w", strip(s[i + 1 : j])))
                    i = j
                    break
                if f == "e":
                    out.append(("s_e", ""))
                i += 1
            continue
        if c in "lLqQ":
            while i < n and (s[i] == " " or s[i] == "\t" or ("0" <= s[i] <= "9")):
                i += 1
            continue
        # (=, d, D, F, g, G, h, H, n, N, p, P, x, z: nothing more)
    return out


def sed_address(s, i):
    """Where an address at i ends (i: none), -1: one that doesn't close."""
    n = len(s)
    if i >= n:
        return i
    c = s[i]
    if c == "$":
        return i + 1
    if ("0" <= c <= "9") or c == "+" or c == "~":
        i += 1
        while i < n and (("0" <= s[i] <= "9") or s[i] == "~"):
            i += 1
        return i
    if c == "/" or c == "\\":
        d = "/"
        if c == "\\":
            if i + 1 >= n:
                return -1
            d = s[i + 1]
            i += 1
        i += 1
        while i < n and s[i] != d:
            i += 2 if s[i] == "\\" else 1
        if i >= n:
            return -1
        i += 1
        while i < n and (s[i] == "I" or s[i] == "M"):
            i += 1
        return i
    return i


# (after these an awk `/` opens a regular expression, not a division)
AWK_BEFORE_REGEX = ("", "(", ",", "{", "}", ";", "\n", "!", "~", "&&", "||", "=", "==", "!=", "<", "<=", ">", ">=",
                    "+", "-", "*", "%", "^", "?", ":", "print", "printf", "return", "in")


def awk_tokens(prog):
    """An awk program's tokens: ("str", its text unescaped), ("id", name),
    ("num", text), ("op", text) (newlines among them: they end
    statements); comments and regular expressions left out."""
    out = []
    n = len(prog)
    i = 0
    prev = ""
    while i < n:
        c = prog[i]
        if c == "\\" and i + 1 < n and prog[i + 1] == "\n":
            i += 2
            continue
        if c == " " or c == "\t" or c == "\r":
            i += 1
            continue
        if c == "#":
            while i < n and prog[i] != "\n":
                i += 1
            continue
        if c == '"':
            j = i + 1
            text = ""
            while j < n and prog[j] != '"':
                if prog[j] == "\\" and j + 1 < n:
                    nxt = prog[j + 1]
                    text += "\n" if nxt == "n" else ("\t" if nxt == "t" else nxt)
                    j += 2
                else:
                    text += prog[j]
                    j += 1
            out.append(("str", text))
            prev = "str"
            i = j + 1
            continue
        if c == "/" and prev in AWK_BEFORE_REGEX:
            j = i + 1
            while j < n and prog[j] != "/" and prog[j] != "\n":
                if prog[j] == "\\":
                    j += 2
                elif prog[j] == "[":
                    # (a bracket expression: a / in it is its own)
                    j += 1
                    if j < n and prog[j] == "^":
                        j += 1
                    if j < n and prog[j] == "]":
                        j += 1
                    while j < n and prog[j] != "]" and prog[j] != "\n":
                        j += 1
                    j += 1
                else:
                    j += 1
            out.append(("re", ""))
            prev = "re"
            i = j + 1
            continue
        if is_word(c) and not ("0" <= c <= "9"):
            j = i
            while j < n and is_word(prog[j]):
                j += 1
            out.append(("id", prog[i:j]))
            prev = prog[i:j] if prog[i:j] in AWK_BEFORE_REGEX else "id"
            i = j
            continue
        if "0" <= c <= "9" or (c == "." and i + 1 < n and "0" <= prog[i + 1] <= "9"):
            j = i
            while j < n and (is_word(prog[j]) or prog[j] == "."):
                j += 1
            out.append(("num", prog[i:j]))
            prev = "num"
            i = j
            continue
        two = prog[i : i + 2]
        if two in ("||", "&&", "|&", ">>", "==", "!=", "<=", ">=", "++", "--", "+=", "-=", "*=", "/=", "%=", "^="):
            out.append(("op", two))
            prev = two
            i += 2
            continue
        out.append(("op", c))
        prev = c
        i += 1
    return out


def awk_effects(prog):
    """What an awk program does that matters: ("runs", why) (system(), a
    pipe to or from a command, |&, @include, @load), ("read", file)
    (getline < "file"), ("write", file) (print > "file", >>), ("read?",
    why), ("write?", why) (a file named by what runs: getline < f, print >
    f, ARGV changed: its files)."""
    out = []
    t = awk_tokens(prog)
    n = len(t)
    in_print = False
    depth = 0
    for k in range(n):
        kind, text = t[k]
        nxt = t[k + 1] if k + 1 < n else ("", "")
        if kind == "op" and (text == ";" or text == "\n" or text == "{" or text == "}"):
            in_print = False
            continue
        if kind == "id" and (text == "print" or text == "printf"):
            in_print = True
            depth = 0
            continue
        if kind == "op" and (text == "(" or text == "["):
            depth += 1
        elif kind == "op" and (text == ")" or text == "]"):
            depth -= 1
        elif kind == "id" and text == "system" and nxt == ("op", "("):
            out.append(("runs", "system()"))
        elif kind == "op" and (text == "|" or text == "|&"):
            out.append(("runs", "a pipe to or from a command"))
        elif kind == "op" and text == "@" and nxt[0] == "id" and (nxt[1] == "include" or nxt[1] == "load"):
            out.append(("runs", "@" + nxt[1]))
        elif kind == "op" and (text == ">" or text == ">>") and in_print and depth == 0:
            if nxt[0] == "str":
                out.append(("write", nxt[1]))
            else:
                out.append(("write?", "print > a file named when it runs"))
        elif kind == "id" and text == "getline":
            # (getline [var] < file: the var a name, maybe subscripted, or $expr)
            j = k + 1
            if j < n and t[j][0] == "op" and t[j][1] == "$":
                j += 2
            elif j < n and t[j][0] == "id":
                j += 1
                if j < n and t[j] == ("op", "["):
                    level = 0
                    while j < n:
                        if t[j] == ("op", "["):
                            level += 1
                        elif t[j] == ("op", "]"):
                            level -= 1
                            if level == 0:
                                break
                        j += 1
                    j += 1
            if j < n and t[j] == ("op", "<"):
                if j + 1 < n and t[j + 1][0] == "str":
                    out.append(("read", t[j + 1][1]))
                else:
                    out.append(("read?", "getline < a file named when it runs"))
        elif kind == "id" and (text == "ARGV" or text == "ARGC"):
            # (ARGV[1] = "/x": the file it reads next, its own)
            j = k + 1
            if j < n and t[j] == ("op", "["):
                level = 0
                while j < n:
                    if t[j] == ("op", "["):
                        level += 1
                    elif t[j] == ("op", "]"):
                        level -= 1
                        if level == 0:
                            break
                    j += 1
                j += 1
            if j < n and t[j][0] == "op" and t[j][1] in ("=", "+=", "-=", "++", "--"):
                out.append(("read?", "ARGV changed: files it picks when it runs"))
    return out


def awk(rt, w, e, ctx, value):
    from ..shells.bash.resolve import exec_name, unknown

    name = str(exec_name(e))
    if not field_known(value):
        unknown(rt, w, name + ": a program only running tells", e.span, ctx, "code", [])
        return
    seen = []
    for kind, arg in awk_effects(field_static(value)):
        if kind == "read":
            e.roles.append(Role("read", Field([arg], False, False), None))
        elif kind == "write":
            e.roles.append(Role("write", Field([arg], False, False), None))
        elif kind not in seen:
            seen.append(kind)
            why = "its program runs commands (" + arg + ")" if kind == "runs" else arg
            unknown(rt, w, name + ": " + why, e.span, ctx, "code", [])


def apply_env(rt, w, e, ctx):
    from ..shells.bash.resolve import copy, exec_name, expanded_later, run, unknown

    name = exec_name(e)
    who = name if name is not None and name != "" else "it"
    for var, value in e.env.items():
        if var not in ENV:
            continue
        r = ENV[var]
        if r == "plain":
            continue
        if r == "shell_expanded":
            # (a shell given it expands it again: PS4 before each traced
            # command, its substitutions run)
            if field_known(value):
                expanded_later(rt, w, copy(ctx), e.span, var, field_static(value))
            else:
                unknown(rt, w, var + ": a value a shell expands, only running tells", e.span, ctx, "code", [])
            continue
        if r == "lookup_path":
            unknown(rt, w, var + "=" + field_text(value) + ": which programs " + who + " runs depends on it", e.span, ctx,
                    "lookup_path", [])
            written = field_static(e.argv[0]) if len(e.argv) > 0 else None
            if var == "PATH" and name is not None and written is not None and "/" not in written \
                    and "\\" not in written:
                # (each directory the line names in it: the program may be
                # found there; PATH=/tmp/x:$PATH git: /tmp/x/git; run
                # without the PATH that found it)
                env = {k: v for k, v in e.env.items() if k != var}
                found_ctx = copy(ctx)
                if var in found_ctx.exported:
                    found_ctx.exported.pop(var)
                for d in path_dirs(value):
                    windows = ":" in d or "\\" in d
                    sep = "\\" if windows else "/"
                    found = d.rstrip("\\/") + sep + name + (".exe" if windows and "." not in name else "")
                    run(rt, w, [Field([found], False, False)], env, [], found_ctx, e.span, e.stdin, e.via + ("PATH",))
        elif r == "git_config_list":
            unknown(rt, w, var + ": git settings only running tells", e.span, ctx, "code", [])
        elif r == "code_file":
            # (code put in through the environment: a library preloaded, a
            # startup file)
            unknown(rt, w, var + "=" + field_text(value) + ": " + who + " runs the code in it", e.span, ctx, "env_code",
                    [value])
        else:
            # (what it runs inherits the variable, which says nothing more
            # there: read without it, or each would run it again)
            inner_ctx = copy(ctx)
            if var in inner_ctx.exported:
                inner_ctx.exported.pop(var)
            role(rt, w, e, inner_ctx, r, value, var, SPECS["git"] if "git" in SPECS else EMPTY)
