# Reading commands

vetter's decisions are only as good as its reading of the command. Each
shell has its own grammar and resolver, and each is checked against the
real thing rather than against expectations. This page describes what each
reader covers, how it's verified, and where it stops.

## bash

Non-interactive bash 5, as agents run it.

**What's read exactly**

- **Words and quoting**: `'...'`, `"..."`, `$'...'`, `$"..."`, `\` escapes,
  adjacent pieces (`a"b"'c'`).
- **Operators**: `;`, `&`, `&&`, `||`, `|`, `|&`, `!`, newlines (an
  unquoted newline separates commands), `#` comments (only at the start of
  a word).
- **Compound commands**: subshells, groups, `if`/`elif`/`else`, both forms
  of `for`, `while`/`until`, `case`, `select`, `[[ ... ]]`, `(( ... ))`,
  function definitions, `coproc`.
- **Expansions**: `$x`, `${x}`, every `${x op word}` form (where
  `${x:-$(cmd)}` hides a command), `$(...)`, backticks, `$((...))`,
  `<(...)`, `>(...)`, brace expansion (`{a,b}`, `{1..9}`), `~`, globs.
- **Redirections**: `<`, `>`, `>>`, `>|`, `<>`, `&>`, `&>>`, `2>&1`,
  `n>&m-`, here-documents (`<<EOF`, `<<-EOF`, `<<'EOF'`, read the way bash's
  lexer reads them) and here-strings. Their targets are files read or
  written.
- **Assignments and state**: `X=1 cmd`, `export`, `declare` (including
  namerefs and `-i`), `set -a`, `alias` (and its expansion), `hash -p`,
  `cd`, `pushd`, `popd`, `CDPATH`.

**How it's verified**

- **Differential testing against bash 5.2** (`python -m tools.bash.bashdiff`):
  bash and vetter must accept or reject a command alike, and bash's own
  canonical form of it (`declare -f` of a function holding it) must have the
  same commands, words, redirections, operators and compound commands as
  vetter's reading.
- **Fuzzing** (`python -m tools.bash.bashfuzz`): random fragments, commands
  generated from bash's grammar, and here-documents, compared the same way,
  each disagreement shrunk to a minimal command. Where vetter is stricter
  than bash, it asks. Any other disagreement is a bug.
- **Against other readers** (`python -m tools.compare.vs_treesitter`): the
  same commands through tree-sitter-bash, which reads about 56% of valid
  commands as bash does.

## PowerShell

Windows PowerShell 5.1 and PowerShell 7.

- **The grammar** covers pipelines, the `&` and `.` call operators, script
  blocks, `--%`, splatting, subexpressions, here-strings, and the Unicode
  dashes and quotes PowerShell accepts.
- **Cmdlets** are bound as PowerShell binds them: aliases (`iex`, `rm`,
  `curl`), parameters by unique prefix (`-Rec` for `-Recurse`), positional
  parameters. Every cmdlet's parameters come from PowerShell itself
  (`tools/powershell/cmdlet_params.py`).
- **Code run from strings** is read again: `Invoke-Expression`, `-Command`,
  `-EncodedCommand`, `[scriptblock]::Create()`, `powershell -c` from bash.
  `.NET` calls that act (`[IO.File]::WriteAllText`) are decided by what they
  do, or are unknown.
- **Verified** against PowerShell's own parser
  (`[System.Management.Automation.Language.Parser]::ParseInput`) through a
  persistent oracle (`python -m tools.powershell.pwshdiff`), with a fuzzer
  (`pwshfuzz`).

## cmd.exe

- **Its phases, in order**: `%VAR%` expansion first (an unknown variable
  makes the line unreadable), carets and quotes, operators (`&`, `&&`,
  `||`, `|`), `rem` and labels.
- **Control flow**: `if`, `for` (`for /f in ('cmd')` runs its command),
  blocks.
