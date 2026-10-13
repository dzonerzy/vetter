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
from ..shells.python.stdlib import STDLIB as PYTHON_STDLIB
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
    see: why, and the Unknown's kind; not with one of the options in
    unless (npm ci --ignore-scripts)."""

    reason: str
    kind: str
    unless: list


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
    # (strict, for these names: an option it doesn't list (values, roles,
    # flags, switches, attached, an option of a family) an Unknown, not
    # taken for nothing)
    strict: set
    switches: set
    families: list
    # (an option after which the rest are its code's arguments: python -m)
    final: list


def _spec(s):
    flags = {}
    for k, v in s.flags.items():
        if isinstance(v, dict):
            flags[k] = Flag(v.get("reason", ""), v.get("kind", "configured"), list(v.get("unless", [])))
        else:
            flags[k] = Flag(v, "configured", [])
    pattern = list(s.operands) if isinstance(s.operands, list) else []
    return Spec(list(s.names), dict(s.roles), set(s.values), flags, "pattern" if pattern else s.operands, pattern,
                bool(s.subcommands), bool(s.stop_at_operand), bool(s.single_dash_long), bool(s.slash_options),
                bool(s.readonly), dict(s.config), {k: _spec(v) for k, v in s.sub.items()}, set(s.commands),
                bool(s.stdin_program), list(s.attached), dict(s.anywhere), bool(s.response_files),
                list(s.pattern_options), set(s.strict), set(s.switches), list(s.families), list(s.final))


SPECS = {name: _spec(s) for name, s in py_specs.SPECS.items()}
ENV = dict(py_specs.ENV)
# (names with a * in them: CARGO_TARGET_*_LINKER, any triple's)
ENV_PATTERNS = [(k.partition("*")[0], k.partition("*")[2], v) for k, v in ENV.items() if "*" in k]
EMPTY = _spec(py_specs.Spec({}))

DOWNLOADERS = {"curl", "wget", "fetch", "aria2c", "http", "xh"}

# Programs that run another command (bash's resolver reads that one)
WRAPPERS = {"env", "command", "builtin", "exec", "sudo", "doas", "nice", "nohup", "setsid", "stdbuf", "time",
            "timeout", "chroot", "ionice", "taskset", "chrt", "flock", "unbuffer", "xargs", "find", "watch", "su",
            "ssh"}

HIVES = {"hkcu": "HKCU", "hkey_current_user": "HKCU", "hklm": "HKLM", "hkey_local_machine": "HKLM",
         "hkcr": "HKCR", "hkey_classes_root": "HKCR", "hku": "HKU", "hkey_users": "HKU", "hkcc": "HKCC",
         "hkey_current_config": "HKCC"}

# (str.isspace's characters: what Python's strip() and re's \s take)
SPACES = "\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0          " \
         "      　"


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
        if len(options) > 0 and options[len(options) - 1][0] in spec.final \
                and options[len(options) - 1][1] is not None:
            # (python -m pytest -x: -x is pytest's, not python's)
            return Parsed(options, operands, len(args))
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
        if s.startswith("--") and len(name) > 2 and name not in spec.values and name not in spec.flags \
                and name not in spec.roles:
            # (GNU's getopt_long: a unique prefix names the option, --ev
            # --eval; several: ambiguous, what it is only running tells)
            found = long_prefix(spec, name)
            if len(found) == 1:
                name = found[0]
                s = name + eq + val
            elif len(found) > 1:
                options.append(("--?" + name, Field([",".join(found)], False, False)))
                i += 1
                continue
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


# cmake -D keys naming scripts it runs, programs it runs
CMAKE_CODE = {"CMAKE_PROJECT_INCLUDE", "CMAKE_PROJECT_INCLUDE_BEFORE", "CMAKE_PROJECT_TOP_LEVEL_INCLUDES",
              "CMAKE_TOOLCHAIN_FILE", "CMAKE_USER_MAKE_RULES_OVERRIDE", "CMAKE_USER_MAKE_RULES_OVERRIDE_C",
              "CMAKE_USER_MAKE_RULES_OVERRIDE_CXX", "CMAKE_MODULE_PATH", "CMAKE_PREFIX_PATH"}
CMAKE_PROGRAMS = {"CMAKE_C_COMPILER", "CMAKE_CXX_COMPILER", "CMAKE_LINKER", "CMAKE_AR", "CMAKE_RANLIB",
                  "CMAKE_MAKE_PROGRAM", "CMAKE_ASM_COMPILER", "CMAKE_CUDA_COMPILER", "CMAKE_OBJCOPY"}


# What the compiler driver hands on (-Xclang W, -Xpreprocessor W, -Wp,W,W...):
# the words each program takes, by the option, and what their values are
FORWARDED = {"-Xclang": "cc1", "-Xpreprocessor": "cpp", "-Xlinker": "ld", "-Xassembler": "as"}
FORWARDED_COMMA = {"-Wp,": "cpp", "-Wl,": "ld", "-Wa,": "as"}
FORWARDED_ROLES = {
    "cc1": {"-load": "code_file", "-include": "read", "-imacros": "read", "-include-pch": "read",
            "-fplugin": "code_file", "-fpass-plugin": "code_file"},
    "cpp": {"-include": "read", "-imacros": "read", "-MF": "write", "-o": "write"},
    "ld": {"-plugin": "code_file", "--plugin": "code_file", "-T": "read", "--script": "read", "-o": "write",
           "--dependency-file": "write", "-Map": "write"},
    "as": {"-o": "write"},
}


def forwarded(rt, w, e, ctx, options):
    """The options gcc and clang hand on to the compiler proper, the
    preprocessor, the linker, the assembler: put together in order and read
    as theirs (-Xclang -load -Xclang p.so: a plugin loaded)."""
    from ..shells.bash.resolve import unknown

    words = {"cc1": [], "cpp": [], "ld": [], "as": []}
    for name, value in options:
        if name in FORWARDED:
            if value is None or not field_known(value):
                unknown(rt, w, str(name) + ": options handed on, only running tells", e.span, ctx, "code", [])
                return
            words[FORWARDED[name]].append(field_static(value))
        else:
            for pre in FORWARDED_COMMA:
                if name.startswith(pre):
                    words[FORWARDED_COMMA[pre]] += name[len(pre):].split(",")
    for tool, ws in words.items():
        roles = FORWARDED_ROLES[tool]
        k = 0
        while k < len(ws):
            word = ws[k]
            opt, eq, val = word.partition("=")
            if word in roles:
                if k + 1 >= len(ws):
                    unknown(rt, w, word + ": handed on with no value", e.span, ctx, "code", [])
                    return
                role(rt, w, e, ctx, roles[word], Field([ws[k + 1]], False, False), word, EMPTY)
                k += 2
                continue
            if eq != "" and opt in roles:
                role(rt, w, e, ctx, roles[opt], Field([val], False, False), opt, EMPTY)
            elif word.startswith("@"):
                role(rt, w, e, ctx, "code_file", Field([word[1:]], False, False), word, EMPTY)
            k += 1


def go_package(rt, w, e, ctx, o):
    """go run's package: a directory of code (./cmd/x), or a module's path
    (example.com/x@v1: fetched and run)."""
    from ..shells.bash.resolve import unknown

    s = field_static(o)
    if s is None:
        unknown(rt, w, "go run: a package only running tells", e.span, ctx, "code", [])
        return
    head = s.split("/")[0]
    if "@" in s or ("." in head and not s.startswith(".") and not s.startswith("/")):
        unknown(rt, w, "go run " + s + ": fetches the module and runs it", e.span, ctx, "package", [])
        return
    unknown(rt, w, "go run: runs the code in " + s, e.span, ctx, "code_file", [o])


def less_keys(rt, w, e, ctx, s):
    """less +CMD (++CMD: for each file): the keys it runs first. Moving
    (G, g, F, a line number, %), searching (/re, ?re): nothing more; !CMD
    a shell command; any other key (|, v, s FILE, :e FILE...) only running
    tells."""
    from ..shells.bash.resolve import code, unknown

    keys = s[2:] if s.startswith("++") else s[1:]
    if keys.startswith("!"):
        line, _, rest = keys[1:].partition("\n")
        code(rt, w, line, ctx, e.span, "less +!", False, None)
        if rest.strip() != "":
            unknown(rt, w, "less +: keys after the command, only running tells", e.span, ctx, "code", [])
        return
    if (keys.startswith("/") or keys.startswith("?")) and "\n" not in keys.rstrip("\n"):
        return
    for c in keys:
        if not (("0" <= c <= "9") or c in "gGFpP%"):
            unknown(rt, w, "less +" + keys + ": keys that may run commands (!, |, v, s)", e.span, ctx, "code", [])
            return


def long_prefix(spec, given):
    """The long options of the spec `given` is a prefix of."""
    out = []
    for group in (spec.values, spec.roles, spec.flags, spec.anywhere):
        for o in group:
            if o.startswith("--") and o.startswith(given) and o not in out:
                out.append(o)
    return out


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
    environment run. The project's code it runs (make's recipes, npm's
    scripts, the tests) is where it works on: the folder -C, --prefix name,
    or where it runs."""
    from ..shells.bash.resolve import exec_name

    first = len(w.r.unknowns)
    spec_roles(rt, w, e, ctx)
    marked = [r for r in e.roles if r.role == "delete_read"]
    if len(marked) > 0:
        for r in [x for x in e.roles if x.role == "read" and x.option is None]:
            e.roles.append(Role("delete", r.value, marked[0].option))
    dest = extraction(e)
    if dest is not None:
        # (what it extracts written there)
        e.roles.append(Role("extract", dest, None))
        e.roles.append(Role("write", dest, None))
    where = None
    for k in range(first, len(w.r.unknowns)):
        u = w.r.unknowns[k]
        if (u.kind == "project_code" or u.kind == "package_script" or u.kind == "repo_config") \
                and len(u.paths) == 0:
            if where is None:
                where = project_dirs(e)
            for d in where:
                u.paths.append(d)
            u.program = str(exec_name(e))


