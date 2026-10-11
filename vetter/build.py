"""vetter with no Python: the agents' hook as an executable, vetter as a
library with a C API; both compiled ahead of time by zrun.build_native
(Zig needed: the ziglang package).

    python -m vetter.build vetter-hook    # ./vetter-hook claude [--policy FILE]
    python -m vetter.build libvetter      # libvetter.so and libvetter.h

The executable is a strict language's one program, `hook`, running the
hook (agents/hook.py) with its arguments; the library the engine's
language (engine.py) with one entry, `vet`.
"""

import sys
from os import getcwd

import zgram
import zrun
from zrules import Rules

from . import engine
from .agents import hook
from .check import check
from .jsontext import dumps
from .places import home_dir, load_policy, native_shell, project_root, temp_dirs
from .policy.language import where

PARSER = zgram.compile("program = 'hook' -> Program\n")
RULES = Rules(PARSER, [])
SOURCE = "hook"

# (the program's arguments, given by its setup)
ARGS = []


def set_args(path, args):
    ARGS.extend(args)


def program_(node, rt):
    agent = ARGS[0] if len(ARGS) > 0 else ""
    policy = ""
    if len(ARGS) == 3 and ARGS[1] == "--policy":
        policy = ARGS[2]
    elif len(ARGS) != 1 or agent not in hook.AGENTS:
        raise ValueError("usage: vetter-hook AGENT [--policy FILE], AGENT one of " + ", ".join(hook.AGENTS))
    hook.run(rt, agent, policy)


def language():
    lang = zrun.Language(PARSER, RULES, strict=True)
    lang.exec("Program")(program_)
    return lang


def build(output, **options):
    """The executable (zrun.build_native's options: target=...)."""
    return zrun.build_native(language(), SOURCE, output, path="vetter-hook", setup=set_args, **options)


def vet(rt, command, shell, cwd, policy_path):
    """A command decided, as `vetter check` decides it here: its decision
    in JSON (decision, reason, rule, by, span). shell, cwd, policy_path ""
    for the default: the system's shell, the working directory, the
    user's policy (else the stock one)."""
    home = home_dir()
    cwd = cwd or getcwd()
    policy = load_policy(rt, policy_path, cwd, home)
    d = check(rt, policy, command, shell or native_shell(), cwd, home, project_root(cwd, home),
              temp_dirs(home, True))
    return dumps({"decision": d.decision, "reason": d.reason, "rule": where(d.rule) if d.rule is not None else None,
                  "by": d.by, "span": [d.span[0], d.span[1]]})


def build_library(output, **options):
    """libvetter (.so, .dll) and its header: zrun_init(0, NULL), then
    zrun_call("vet", {command, shell, cwd, policy}, 4, &out), out a str
    of JSON (zrun.h)."""
    lang = engine.language({"vet": vet})
    program = {"vet": ["command", "shell", "cwd", "policy"]}
    text = "".join(f"entry {n}({', '.join(ps)}) = {n}\n" for n, ps in program.items())
    return zrun.build_native(lang, text, output, path="libvetter", shared=True, **options)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "vetter-hook"
    print(build_library(out) if "lib" in out.rsplit("/", 1)[-1] else build(out))
