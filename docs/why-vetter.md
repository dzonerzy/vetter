# Why vetter

AI coding agents run shell commands on your machine. Before each one, the
agent decides whether to run it, ask you, or refuse. Almost every agent
makes that decision by matching the command's **text** against a list of
rules. That approach fails in both directions: it lets dangerous commands
through, and it asks about harmless ones until people stop reading the
prompts.

vetter replaces text matching with an exact reading of the command.

## How agents decide today

| Agent | Built-in rules | How they match |
|---|---|---|
| Claude Code | `Bash(npm run test:*)` allow / ask / deny | prefixes and wildcards; splits on `&&`, `\|\|`, `;`, `\|` |
| Codex CLI | execpolicy `.rules` (Starlark `prefix_rule`) | token prefixes; prompts on redirections and substitutions |
| Gemini CLI | TOML policy engine | `commandPrefix`, `commandRegex` |
| Copilot (VS Code) | `chat.tools.terminal.autoApprove` | a regex per sub-command, split with tree-sitter |
| Cursor | allowlist / denylist | text |
| Roo Code | allowed / denied prefixes | text |

Two vendors say so in their own documentation: Copilot's auto-approve and
Codex's hooks are "not a security boundary".

## What goes wrong

### Commands that slip through

The command does more than the rule saw:

- **Cursor**: CVE-2025-54131, `$(...)` and backticks bypassed the
  allowlist. CVE-2026-22708, shell built-ins and environment variables.
  The HiddenLayer advisory (CVSS 9.8): `ls $({rm,./test})`, brace expansion.
- **Codex**: CVE-2026-19591, PowerShell's `--%` token misread and approval
  skipped. "GitPwned" (Pillar Security): "safe" `git show`, `git diff` and
  `git log` write files and run code through `--output` and `--textconv`.
- **Gemini CLI** (Tracebit, July 2025): an allowed `grep`, then `;` and
  `env | curl`, exfiltrated data.
