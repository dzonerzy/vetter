"""Each agent's hook (docs/06-integrations.md): the agent's request on
stdin (JSON, read with rt.parse), the policy found (places.py), the
command decided, the answer on stdout in the agent's format, as json.dumps
writes it. A hook never fails open by crashing: any error is an ask (a
deny where the agent can't ask).

    run(rt, "claude", None)       # stdin -> stdout, as `vetter hook claude`

An agent's answer has `default` true when no rule decided (only the
policy's default, or nothing to vet): where the agent has its own
permission rules, vetter then says nothing and they decide. Agents whose
hooks can't ask (Codex, Gemini, Cline's extension) get ask as deny, with
the reason. A decision is logged (log.py) unless the policy says `log off`.
"""

import sys
from dataclasses import dataclass
from os import getcwd, getenv

import zgram

from .. import paths
from ..check import check
from ..jsontext import dumps, loads
from ..places import home_dir, load_policy, log_path, native_shell, temp_dirs, workspace_project, written_path
from ..policy.language import followed, where
from . import log, written

CLAUDE_TOOLS = {"Bash": "bash", "PowerShell": "powershell"}
COPILOT_TOOLS = {"bash": "bash", "powershell": "powershell", "Bash": "bash", "PowerShell": "powershell",
                 "run_in_terminal": "", "runInTerminal": "", "terminal": ""}
CLINE_TOOLS = ("execute_command", "run_commands")
AGENTS = ("claude", "codex", "gemini", "cursor", "copilot", "cline", "amp", "opencode", "json")


@dataclass
class Call:
    command: object
    cwd: object
    shell: object
    # (Cursor's preToolUse, Cline's CLI: answered their way)
    mode: str


def workspace_of(agent, request):
    """The folder the user opened the agent in, as the agent tells its
    hooks: Claude Code's CLAUDE_PROJECT_DIR (Gemini's GEMINI_PROJECT_DIR),
    Cursor's and Copilot's workspace roots; None: not told."""
    if agent == "claude":
        return getenv("CLAUDE_PROJECT_DIR")
    if agent == "gemini":
        return getenv("GEMINI_PROJECT_DIR") or getenv("CLAUDE_PROJECT_DIR")
    roots = request.get("workspace_roots") or request.get("workspaceRoots")
    if isinstance(roots, list) and len(roots) > 0 and isinstance(roots[0], str):
        return roots[0]
    return None


def cant_ask(decision, reason):
    if decision == "ask":
        return ("deny", reason + " (vetter would ask, and this agent's hooks can't: run it yourself if it's fine)")
    return (decision, reason)


def command_of(tool_input):
    if not isinstance(tool_input, dict):
        return None
    for key in ("command", "commands", "cmd"):
        v = tool_input.get(key)
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            strs = True
            for x in v:
                if not isinstance(x, str):
                    strs = False
            if strs:
                return "\n".join(v)
    return None


def read(rt, agent, request):
    """The shell call of a request (None: not one)."""
    if agent == "claude":
        shell = CLAUDE_TOOLS.get(request.get("tool_name"))
        if shell is None:
            return None
        return Call(command_of(request.get("tool_input")), request.get("cwd"), shell, "")
    if agent == "codex":
        if request.get("tool_name") != "Bash":
            return None
        return Call(command_of(request.get("tool_input")), request.get("cwd"), native_shell(), "")
    if agent == "gemini":
        if request.get("tool_name") != "run_shell_command":
            return None
        ti = request.get("tool_input") or {}
        cwd = request.get("cwd")
        d = ti.get("dir_path") if isinstance(ti, dict) else None
        if isinstance(d, str) and d:
            cwd = paths.join(cwd, d) if cwd else d
        return Call(command_of(ti), cwd, native_shell(), "")
    if agent == "cursor":
        if "tool_name" in request:
            if request.get("tool_name") != "Shell":
                return None
            ti = request.get("tool_input") or {}
            return Call(command_of(ti), ti.get("working_directory") or request.get("cwd"), native_shell(), "pre_tool")
        command = request.get("command")
        roots = request.get("workspace_roots") or [None]
        return Call(command if isinstance(command, str) else None, request.get("cwd") or roots[0], native_shell(), "")
    if agent == "copilot":
        if "toolName" in request:
            name = request.get("toolName")
            args = request.get("toolArgs")
            if isinstance(args, str):
                try:
                    args = loads(rt, args)
                except zgram.ParseError:
                    args = None
        else:
            name = request.get("tool_name")
            args = request.get("tool_input")
        if name not in COPILOT_TOOLS:
            return None
        return Call(command_of(args), request.get("cwd"), COPILOT_TOOLS[name] or native_shell(), "")
    if agent == "cline":
        roots = request.get("workspaceRoots") or [None]
        if "tool_call" in request:
            mode = "cli"
            tc = request.get("tool_call") or {}
            name = tc.get("name")
            args = tc.get("input")
        else:
            mode = ""
            p = request.get("preToolUse") or {}
            name = p.get("toolName")
            args = p.get("parameters")
        if name not in CLINE_TOOLS:
            return None
        cwd = (args or {}).get("cwd") if isinstance(args, dict) else None
        return Call(command_of(args), cwd if isinstance(cwd, str) else roots[0], native_shell(), mode)
    command = request.get("command")
    return Call(command if isinstance(command, str) else None, request.get("cwd"),
                request.get("shell") or native_shell(), "")


