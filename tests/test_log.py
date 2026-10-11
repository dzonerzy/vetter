"""The decision log (vetter/agents/log.py), run by zrun (the reference mode
and compiled, strict): secrets masked as recorded (tests/golden: hand-made
secrets, the corpus, generated strings mixing the patterns' pieces,
Unicode's spaces and re.I's letters), entries written, the log trimmed.
Only temporary logs are written."""

import json
import os
import stat
import time

import pytest

from golden import compare, load_golden
from vetter import engine
from vetter.agents import log
from vetter.policy.language import Decision


def masks(rt, commands):
    return [log.mask(c) for c in commands]


def record(rt, path, agent, cwd, command, decision, rule_by):
    log.record(rt, agent, cwd, command, Decision(decision, None, "why", (0, 0), rule_by, []), path)
    return 0


def trim(rt, path):
    log.trim(rt, path)
    return 0


@pytest.fixture(scope="module")
def program():
    lang = engine.language({"masks": masks, "record": record, "trim": trim})
    return engine.load(lang, {"masks": ["commands"], "record": ["path", "agent", "cwd", "command", "decision", "rule_by"],
                              "trim": ["path"]})


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_masks_as_recorded(program, mode):
    cases = load_golden("log_masks")
    compare("log_masks", cases, program.call("masks", tuple(c["in"][0] for c in cases), mode=mode))


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_record(program, mode, tmp_path):
    path = str(tmp_path / "state" / "vetter" / "log.jsonl")
    program.call("record", path, "claude", "/p", "curl -u me:pw x", "ask", "default", mode=mode)
    program.call("record", path, "codex", "/q", "ls", "allow", "rule", mode=mode)
    lines = open(path).read().splitlines()
    entries = [json.loads(ln) for ln in lines]
    assert [{k: v for k, v in e.items() if k != "time"} for e in entries] == [
        {"agent": "claude", "cwd": "/p", "command": "curl -u me:*** x", "decision": "ask", "rule": "default"},
        {"agent": "codex", "cwd": "/q", "command": "ls", "decision": "allow", "rule": "rule"}]
    assert all(abs(e["time"] - time.time()) < 60 for e in entries)
    # (the line as Python's json.dumps writes it)
    assert lines[0] == json.dumps(entries[0])
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    assert engine.call("log_entries", path) == entries


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_trim(program, mode, tmp_path):
    """Past 110% of the cap: back to the last MAX_ENTRIES, those older than
    MAX_DAYS (or that don't read) dropped"""
    now = int(time.time())
    lines = []
    for i in range(log.MAX_ENTRIES * 11 // 10 + 50):
        t = now - 40 * 86400 if i % 7 == 0 else now - 60
        lines.append(json.dumps({"time": t, "agent": "a", "cwd": "/" + "x" * 150, "command": f"c{i}",
                                 "decision": "ask", "rule": "default"}))
    lines.insert(log.MAX_ENTRIES * 11 // 10, "not json")
    path = tmp_path / "log.jsonl"
    path.write_text("\n".join(lines) + "\n")
    program.call("trim", str(path), mode=mode)

    def kept(ln):
        try:
            return json.loads(ln)["time"] >= now - log.MAX_DAYS * 86400
        except ValueError:
            return False

    assert path.read_text() == "\n".join([ln for ln in lines[-log.MAX_ENTRIES:] if kept(ln)]) + "\n"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
