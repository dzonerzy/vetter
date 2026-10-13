# Changelog

All notable changes to vetter are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **`python -m` with a standard-library module** was the project's code,
  allowed: `-m timeit CODE`, `-m cProfile SCRIPT`, `-m base64 FILE` run or
  read what they're given. Such a module is asked now, but `unittest` (the
  project's tests), `venv` (the folders it makes) and `json.tool` (a file
  read, one written).
- **A link made in the command** (`os.symlink`, `os.link`,
  `Path.symlink_to`, `hardlink_to`) was only the link's write: what's
  read or written through it is its target's, so the target is read and
  written too (as `ln`'s spec has it).
- **`.read()` and `.write()` of any value** were taken to only compute:
  `ConfigParser().read(PATH)`, `ElementTree.write(PATH)`,
  `MimeTypes().read(PATH)` open files. They're a stream's only now (an
  open file, `sys.stdin`, `sys.stdout`, a `StringIO`); an ElementTree's
  `write()` and `parse()` are its path's write and read.
- **Modules taken as pure whose objects act later**: `shlex.shlex` (its
  source directive opens files), `mimetypes`, `types`, `gettext` no longer
  are (`shlex.split`, `quote`, `join` and `mimetypes.guess_type` still);
  nor a pure module's `main()` (it reads `sys.argv`'s files) or private
  names; `typing.get_type_hints` and `functools.singledispatch` evaluate
  annotations given as strings: asked.

## [0.2.0] - 2026-10-13

The first published release.

### Added
- **Python read and followed**: the code given to `python -c`, or to
  python on its stdin (a here-document, `echo ... |`), is parsed (Python
  3.8-3.13, checked against CPython's parser on the standard library) and
  evaluated abstractly: what it reads, writes and deletes, the commands it
  runs (`os.system`, `subprocess`, `os.exec*`, resolved as shell commands,
  with the folder, environment and input it gives them), where it connects.
  Both ways of a branch, loops until their values settle, exceptions, early
  returns, closures and shared lists followed; what it can't follow
  (`eval`, `exec`, `__import__`, `ctypes`, third-party calls) asked.
  Programs built to mislead it, run for real (`tools/oracle/pyfuzz.py`):
  none did more than vetter allowed.
- **`vetter learn`**: rules from the asks you said yes to. The hook logs
  each call's id and, through a `PostToolUse` hook (Claude Code, Codex),
  that it ran; `vetter learn` suggests the narrowest rule for each
  (a program and its subcommands, a host, a folder), never from what vetter
  couldn't see, an ask made on purpose, or a rule that would allow what you
  said no to. `--apply` adds them to your policy.
- **Known paths where they were unknown**: `find -exec`'s `{}` is a file
  under its starting point, `xargs` fed by `echo` gets its words (`-i`,
  `-I` in place), PowerShell's `foreach` over constant strings binds its
  variable, `$_` from `Get-ChildItem PATH` is a file under PATH.
- **The stock policy**: read-only `gh`, `az`, `bq` and `kubectl`
  subcommands allowed; any program with `--help` or `--version` (its run
  only); `git branch -d` (`-D` still asked).
- **Documentation** rewritten for readers (`docs/`), a logo, the corpus'
  own README.
- `tools/compare/guards.py` tells the attacks vetter allows by policy from
  the ones it couldn't read; `tests/test_corpus.py` decides the corpus in
  both of zrun's modes.

### Changed
- **A path only running tells is asked about, not denied**: `rm -rf "$X"`
  no longer matches `deny delete outside $project` (an unknown path isn't
  known to be outside); it still keeps an allow from applying.
- **Data written in the command isn't local data sent out**:
  `curl -d 'a=1'` is the network's rule (asked); a file (`-d @f`, `-F
  k=@f`, `-T f`), a pipe or a value only running tells is still denied.
- **Python's network isn't python's own**: a rule allowing `python3`
  doesn't cover the connections its `-c` code makes.
- **`curl ... | python3 -c CODE`** isn't "a download piped into a shell":
  the code is read, and what it does with its input decided (a shell fed
  from it, `exec` of it, a file it writes then run: still denied).
- vetter is licensed under Apache-2.0, the corpus under CC BY 4.0.
- zrun 0.7.4 or later.

### Fixed
- `vetter why` printed an execution's `(via ...)` twice.

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
