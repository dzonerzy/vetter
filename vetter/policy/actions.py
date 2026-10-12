"""What a command does, as actions: a resolution's executions and unknowns
made Parts, each with its actions: run, read / write / delete (absolute
paths), network / download / send (hosts)."""

from dataclasses import dataclass

from .. import paths
from ..paths import fold
from ..shells.bash.expand import Dynamic, field_known, field_static, field_text
from ..shells.bash.resolve import exec_name
from ..specs import SPECS, parse

DOWNLOADERS = {"curl", "wget", "fetch", "aria2c", "http", "xh", "Invoke-WebRequest", "Invoke-RestMethod",
               "Start-BitsTransfer", "bitsadmin", "certutil"}
SENDING_OPTIONS = {"-d", "--data", "--data-binary", "--data-raw", "--data-urlencode", "--data-ascii", "--json",
                   "-F", "--form", "-T", "--upload-file", "--post-data", "--post-file", "--body-data",
                   "--body-file"}
SOCKETS = {"nc", "ncat", "netcat", "socat", "telnet"}

# What vetter can't see, by the kind the resolver gives it
RUN_KINDS = {
    "code": "unknown", "lookup_path": "unknown", "code_file": "script", "downloaded_code": "downloaded",
    "package": "package", "package_script": "project-code", "project_code": "project-code",
    "inline_code": "inline", "configured": "configured", "persistent": "configured", "env_code": "injected",
    "repo_config": "project-code",
}
QUIET = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/zero", "/dev/random", "/dev/urandom"}


@dataclass
class Action:
    verb: str
    path: object
    host: object
    kind: object
    # (the value as written, for traces)
    text: str
    # (the folder a tool works on, its path: not a program found there)
    folder: bool = False
    # (asked for by the code a program is given (python -c): not the
    # program's own doing, a rule allowing the program doesn't cover it)
    inline: bool = False


def action_text(a):
    """str(action)"""
    obj = a.kind
    if obj is None or obj == "":
        obj = a.path
    if obj is None or obj == "":
        obj = a.host
    if obj is None or obj == "":
        obj = a.text
    if obj is None:
        obj = ""
    out = a.verb + " " + obj
    return out.strip()


@dataclass
class Part:
    """One thing a command does: an execution, or what vetter can't see."""

    what: object
    name: object
    positional: list
    flags: set
    actions: list
    via: tuple
    span: tuple
    dynamic: bool
    label: str
    producer: object
    unknown: bool
    words: list
    # (an execution's: it's a cmdlet vetter knows)
    cmdlet: bool


def execution_text(e):
    """str(execution): its words, `   (via a <- b)`"""
    words = " ".join([field_text(f) for f in e.argv])
    via = " <- ".join([v for v in e.via])
    return words + ("   (via " + via + ")" if via != "" else "")


def parts(resolution, home):
    out = []
    # (the parts of executions, by the execution's index; -1: none)
    index = []
    for e in resolution.executions:
        if (e.kind == "group" or e.kind == "redirect") and len(file_actions(e)) == 0:
            index.append(-1)
            continue
        index.append(len(out))
        out.append(execution_part(e, home))
    n = len(resolution.executions)
    for k in range(n):
        e = resolution.executions[k]
        if index[k] < 0:
            continue
        piped = e.stdin is not None and e.stdin.producer is not None
        # (its producer: what's piped in, else what it reads through <(cmd))
        producer = e.stdin.producer if piped else e.fed
        if producer is None:
            continue
        p = out[index[k]]
        for j in range(n):
            if resolution.executions[j] is producer:
                p.producer = out[index[j]] if index[j] >= 0 else None
                break
        if not piped:
            continue
        if p.name in DOWNLOADERS or p.name in SOCKETS:
            # (what's piped into it is sent)
            for a in [x for x in p.actions]:
                if a.verb == "network" or a.verb == "download":
                    sent = False
                    for x in p.actions:
                        if x.verb == "send" and x.host == a.host:
                            sent = True
                    if not sent:
                        p.actions.append(Action("send", None, a.host, None, a.text))
            if p.name in SOCKETS:
                sends = False
                for a in p.actions:
                    if a.verb == "send":
                        sends = True
                if not sends:
                    p.actions.append(Action("send", None, None, None, "?"))
    for u in resolution.unknowns:
        out.append(unknown_part(u))
    generated(out)
    extracted(out)
    return out


