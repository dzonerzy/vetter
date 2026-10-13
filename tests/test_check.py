"""Checking a command (vetter/check.py and the policy), run by zrun (the
reference mode and compiled, strict): the stock policy (and the corpus'
with its payload rule) loaded, every command decided as recorded
(tests/golden): the decision, its reason, span, rule, and every part's and
action's; traced (`vetter why --all`), every rule's step and why."""

import pytest

import shared
from golden import compare, load_golden
from tools.corpus.decide_corpus import PAYLOAD_POLICY
from vetter import engine
from vetter.check import check
from vetter.places import STOCK
from vetter.policy import language
from vetter.policy.language import TEST_PLACES

POLICIES = {"stock": (STOCK[0], STOCK[1]), "payload": (PAYLOAD_POLICY, "corpus.vet")}


def rule_where(r):
    # (the policy file's name: where the checkout is differs from machine to machine)
    return None if r is None else [r.decision, r.reason, r.file.replace("\\", "/").rpartition("/")[2], r.line,
                                   r.text, r.locked]


def decide(rt, command, shell, cwd, home, text, filename):
    p = language.load(rt, text, filename)
    d = check(rt, p, command, shell, cwd, home, cwd, None)
    out_parts = []
    for part in d.parts:
        acts = [[a.action.verb, a.action.path, a.action.host, a.action.kind, a.decision, a.reason, a.by,
                 rule_where(a.rule), len(a.steps)] for a in part.actions]
        out_parts.append([part.decision, part.reason, part.by, rule_where(part.rule), part.part.name,
                          part.part.positional, sorted([f for f in part.part.flags]), acts])
    return [d.decision, d.reason, d.span, d.by, rule_where(d.rule), out_parts]


def traced(rt, command, shell, cwd, home, text, filename):
    """Each step of each action: the rule's line, matched, why"""
    p = language.load(rt, text, filename)
    p.trace = True
    d = check(rt, p, command, shell, cwd, home, cwd, None)
    return [[[[s.rule.line, s.matched, s.why] for s in a.steps] for a in part.actions] for part in d.parts]


@pytest.fixture(scope="module")
def program():
    return shared.program()


def run_case(program, case, mode):
    command, shell, policy = case["in"]
    cwd, home = TEST_PLACES["windows" if shell in ("powershell", "cmd") else "posix"]
    text, filename = POLICIES[policy]
    return [program.call("decide", command, shell, cwd, home, text, filename, mode=mode),
            program.call("traced", command, shell, cwd, home, text, filename, mode=mode)]


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_as_recorded(program, mode):
    cases = load_golden("check")
    compare("check", cases, [run_case(program, c, mode) for c in cases])


def test_policy_tests_pass():
    """The stock policy's own tests (`vetter test`), natively"""
    p = engine.call("load_text", STOCK[0], STOCK[1])
    assert len(p.tests) > 50 and engine.call("run_tests", p) == []
    assert language.unreachable(p) == []
