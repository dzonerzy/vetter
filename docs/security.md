# Security model

## What vetter is

vetter is an **approval layer**: it decides whether a command an agent wants
to run should run, be asked about, or be refused, before it runs. It's the
layer that agents' text-matching allowlists were meant to be, and that their
CVEs showed they weren't (see [Why vetter](why-vetter.md)).

## What vetter isn't

vetter is **not a sandbox**. No reading of a command, however exact,
replaces one: what a program does with its own files and settings goes
beyond what a command line shows. Once vetter allows `make`, the Makefile
decides what runs.

Use vetter **with** the agent's sandbox where there is one (Claude Code's,
Codex's, a container). The two cover different things:

- **The sandbox limits** what anything that gets through can reach.
- **vetter stops** what a sandbox typically allows: deleting the project,
  rewriting git history, planting a hook or a Makefile that runs later
  outside the sandbox, sending data to a host the sandbox allows. It also
  asks about less, because it can tell harmless commands apart.

Where there's no sandbox (native Windows, for instance), vetter is the
boundary there is.

## The threat

vetter assumes the command may be written by an adversary: a prompt
injection in a web page, an issue, a dependency's README or a file in the
repository, steering the agent. The command may be obfuscated on purpose
(`$'\x72m'`, `{rm,-rf,~}`, string-built PowerShell cmdlets, Unicode
look-alikes, here-documents fed to shells, Python with aliased lists).

vetter does **not** defend against:

- **A malicious program that is allowed to run.** If `make` is allowed, the
  Makefile is trusted. The stock policy allows the project's own code to
  run in the project, and asks when the agent wrote it (`run generated`).
- **Compromised system binaries**, or a `PATH` vetter doesn't control.
- **Changes on the machine between the decision and the run**, other than
  those the command itself makes.
- **Tools that don't go through the hook**: file edits by the agent's own
  editing tools (which vetter only remembers, to catch them being run later)
  and MCP tool calls.

## Guarantees

- **Fail closed.** What vetter can't read exactly, or can't know before the
  command runs, is never allowed by accident: it's unknown, and the policy
  decides (ask, by default). An error inside vetter is an ask, or a deny
  where the agent can't ask.
- **A rule never denies on a guess.** A path only known when the command runs
  is in no place: it's asked rather than denied or allowed.
- **Used deny rules come first.** Rules you write, rules imported from an
  agent and rules learned from your answers can't override a deny rule of
  the policy they use. Only an explicit `drop` can remove one.
- **The project can't allow itself anything.** A repository's `.vetter.vet`
  can add deny and ask rules, never allow rules: the agent can write that
  file.
- **Asks the policy makes on purpose aren't learned.** `vetter learn` never
  turns asks about losing work, `sudo` or running what the agent wrote into
  rules.

## How it's checked

- The bypass corpus: every known bypass from CVEs, advisories, issues and
  two audits, written as a test, plus generated obfuscations.
- Oracles that run commands for real in a sandbox and compare what they did
  with what vetter decided, on Linux and on Windows.
- Fuzzers for each reader against the real shell or parser.

See [Testing and benchmarks](testing.md).

## Known limitations

- **Pipelines and stdin** are followed when the input is written in the
  command (a here-document, `echo ... |`). Input from a program is data
  vetter can't see, and a shell or interpreter reading it is asked about.
- **`node -e`, `perl -e`, `ruby -e`**: their code isn't read, so it's asked
  about (`run inline`).
- **zsh-only syntax** is read as bash reads it. Commands that differ between
  the two (`=(...)`, glob qualifiers) may be unreadable, and so asked.
- **Paths from the environment** of the machine where the hook runs are
  resolved there. A command run elsewhere (over ssh) is decided as what it
  runs locally.

## Reporting a vulnerability

A command that vetter allows but shouldn't is a security bug. Please report
it privately to the maintainer with the command, the shell, the policy
(stock, or yours), and what the command does when it runs.
