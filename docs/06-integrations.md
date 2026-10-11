# 6. Integrations

Most agents let an external program approve or block a tool call before it
runs: JSON on stdin with the tool and its input, a decision on stdout (or
exit 2 to block). One engine, each agent's request and answer
(`vetter/agents/hook.py`), and `vetter install AGENT` to register it.

| Agent | `vetter install` writes | Request | Answer | Ask? | On a hook failure |
|---|---|---|---|---|---|
| Claude Code | `~/.claude/settings.json`: `PreToolUse`, matcher `Bash\|PowerShell` | `tool_name`, `tool_input.command`, `cwd` | `hookSpecificOutput.permissionDecision` | yes | vetter answers ask |
| Codex CLI | `~/.codex/hooks.json`: `PreToolUse`, matcher `^Bash$` (trust it with `/hooks`) | Claude's | deny only: `hookSpecificOutput` deny; allow is saying nothing | no: an ask fails the hook and the call goes ahead, so vetter denies | fails open |
| Gemini CLI | `~/.gemini/settings.json`: `BeforeTool`, matcher `run_shell_command` | `tool_input.command`, `dir_path` | `{"decision": "allow" \| "deny", "reason"}` | no: deny | fails open |
| Cursor | `~/.cursor/hooks.json`: `beforeShellExecution`, `failClosed` | `command`, `cwd` | `{"permission", "user_message", "agent_message"}` | yes (not in `preToolUse`) | blocks (`failClosed`) |
| Copilot CLI | `~/.copilot/hooks/vetter.json`: `preToolUse`, matcher `bash\|powershell` | `toolName`, `toolArgs` (a JSON string), `cwd` | `{"permissionDecision", "permissionDecisionReason"}` | yes (not on the cloud agent) | errors block, timeouts don't |
| VS Code (Copilot agent) | `~/.copilot/hooks/vetter-vscode.json`: `PreToolUse` (no matcher: every tool, vetter picks the terminal ones) | Claude's | Claude's | yes | fails open |
| Cline | `~/Documents/Cline/Hooks/PreToolUse` (an executable; Enable Hooks) | `preToolUse.toolName` / `parameters.command`; the CLI's `tool_call` | `{"cancel", "errorMessage"}`; the CLI's `review` | CLI only | fails open |
| Amp | `~/.config/amp/plugins/vetter.ts` (a plugin calling `vetter hook amp`) | the plugin's `tool.call` event | `allow` / `reject-and-continue` | through Amp's `ctx.ui.confirm` | not documented |
| opencode | `~/.config/opencode/plugins/vetter.js` (a plugin calling `vetter hook opencode`) | `tool.execute.before`, tool `bash` | throws to block | no: deny | not documented |

`vetter hook json` is vetter's own shape for other harnesses:
`{"command", "cwd", "shell"}` in, `{"decision", "reason", "default"}` out.

No external hook (built-in lists, modes or SDK classes only): Roo Code,
Zed, Goose, Aider, OpenHands. Later: a shell wrapper on PATH or an MCP
proxy.

## Decisions

- **When no rule decides** (only the policy's default), vetter says nothing
  where the agent has its own permissions (Claude, Codex, Gemini, Copilot,
  VS Code, opencode): they decide, as without vetter. A deny is always said.
- **Where the agent can't ask** (Codex, Gemini, Cline's extension,
  opencode), a rule's ask becomes a deny that says so ("vetter would ask...:
  run it yourself if it's fine"): failing open on what a person should look
  at would let it run.
- **vetter never fails open by crashing**: an error in vetter is its ask (a
  deny where asking isn't possible). Where the agent offers it, `install`
  sets fail-closed (Cursor's `failClosed`).
- **Which shell**: Claude's and Copilot's tools say it (`Bash`,
  `PowerShell`); the others run the system's shell: bash, or PowerShell on
  Windows.

## Checked

- Codex CLI 0.162.1, end to end (2026-10-11): a throwaway `CODEX_HOME`, the
  hook in its `hooks.json`, `codex exec` asked to write a file a test policy
  denies: `hook: PreToolUse Blocked` with vetter's reason, the file not
  written.
- Claude Code: the hook's requests and answers (M1).
- The others from their official documentation (October 2026), each with
  its payloads in `tests/test_hook.py`; to run end to end when the agent is
  at hand. Unverified there: Amp's plugin API details (`ctx.ui.confirm`),
  the exact name of VS Code's terminal tool (`run_in_terminal` assumed),
  Cline's current shell tool name (`execute_command`, `run_commands`).

## Startup time

A hook is a new process for every command. `vetter hook` (Python, zrun's
reference mode): about 70 ms, most of it Python starting. The executable
(`python -m vetter.build vetter-hook`, no Python in it): about 1.7 ms, the
decision itself 0.02 ([10-native.md](10-native.md)).
