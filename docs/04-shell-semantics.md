# 4. Reading the shell exactly

This is the hard part, and the moat. Everyone else uses regexes, a
tokenizer, or tree-sitter-bash (error-tolerant, built for highlighting, not
exact to bash). vetter's reading must be bash's.

## Scope, in order

Agents run commands in whatever shell the system gives them: bash or zsh on
Linux and macOS, PowerShell (and sometimes cmd.exe) on Windows. vetter needs
all of them; each is its own grammar and its own resolver behind the same
policy.

1. **bash** (5.x), non-interactive: what most agents run.
2. **PowerShell** (5.1 and 7): Windows agents' shell. Codex wraps commands in
   it; its CVEs (`--%` stop-parsing, script blocks `& { }`, `-EncodedCommand`,
   `Invoke-Expression`, `Start-Process`, call operator `&` on strings,
   backtick escapes) are as real as bash's.
3. **cmd.exe**: still what some tools and `.bat` files go through: `&`, `&&`,
   `||`, `|`, `^` escapes, `%VAR%` and delayed `!VAR!` expansion,
   `cmd /c`, `call`, `start`.
4. **zsh** and **POSIX sh** differences that matter (`>|`, glob qualifiers,
   `=(...)`): zsh is the default shell on macOS, and CVE-2026-24053 came from
   it.

Across shells: a command can start another shell (`powershell -c` from
bash, `cmd /c` from PowerShell, `bash -c` from cmd under WSL): the resolver
recurses into it with that shell's grammar.

The rest of this page is about bash; PowerShell and cmd get their own pages
when their grammars start.

## What must be exact

- **Words and quoting**: `'...'`, `"..."`, `$'...'`, `\` escapes, adjacent
  pieces (`a"b"'c'`), `$"..."`.
- **Operators**: `;`, `&`, `&&`, `||`, `|`, `|&`, `!`, newlines (an
  unquoted newline separates commands: a classic bypass), `#` comments (only
  at the start of a word).
- **Compound commands**: subshells, groups, `if/elif/else`, `for`
  (both forms), `while/until`, `case`, `select`, `[[ ... ]]`, `(( ... ))`,
  function definitions.
- **Expansions**: `$x`, `${x}`, all `${x op word}` forms (where
  `${x:-$(cmd)}` hides a command: CVE-2026-63108), `$(...)`, backticks,
  `$((...))`, `$[...]`, `<(...)`, `>(...)`, brace expansion `{a,b}` and `{1..9}`
  (`$({rm,./test})`: the HiddenLayer bypass), tilde, globs, `!` history
  (off in non-interactive shells: say so, not guess).
- **Redirections**: `<`, `>`, `>>`, `>|`, `<>`, `&>`, `&>>`, `2>&1`,
  `n>&m-`, here-documents `<<EOF`, `<<-EOF`, `<<'EOF'` (expanded or not),
  here-strings `<<<`. Their targets are files written or read. A
  here-document's body is read the way bash's lexer reads it: after the
  line's newline, an expanded body's `\`-newlines joined *before* the
  delimiter is looked for, and its `$(...)` and backticks parsed: they run.
- **Assignments**: `X=1 cmd` (environment for one command),
  `PATH=... cmd`, `IFS=...`, `export`, `declare`, `alias` (aliases are off
  in non-interactive bash: treat `alias` as a definition, not an expansion).

## How we make sure

- **Differential testing against bash** (`tools/bash/bashdiff.py`). Two checks
  per command: `bash -n` and vetter accept (or reject) it alike; and bash's
  canonical form of it (`declare -f` of a function holding it), read by
  vetter, has the same commands, words (values after quote removal),
  redirections, operators and compound commands as vetter's reading of the
  original. Where bash prints an equivalent form (`|&` as `2>&1 |`, a
  default fd, `elif` as `else if`, `! !` dropped, redirections moved last, a
  function body put in braces), the comparison normalizes it; where bash's
  printing is wrong (`>1 in` printed `in > 1`; `coproc`), it's skipped.
- **The reference is bash 5.2 or later** (`--bash PATH`): 5.1's `-n`
  doesn't look inside `$(...)`, so it accepts commands that fail when run.
  No bash looks inside backticks or here-document bodies before running
  them: vetter does, and what isn't bash there is `Unreadable`.
- **Fuzzing** (`tools/bash/bashfuzz.py`): random fragment soups (mostly not
  bash: acceptance), commands generated from bash's grammar (every compound
  command, word form and redirection) and here-documents (quoted, `<<-`,
  `\`-newline in bodies and delimiters), compared the same way; each
  disagreement shrunk to a minimal command. Where vetter is stricter than
  bash it asks: safe. Every other disagreement is a bug.
- **The bypass corpus** ([08-bypass-corpus.md](08-bypass-corpus.md)) as
  regression tests.
- **Against other readers** (`tools/compare/vs_treesitter.py`): the same commands
  through tree-sitter-bash, the parser most tools build on.

## When it's not exact

Some things can't be known before running: the output of `$(cmd)` used as a
command name, `eval "$x"`, `source file`, a variable set by an earlier
command, a glob's matches. vetter marks those parts **dynamic** and the
policy decides (`unknown: ask` by default). It never fills the gap with a
guess.