- **Code run from strings** is read again: `cmd /c` (with `/v:on`'s delayed
  expansion), `call`, `start`, `powershell`, `conhost`. `forfiles /c`,
  `schtasks /create` and `rundll32` are unknown.
- **Verified** on cmd.exe itself, since it has no parser to compare with.
  Probes replace the payload with `echo`, and the Windows oracle
  (`tools/oracle/windows.py`) runs attacks for real.

## Python

The code given to `python -c`, or to python on its standard input
(`python - <<'EOF'`, `echo ... | python`), is read and followed instead of
being asked about wholesale.

- **The grammar** (`vetter/shells/python/python.zgram`) covers Python 3.8
  to 3.13 as agents write it, after a scanner that does what Python's
  tokenizer does: logical lines, indentation, and `\r\n` and a lone `\r` as
  newlines. Not covered (asked): `match` and type parameters.
  `python -m tools.python.pydiff` compares it with CPython's parser on the
  standard library and installed packages: 0 differences in 1,584 files.
- **The evaluator** (`vetter/shells/python/resolve.py`) follows the code
  abstractly: values are known (a string, a number, a list, a module, a
  function of the code's own, a path) or not. It follows both branches of an
  `if` whose test isn't known, and runs loops until their values settle. It
  knows that code after `return` doesn't run, that an exception handler sees
  every value its `try` assigned, and that two names for one list share
  changes.
- **Default deny**: each standard-library function vetter follows is listed
  with what it does (`vetter/shells/python/stdlib.py`). Anything else is
  asked: `eval`, `exec`, `__import__`, `ctypes`, `pickle`, `getattr` of a
  computed name, Python's internals, calls into third-party libraries, and
  names that aren't ASCII (Python folds them: `ｃｍｄ` is `cmd`).
- **What it finds is decided like everything else**: commands run through
  `os.system` and `subprocess` are read as shell commands, with the folder
  and environment the code set up and what it feeds their input. Files are
  read, written and deleted, and connections made through `urllib`,
  `requests`, `httpx` and `socket`.
- **Imports**: `python -c` puts the current folder first on the module path,
  so an import is the project's code where it runs (unless `-I`, `-P` or
  `PYTHONSAFEPATH`). `sys.path.insert(0, "src")` with a known folder makes
  imports from it that folder's code.
- **Verified**: values are computed exactly or not at all
  (`python -m tools.python.valuediff` compares random expressions with
  Python's results), and `python -m tools.oracle.pyfuzz` runs thousands of
  programs built to mislead the evaluator in the sandbox (see
  [Testing](testing.md#python)).

- **`python -m MODULE`**: a module of the project or an installed package
  is the project's code. A standard-library module runs or reads what it's
  given (`-m timeit CODE`, `-m cProfile SCRIPT`, `-m base64 FILE`), so it's
  asked, except `unittest` (the project's tests), `venv` (the folders it
  makes) and `json.tool` (a file read, one written).
- **Links**: a link the code makes (`os.symlink`, `Path.symlink_to`) is
  written, and its target read and written too: what's done through the
  link is done to the target.

`node -e`, `perl -e` and `ruby -e` code isn't read yet: it's `run inline`.

## Command specs

What a program does with its arguments is described in
`vetter/specs/*.toml`: which arguments are files it reads, writes or
deletes, URLs, programs or code it runs, options taking values, and the
environment variables that change what it runs (`GIT_SSH_COMMAND`,
`LD_PRELOAD`, `MAKEFLAGS`). `strict` specs make any option they don't list
unknown, rather than assuming it's harmless. See
[`vetter/specs/README.md`](../vetter/specs/README.md) for the format.

## When a reading isn't certain

Some things can't be known before a command runs: the output of `$(cmd)`
used as a command name, `eval "$x"`, a variable set by a program, a glob's
matches. vetter marks those parts as **unknown** and never fills the gap
with a guess. The policy decides what happens to them, and by default it
asks.