- **Claude Code**: CVE-2025-55284 (a safe list that was too broad),
  CVE-2026-24887 (`find` misparsed, prompt skipped), CVE-2026-24053
  (zsh's `>|` redirection).
- **Roo Code**: CVE-2026-63108 (`${x:-$(…)}`), CVE-2026-82536 (pipes
  missing from its parser), CVE-2026-82537 (comments).
- **Trail of Bits**, "Prompt injection to RCE in AI agents" (2025-10-22):
  argument injection through allowlisted `find`, `grep`, `git` and
  `go test`.

### Prompts nobody reads

When a rule can't tell that a command is harmless, the user is asked again
and again:

- claude-code #28240, "Permission prompt incorrectly triggers on cd instead
  of the actual command in compound bash statements": 209 reactions.
- claude-code #16561, "Parse compound Bash commands and match each component
  against permissions": 176 reactions.
- claude-code #30519, "Permissions matching is fundamentally broken — 30+
  open issues": 80 reactions.
- codex #2860, "Unusable on Windows due to permission ask for every shell
  command": 110 reactions.
- vscode #252496, "Auto-approve terminal command execution": 254 reactions.
- Hacker News, "Humans missed 1 in 3 threats approving AI agent commands":
  340 points. Approving everything by hand isn't a defense either.

### Why it keeps happening

A shell command is a program. What it runs depends on quoting, expansions,
substitutions, redirections and wrappers (`sudo`, `env`, `timeout`,
`xargs`, `find -exec`, `sh -c`, `eval`), and on what each program does
with its arguments (`git --output`, `find -delete`, `tar --to-command`).
Prefixes, globs and regular expressions see none of that. tree-sitter-bash
is built for syntax highlighting: it tolerates errors and isn't exact to
bash. Each fix patches one trick, and the next CVE uses another.

## What vetter does instead

vetter reads a command the way the shell will run it, finds everything it
would do, and decides each of those things with a policy you can read and
test:

- **Exact reading.** bash, PowerShell and cmd.exe are parsed with grammars
  checked against the real shells, and Python given to `python -c` is
  followed too. Wrappers, `sh -c`, `eval`, here-documents, substitutions and
  aliases are read through.
- **Actions, not text.** A rule says `delete outside $project`, and it holds
  for `rm -rf`, `find -delete`, `shutil.rmtree()`, `Remove-Item -Recurse` and
  `rd /s` alike. Command specs describe what hundreds of programs do with
  their arguments.
- **Never guesses.** What vetter can't know before the command runs is
  marked as such, and the policy decides: by default, it asks.
- **Fewer prompts.** A compound command whose every part is allowed is
  allowed. `cd src && npm test` doesn't ask.
- **Explained.** Every decision names the rule that made it and points at the
  part of the command it's about.

## How it compares

| | dcg and similar guards | Agent built-ins | vetter |
|---|---|---|---|
| Reading of the command | tree-sitter or regexes | prefixes and regexes | exact, checked against the real shells |
| Parts it can't know | guessed | guessed, or always asked | marked; the policy decides |
| Wrappers, `sh -c`, `find -exec`, `xargs` | some | few | all known ones, recursively |
| What arguments mean (`--output`, `-exec`) | pattern lists | no | command specs |
| Policy checked when it loads | no | Codex's examples only | dead rules, unknown names, tests |
| Explains its decisions | partly | no | the rule and the span |
| Embeddable | no | no | a C library |

On the test suite that dcg's own authors ship, vetter stops 94% of the
attacks, against dcg's 68% and cc-safety-net's 47%. Every attack vetter lets
through is one it read correctly and allowed on purpose: deleting build
output, deleting temporary files, deleting a merged git branch. See
[Testing and benchmarks](testing.md#comparison-with-other-guards).

## The landscape

As of October 2026:

| Project | What it is | How it reads commands |
|---|---|---|
| [destructive_command_guard](https://github.com/Dicklesworthstone/destructive_command_guard) | a pre-execution guard for about 15 agents, rule packs in TOML and YAML (Rust) | patched tree-sitter-bash, a tokenizer and regular expressions |
| [cc-safety-net](https://github.com/kenryu42/cc-safety-net) | blocks destructive commands and secret access for about 16 agents (TypeScript) | its own parser; presets and JSON rulebooks |
| [Codex execpolicy](https://github.com/openai/codex/tree/main/codex-rs/execpolicy) | built into Codex: Starlark `prefix_rule`, examples checked at load | tree-sitter-bash, plain word lists |
| [agentjail](https://github.com/LuD1161/agentjail) | a daemon for Claude Code, Codex and Cursor; Rego rules | "structured parsing" |
| [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit) | a broad governance suite: YAML, OPA, Cedar | a command denylist |

Further away: NeMo Guardrails, Guardrails AI and LlamaFirewall work on
conversations and outputs, not shell commands. MCP gateways filter wire
traffic. Anthropic's sandbox-runtime is an OS sandbox, which complements
vetter rather than replacing it (see [Security model](security.md)).

## Sources

- claude-code issues [#28240](https://github.com/anthropics/claude-code/issues/28240), [#16561](https://github.com/anthropics/claude-code/issues/16561), [#30519](https://github.com/anthropics/claude-code/issues/30519)
- [codex #2860](https://github.com/openai/codex/issues/2860), [gemini-cli #11766](https://github.com/google-gemini/gemini-cli/issues/11766), [vscode #252496](https://github.com/microsoft/vscode/issues/252496), [Roo-Code #12292](https://github.com/RooCodeInc/Roo-Code/issues/12292)
- [Cursor forum: chained commands bypass the denylist](https://forum.cursor.com/t/chained-commands-bypass-yolo-mode-denylist/50775)
- [HiddenLayer advisory on Cursor](https://www.hiddenlayer.com/sai-security-advisory/sai-security-advisor-2025-11-cursor), [CVE-2026-22708](https://cvefeed.io/vuln/detail/CVE-2026-22708)
- [Pillar Security: GitPwned](https://www.pillar.security/blog/gitpwned-allowlist-to-rce), [CVE-2026-19591](https://www.sentinelone.com/vulnerability-database/cve-2026-19591/)
- [Gemini CLI stealthy execution](https://bleepingcomputer.com/news/security/flaw-in-gemini-cli-ai-coding-assistant-allowed-stealthy-code-execution)
- [CVE-2025-55284](https://nvd.nist.gov/vuln/detail/cve-2025-55284), [CVE-2026-24887](https://cvefeed.io/vuln/detail/CVE-2026-24887), [CVE-2026-24053](https://osv.dev/vulnerability/CVE-2026-24053), [CVE-2026-63108](https://cveawg.mitre.org/api/cve/CVE-2026-63108)
- [Trail of Bits: prompt injection to RCE](https://blog.trailofbits.com/2025/10/22/prompt-injection-to-rce-in-ai-agents/), [arXiv 2509.24240](https://arxiv.org/pdf/2509.24240), [APIsec: catfishing the allowlist](https://labs.apisec.ai/research/articles/catfishing-the-allowlist-mcp-argument-injection)
- Hacker News: ["Continue? Y/N"](https://news.ycombinator.com/item?id=48308376), ["Humans missed 1 in 3 threats"](https://news.ycombinator.com/item?id=49195468)