def looked_up(p):
    """The files a command name may be found as before PATH's (cmd's
    current folder)."""
    if p.unknown:
        return []
    out = []
    for r in p.what.roles:
        if r.role == "lookup":
            f = absolute(p.what.cwd, r.value)
            if f is not None:
                out.append(f)
    return out


def extracted(parts):
    """What's below where an archive was extracted, later in the command,
    may be a link it made (proc/self/root: /): a file there is one only
    running tells; what runs from there, not the project's own."""
    roots = []
    for p in parts:
        if len(roots) > 0:
            for a in p.actions:
                if a.path is None or not below_any(a.path, roots):
                    continue
                if a.verb == "run":
                    if a.kind is None or a.kind == "script" or a.kind == "project-code":
                        a.kind = "generated"
                elif a.verb == "read" or a.verb == "write" or a.verb == "delete":
                    a.text = a.text + " (below what an archive extracted: maybe through a link it made)"
                    a.path = None
        if p.unknown:
            continue
        for r in p.what.roles:
            if r.role == "extract":
                root = absolute(p.what.cwd, r.value)
                roots.append(root if root is not None else "")


def below_any(path, roots):
    for r in roots:
        # ("": a root only running tells, anywhere)
        if r == "" or path.startswith(r.rstrip("/") + "/"):
            return True
    return False


def generated(parts):
    """What the command runs that it wrote itself (`echo ... > x.sh; sh
    x.sh`) isn't the project's own code: its run's kind `generated`. What
    build tools write (gcc -o app && ./app) is the project's, unless the
    command wrote something itself too (a source it then built)."""
    written = []
    built = []
    for p in parts:
        for a in p.actions:
            if a.verb == "write" and a.path is not None:
                if p.name is not None and p.name in BUILD_TOOLS:
                    built.append(a.path)
                else:
                    written.append(a.path)
    if len(written) == 0:
        return
    written += built
    folded = [fold(f) for f in written]
    for p in parts:
        for found in looked_up(p):
            # (git after writing git.cmd where cmd looks first: that runs)
            if fold(found) in folded:
                p.actions.append(Action("run", found, None, "generated", "cmd finds " + found + " first"))
    for p in parts:
        for a in p.actions:
            # (downloaded, injected, ...: what's worse about it kept)
            plain = a.kind is None or a.kind == "script" or a.kind == "project-code"
            if a.verb == "run" and plain and a.path is not None and a.path in written and not a.folder:
                a.kind = "generated"
            elif a.verb == "run" and a.kind == "project-code" and a.path is not None:
                # (make -C d after writing d/Makefile: what it runs, written)
                for f in written:
                    if defines(f, a.path, p.what.program if p.unknown else ""):
                        a.kind = "generated"


# The files that say what a tool on a folder runs: its build's, its tests',
# its package's scripts, the repository's config and hooks
DEFINITIONS = ("Makefile", "makefile", "GNUmakefile", "build.ninja", "CMakeLists.txt", "CMakePresets.json",
               "CMakeUserPresets.json", "conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini",
               "setup.py", "package.json", ".npmrc", ".yarnrc", ".yarnrc.yml", ".pnpmfile.cjs", "Cargo.toml",
               "build.rs", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
               "gradle.properties", "pom.xml", "build.zig", "build.zig.zon", "go.mod", "go.work", "Dockerfile",
               "Containerfile", "Rakefile", "Gemfile", "noxfile.py", "Justfile", "justfile", "Taskfile.yml")
# (in these folders, any file: .cargo/config.toml, .git/config, .git/hooks/*)
DEFINITION_DIRS = ("/.git/", "/.cargo/", "/.mvn/", "/.gradle/", "/.husky/")


