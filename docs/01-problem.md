# 1. The problem

## What agents do today

Every major coding agent can run shell commands. Before running one it
decides: run it, ask the user, or refuse. The decision is made by matching the
command's **text** against rules:

| Agent | Built-in rules | How they match |
|---|---|---|
| Claude Code | `Bash(npm run test:*)` allow/ask/deny | prefixes and wildcards; splits `&&`, `\|\|`, `;`, `\|` |
| Codex CLI | execpolicy `.rules` (Starlark `prefix_rule`) | token prefixes; gives up (prompts) on redirections, substitutions |
| Gemini CLI | TOML policy engine | `commandPrefix`, `commandRegex` |
| Copilot (VS Code) | `chat.tools.terminal.autoApprove` | regex per sub-command (tree-sitter split) |
| Cursor | allowlist / denylist | text |
| Roo Code | allowed / denied prefixes | text |

Two vendors say it in their own docs: Copilot's auto-approve and Codex's hooks
are "not a security boundary".

## What goes wrong

Text matching fails both ways.

**Bypasses.** The command does more than the rule saw:

- Cursor, CVE-2025-54131: `$(...)` and backticks bypassed the allowlist.
- Cursor, CVE-2026-22708: shell built-ins and environment variables.
- Cursor, HiddenLayer advisory (CVSS 9.8): `ls $({rm,./test})`, brace
  expansion.
- Codex, CVE-2026-19591: PowerShell's `--%` token misread, approval skipped.
- Codex, "GitPwned" (Pillar Security): "safe" `git show/diff/log` with
  `--output` and `--textconv` write files and run code.
- Gemini CLI (Tracebit, July 2025): an allowed `grep`, then `;` and
  `env | curl`, exfiltrated data.
- Claude Code: CVE-2025-55284 (a too-broad safe list), CVE-2026-24887 (`find`
  misparsed, prompt skipped), CVE-2026-24053 (zsh `>|` redirection).
- Roo Code: CVE-2026-63108 (`${x:-$(…)}`), CVE-2026-82536 (pipe missing
  from its parser), CVE-2026-82537 (comments).
- Trail of Bits, "Prompt injection to RCE in AI agents" (2025-10-22): argument
  injection through allowlisted `find`, `grep`, `git`, `go test`.

**Too many prompts.** The rule can't see that a command is harmless, so the
user is asked again and again until they stop reading:

- claude-code #28240, "Permission prompt incorrectly triggers on cd instead of
  the actual command in compound bash statements": 209 reactions, open.
- claude-code #16561, "Parse compound Bash commands and match each component
  against permissions": 176 reactions.
- claude-code #30519, "Permissions matching is fundamentally broken — 30+ open
  issues": 80 reactions, open.
- codex #2860, "Unusable on Windows due to permission ask for every shell
  command": 110 reactions.
- vscode #252496, "Auto-approve terminal command execution": 254 reactions.
- HN, "Humans missed 1 in 3 threats approving AI agent commands": 340 points,
  245 comments. Approving by hand isn't a defense either.

## Why it keeps happening

A shell command is a program. What it runs depends on quoting, expansions,
substitutions, redirections, wrappers (`sudo`, `env`, `timeout`, `xargs`,
`find -exec`, `sh -c`, `eval`), and on what each program does with its
arguments (`git --output`, `find -delete`, `tar --to-command`). Prefixes,
globs and regexes see none of it; tree-sitter-bash is error-tolerant and not
exact to bash. Each fix patches one trick; the next CVE uses another.

## Who has it

Everyone using a coding agent with auto-approval, and everyone building one.
The demand is visible: destructive_command_guard, a pre-execution guard for
about fifteen agents, reached 6,100 GitHub stars in nine months; cc-safety-net
1,600; dozens of smaller guards appeared in 2026. Funded companies (Rein $25M,
Geordie $30M, Reco $55M in 2026) sell enterprise agent-security platforms; none
of them is a precise command-policy engine.

Sources are linked in [07-landscape.md](07-landscape.md#sources).