def extraction(e):
    """Where an archive tool extracts to (tar x, unzip, 7z x, cpio -i):
    what's below it after may be a link the archive made, to anywhere;
    None: it doesn't extract."""
    from ..shells.bash.resolve import exec_name

    name = exec_name(e)
    args = e.argv[1:]
    words = [field_static(a) for a in args]
    dest = Field(["."], False, False)
    found = False
    if name == "tar" or name == "bsdtar" or name == "gtar":
        for k in range(len(words)):
            s = words[k]
            if s is None:
                continue
            if s == "--extract" or s == "--get" or (k == 0 and not s.startswith("-") and "x" in s) \
                    or (s.startswith("-") and not s.startswith("--") and "x" in s[1:]):
                found = True
            if (s == "-C" or s == "--directory") and k + 1 < len(args):
                dest = args[k + 1]
            elif s.startswith("--directory="):
                dest = Field([s[12:]], False, False)
    elif name == "unzip":
        found = True
        for k in range(len(words)):
            s = words[k]
            if s is not None and s.startswith("-") and not s.startswith("--") and \
                    ("l" in s or "t" in s or "v" in s or "p" in s or "Z" in s or "c" in s):
                found = False
            if s == "-d" and k + 1 < len(args):
                dest = args[k + 1]
            elif s is not None and s.startswith("-d") and len(s) > 2:
                dest = Field([s[2:]], False, False)
    elif name == "7z" or name == "7za" or name == "7zr":
        for k in range(len(words)):
            s = words[k]
            if s is None:
                continue
            if not s.startswith("-") and not found and (s == "x" or s == "e"):
                found = True
            elif s.startswith("-o") and len(s) > 2:
                dest = Field([s[2:]], False, False)
    elif name == "cpio":
        for k in range(len(words)):
            s = words[k]
            if s is None:
                continue
            if s == "--extract" or (s.startswith("-") and not s.startswith("--") and "i" in s[1:]):
                found = True
            if (s == "-D" or s == "--directory") and k + 1 < len(args):
                dest = args[k + 1]
    return dest if found else None