# Each tool's own: the files and folders saying what it runs (another tool's,
# a pyproject.toml for git, nothing to it); a tool not here, any of them
TOOL_DEFINITIONS = {
    "git": ((), ("/.git/",)),
    "make": (("Makefile", "makefile", "GNUmakefile"), ()),
    "gmake": (("Makefile", "makefile", "GNUmakefile"), ()),
    "ninja": (("build.ninja",), ()),
    "cmake": (("CMakeLists.txt", "CMakePresets.json", "CMakeUserPresets.json"), ()),
    "cargo": (("Cargo.toml", "build.rs"), ("/.cargo/",)),
    "npm": (("package.json", ".npmrc"), ()),
    "pnpm": (("package.json", ".npmrc", ".pnpmfile.cjs"), ()),
    "yarn": (("package.json", ".npmrc", ".yarnrc", ".yarnrc.yml"), ()),
    "bun": (("package.json", ".npmrc", "bunfig.toml"), ()),
    "pytest": (("conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"), ()),
    "py.test": (("conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"), ()),
    "gradle": (("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties"),
               ("/.gradle/",)),
    "mvn": (("pom.xml",), ("/.mvn/",)),
    "zig": (("build.zig", "build.zig.zon"), ()),
    "go": (("go.mod", "go.work"), ()),
    "docker": (("Dockerfile", "Containerfile"), ()),
}


def defines(path, folder, tool):
    """Is the file one that says what the tool (any, "") on the folder
    runs: in the folder or below it, or above it (a workspace's, the
    repository's)?"""
    parent, _, leaf = path.rpartition("/")
    leaves = DEFINITIONS
    dirs = DEFINITION_DIRS
    if tool in TOOL_DEFINITIONS:
        leaves = TOOL_DEFINITIONS[tool][0]
        dirs = TOOL_DEFINITIONS[tool][1]
    special = False
    for d in dirs:
        if d in path + "/" and d not in folder + "/":
            special = True
    if leaf not in leaves and not special:
        return False
    here = folder.rstrip("/") + "/"
    if path.startswith(here):
        return True
    top = parent
    for d in dirs:
        k = (path + "/").find(d)
        if k >= 0 and k < len(top):
            top = path[:k]
    return here.startswith(top.rstrip("/") + "/")


# Programs that write what they build from the project's sources
BUILD_TOOLS = {"gcc", "g++", "cc", "c++", "clang", "clang++", "rustc", "cargo", "go", "javac", "zig", "make", "gmake",
               "cmake", "ninja", "tsc", "dotnet", "mvn", "gradle", "npm", "pnpm", "yarn", "bun", "pip", "pip3", "uv"}


def execution_part(e, home):
    plain = e.kind != "group" and e.kind != "redirect"
    name = exec_name(e) if plain else None
    actions = []
    first = e.argv[0] if len(e.argv) > 0 else None
    if plain:
        named_by_path = first is not None and field_known(first) and ("/" in field_static(first)
                                                                      or "\\" in field_static(first))
        path = absolute(e.cwd, first) if named_by_path else None
        actions.append(Action("run", path, None, None, field_text(first) if first is not None else "None"))
    actions += file_actions(e)
    readonly = (name is not None and name in SPECS and SPECS[name].readonly) or e.readonly
    if readonly:
        reads = False
        for a in actions:
            if a.verb == "read":
                reads = True
        if not reads:
            actions.append(Action("read", e.cwd, None, None, "."))
    hosts = hosts_of(e)
    for h, text in hosts:
        # (a rule about `network` covers download and send too)
        actions.append(Action("download" if name in DOWNLOADERS else "network", None, h, None, text))
    fl = flags(e)
    sending = False
    if name in DOWNLOADERS:
        for f in fl:
            if f in SENDING_OPTIONS:
                sending = True
    for r in e.roles:
        if r.role == "send":
            sending = True
    if sending:
        for h, text in hosts:
            actions.append(Action("send", None, h, None, text))
    for r in e.roles:
        if r.role == "code_url" or r.role == "code_send":
            known = field_known(r.value)
            actions.append(Action("network" if r.role == "code_url" else "send", None,
                                  url_host(field_static(r.value)) if known else None, None,
                                  field_static(r.value) if known else field_text(r.value), False, True))
    dynamic = False
    for a in e.argv:
        if not field_known(a):
            dynamic = True
    return Part(e, name, positional(e) if name is not None else [], fl, actions, e.via, e.span, dynamic,
                execution_text(e), None, False, e.words, e.cmdlet)