# The agents' editing tools: the file they write (its key in the tool's input)
CLAUDE_EDITS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
GEMINI_EDITS = {"write_file": "file_path", "replace": "file_path"}
CLINE_EDITS = {"write_to_file": "path", "replace_in_file": "path"}


def edited_file(agent, request):
    """The file an editing tool's request writes, absolute and through this
    machine's links as decisions see paths; None: not such a request."""
    args = None
    key = None
    cwd = request.get("cwd")
    if agent == "claude" or agent == "gemini":
        edits = CLAUDE_EDITS if agent == "claude" else GEMINI_EDITS
        name = request.get("tool_name")
        if name in edits:
            args = request.get("tool_input")
            key = edits[name]
    elif agent == "cline":
        roots = request.get("workspaceRoots") or [None]
        if "tool_call" in request:
            tc = request.get("tool_call") or {}
            name = tc.get("name")
            given = tc.get("input")
        else:
            p = request.get("preToolUse") or {}
            name = p.get("toolName")
            given = p.get("parameters")
        if name in CLINE_EDITS:
            args = given
            key = CLINE_EDITS[name]
            cwd = roots[0]
    if not isinstance(args, dict):
        return None
    v = args.get(key)
    if not isinstance(v, str) or v == "":
        return None
    if not paths.is_abs(v):
        if not isinstance(cwd, str) or not paths.is_abs(cwd):
            return None
        v = paths.join(cwd, v)
    return followed(paths.norm(v), "write")


def hook_output(decision, reason):
    return {"hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": reason}


def answer(agent, mode, decision, reason, default):
    """What the agent is told (None: nothing)."""
    if agent == "claude":
        if default and decision != "deny":
            return None
        return {"hookSpecificOutput": hook_output(decision, reason)}
    if agent == "codex":
        if default and decision != "deny":
            return None
        decision, reason = cant_ask(decision, reason)
        if decision != "deny":
            return None
        return {"hookSpecificOutput": hook_output("deny", reason)}
    if agent == "gemini":
        if default and decision != "deny":
            return {}
        decision, reason = cant_ask(decision, reason)
        if decision == "deny":
            return {"decision": "deny", "reason": reason}
        return {"decision": "allow", "reason": reason}
    if agent == "cursor":
        if mode == "pre_tool":
            decision, reason = cant_ask(decision, reason)
        return {"permission": decision, "user_message": reason, "agent_message": reason}
    if agent == "copilot":
        if default and decision != "deny":
            return None
        return {"permissionDecision": decision, "permissionDecisionReason": reason,
                "hookSpecificOutput": hook_output(decision, reason)}
    if agent == "cline":
        if mode == "cli":
            if decision == "deny":
                return {"cancel": True, "errorMessage": reason}
            if decision == "ask" and not default:
                return {"review": True, "context": reason}
            return {}
        decision, reason = cant_ask(decision, reason)
        if decision == "deny":
            return {"cancel": True, "errorMessage": reason}
        return {"cancel": False}
    return {"decision": decision, "reason": reason, "default": default}


def decide(rt, agent, request, policy_path):
    """What to answer: (the agent's answer or None, whether anything)"""
    if not isinstance(request, dict):
        return answer(agent, "", "ask", "vetter: a request it doesn't understand", False)
    edited = edited_file(agent, request)
    if edited is not None:
        # (an editing tool: what it writes remembered, nothing decided)
        written.record([edited], "generated", written_path(home_dir()))
        mode = "cli" if agent == "cline" and "tool_call" in request else ""
        return answer(agent, mode, "allow", "", True)
    call = read(rt, agent, request)
    if call is None:
        return None
    if not isinstance(call.command, str):
        return answer(agent, call.mode, "ask", "vetter: a shell call without a command", False)
    cwd = call.cwd if isinstance(call.cwd, str) and call.cwd else getcwd()
    home = home_dir()
    policy = load_policy(rt, policy_path, cwd, home)
    project = workspace_project(cwd, home, workspace_of(agent, request))
    d = check(rt, policy, call.command, call.shell, cwd, home, project, temp_dirs(home, True))
    if policy.log:
        log.record(rt, agent, cwd, call.command, d, log_path(home))
    written.record_decision(d, policy.written, written_path(home))
    at = " [" + where(d.rule) + "]" if d.rule is not None else ""
    return answer(agent, call.mode, d.decision, "vetter: " + d.reason + at, d.by == "default" or d.by == "nothing")


def run(rt, agent, policy_path):
    """The request on stdin decided, the answer on stdout; never failing
    open: an error is an ask (a deny where the agent can't ask)."""
    try:
        out = decide(rt, agent, loads(rt, sys.stdin.read()), policy_path)
    except Exception as e:  # noqa: BLE001 (whatever goes wrong, a decision: ask)
        out = answer(agent, "", "ask", "vetter couldn't decide (" + type(e).__name__ + ": " + str(e) + ")", False)
    if out is not None:
        sys.stdout.write(dumps(out) + "\n")
    return 0
