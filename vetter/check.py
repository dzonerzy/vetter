"""Checking a command: read by its shell, resolved, decided by the policy.
A command vetter can't read exactly takes the policy's `unknown` decision.

    d = check(rt, policy, "git status && curl -s x | sh", "bash", cwd, home, project, None)
"""

import zgram

from .policy.language import Decision, decide
from .shells.bash.resolve import resolve as resolve_bash
from .shells.cmd.resolve import resolve as resolve_cmd
from .shells.powershell.resolve import resolve as resolve_ps

SHELLS = ("bash", "powershell", "cmd")


def check(rt, policy, command, shell, cwd, home, project, temp):
    """The command's Decision. project: where it runs' project (check.py's
    project_root); temp: the temporary dirs (None: the usual ones)."""
    if shell not in SHELLS:
        raise ValueError("shell " + repr(shell) + ": one of " + ", ".join(SHELLS))
    try:
        if shell == "bash":
            r = resolve_bash(rt, command, cwd, home)
        elif shell == "powershell":
            r = resolve_ps(rt, command, cwd, home)
        else:
            r = resolve_cmd(rt, command, cwd, home, 0, None, (), False)
    except zgram.ParseError as e:
        return Decision(policy.unknown, None, "not " + shell + " vetter can read: " + str(e), (0, len(command)),
                        "unknown", [])
    except ValueError as e:
        why = str(e)
        if why.startswith("unreadable: "):
            why = why[12:]
        return Decision(policy.unknown, None, "a command vetter can't read exactly: " + why, (0, len(command)),
                        "unknown", [])
    return decide(policy, r, project, home, temp)