def unknown_part(u):
    kind = RUN_KINDS[u.kind] if u.kind in RUN_KINDS else "unknown"
    found = [absolute(u.cwd, f) for f in u.paths]
    actions = [Action("run", found[0] if len(found) > 0 else None, None, kind, u.reason, kind == "project-code")]
    return Part(u, None, [], set(), actions, u.via, u.span, True, u.reason, None, True, [], False)


def writes(r):
    return r.op == ">" or r.op == ">>" or r.op == ">|" or r.op == "&>" or r.op == "&>>" or r.op == "<>"


def reads(r):
    return r.op == "<" or r.op == "<>"


def file_actions(e):
    out = []
    for r in e.roles:
        # (reading or writing <(cmd), >(cmd): a pipe, cmd decided on its own)
        pipe = r.role != "delete" and is_procsub(r.value)
        # (an operand `-`: its stdin or stdout, not a file)
        dash = r.role != "delete" and field_known(r.value) and field_static(r.value) == "-"
        if (r.role == "write" or r.role == "read" or r.role == "delete") and not pipe and not dash:
            out.append(Action(r.role, absolute(e.cwd, r.value), None, None, field_text(r.value)))
    for r in e.redirects:
        if r.target is None or r.op == ">&" or r.op == "<&":
            continue
        if field_known(r.target) and field_static(r.target) in QUIET:
            continue
        if is_procsub(r.target):
            # (> >(cmd): a pipe to cmd, decided on its own; no file)
            continue
        verb = "write" if writes(r) else ("read" if reads(r) else None)
        if verb is not None:
            out.append(Action(verb, absolute(e.cwd, r.target), None, None, field_text(r.target)))
    return out


def is_procsub(f):
    """A field that's only a process substitution, <(...) or >(...)."""
    if len(f.parts) != 1 or not isinstance(f.parts[0], Dynamic):
        return False
    node = f.parts[0].node
    return node is not None and node.rule == "procsub"


def absolute(cwd, f):
    """A Field's absolute path; a pattern: the directory before its first
    wildcard; None if only running tells."""
    p = field_static(f)
    if p is None:
        return None
    if f.glob:
        cut = len(p)
        for c in "*?[":
            k = p.find(c)
            if k >= 0 and k < cut:
                cut = k
        head = p[:cut]
        p = head.rpartition("/")[0] if "/" in head else ""
        if p == "" and field_static(f).startswith("/"):
            p = "/"
    return paths.join(cwd, p if p != "" else ".")


def hosts_of(e):
    out = []
    for r in e.roles:
        if r.role != "url":
            continue
        if not field_known(r.value):
            out.append((None, field_text(r.value)))
            continue
        out.append((url_host(field_static(r.value)), field_static(r.value)))
    return out


SCHEME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-."
HEX = "0123456789abcdefABCDEF"


def ascii_lower(s):
    out = ""
    for c in s:
        out += chr(ord(c) + 32) if c >= "A" and c <= "Z" else c
    return out


def is_ascii(s):
    return len(s.encode()) == len(s)


