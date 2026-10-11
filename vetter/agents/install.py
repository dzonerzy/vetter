"""Installing vetter's hook in an agent's settings (docs/06-integrations.md):
the hook command (`python -m vetter hook AGENT`) added where the agent runs
its hooks, ours replaced, others' kept.

    vetter install claude | codex | gemini | cursor | copilot | vscode | cline | amp | opencode
"""

import json
import os
import pathlib
import shlex
import subprocess
import sys

MARK = "-m vetter hook"


def hook_command(agent):
    """How the agent runs vetter: this Python, this package."""
    argv = [sys.executable, "-m", "vetter", "hook", agent]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _home(*parts):
    return pathlib.Path("~").expanduser().joinpath(*parts)


def _ours(entry):
    return MARK in json.dumps(entry)


def _hook_list(data, *keys):
    """data[k1][k2]...: the list there, made if missing, vetter's old
    entries taken out."""
    d = data
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    lst = d.setdefault(keys[-1], [])
    lst[:] = [e for e in lst if not _ours(e)]
    return lst


def _claude_like(data, event, matcher, agent, timeout):
    pre = _hook_list(data, "hooks", event)
    group = {"hooks": [{"type": "command", "command": hook_command(agent), "timeout": timeout}]}
    if matcher is not None:
        group = {"matcher": matcher, **group}
    pre.append(group)


def _claude(data):
    # (the editing tools too: what they write, run later, is the agent's)
    _claude_like(data, "PreToolUse", "Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit", "claude", 10)


def _codex(data):
    _claude_like(data, "PreToolUse", "^Bash$", "codex", 30)


def _gemini(data):
    lst = _hook_list(data, "hooks", "BeforeTool")
    lst.append({"matcher": "run_shell_command|write_file|replace",
                "hooks": [{"name": "vetter", "type": "command", "command": hook_command("gemini"), "timeout": 10000}]})


def _cursor(data):
    data.setdefault("version", 1)
    lst = _hook_list(data, "hooks", "beforeShellExecution")
    lst.append({"command": hook_command("cursor"), "timeout": 30, "failClosed": True})


def _copilot(data):
    data.setdefault("version", 1)
    lst = _hook_list(data, "hooks", "preToolUse")
    cmd = hook_command("copilot")
    lst.append({"type": "command", "matcher": "bash|powershell", "bash": cmd, "powershell": cmd, "timeoutSec": 30})


def _vscode(data):
    # (VS Code runs it for every tool: the terminal ones are vetted)
    _claude_like(data, "PreToolUse", None, "copilot", 30)


# agent: (file, how to add vetter to its JSON, what to tell)
JSON_TARGETS = {
    "claude": (lambda: _home(".claude", "settings.json"), _claude,
               "Bash and PowerShell commands go through vetter; what Write and Edit write is remembered"),
    "codex": (lambda: _home(".codex", "hooks.json"), _codex,
              "approve the hook in Codex with /hooks (Codex skips hooks it hasn't trusted); its hooks can't ask: "
              "vetter's ask is a deny there"),
    "gemini": (lambda: _home(".gemini", "settings.json"), _gemini,
               "shell commands go through vetter; Gemini's hooks can't ask: vetter's ask is a deny there"),
    "cursor": (lambda: _home(".cursor", "hooks.json"), _cursor,
               "shell commands go through vetter (failClosed: a vetter that fails blocks)"),
    "copilot": (lambda: _home(".copilot", "hooks", "vetter.json"), _copilot,
                "Copilot CLI's bash and powershell calls go through vetter"),
    "vscode": (lambda: _home(".copilot", "hooks", "vetter-vscode.json"), _vscode,
               "VS Code's agent terminal commands go through vetter (chat.useHooks on)"),
}

