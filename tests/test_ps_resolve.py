"""What a PowerShell command runs (vetter/shells/powershell), run by zrun
(the reference mode and compiled, strict): the executions (arguments,
redirections, stdin, working directory, spans, via, roles, cmdlets) and
unknowns, as recorded (tests/golden), on the corpus and generated
commands."""

import pytest
import zgram

from golden import compare, load_golden
from test_bash_resolve import field, fields, stdin_of
from vetter import engine
from vetter.shells.powershell import resolve


def resolved(rt, command, cwd, home):
    try:
        r = resolve.resolve(rt, command, cwd, home)
    except zgram.ParseError:
        return "no"
    except ValueError:
        return "no"
    executions = []
    for e in r.executions:
        reds = []
        for d in e.redirects:
            reds.append([d.fd, d.op, field(d.target) if d.target is not None else None])
        roles = [[x.role, field(x.value), x.option] for x in e.roles]
        env = sorted([[k, field(v)] for k, v in e.env.items()])
        executions.append([fields(e.argv), env, reds, e.cwd, e.span, e.via, stdin_of(e.stdin), e.kind, roles,
                           e.cmdlet, e.readonly])
    unknowns = [[u.reason, u.span, u.via, u.kind, fields(u.paths), u.cwd] for u in r.unknowns]
    return [executions, unknowns, sorted([d for d in r.downloads])]


@pytest.fixture(scope="module")
def program():
    lang = engine.language({"ps_resolve": resolved})
    return engine.load(lang, {"ps_resolve": ["command", "cwd", "home"]})


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_as_recorded(program, mode):
    cases = load_golden("ps_resolve")
    compare("ps_resolve", cases, [program.call("ps_resolve", *c["in"], mode=mode) for c in cases])