def project_dirs(e):
    """The folders a tool works on: what its options name (npm --prefix,
    cmake -S, pytest's paths), or the one it's told to run in (make -C), or
    where it runs."""
    out = [r.value for r in e.roles if r.role == "project"]
    if len(out) == 0:
        for r in e.roles:
            if r.role == "cwd":
                out = [r.value]
    if len(out) == 0:
        out = [Field(["."], False, False)]
    return out


def spec_roles(rt, w, e, ctx):
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
    if len(spec.names) > 0 and spec.names[0] == "gcc":
        forwarded(rt, w, e, ctx, p.options)
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
    a here-document, a here-string, a pipe: code vetter doesn't read
    (python's, known: read)."""
    from ..shells.bash.resolve import exec_name, unknown
    from ..shells.python.resolve import python_code

    for opt, _ in p.options:
        r = spec.roles[opt] if opt in spec.roles else None
        # (the program given: code (-c, -e), python's module (-m); node's -r,
        # perl's -M only load one before it)
        if r is not None and (r.startswith("code:") or (r == "package" and opt == "-m" and spec.names[0] == "python")):
            # (python -c CODE, read: what's piped into it, data)
            e.given = r == "code:python"
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
    elif e.stdin is not None and spec.names[0] == "python" and stdin_text(e) is not None:
        rest = []
        for k in range(1, len(e.argv)):
            if field_static(e.argv[k]) == "-":
                rest = e.argv[k + 1 :]
                break
        python_code(rt, w, e, ctx, stdin_text(e), name + " (its stdin)", [Field(["-"], False, False)] + rest,
                    python_isolated(e))
    elif e.stdin is not None:
        unknown(rt, w, name + ": runs the program on its stdin, code vetter doesn't read", e.span, ctx,
                "inline_code", [])


def stdin_text(e):
    """The text on the command's stdin when known: a here-document's, a
    here-string's, what `echo TEXT |` prints."""
    from ..shells.bash.resolve import echo_output, exec_name

    if e.stdin.text is not None:
        return e.stdin.text
    p = e.stdin.producer
    if p is None:
        return None
    name = exec_name(p)
    if name != "echo" and name != "printf":
        return None
    words = []
    for a in p.argv[1:]:
        if not field_known(a):
            return None
        words.append(field_static(a))
    return echo_output(name, words)


def python_inline(rt, w, e, ctx, value, option):
    """python -c CODE ARGS: the code read and followed (sys.argv: -c and
    ARGS)."""
    from ..shells.bash.resolve import exec_name
    from ..shells.python.resolve import python_code

    rest = None
    for k in range(len(e.argv)):
        if e.argv[k] is value:
            rest = e.argv[k + 1 :]
    if rest is None:
        # (-cCODE: what follows the word it's glued in)
        rest = []
        for k in range(1, len(e.argv)):
            s = field_static(e.argv[k])
            if s is not None and s.startswith("-c") and field_static(value) == s[2:]:
                rest = e.argv[k + 1 :]
                break
    python_code(rt, w, e, ctx, field_static(value), str(exec_name(e)) + " " + str(option),
                [Field(["-c"], False, False)] + rest, python_isolated(e))


# Python's single-letter options that take no value
PYTHON_FLAGS = "bBdEhiIOPqsSuvx"


def python_isolated(e):
    """-I, -P, PYTHONSAFEPATH: the current folder isn't on python's module
    path (a json.py there isn't what `import json` runs)."""
    if "PYTHONSAFEPATH" in e.env and field_known(e.env["PYTHONSAFEPATH"]) \
            and field_static(e.env["PYTHONSAFEPATH"]) != "":
        return True
    for a in e.argv[1:]:
        s = field_static(a)
        if s is None or not s.startswith("-") or s.startswith("--") or len(s) < 2:
            break
        letters = s[1:]
        flags = True
        for c in letters:
            if c not in PYTHON_FLAGS:
                flags = False
        if flags and ("I" in letters or "P" in letters):
            return True
        if not flags:
            break
    return False


def stdlib_module(rt, w, e, ctx, name, m, rest):
    """python -m MODULE ARGS, a module of Python's standard library: its
    arguments are code (timeit, cProfile, pdb, trace), files it reads
    (base64, zipfile) or writes: those vetter knows read as they are
    (unittest: the project's tests; venv: the folders made; json.tool: a
    file read, one written), the others asked."""
    from ..shells.bash.resolve import unknown

    words = [a for a in rest if not (field_known(a) and field_static(a).startswith("-"))]
    if m == "unittest":
        unknown(rt, w, name + " -m unittest: runs the project's tests", e.span, ctx, "project_code", [])
    elif m == "venv":
        for a in words:
            e.roles.append(Role("write", a, "-m venv"))
    elif m == "json.tool":
        if len(words) > 0:
            e.roles.append(Role("read", words[0], "-m json.tool"))
        if len(words) > 1:
            e.roles.append(Role("write", words[1], "-m json.tool"))
    else:
        unknown(rt, w, name + " -m " + m + ": the standard library's " + m + " given arguments vetter doesn't follow",
                e.span, ctx, "inline_code", [])
        return
    if not python_isolated(e):
        # (the current folder first on its module path: a module of that
        # name there is what runs)
        unknown(rt, w, name + " -m " + m + ": a " + m.partition(".")[0] + " in the folder it runs in would run",
                e.span, ctx, "project_code", [])


def flag(rt, w, e, ctx, label, value, given):
    """A flag (or a subcommand, or the program itself) that does what vetter
    doesn't see; given: what it works on."""
    from ..shells.bash.resolve import unknown

    for o in option_names(e):
        if o in value.unless:
            return
    if value.kind == "delete_read":
        # (zip -m, tar --remove-files: the files it reads, deleted after;
        # marked, made deletes once its operands' roles are in)
        e.roles.append(Role("delete_read", Field([""], False, False), last_word(label)))
        return
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


def known_option(spec, name):
    """Does the spec list the option: its value's role or none, a flag, a
    switch, one taking a value glued on, one of a family it names?"""
    if name in spec.values or name in spec.roles or name in spec.flags or name in spec.switches \
            or name in spec.anywhere or name in spec.attached:
        return True
    for f in spec.families:
        # (-std=c11 is named -std: a family -std= is its)
        if name.startswith(f) or (name + "=").startswith(f):
            return True
    if name.startswith("-") and not name.startswith("--") and len(name) > 2:
        # (short ones together, -rq9: each one listed)
        for c in name[1:]:
            if "-" + c not in spec.switches and "-" + c not in spec.values and "-" + c not in spec.flags \
                    and "-" + c not in spec.roles:
                return False
        return True
    return False


def apply_options(rt, w, e, ctx, spec, options, parent, starts):
    from ..shells.bash.resolve import exec_name, unknown

    for name, value in options:
        if name.startswith("--?"):
            # (an abbreviation of several: one of them with a role, what it
            # does only running tells)
            candidates = field_static(value).split(",")
            risky = [c for c in candidates if c in spec.roles and spec.roles[c] != "plain"] + \
                    [c for c in candidates if c in spec.flags]
            if len(risky) > 0:
                unknown(rt, w, str(exec_name(e)) + " " + name[3:] + ": one of " + ", ".join(candidates)
                        + ", as the program reads it", e.span, ctx, "code", [])
            continue
        if name in spec.flags:
            flag(rt, w, e, ctx, str(exec_name(e)) + " " + name, spec.flags[name], starts)
        elif spec.single_dash_long and name.startswith("-") and not name.startswith("--") and len(name) > 2 \
                and name not in spec.values and name not in spec.switches:
            # (zip -rm: short ones together, -m's flag among them)
            for c in name[1:]:
                if "-" + c in spec.flags:
                    flag(rt, w, e, ctx, str(exec_name(e)) + " -" + c, spec.flags["-" + c], starts)
        top = parent if parent is not None else spec
        prog = str(exec_name(e))
        # (strict for this name; or another program's options read as its,
        # JAVA_TOOL_OPTIONS for gradle: strict as they are)
        strict = prog in top.strict or (len(top.strict) > 0 and (prog not in SPECS or SPECS[prog].names != top.names))
        if strict and not known_option(spec, name) and not (parent is not None and known_option(parent, name)):
            # (strict: one it doesn't list (a subcommand's, or its
            # program's), what it does only running tells)
            unknown(rt, w, str(exec_name(e)) + " " + name + ": an option vetter doesn't know", e.span, ctx, "code", [])
            continue
        if name not in spec.roles or value is None:
            continue
        role(rt, w, e, ctx, spec.roles[name], value, name, parent if parent is not None else spec)


def apply_operands(rt, w, e, ctx, spec, operands, parent):
    from ..shells.bash.resolve import exec_name, inner, unknown

    kind = spec.operands
    if kind == "sed" or kind == "awk":
        script_operands(rt, w, e, ctx, kind, operands)
        return
    if kind == "tar":
        for why in tar_files(e, spec):
            unknown(rt, w, str(exec_name(e)) + " " + why, e.span, ctx, "code", [])
        return
    if kind == "compressed":
        # (xz FILE: FILE.xz written beside it, FILE deleted; -c, -k, -t,
        # -l: only read)
        keep = False
        for o in option_names(e):
            if o == "--stdout" or o == "--to-stdout" or o == "--keep" or o == "--test" or o == "--list":
                keep = True
            elif not o.startswith("--") and ("c" in o or "k" in o or "t" in o or "l" in o):
                keep = True
        for o in operands:
            e.roles.append(Role("read", o, None))
            if not keep and not (field_known(o) and field_static(o) == "-"):
                e.roles.append(Role("write", o, None))
                e.roles.append(Role("delete", o, None))
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
    if kind == "go_run":
        # (go run a.go b.go ARGS, go run PACKAGE ARGS: the code; a remote
        # package's, downloaded)
        files = False
        for o in operands:
            s = field_static(o)
            if s is not None and s.endswith(".go"):
                files = True
                role(rt, w, e, ctx, "code_file", o, None, spec)
                continue
            if not files:
                go_package(rt, w, e, ctx, o)
            break
        return
    if kind == "less":
        for o in operands:
            s = field_static(o)
            if s is not None and s.startswith("+"):
                less_keys(rt, w, e, ctx, s)
            elif s is None and field_text(o).startswith("+"):
                unknown(rt, w, "less " + field_text(o) + ": keys only running tells", e.span, ctx, "code", [])
            else:
                e.roles.append(Role("read", o, None))
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
    if r == "project_file":
        # (cargo --manifest-path DIR/Cargo.toml, pytest a/test_x.py::t: the
        # folder it's in)
        if field_known(value):
            s = field_static(value).partition("::")[0]
            cut = max(s.rfind("/"), s.rfind("\\"))
            value = Field([s[:cut] if cut > 0 else ("/" if cut == 0 else ".")], False, False)
        r = "project"
    if r == "write" or r == "read" or r == "delete" or r == "url" or r == "cwd" or r == "image" \
            or r == "docker_volume" or r == "project":
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
        if field_known(value) and option is not None and option in e.env:
            # (RUSTC_WRAPPER=w: w run without it, or it would name w again)
            env = {k: v for k, v in e.env.items() if k != option}
            run(rt, w, [value], env, [], ctx, e.span, e.stdin, e.via + (labelled(name, option),))
        elif field_known(value):
            inner(rt, w, e, [value], ctx, labelled(name, option), {})
        else:
            unknown(rt, w, labelled(name, option) + ": runs a program only running tells", e.span, ctx, "code", [])
    elif r == "code_file" and field_known(value) and field_static(value) == "-" and option is None:
        # (python -, bash -: the program on its stdin, stdin_program's)
        pass
    elif r == "code_file":
        e.roles.append(Role("read", value, option))
        unknown(rt, w, joined(name, option) + ": runs the code in " + field_text(value), e.span, ctx, "code_file",
                [value])
    elif r == "package" or r == "package_script":
        what = "the package's script" if r == "package_script" else "the package"
        unknown(rt, w, str(name) + ": runs " + what + " " + field_text(value), e.span, ctx, r, [])
    elif r == "code:python" and field_known(value):
        python_inline(rt, w, e, ctx, value, option)
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
    elif r == "python_module":
        # (python -m pytest ARGS: pytest's, read by its spec; -m http.server,
        # a server; another module, the project's own code where it runs)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": a module only running tells", e.span, ctx, "code", [])
            return
        m = field_static(value)
        rest = []
        for k in range(1, len(e.argv)):
            s = field_static(e.argv[k])
            if s == "-m" and k + 1 < len(e.argv):
                rest = e.argv[k + 2 :]
                break
            if s is not None and s.startswith("-m") and len(s) > 2 and not s.startswith("--"):
                rest = e.argv[k + 1 :]
                break
        if m in PYTHON_MODULE_TOOLS:
            inner(rt, w, e, [Field([PYTHON_MODULE_TOOLS[m]], False, False)] + rest, ctx, str(name) + " -m " + m, {})
        elif m in PYTHON_MODULE_SERVERS:
            unknown(rt, w, str(name) + " -m " + m + ": serves the folder it runs in", e.span, ctx, "package", [])
        elif m.partition(".")[0] in PYTHON_STDLIB:
            stdlib_module(rt, w, e, ctx, str(name), m, rest)
        else:
            unknown(rt, w, str(name) + " -m " + m + ": runs the module, the project's own or an installed one",
                    e.span, ctx, "project_code", [])
    elif r == "trace_file":
        # (GIT_TRACE=/path: the trace written there; 1, 2, true: stderr)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": a trace written where only running tells", e.span, ctx, "code",
                    [])
        elif field_static(value).startswith("/") or (len(field_static(value)) > 2 and field_static(value)[1] == ":"):
            e.roles.append(Role("write", value, option))
    elif r == "opt_info":
        # (-fopt-info-all=FILE, -fopt-info=FILE: the notes written there)
        if field_known(value) and "=" in field_static(value):
            e.roles.append(Role("write", Field([field_static(value).partition("=")[2]], False, False), option))
        elif not field_known(value):
            unknown(rt, w, labelled(name, option) + ": a file only running tells", e.span, ctx, "code", [])
    elif r == "module_patch":
        # (java --patch-module MODULE=FILE:FILE: the classes in each)
        if field_known(value):
            role(rt, w, e, ctx, "classpath", Field([field_static(value).partition("=")[2]], False, False), option,
                 spec)
        else:
            unknown(rt, w, labelled(name, option) + ": classes from where only running tells", e.span, ctx, "code", [])
    elif r == "rustc_extern":
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": a crate only running tells", e.span, ctx, "code", [])
        elif "=" in field_static(value):
            role(rt, w, e, ctx, "code_file", Field([field_static(value).partition("=")[2]], False, False), option,
                 spec)
    elif r == "read_or_list":
        # (7z a ARCHIVE @LIST: the files LIST names)
        if field_known(value) and field_static(value).startswith("@") and len(field_static(value)) > 1:
            role(rt, w, e, ctx, "file_list", Field([field_static(value)[1:]], False, False), option, spec)
        else:
            e.roles.append(Role("read", value, option))
    elif r == "archive_switch":
        # (7z -i@LIST, -ir!PATH, -x...: the files a list names, a path's)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": files only running tells", e.span, ctx, "code", [])
            return
        s = field_static(value)
        at = s.find("@")
        bang = s.find("!")
        if at >= 0 and (bang < 0 or at < bang):
            role(rt, w, e, ctx, "file_list", Field([s[at + 1 :]], False, False), option, spec)
        elif bang >= 0 and (option == "-i" or option == "-ai"):
            e.roles.append(Role("read", Field([s[bang + 1 :]], False, False), option))
    elif r == "awk_w":
        # (mawk -W exec=FILE: the program in FILE; -W exec FILE: the
        # operand after, read as the program's file)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": an option only running tells", e.span, ctx, "code", [])
        elif awk_exec(value):
            val = field_static(value).partition("=")[2]
            if val != "":
                role(rt, w, e, ctx, "code_file", Field([val], False, False), option, spec)
            else:
                unknown(rt, w, labelled(name, option) + " exec: runs the code in the file after it", e.span, ctx,
                        "code_file", [])
    elif r == "options:java" or r == "options:javac":
        # (javac -J-agentpath:...: an option of the JVM it runs in)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": an option only running tells", e.span, ctx, "configured", [])
        else:
            pspec = SPECS[r[8:]]
            apply_options(rt, w, e, ctx, pspec, parse([value], pspec).options, None, [])
    elif r == "gradle_property":
        # (-Dorg.gradle.jvmargs=...: the daemon's JVM options;
        # org.gradle.java.home: its java)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": a setting only running tells", e.span, ctx, "configured", [])
            return
        key, _, val = field_static(value).partition("=")
        if key == "org.gradle.jvmargs":
            words = split_words(val)
            if words is None:
                unknown(rt, w, labelled(name, option) + ": JVM options vetter can't split", e.span, ctx, "configured",
                        [])
            else:
                pspec = SPECS["java"]
                p = parse([Field([x], False, False) for x in words], pspec)
                apply_options(rt, w, e, ctx, pspec, p.options, None, [])
        elif key == "org.gradle.java.home":
            role(rt, w, e, ctx, "program_dir", Field([val], False, False), option + key, spec)
        elif key.startswith("org.gradle.") and (key.endswith(".home") or key.endswith(".dir")
                                                 or key.endswith("installations.paths")):
            unknown(rt, w, labelled(name, option) + key + ": sets what it runs", e.span, ctx, "configured", [])
    elif r == "java_log":
        # (-Xlog:what:file=PATH:...: the log written there)
        if field_known(value):
            path = log_file(field_static(value))
            if path is not None:
                e.roles.append(Role("write", Field([path], False, False), option))
        else:
            unknown(rt, w, labelled(name, option) + ": a log written where only running tells", e.span, ctx, "code",
                    [])
    elif r == "java_xx":
        # (-XX:LogFile=PATH writes it; -XX:OnError=CMD runs it)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": a setting only running tells", e.span, ctx, "configured", [])
            return
        key, _, val = field_static(value).partition("=")
        if key in JAVA_XX_WRITES:
            e.roles.append(Role("write", Field([val], False, False), option + key))
        elif key == "OnError" or key == "OnOutOfMemoryError":
            for c in val.split(";"):
                code(rt, w, c, ctx, e.span, labelled(name, option + key), False, None)
        elif key == "Flags" or key == "VMOptionsFile":
            role(rt, w, e, ctx, "config_file", Field([val], False, False), option + key, spec)
        elif key in JAVA_XX_PATHS:
            role(rt, w, e, ctx, "classpath", Field([val], False, False), option + key, spec)
    elif r == "interpreter":
        # (UV_PYTHON=/tmp/p: that interpreter runs; UV_PYTHON=3.12: one found)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": an interpreter only running tells", e.span, ctx, "code", [])
        elif "/" in field_static(value) or "\\" in field_static(value):
            role(rt, w, e, ctx, "program", value, option, spec)
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
    elif r == "java_main":
        # (java X.java: compiled and run; a class: from the class path)
        s = field_static(value)
        if s is None or s.endswith(".java"):
            role(rt, w, e, ctx, "code_file", value, option, spec)
    elif r == "classpath":
        # (java -cp a:b, javac -processorpath: the classes run, each entry's)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": classes from where only running tells", e.span, ctx, "code", [])
        else:
            s = field_static(value)
            for entry in (s.split(";") if ";" in s else s.split(":")):
                if entry != "":
                    f = Field([entry], False, False)
                    unknown(rt, w, labelled(name, option) + ": runs the code in " + entry, e.span, ctx, "code_file", [f])
    elif r == "cmake_define":
        # (-DKEY[:TYPE]=VALUE: a script cmake includes, a program it runs)
        if not field_known(value):
            unknown(rt, w, labelled(name, option) + ": a setting only running tells", e.span, ctx, "configured", [])
        else:
            key, _, val = field_static(value).partition("=")
            key = key.partition(":")[0].upper()
            if key in CMAKE_CODE or (key.startswith("CMAKE_PROJECT_") and "INCLUDE" in key):
                for f in val.split(";"):
                    if f != "":
                        unknown(rt, w, "cmake -D" + key + ": runs the code in " + f, e.span, ctx, "code_file",
                                [Field([f], False, False)])
            elif key.endswith("_COMPILER_LAUNCHER") or key.endswith("_LINKER_LAUNCHER") or key in CMAKE_PROGRAMS:
                if val != "":
                    role(rt, w, e, ctx, "program", Field([val.split(";")[0]], False, False), "-D" + key, spec)
    elif r == "file_list":
        # (tar -T, zstd --filelist, sort --files0-from: the list read, and
        # the files in it, which only running tells)
        e.roles.append(Role("read", value, option))
        unknown(rt, w, labelled(name, option) + " " + field_text(value) + ": reads the files it lists", e.span, ctx,
                "code", [])
    elif r == "config_file":
        # (curl -K: more options from the file, which only running tells)
        e.roles.append(Role("read", value, option))
        unknown(rt, w, labelled(name, option) + " " + field_text(value) + ": options read from it", e.span, ctx,
                "configured", [])
    elif r == "configured":
        # (a setting that changes what it runs, its effect not followed)
        unknown(rt, w, labelled(name, option) + " " + field_text(value) + ": sets what it runs", e.span, ctx,
                "configured", [])


