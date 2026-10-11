# 9. Roadmap

Each milestone ends with something that can be shown.

## M0 — Prove the core (weeks 1-2)

- The bypass corpus: the cases from the CVEs, advisories and issues found so
  far, plus GTFOBins-style argument injection, in the format of
  [08-bypass-corpus.md](08-bypass-corpus.md).
- The bash grammar in zgram: words, quoting, operators, compound commands,
  expansions, redirections, here-docs.
- Differential testing against bash (`declare -f`) on the corpus and on
  generated commands.
- **Demo:** every corpus command parsed the way bash parses it; the same
  corpus through tree-sitter-bash and dcg's reading, with their mistakes
  shown.

Status (done): the corpus (145 cases: `parsing.toml` from what fuzzing
found, `gpt-obfuscated*.toml` written by gpt-5.6-sol), the grammar with
here-documents, expanded bodies and backticks read, the differential tester
and the fuzzer against bash 5.2 (`tools/bash/`:
the whole corpus read as bash reads it; of the last 10,000 generated
commands 9,994 agree and on the other 6 vetter is stricter, i.e. asks), and
the comparisons:

- tree-sitter-bash (`tools/compare/vs_treesitter.py`): reads ~56% of valid commands
  as bash does (fails on here-docs, `;&`, `{fd}>`; misses the commands after
  `time`, `coproc`, a `\`-newline in a name);
- dcg 0.15.3 (`tools/compare/vs_dcg.py`): lets through 59 of 135 bypasses with its
  stock packs; of the 30 obfuscated `rm -rf ~/project` (which it denies in
  plain form) 9, three of them static (`bash -c $'\x72\x6d -\x72\x66 ...'`,
  `sh -c "r\\m ..."`, `bash <<< 'r\m ...'`); with a pack that blocks the
  other gpt cases' payload (touch) the way it blocks rm -rf, still 12 of
  those 40 (command names built at run time); and it blocks 3 harmless
  commands (`rm -rf` as here-doc text, in arithmetic).

## M1 — Decide (weeks 3-4)

- The resolver: executions, wrappers (table), `sh -c` recursion, `cd`
  tracking, expansions classified, redirections as file writes.
- Command specs for the first programs: git, rm, find, xargs, curl, wget, tar,
  sed, grep, npm, pip, cargo, go, docker, ssh, rsync.
- A minimal policy, written in a first subset of the language (not code to
  throw away), and `vetter check`.
- The Claude Code hook (`vetter install claude`), fail-closed.
- **Demo:** the corpus fully denied or asked; a real Claude Code session with
  fewer prompts than its built-in rules.

Status: done but the demo session.
- `vetter/shells/bash/expand.py`: bash's expansions in order (braces, ~, the variables
  known from straight-line assignments with their operations, IFS
  splitting, patterns, quote removal); `resolve.py`: executions
  through lists, conditions (what they change becomes unknown), loops (a
  few known items: the body once each), functions, substitutions, here-doc
  bodies, backticks, wrappers, `bash -c`/`eval`/here-documents fed to a
  shell read again, `cd`, exports, downloads run later.
- `vetter/specs/` (the engine and its `*.toml`): roles of arguments (files
  written/read/deleted, URLs, commands and programs run: git config keys,
  `-exec`, `--to-command`, `-e`, sed's `e`, ssh's ProxyCommand...) and of
  environment variables (GIT_SSH_COMMAND, LD_PRELOAD, PATH...).
- A first subset of the language (draft 1), replaced since by draft 2 (M2).
- `vetter check | why | test | hook claude | install claude`.
- On the corpus with the stock policy: no bypass allowed, no harmless command
  asked; 2 deny cases only asked (`echo hi |& sh`, `diff <(curl …) >(sh)`).

## M2 — The policy language (weeks 5-7)

- The language of [05-policy-language.md](05-policy-language.md) in zgram,
  checked with zrules (types, unknown names, dead and shadowed rules,
  conflicts), tests run at load time.
- Compiled with zrun to native code; `vetter test`, `vetter lint`,
  `vetter explain`.
- The stock policy.
- `vetter import claude` and `vetter import codex`.

Status: draft 2 in `vetter/policy/` (language.py: grammar, loading, first
match per action with its reasons; actions.py; trace.py), the stock policy
in it (`policy/builtin/stock.vet`, 22 rules, 64 tests across the three shells), `vetter why`
(`--all`, `--rule`), `vetter test --coverage`, rules never reached found
when it loads, `use`/`drop`, a project's `.vetter.vet` (deny and ask only),
the decision log with secrets masked and `vetter replay`. Then: the checks
on zrules (`vetter/policy/checks.py`: an unknown place is an error with its
likely fix; a mistyped list, program, subcommand or flag a warning, against
the specs' `commands` and options; unused lists, two rules with one
reason), `vetter lint`, `vetter import claude|codex` (their rules first,
the stock denies before all), `$project` / `$home` / `$temp` for what's
known when deciding (`$project`: the git root, `$temp`: the machine's
`TMPDIR`/`TEMP` too). Left: zrun compiling.

## M3 — Every agent (weeks 8-9)

- Adapters: Codex, Gemini CLI, Cursor, Copilot (VS Code and CLI), Cline, Amp,
  opencode.
- Standalone native binaries (zrun `build_native`) for Linux, Windows; macOS
  when zgram's LLVM has its backend.
- `libvetter.so` with its C API; Python and Node bindings first.

Status: the adapters are done (`vetter/agents/hook.py`,
[06-integrations.md](06-integrations.md)): `vetter hook` and
`vetter install` for Claude Code, Codex, Gemini CLI, Cursor, Copilot CLI,
VS Code, Cline, Amp and opencode (plugins for the last two), and
`vetter hook json` for other harnesses; each agent's payloads in
`tests/test_hook.py`; Codex checked end to end. vetter is native
([10-native.md](10-native.md)): the hook as an executable (about 1.7 ms a
call; Linux and Windows) and `libvetter` (.so, .dll) built by zrun. Left:
shipping them (wheels with the executable, `vetter install` pointing at
it).

## M3b — Windows shells (weeks 9-11)

- PowerShell grammar and resolver: pipelines, `&` and `.` call operators,
  script blocks, `--%`, `-EncodedCommand`, `Invoke-Expression`, aliases
  (`iex`, `rm`, `curl`), parameter binding by prefix (`-Rec` for `-Recurse`).
- cmd.exe grammar and resolver: `&`, `&&`, `||`, `^`, `%VAR%`, `!VAR!`,
  `cmd /c`, `call`, `start`.
- Command specs for Windows programs (`Remove-Item`, `Invoke-WebRequest`,
  `del`, `rd`, `certutil`, `bitsadmin`, ...).
- Bypass corpus entries for both; differential testing against `pwsh`'s
  own parser (`[System.Management.Automation.Language.Parser]::ParseInput`)
  and cmd where possible; a fuzzer for each, like `tools/bash/bashfuzz.py`.
- Generated obfuscation batches like bash's (`gpt-obfuscated*.toml`): one
  with a harmless payload, one with the payload the guards block in plain
  form (`Remove-Item -Recurse -Force ~/project`, `rd /s /q %USERPROFILE%\project`),
  so the comparison with dcg and others measures their reading.

Status:
- PowerShell (`vetter/shells/powershell/`): the grammar (5.1; zgram 0.5.3's
  `\xHH` for the Unicode dashes and quotes), checked against PowerShell's
  own parser through a persistent oracle (`tools/powershell/`: 133/133
  built-in and corpus commands; the fuzzer's remaining disagreements are
  garbage vetter rejects, i.e. asks); the resolver: cmdlets with aliases and
  prefix binding (`specs/powershell.toml`), `iex`/`-Command`/
  `-EncodedCommand` read again, pipelines (`iwr | iex`), .NET calls that act
  (`[IO.File]::WriteAllText`, `[scriptblock]::Create().Invoke()`) as
  unknowns, `--%` split as Windows splits a command line.
- cmd.exe (`vetter/shells/cmd/`): its phases (%VAR% first: an unknown one
  makes the line unreadable; carets and quotes; operators; `rem` and a blank
  ending the line), `if`/`for` (`for /f in ('cmd')` runs it), blocks, the
  internal commands' file actions, `call`/`start`/`cmd /c` (`/v:on`)/
  `powershell`/`conhost`/`wmic ... create` read again (`forfiles /c`,
  `schtasks /create`, `rundll32` and the like: unknowns). No parser to compare with:
  checked on cmd itself with `echo`-only probes.
- One policy for the three: Windows places (paths case-insensitive, `C:/`,
  `HKCU:`), the stock policy's lists and tests for each shell (`[ps]`,
  `[cmd]` in `tests`); `vetter check|why --shell`; the Claude Code hook
  reads its `PowerShell` tool as PowerShell.
- Corpus (`docs/08-bypass-corpus.md`): for PowerShell and cmd the bash
  families (arguments, wrappers, separators, expansion, substitution,
  redirections, comments-env, parsing, harmless) and the two obfuscated
  batches each (harmless payload; `Remove-Item -Recurse -Force`, `rd /s /q`):
  285 cases, none allowed, no harmless one asked. What they found, fixed:
  PowerShell starting cmd (read by cmd's rules, `--%` too), `Start-Process`
  arguments joined into a command line, `-Verb RunAs`, `$env:` assignments
  reaching later programs, `'x' > $PROFILE`, `$( )` in strings, unbound
  arguments (now unknown), every cmdlet's parameters from PowerShell itself
  (`tools/powershell/cmdlet_params.py`), Windows programs' specs
  (`specs/windows.toml`: certutil, bitsadmin, esentutl, regsvr32, mshta,
  msiexec, reg...), cmd labels and `@rem`, quoted pieces in one word, `for`
  values substituted, `GIT_SSH_COMMAND` read once.

## M4 — The editor and the launch (weeks 12-14)

- zlsp for `.vet` files: errors, completion from specs, hover.
- The published benchmark: bypass corpus and false prompts, vetter against
  dcg, cc-safety-net, Codex execpolicy and the built-ins.
- Launch: README with the benchmark, a write-up of the bypass families,
  Show HN, posts in the agents' communities.

## Later

- zsh and POSIX sh differences in full.
- File-edit and MCP tool policies with the same language.
- Shared policy packs (per stack: node, python, rust, infra).
- A shell wrapper on PATH for agents without hooks.

## Open questions

- **License.** Open source to be adopted (MIT/Apache) — and a business on top
  (support, enterprise policy management) or not?
- **Name** on PyPI/crates/npm: `vetter` is free on PyPI and crates.io (to
  check on npm, and for trademarks).
- **Where it lives.** In zsuite while it's designed; its own repository
  before the launch.
- **What Windows agents really run**: PowerShell 5.1 or 7, cmd, Git Bash,
  WSL: check each agent's default before M3b.