def url_host(u):
    """The host a URL names (policy/actions.py's url_host)."""
    if "://" not in u:
        u = "//" + u
    i = 0
    while i < len(u) and ord(u[i]) <= 0x20:
        i += 1
    u = u[i:].replace("\t", "").replace("\r", "").replace("\n", "")
    i = u.find(":")
    if i > 0 and ((u[0] >= "a" and u[0] <= "z") or (u[0] >= "A" and u[0] <= "Z")):
        scheme = True
        for c in u[:i]:
            if c not in SCHEME_CHARS:
                scheme = False
        if scheme:
            u = u[i + 1 :]
    if u[:2] != "//":
        return None
    end = len(u)
    for c in "/?#":
        k = u.find(c, 2)
        if k >= 0 and k < end:
            end = k
    netloc = u[2:end]
    if ("[" in netloc) != ("]" in netloc):
        return None
    hostinfo = netloc.rpartition("@")[2]
    before, bracket, bracketed = hostinfo.partition("[")
    hostname = ""
    if bracket != "":
        hostname, closed, port = bracketed.partition("]")
        if before != "" or closed == "" or (port != "" and not port.startswith(":")) or not bracketed_host(hostname):
            return None
    elif "[" in netloc:
        # (brackets, but not around the host: urlsplit refuses it)
        return None
    else:
        hostname = hostinfo.partition(":")[0]
    if hostname == "" or not is_ascii(hostname):
        return None
    hostname, percent, zone = hostname.partition("%")
    return ascii_lower(hostname) + percent + zone


def all_hex(s):
    for c in s:
        if c not in HEX:
            return False
    return True


def bracketed_host(h):
    if h.startswith("v"):
        dot = h.find(".")
        return dot > 1 and all_hex(h[1:dot]) and dot < len(h) - 1
    address, percent, zone = h.partition("%")
    if percent != "" and zone == "":
        return False
    return ipv6(address)


def ipv4(s):
    parts_ = s.split(".")
    if len(parts_) != 4:
        return False
    for p in parts_:
        if len(p) == 0 or len(p) > 3:
            return False
        for c in p:
            if c < "0" or c > "9":
                return False
        if int(p) > 255 or (p != "0" and p.startswith("0")):
            return False
    return True


def ipv6(s):
    """As ipaddress reads one (policy/actions.py's _ipv6)."""
    head, colon, last = s.rpartition(":")
    if colon != "" and "." in last:
        # (the last 32 bits as an IPv4 address: two groups)
        if not ipv4(last):
            return False
        s = head + ":0:0"
    if s.count("::") > 1:
        return False
    named = []
    if "::" in s:
        before, _, after = s.partition("::")
        if before != "":
            named += before.split(":")
        if after != "":
            named += after.split(":")
        if len(named) > 7:
            return False
    else:
        named = s.split(":")
        if len(named) != 8:
            return False
    for g in named:
        if len(g) < 1 or len(g) > 4 or not all_hex(g):
            return False
    return True


def positional(e):
    """The execution's operands in order (option values skipped as its spec
    says), as text (None: dynamic)."""
    name = exec_name(e)
    spec = SPECS[name] if name is not None and name in SPECS else None
    args = e.argv[1:]
    out = []
    while True:
        if spec is None:
            dd = False
            for a in args:
                s = field_static(a) if field_known(a) else None
                if not dd and s == "--":
                    dd = True
                    continue
                if dd or s is None or not s.startswith("-"):
                    out.append(s)
            return out
        p = parse(args, spec)
        for o in p.operands:
            out.append(field_static(o) if field_known(o) else None)
        if spec.subcommands and len(p.operands) > 0 and field_known(p.operands[0]) \
                and field_static(p.operands[0]) in spec.sub:
            spec = spec.sub[field_static(p.operands[0])]
            args = args[p.end :]
            continue
        rest = args[p.end :]
        if spec.stop_at_operand:
            for a in rest:
                out.append(field_static(a) if field_known(a) else None)
            return out
        args = rest
        spec = None


def flags(e):
    out = set()
    for a in e.argv[1:]:
        if not field_known(a):
            continue
        s = field_static(a)
        if s == "--":
            break
        if s.startswith("--"):
            out.add(s.partition("=")[0])
        elif s.startswith("-") and len(s) > 1:
            out.add(s)
            out.add(s.partition("=")[0])
            if e.cmdlet:
                # (a cmdlet's parameters are words: -OutFile isn't -O -u -t...)
                continue
            for c in s[1:]:
                if not ((c >= "a" and c <= "z") or (c >= "A" and c <= "Z") or (c >= "0" and c <= "9")):
                    break
                out.add("-" + c)
    return out