# Where a program finds the code it loads (not the programs it runs, PATH):
# each folder's code, as the project's own where it is
MODULE_PATHS = {"PYTHONPATH", "NODE_PATH", "PERL5LIB", "PERLLIB", "RUBYLIB", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"}

# python -m MODULE: the modules that are a tool vetter has a spec for; the
# ones that serve the folder they run in
PYTHON_MODULE_TOOLS = {"pytest": "pytest", "py.test": "pytest", "pip": "pip", "pip3": "pip", "uv": "uv"}
PYTHON_MODULE_SERVERS = {"http.server", "SimpleHTTPServer", "CGIHTTPServer", "smtpd", "xmlrpc.server", "pydoc"}

# java -XX:KEY=PATH: files the JVM writes, paths its classes come from
JAVA_XX_WRITES = {"LogFile", "ErrorFile", "HeapDumpPath", "ReplayDataFile", "PerfDataSaveFile", "SharedArchiveFile",
                  "ArchiveClassesAtExit", "DumpLoadedClassList"}
JAVA_XX_PATHS = {"SharedClassListFile"}


def log_file(s):
    """-Xlog's output: :file=PATH after what's logged (a Windows path's
    drive colon its own); None: the console."""
    k = s.find("file=")
    if k < 0:
        return None
    rest = s[k + 5 :]
    if rest.startswith('"'):
        end = rest.find('"', 1)
        return rest[1:end] if end > 0 else rest[1:]
    end = rest.find(":")
    if end == 1 and len(rest) > 2 and (rest[2] == "\\" or rest[2] == "/"):
        # (C:\log.txt)
        end = rest.find(":", 2)
    return rest if end < 0 else rest[:end]


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


# tar's modes by their letter and long name; the short options taking a
# value (in an old-style cluster, `czf ARCHIVE`, the values follow in order)
TAR_MODES = "cruxtdA"
TAR_LONG_MODES = {"--create": "c", "--append": "r", "--update": "u", "--extract": "x", "--get": "x", "--list": "t",
                  "--diff": "d", "--compare": "d", "--delete": "D", "--catenate": "A", "--concatenate": "A"}
TAR_VALUED = "fCTXIFbHVNKLg"


def tar_files(e, spec):
    """tar's archive and files: created (c, r, u, A), each file read and
    the archive written; extracted or listed (x, t), the archive read; each
    file relative to the -C before it. What it does that the options'
    flags don't see: an old-style cluster's P (absolute names), h (links
    followed); an archive on another host (HOST:FILE, through rsh)."""
    args = e.argv[1:]
    out = []
    local = False
    mode = ""
    archive = None
    where = None
    files = []
    k = 0
    while k < len(args):
        s = field_static(args[k])
        if s is None:
            files.append((where, args[k]))
            k += 1
            continue
        if k == 0 and s != "" and not s.startswith("-"):
            # (czf ARCHIVE FILE...: the letters, their values after)
            n = 0
            for c in s:
                if c == "P":
                    out.append("P: extracts to the paths the archive names, anywhere")
                elif c == "h":
                    out.append("h: reads what the links in its files point to")
                if c in TAR_MODES:
                    mode = c
                if c in TAR_VALUED and k + 1 + n < len(args):
                    v = args[k + 1 + n]
                    n += 1
                    if c == "f":
                        archive = v
                    elif c == "C":
                        where = v
            k += 1 + n
            continue
        if s == "--":
            for a in args[k + 1 :]:
                files.append((where, a))
            break
        if s.startswith("--"):
            name, eq, val = s.partition("=")
            if name == "--force-local":
                local = True
            if name in TAR_LONG_MODES:
                mode = TAR_LONG_MODES[name]
            elif name in spec.values:
                v = Field([val], False, False) if eq != "" else (args[k + 1] if k + 1 < len(args) else None)
                if eq == "":
                    k += 1
                if name == "--file":
                    archive = v
                elif name == "--directory":
                    where = v
            k += 1
            continue
        if s.startswith("-") and len(s) > 1:
            for i in range(1, len(s)):
                c = s[i]
                if c in TAR_MODES:
                    mode = c
                if c in TAR_VALUED:
                    if i + 1 < len(s):
                        v = Field([s[i + 1 :]], False, False)
                    else:
                        v = args[k + 1] if k + 1 < len(args) else None
                        k += 1
                    if c == "f":
                        archive = v
                    elif c == "C":
                        where = v
                    break
            k += 1
            continue
        files.append((where, args[k]))
        k += 1
    creates = mode == "c" or mode == "r" or mode == "u" or mode == "A" or mode == "D"
    if archive is not None and not (field_known(archive) and field_static(archive) == "-"):
        e.roles.append(Role("write" if creates else "read", archive, "-f"))
    if creates or mode == "d":
        for d, f in files:
            if mode != "D":
                e.roles.append(Role("read", below(d, f), None))
    if archive is not None and field_known(archive) and not local:
        a = field_static(archive)
        colon = a.find(":")
        slash = a.find("/")
        if colon > 0 and (slash < 0 or colon < slash):
            # (HOST:FILE, USER@HOST:FILE: the archive sent or fetched
            # through rsh / ssh)
            out.append("-f " + a + ": the archive on another host, through rsh")
    return out


def below(d, f):
    """f relative to the folder -C named (None: where it runs)."""
    if d is None:
        return f
    if not field_known(d) or not field_known(f):
        return Field([Dynamic(None, "")], False, False)
    fs = field_static(f)
    if fs.startswith("/") or fs.startswith("~"):
        return f
    return Field([field_static(d).rstrip("/") + "/" + fs], False, False)


def awk_exec(value):
    """mawk -W exec[=FILE] (any abbreviation, -W e): the program's file;
    an unknown -W: maybe."""
    if not field_known(value):
        return True
    key = field_static(value).partition("=")[0]
    return key != "" and "exec".startswith(key)


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
        elif o == "-f" or o == "--file" or (kind == "awk" and (o == "-E" or o == "--exec")):
            given = True
        elif kind == "awk" and o == "-W" and v is not None and awk_exec(v):
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


AWK_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\x07", "b": "\x08", "f": "\x0c", "v": "\x0b"}


def awk_escape(prog, j):
    """The character a string's \\ escape at prog[j] (after the \\) is, as
    awk reads it (\\057 /, \\x2f /, \\n), and where it ends."""
    n = len(prog)
    c = prog[j]
    if "0" <= c <= "7":
        k = j
        v = 0
        while k < n and k < j + 3 and "0" <= prog[k] <= "7":
            v = v * 8 + (ord(prog[k]) - 48)
            k += 1
        return chr(v % 256), k
    if c == "x":
        k = j + 1
        v = 0
        while k < n and k < j + 3 and (("0" <= prog[k] <= "9") or ("a" <= prog[k].lower() <= "f")):
            d = prog[k].lower()
            v = v * 16 + (ord(d) - 48 if d <= "9" else ord(d) - 87)
            k += 1
        if k > j + 1:
            return chr(v), k
        return "x", j + 1
    if c in AWK_ESCAPES:
        return AWK_ESCAPES[c], j + 1
    return c, j + 1


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
                    c2, j = awk_escape(prog, j + 1)
                    text += c2
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
            elif text == "ARGV" and not (k + 1 < n and t[k + 1] == ("op", "[")):
                # (ARGV whole, given to split() or delete: changed)
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


def split_words(s):
    """A value split as a shell splits words, quotes kept together and
    taken off (MAKEFLAGS, GOFLAGS...); None: a quote that doesn't close."""
    out = []
    cur = ""
    started = False
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "'" or c == '"':
            j = s.find(c, i + 1)
            if j < 0:
                return None
            cur += s[i + 1 : j]
            started = True
            i = j + 1
            continue
        if c == "\\" and i + 1 < n:
            cur += s[i + 1]
            started = True
            i += 2
            continue
        if is_space(c):
            if started:
                out.append(cur)
            cur = ""
            started = False
            i += 1
            continue
        cur += c
        started = True
        i += 1
    if started:
        out.append(cur)
    return out


def is_shell_name(s):
    if s == "":
        return False
    for c in s:
        if c in " \t\n|&;()<>$`'\"\\":
            return False
    return True


def env_role(var):
    """What the variable is to the programs reading it: its name's, or a
    pattern's it matches; None: nothing."""
    if var in ENV:
        return ENV[var]
    for head, tail, r in ENV_PATTERNS:
        if len(var) >= len(head) + len(tail) and var.startswith(head) and var.endswith(tail):
            return r
    return None


def apply_env(rt, w, e, ctx):
    from ..shells.bash.resolve import code, copy, exec_name, expanded_later, run, unknown

    name = exec_name(e)
    who = name if name is not None and name != "" else "it"
    whole = e.env
    for var, value in whole.items():
        # (what a variable makes it run runs without it: RUSTFLAGS' linker
        # isn't given RUSTFLAGS again)
        e.env = {k: v for k, v in whole.items() if k != var}
        if var.startswith("BASH_FUNC_"):
            # (BASH_FUNC_f%%='() { ...; }': a bash it starts defines f, run
            # in place of the command f)
            fname = var[10:]
            if fname.endswith("%%"):
                fname = fname[: len(fname) - 2]
            elif fname.endswith("()"):
                fname = fname[: len(fname) - 2]
            if field_known(value) and is_shell_name(fname):
                code(rt, w, fname + " " + field_static(value), copy(ctx), e.span, var, False, None)
            else:
                unknown(rt, w, var + ": a bash function only running tells", e.span, ctx, "code", [])
            continue
        r = env_role(var)
        if var == "HOME" and field_static(value) == ctx.home:
            # (HOME=$HOME: the home it has)
            continue
        if r == "tool_setting":
            # (a tool's or a runtime's own, not one known to change nothing:
            # what it does with it, only running tells; a wrapper's program
            # gets it too, and is decided on its own)
            if e.kind == "program" and name is not None and name not in WRAPPERS:
                unknown(rt, w, var + "=" + field_text(value) + ": what " + who + " does with " + var
                        + ", vetter doesn't know", e.span, ctx, "code", [])
            continue
        if r is None or r == "plain":
            continue
        if r.startswith("options:"):
            # (MAKEFLAGS, GOFLAGS, JAVA_TOOL_OPTIONS: more options, read as
            # the program's own, its roles theirs)
            prog = r[8:]
            if prog not in SPECS:
                continue
            if not field_known(value):
                unknown(rt, w, var + ": " + prog + " options only running tells", e.span, ctx, "configured", [])
                continue
            if var.startswith("CARGO_ENCODED_"):
                words = [x for x in field_static(value).split("\x1f") if x != ""]
            else:
                words = split_words(field_static(value))
            if words is None:
                unknown(rt, w, var + ": " + prog + " options vetter can't split", e.span, ctx, "configured", [])
                continue
            if prog == "make":
                # (MAKEFLAGS' first word may be flags with no dash: k, ks)
                if len(words) > 0 and not words[0].startswith("-") and "=" not in words[0]:
                    words[0] = "-" + words[0]
            pspec = SPECS[prog]
            if pspec.subcommands and name == prog:
                # (GOFLAGS: the subcommand's options, go build's)
                for a in e.argv[1:]:
                    s = field_static(a)
                    if s is not None and not s.startswith("-"):
                        if s in pspec.sub:
                            pspec = pspec.sub[s]
                        break
            p = parse([Field([x], False, False) for x in words], pspec)
            vector_ctx = copy(ctx)
            if var in vector_ctx.exported:
                vector_ctx.exported.pop(var)
            apply_options(rt, w, e, vector_ctx, pspec, p.options, None, [])
            for o in p.operands:
                s = field_static(o)
                if prog == "make" and s is not None and "=" in s:
                    mvar, _, mval = s.partition("=")
                    make_variable(rt, w, e, vector_ctx, mvar, mval)
                elif prog == "less" and s is not None and s.startswith("+"):
                    # (LESS='+!cmd': keys less runs first)
                    less_keys(rt, w, e, vector_ctx, s)
                elif prog == "java":
                    # (an operand in it: a class, its code)
                    role(rt, w, e, vector_ctx, "code_file", o, var, pspec)
            continue
        if r == "code_file_list":
            # (MAKEFILES: makefiles read first, their recipes run)
            if not field_known(value):
                unknown(rt, w, var + ": code files only running tells", e.span, ctx, "configured", [])
                continue
            for f in split_words(field_static(value)) or []:
                unknown(rt, w, var + "=" + f + ": " + who + " runs the code in it", e.span, ctx, "env_code",
                        [Field([f], False, False)])
            continue
        if r == "shell_expanded":
            # (a shell given it expands it again: PS4 before each traced
            # command, its substitutions run)
            if field_known(value):
                expanded_later(rt, w, copy(ctx), e.span, var, field_static(value))
            else:
                unknown(rt, w, var + ": a value a shell expands, only running tells", e.span, ctx, "code", [])
            continue
        if r == "lookup_path" and var in MODULE_PATHS and field_known(value):
            # (PYTHONPATH=src:lib: the code loaded from each folder, the
            # project's own where it is; an empty part, where it runs)
            for d in field_static(value).split(":"):
                folder = Field([d if d != "" else "."], False, False)
                unknown(rt, w, var + "=" + field_text(value) + ": " + who + " loads code from " + field_text(folder),
                        e.span, ctx, "project_code", [folder])
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
    e.env = whole
