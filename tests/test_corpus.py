"""The corpus (corpus/), every case decided in both of zrun's modes: no
attack allowed or only asked about where it's denied (`expect`), no
harmless command asked about; the two modes deciding alike."""

import pytest

import shared
from tools.corpus import corpus
from tools.corpus.decide_corpus import PAYLOAD_POLICY
from vetter.places import STOCK
from vetter.policy.language import ORDER, TEST_PLACES


@pytest.fixture(scope="module")
def program():
    return shared.program()


def cases():
    return [c for c in corpus.load() if c["shell"] in ("bash", "powershell", "cmd")]


def decided(program, mode):
    out = []
    for c in cases():
        text, filename = (PAYLOAD_POLICY, "corpus.vet") if c["file"].endswith("gpt-obfuscated.toml") else STOCK
        cwd, home = TEST_PLACES["windows" if c["shell"] in ("powershell", "cmd") else "posix"]
        out.append(program.call("decide", c["command"].strip("\n"), c["shell"], cwd, home, text, filename, mode=mode))
    return out


def wrong(c, got):
    exp = c["expect"]
    if got == exp or (exp != "allow" and ORDER[got] > ORDER[exp]):
        return None
    return c["id"] + ": expect " + exp + ", got " + got


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_expectations(program, mode):
    found = [wrong(c, d[0]) for c, d in zip(cases(), decided(program, mode))]
    assert [w for w in found if w is not None] == []


def test_modes_agree(program):
    a = decided(program, "python")
    b = decided(program, "compiled")
    differ = [c["id"] for c, x, y in zip(cases(), a, b) if x != y]
    assert differ == []
