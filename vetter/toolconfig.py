"""The configs a tool reads from the folder it runs in and the ones above
it, read where the hook decides: the programs they make it run, whatever
the command (cargo tree runs rustc through .cargo/config.toml's
build.rustc-wrapper; any yarn runs .yarnrc.yml's yarnPath; any mvn starts
its JVM with .mvn/jvm.config's options).

A program named by a path is a file of the project's (or not): it runs as
the project's own code, from where it is. One named by its name alone
(sccache, mold) is the system's.

    configured("cargo", "tree", "/p")   # [(path or None, "the setting")]
"""

from .gitconfig import dirname, join
from os.path import isfile


def found_up(cwd, rel):
    """rel in cwd and in each folder above it, the nearest first."""
    out = []
    d = cwd
    while d is not None and d != "":
        f = join(d, rel)
        if isfile(f):
            out.append(f)
        parent = dirname(d)
        if parent == d:
            break
        d = parent
    return out


def text_of(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""
    except UnicodeDecodeError:
        # (what's in one that isn't UTF-8: unknown, as if it ran something)
        return None


def unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[len(s) - 1] and (s[0] == '"' or s[0] == "'"):
        return s[1 : len(s) - 1]
    return s


def program_at(base, value, setting):
    """A program a setting names: a path, (that file, the setting); a name
    alone (on PATH): none."""
    v = unquote(value)
    if v == "" or ("/" not in v and "\\" not in v):
        return []
    if not (v.startswith("/") or v.startswith("~") or (len(v) > 1 and v[1] == ":")):
        v = join(base, v)
    return [(v, setting)]


# cargo's settings naming a program it runs (build., target.<t>., host.)
CARGO_PROGRAMS = ("rustc-wrapper", "rustc-workspace-wrapper", "rustc", "rustdoc", "linker", "runner")


def cargo(sub, cwd):
    """.cargo/config.toml, .cargo/config in cwd and above: the programs
    they name; an alias of the subcommand run; [env]'s variables."""
    out = []
    for f in found_up(cwd, ".cargo/config.toml") + found_up(cwd, ".cargo/config"):
        text = text_of(f)
        # (paths in it: relative to the folder .cargo is in)
        base = dirname(dirname(f))
        if text is None:
            out.append((None, f + ": not UTF-8"))
            continue
        section = ""
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("["):
                section = line.strip("[]").strip()
                continue
            if line == "" or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            full = (section + "." if section != "" else "") + key.strip()
            leaf = full[full.rfind(".") + 1 :]
            setting = f + ": " + full + " = " + value.strip()
            if leaf in CARGO_PROGRAMS and (full.startswith("build.") or full.startswith("target.")
                                           or full.startswith("host.")):
                out += program_at(base, value, setting)
            elif full.startswith("alias.") and leaf == sub:
                out.append((None, setting))
            elif full.startswith("env."):
                out.append((None, setting))
    return out


def yarn(cwd):
    """.yarnrc.yml: yarnPath (the yarn that runs, any command), plugins."""
    out = []
    for f in found_up(cwd, ".yarnrc.yml"):
        text = text_of(f)
        if text is None:
            out.append((None, f + ": not UTF-8"))
            continue
        base = dirname(f)
        plugins = False
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("yarnPath:"):
                out += program_at(base, line[9:], f + ": " + line)
            elif line.startswith("plugins:"):
                plugins = True
            elif plugins and line.startswith("- path:"):
                out += program_at(base, line[7:], f + ": plugin " + line[7:].strip())
            elif plugins and line.startswith("path:"):
                out += program_at(base, line[5:], f + ": plugin " + line[5:].strip())
            elif raw != "" and not raw.startswith(" ") and not raw.startswith("-"):
                plugins = False
    return out


# JVM options that load code: an agent, classes put first, a command on error
JVM_CODE = ("-javaagent:", "-agentpath:", "-Xbootclasspath", "-XX:OnError", "-XX:OnOutOfMemoryError")


def maven(cwd):
    """.mvn/jvm.config (the JVM's options, any mvn), nearest first."""
    out = []
    for f in found_up(cwd, ".mvn/jvm.config"):
        text = text_of(f)
        if text is None:
            out.append((None, f + ": not UTF-8"))
            continue
        base = dirname(dirname(f))
        for word in text.split():
            for pre in JVM_CODE:
                if word.startswith(pre):
                    value = word[len(pre) :].partition("=")[0]
                    if pre.startswith("-XX:") or pre == "-Xbootclasspath":
                        out.append((None, f + ": " + word))
                    else:
                        out += program_at(base, value, f + ": " + word)
        break
    return out


# npm's settings naming a program it runs
NPM_PROGRAMS = ("script-shell", "shell", "git", "editor", "browser", "viewer", "node-gyp", "init-module")


def npm(cwd):
    """.npmrc in cwd and above: the programs it names; node-options'
    --require."""
    out = []
    for f in found_up(cwd, ".npmrc"):
        text = text_of(f)
        if text is None:
            out.append((None, f + ": not UTF-8"))
            continue
        base = dirname(f)
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("#") or line.startswith(";") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key in NPM_PROGRAMS:
                out += program_at(base, value, f + ": " + line)
            elif key == "node-options":
                words = unquote(value).split()
                for k in range(len(words)):
                    if (words[k] == "--require" or words[k] == "-r" or words[k] == "--import") and k + 1 < len(words):
                        out += program_at(base, words[k + 1], f + ": " + line)
    return out


def virtualenv_activate(path):
    """Is the file a virtualenv's bin/activate (venv's, virtualenv's,
    uv's): it defines deactivate, sets VIRTUAL_ENV, and goes nowhere, runs
    nothing more (no cd, eval, exec, source)? A file not there: sourcing it
    fails, nothing done."""
    if not isfile(path):
        return True
    text = text_of(path)
    if text is None or "deactivate" not in text or "VIRTUAL_ENV" not in text:
        return False
    for raw in text.splitlines():
        words = raw.strip().split()
        if len(words) > 0 and words[0] in ("cd", "pushd", "popd", "eval", "exec", "source", "builtin", "command"):
            return False
    return True


def configured(tool, sub, cwd):
    """What tool (its subcommand sub) runs because of the configs it reads
    from cwd and above: [(path or None, the setting)]."""
    if tool == "cargo":
        return cargo(sub, cwd)
    if tool == "yarn":
        return yarn(cwd)
    if tool == "mvn" or tool == "mvnw":
        return maven(cwd)
    if tool == "npm" or tool == "npx":
        return npm(cwd)
    return []
