# Changelog

All notable changes to vetter are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-12

The first release (tagged, not published): vetter vets every command an AI
agent wants to run, reading it as its shell reads it (bash, PowerShell,
cmd.exe) and deciding it by a policy, as the agent's hook (Claude Code,
Codex, Gemini, Cursor, Copilot, Cline, Amp, opencode, VS Code), a CLI, an
executable, and a C library.

### Added
- **Reading commands as their shells do**: bash (expansions, substitutions,
  arithmetic, aliases, functions, here-documents, the directory stack,
  namerefs, exports), PowerShell (cmdlets and their parameters, aliases,
  default parameter values, `-EncodedCommand`, script blocks, .NET calls,
  provider paths), cmd.exe (`%VAR%` and delayed `!VAR!`, carets, `for`,
  `call`, `if`, `COMSPEC`, stdin continuation); what each program does with
  its arguments and environment from command specs (`vetter/specs`), the
  tools agents use most read strictly (every option listed).
- **The policy language** (`docs/policy-language.md`): rules on what a
  command does (reads, writes, deletes, runs, downloads, sends) and where,
  by program and subcommand, with conditions; the stock policy; `vetter
  check`, `why` (each rule's verdict), `test`, `lint`, `replay`, `import`
  (an agent's permission rules as a policy), `install`.
- **Deciding on the machine**: symbolic links followed, what the agent's
  earlier commands and editing tools wrote remembered (running it asks),
  the configs a tool reads from the project (git's, cargo's, yarn's,
  maven's, npm's) read for the programs they name, the workspace the agent
  was opened in as the project.
- **A bypass corpus** (`corpus/`, 793 cases: bash, PowerShell, cmd, and
  harmless commands that must be allowed), and **oracles** that run
  commands for real (`tools/oracle`: bash in bubblewrap under strace, cmd
  and PowerShell on Windows from WSL, each attack written many ways);
  `pytest --oracle`. A comparison with dcg and cc-safety-net
  (`tools/compare/guards.py`, results in `docs/testing.md`).

### Security
- Two analyzer audits' findings fixed (the first: 49; its second round:
  40), each runtime-verified, by
  what they share rather than one by one; the oracles' own finds since
  (aliases losing redirections, `if`'s redirections in cmd, PowerShell's
  `${C:\...}` and script blocks' redirections, Windows path forms).
