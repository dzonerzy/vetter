# 2. Goals and non-goals

## Goals

1. **Exact.** vetter's reading of a command is bash's reading of it.
   Every program the command would run, every file it would write, is found.
   Checked against bash itself (differential testing), not against our
   expectations.
2. **Fail closed.** What vetter can't decide exactly (a substitution whose
   output is a command, `eval` of a variable, a construct it doesn't know)
   is never allowed by accident: the policy says what happens (ask or deny),
   and the default is ask.
3. **Fewer prompts, not more.** Precision cuts both ways: a compound command
   whose every part is allowed is allowed. `cd src && npm test` doesn't ask.
   The measure is prompts saved on real agent sessions.
4. **Policies you can trust.** A typed policy language, checked when it
   loads: unknown commands and flags, rules that can never match, rules
   hidden by earlier ones, conflicts. Test cases live next to the rules and
   run at load time; a failing test is a load error.
5. **Explained decisions.** Every answer says which rule decided it and
   which part of the command it matched, with its position.
6. **Fast.** Under 1 ms per decision for typical commands, with the policy
   compiled to native code. The check runs before every command; it must be
   invisible.
7. **One engine, every agent.** Ready hooks for each agent's pre-execution
   interface (Claude Code, Codex, Gemini CLI, Cursor, Copilot, Cline, Amp,
   opencode), a CLI, and a C library for custom harnesses. Import the rules
   people already wrote (Claude Code permissions, Codex `.rules`).
8. **Knows commands, not just shells.** Built-in knowledge of what common
   programs do with their arguments: which arguments are paths, which flags
   write files or run other programs (`git --output`, `--textconv`,
   `find -exec`, `-delete`, `tar --to-command`, `xargs`, `rsync -e`, ...).
   Most real bypasses are here, not in the shell syntax.
9. **A public bypass corpus.** Every known bypass (from CVEs, advisories,
   issues) as a test, run against vetter and the alternatives, published.

## Non-goals (for now)

- **Not a sandbox.** vetter decides before a command runs; an OS sandbox
  (Anthropic's sandbox-runtime, containers, VMs) limits what it can do once
  running. They're complementary; vetter can recommend one for what it asks
  about.
- **No LLM in the decision.** Decisions are deterministic and explainable. An
  LLM may help *write* policies, never decide.
- **Not an enterprise platform.** No dashboards, fleets, SIEM. A precise
  engine others can build on.
- **Not MCP traffic or network filtering** at first. Tool calls other than
  shell (file edits, MCP) get simple path and argument rules in the first
  versions; the depth goes into the shell.
- **Not every shell at once.** bash first, then PowerShell and cmd.exe
  (Windows agents, with their own CVEs), then zsh and POSIX sh differences.
  All of them before calling vetter complete.

## How we'll know it works

| Measure | Target |
|---|---|
| Bypass corpus | 100% of known bypasses denied or asked, with the stock policy |
| Differential tests against bash | no disagreement on the corpus of real agent commands |
| False prompts | at least half fewer than each agent's built-in rules, on recorded sessions |
| Latency | p99 under 1 ms per decision |
| Adoption | a hook for each of the eight agents; installable in one command |