AMP_PLUGIN = """\
// vetter: every shell command Amp runs is decided by `vetter hook amp` first.
// Written by `vetter install amp`; run it again to update.
import { spawnSync } from "node:child_process";

const VETTER = %(argv)s;

export default function (amp) {
  amp.on("tool.call", async (event, ctx) => {
    const call = amp.helpers.shellCommandFromToolCall(event);
    if (!call) return { action: "allow" };
    const r = spawnSync(VETTER[0], VETTER.slice(1), {
      input: JSON.stringify({ command: call.command, cwd: call.dir }),
      encoding: "utf8",
    });
    let d;
    try {
      d = JSON.parse(r.stdout);
    } catch {
      return { action: "reject-and-continue", message: "vetter couldn't decide: " + (r.stderr || r.error) };
    }
    if (d.decision === "allow") return { action: "allow" };
    if (d.decision === "ask" && ctx.ui && ctx.ui.confirm && (await ctx.ui.confirm(d.reason + "\\n\\nRun it?"))) {
      return { action: "allow" };
    }
    return { action: "reject-and-continue", message: d.reason };
  });
}
"""

OPENCODE_PLUGIN = """\
// vetter: every bash command opencode runs is decided by `vetter hook opencode`
// first. Written by `vetter install opencode`; run it again to update.
import { spawnSync } from "node:child_process";

const VETTER = %(argv)s;

export const Vetter = async ({ directory }) => ({
  "tool.execute.before": async (input, output) => {
    if (input.tool !== "bash") return;
    const r = spawnSync(VETTER[0], VETTER.slice(1), {
      input: JSON.stringify({ command: output.args.command, cwd: output.args.workdir || directory }),
      encoding: "utf8",
    });
    let d;
    try {
      d = JSON.parse(r.stdout);
    } catch {
      throw new Error("vetter couldn't decide: " + (r.stderr || r.error));
    }
    // (no rule decided: opencode's own permissions do; it can't ask here)
    if (d.decision === "deny") throw new Error(d.reason);
    if (d.decision === "ask" && !d.default) throw new Error(d.reason + " (vetter would ask; run it yourself if it's fine)");
  },
});
"""

CLINE_HOOK = """#!/bin/sh
# vetter: Cline's PreToolUse hook. Written by `vetter install cline`.
exec %(command)s
"""


def _file_targets():
    argv = json.dumps([sys.executable, "-m", "vetter", "hook"])
    return {
        "amp": (_home(".config", "amp", "plugins", "vetter.ts"),
                AMP_PLUGIN % {"argv": argv[:-1] + ', "amp"]'}, False,
                "Amp's shell commands go through vetter (a plugin: ask is Amp's confirm)"),
        "opencode": (_home(".config", "opencode", "plugins", "vetter.js"),
                     OPENCODE_PLUGIN % {"argv": argv[:-1] + ', "opencode"]'}, False,
                     "opencode's bash commands go through vetter (a plugin: it can't ask; vetter's ask is a deny)"),
        "cline": (_home("Documents", "Cline", "Hooks", "PreToolUse"),
                  CLINE_HOOK % {"command": hook_command("cline")}, True,
                  "Cline's commands go through vetter (turn on Enable Hooks in its settings; it can only cancel: "
                  "vetter's ask is a deny)"),
    }


AGENTS = sorted(set(JSON_TARGETS) | {"amp", "opencode", "cline"})


def install(agent, settings=None, dry_run=False):
    if agent in JSON_TARGETS:
        where, add, note = JSON_TARGETS[agent]
        path = pathlib.Path(settings).expanduser() if settings else where()
        data = json.loads(path.read_text()) if path.exists() and path.read_text().strip() else {}
        add(data)
        text = json.dumps(data, indent=2) + "\n"
        executable = False
    elif agent in ("amp", "opencode", "cline"):
        where, text, executable, note = _file_targets()[agent]
        path = pathlib.Path(settings).expanduser() if settings else where
    else:
        raise ValueError(f"vetter doesn't know the agent {agent!r} (it knows {', '.join(AGENTS)})")
    if dry_run:
        print(f"would write {path}:\n{text}")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() != text:
        backup = path.with_name(path.name + ".vetter-backup")
        backup.write_text(path.read_text())
        print(f"backup: {backup}")
    path.write_text(text)
    if executable:
        path.chmod(0o755)
    print(f"installed in {path}: {note}")
    print("decisions are logged on this machine only (~/.local/state/vetter/log.jsonl, secrets masked) for "
          "`vetter replay`; `log off` in ~/.config/vetter/policy.vet turns it off")
    return 0
