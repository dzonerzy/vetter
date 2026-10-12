# Agents

Most coding agents let an external program approve or block a tool call
before it runs: they send the call as JSON on standard input and read a
decision back. vetter has a hook for each of them (`vetter hook AGENT`) and
installs itself with `vetter install AGENT`.

## Supported agents

| Agent | `vetter install` writes | Can ask you? | If the hook fails |
|---|---|---|---|
| Claude Code | `~/.claude/settings.json`: `PreToolUse` for `Bash` and `PowerShell` (and the editing tools, to remember what the agent writes); `PostToolUse` for learning | yes | vetter answers ask |
| Codex CLI | `~/.codex/hooks.json`: `PreToolUse` for `Bash`; `PostToolUse` for learning (trust it with `/hooks`) | no: an ask is a deny | fails open |
| Gemini CLI | `~/.gemini/settings.json`: `BeforeTool` for `run_shell_command` | no: an ask is a deny | fails open |
| Cursor | `~/.cursor/hooks.json`: `beforeShellExecution`, `failClosed` | yes | blocks |
| Copilot CLI | `~/.copilot/hooks/vetter.json`: `preToolUse` for `bash` and `powershell` | yes | errors block, timeouts don't |
| VS Code (Copilot agent) | `~/.copilot/hooks/vetter-vscode.json`: `PreToolUse` | yes | fails open |
| Cline | `~/Documents/Cline/Hooks/PreToolUse` (enable hooks in Cline) | the CLI only | fails open |
| Amp | `~/.config/amp/plugins/vetter.ts`, a plugin calling `vetter hook amp` | through Amp's confirmation | not documented |
| opencode | `~/.config/opencode/plugins/vetter.js`, a plugin calling `vetter hook opencode` | no: an ask is a deny | not documented |

`vetter install AGENT --dry-run` shows the change without writing it, and
`--settings FILE` writes another file. vetter's own entries are replaced,
everyone else's kept.

For other harnesses, `vetter hook json` reads `{"command", "cwd", "shell"}`
and answers `{"decision", "reason", "default"}`. The C library is another
way in (see [Embedding](embedding.md)).

Agents with no external hook today (built-in lists or modes only): Roo
Code, Zed, Goose, Aider, OpenHands.

## What the agent is told

- **A rule's decision is always given**, with its reason: `vetter: deleting
  outside the project: ... [stock.vet:35]`.
- **When no rule decided** (only the policy's default), vetter stays silent
  where the agent has permission rules of its own (Claude Code, Codex,
  Gemini, Copilot, VS Code, opencode): those decide, as they would without
  vetter. A deny is never silent.
- **Where the agent can't ask** (Codex, Gemini, Cline's extension,
  opencode), an ask becomes a deny whose reason says so: "vetter would ask
  ...: run it yourself if it's fine". Letting it run would fail open on
  exactly what a person should look at.
- **vetter never fails open by crashing.** An error inside vetter is an ask,
  or a deny where the agent can't ask. Where the agent supports it,
  `install` makes the hook fail closed (Cursor's `failClosed`).
- **Which shell.** Claude Code's and Copilot's tools say which shell runs
  the command. For the others it's the system's: bash, or PowerShell on
  Windows.

## The project

When the agent tells its hook which workspace it was opened in (Claude
Code's `CLAUDE_PROJECT_DIR`, Gemini's `GEMINI_PROJECT_DIR`, Cursor's and
Copilot's workspace roots), that's `$project` for commands run inside it.
Otherwise vetter finds the project from the working directory (see
[Places](policy-language.md#places)).

## The log

Each decision is logged in `~/.local/state/vetter/log.jsonl`: the time, the
agent, the working directory, the command, the decision and the rule. The
file is readable only by you, keeps the last 10,000 decisions (30 days at
most), and secrets are masked before they're written: values of variables
named like `TOKEN`, `KEY`, `SECRET` or `PASSWORD`, `Authorization` headers,
`-u user:pass`, credentials in URLs, AWS keys and JWTs.

Turn it off with `log off` in your policy. `vetter replay --policy FILE`
decides the logged commands with another policy and shows what would
change: you can test a policy change on the commands you actually run.

## Learning from your answers

With Claude Code and Codex, the hook also logs the id of each call, and a
`PostToolUse` hook records when a call ran. A command vetter asked about
that went on to run is one you said yes to. `vetter learn` turns those yeses
into rules:

```console
$ vetter learn
  1. allow network to api.example.com
     said yes 4 times: curl -s https://api.example.com/v1/items; ...
  2. allow terraform validate
     said yes 3 times: terraform validate; terraform validate -json
  3. allow delete in /home/u/proj/out
     said yes 2 times: rm -rf out/a; rm -rf out/b

`vetter learn --apply all` (or --apply 1,3) adds them to /home/u/.config/vetter/policy.vet
```

Each command is decided again, and what made it asked becomes the
narrowest rule that would have allowed it:

| Asked because | Rule learned |
|---|---|
| no rule named the program | the program and its subcommands (the words before its first option) |
| the network rule | the host |
| the deleting rule | the project's folder it deletes in |
| nothing allowed the write or read | the folder |

Never learned:

- anything vetter couldn't see into;
- an ask a rule makes on purpose: losing uncommitted work, `sudo`, running
  what the agent wrote, configuring what runs later;
- anything denied;
- a rule that would also allow a command you once said no to.

A suggestion needs two yeses by default (`--min N`). The rules go in your
policy (`~/.config/vetter/policy.vet`, or `--policy FILE`) before its `use`
line, where the used policy's deny rules still come first: a learned host
doesn't let a file be sent there. They never go in a project's
`.vetter.vet`, whose allow rules don't count.

An ask by the default (no rule) leaves the agent's own prompt in charge: a
call that ran after it was approved there, or allowed by the agent's own
permission rules.

## Speed

The hook runs once per command, as a new process. `vetter hook` through
Python takes about 70 ms, most of it Python starting. The standalone
executable takes about 1.7 ms, of which the decision itself is about
0.02 ms: see [Embedding and native builds](embedding.md).

## Verified

- **Codex CLI 0.162.1**, end to end (2026-10-11): a throwaway `CODEX_HOME`,
  the hook installed, `codex exec` asked to write a file a test policy
  denies. Codex reported `hook: PreToolUse Blocked` with vetter's reason, and
  the file wasn't written.
- **Claude Code**: requests and answers checked against the hook interface.
- **The others**: built from their official documentation (October 2026),
  each agent's payloads tested in `tests/test_hook.py`. Not yet verified end
  to end: Amp's plugin API details, the name of VS Code's terminal tool,
  Cline's current shell tool name.
