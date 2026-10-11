"""vetter's code run by zrun. vetter is written in zrun's strict subset of
Python: the CLI runs it as Python (zrun's reference mode: nothing compiled,
as quick to start as Python), the agents' hook and libvetter compiled
ahead of time (build.py), the tests both ways.

A small strict language does it: its program is lines `entry name(a, b) =
name`, each a function of the program running the vetter function
registered under that name, given rt (rt.parse: the shells', the policies'
and JSON's grammars) and the arguments.

    call("check", policy, "ls -l", "bash", cwd, home, project, temp)
    run(syntax.parse, "ls -l")               # any function given rt (tools)

    lang = language({"read": read})          # tests: functions of their own
    program = load(lang, {"read": ["command"]})
    program.call("read", "ls -l", mode="compiled")
"""

import zgram
import zrun
from zrules import Rules, scopes

GRAMMAR = r"""
program = ws (body:entry ws)*                                                     -> Program
entry   = 'entry' kw ws name:ident ws '(' ws (params:ident (ws ',' ws params:ident)*)? ws ')' ws '=' ws body:target  -> Entry
target  = [a-z_]+                                                                 -> Target
ident   = [a-z_]+                                                                 -> Name
@silent kw = ![a-z_]
@silent ws = [ \t\n]*
"""

PARSER = zgram.compile(GRAMMAR)
RULES = Rules(PARSER, [scopes(scope=("Program", "Entry"), define=("Entry > .params",), define_outer="Entry > .name",
                              use="Name", hoist="Entry > .name")])


# The functions entries run, by name (a table the semantics only read: a
# constant of the compiled code, each function compiled with it)
FUNCTIONS = {}


def program_(node, rt):
    pass


def target(node, rt):
    params = node.parent.params
    args = [rt.load(p) for p in params]
    raise rt.Return(FUNCTIONS[node.text](rt, *args))


def language(functions):
    """A strict language running `functions` (name -> fn(rt, *args))."""
    FUNCTIONS.update(functions)
    lang = zrun.Language(PARSER, RULES, strict=True)
    lang.function("Entry")
    lang.exec("Program")(program_)
    lang.exec("Target")(target)
    return lang


def load(lang, entries):
    """The program of `entries` (name -> its parameters' names)."""
    text = "".join(f"entry {n}({', '.join(ps)}) = {n}\n" for n, ps in entries.items())
    return lang.load(text, "vetter")


# ----------------------------------------------------------------------
# The CLI's: vetter's functions run as Python
# ----------------------------------------------------------------------


def _entries():
    from .agents import hook, log
    from .check import check
    from .places import load_policy
    from .policy.language import coverage, load, run_tests

    return {"load_policy": load_policy, "load_text": load, "check": check, "hook": hook.run,
            "run_tests": run_tests, "coverage": coverage, "log_entries": log.entries}


class Failed:
    """What a function run raised (an exception leaving a program is a
    zrun.Error: the original raised again by run())"""

    def __init__(self, error):
        self.error = error


def run_one(rt, fn, args):
    try:
        return fn(rt, *args)
    except Exception as e:  # noqa: BLE001 (given back: run() raises it)
        return Failed(e)


_program = None


def run(fn, *args):
    """fn(rt, *args) run as Python (the reference mode), given an rt: what
    it returns, what it raises raised."""
    global _program
    if _program is None:
        _program = load(language({"run_one": run_one}), {"run_one": ["fn", "args"]})
    r = _program.call("run_one", fn, args, mode="python")
    if isinstance(r, Failed):
        raise r.error
    return r


def call(name, *args):
    """One of vetter's functions run by name (the CLI's): load_policy,
    load_text, check, hook, run_tests, coverage, log_entries."""
    return run(_entries()[name], *args)
