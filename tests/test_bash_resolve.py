"""What a bash command runs (vetter/shells/bash/resolve.py), run by zrun
(the reference mode and compiled, strict): every execution (its argv,
environment, redirections, working directory, standard input, roles), the
unknowns, the functions and downloads, as recorded (tests/golden), on the
corpus and generated commands, with a working directory and without."""

import pytest
import zgram

from golden import compare, load_golden
from vetter import engine
from vetter.shells.bash import expand, resolve


def field(f):
    parts = []
    for p in f.parts:
        if isinstance(p, expand.Dynamic):
            parts.append(["dyn", expand.dynamic_text(p)])
        else:
            parts.append(p)
    return [parts, f.glob, f.splits]


def fields(fs):
    return [field(f) for f in fs]


def stdin_of(s):
    if s is None:
        return None
    if s.producer is None:
        return [s.text, None]
    return [s.text, [fields(s.producer.argv), s.producer.span]]


def resolved(rt, command, cwd, home):
    try:
        r = resolve.resolve(rt, command, cwd, home)
    except zgram.ParseError:
        return "no"
    except ValueError:
        return "no"
    executions = []
    for e in r.executions:
        env = sorted([[k, field(v)] for k, v in e.env.items()])
        reds = []
        for d in e.redirects:
            reds.append([d.fd, d.op, field(d.target) if d.target is not None else None,
                         d.heredoc.heredoc.op_start if d.heredoc is not None else None])
        roles = [[r.role, field(r.value), r.option] for r in e.roles]
        executions.append([fields(e.argv), env, reds, e.cwd, e.span, e.via, stdin_of(e.stdin), e.kind, e.words,
                           roles])
    unknowns = [[u.reason, u.span, u.via, u.kind, fields(u.paths), u.cwd] for u in r.unknowns]
    return [executions, unknowns, sorted([f for f in r.functions]), sorted([d for d in r.downloads])]


@pytest.fixture(scope="module")
def program():
    lang = engine.language({"resolve": resolved})
    return engine.load(lang, {"resolve": ["command", "cwd", "home"]})


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_as_recorded(program, mode):
    cases = load_golden("bash_resolve")
    compare("bash_resolve", cases, [program.call("resolve", *c["in"], mode=mode) for c in cases])
