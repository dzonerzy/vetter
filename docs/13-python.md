# 13. Reading Python

Agents run Python as often as they run shell: `python3 -c '...'` to look
at a JSON file, `python3 - <<'EOF'` for anything longer. Until now that was
code vetter didn't read: every such command was asked about, and a
harmless one-liner looked the same as `os.system("rm -rf ~")`. Now the
code is read and followed like a command line: what it reads, writes and
deletes, the commands it runs (resolved as bash's are, then decided by the
same policy), where it connects, the folder it moves to, the environment
it gives what it runs.

## What's read

- `python -c CODE ARGS` (`sys.argv` is `-c` and ARGS), `python - ARGS` and
  `python` with its program on stdin: a here-document, a here-string,
  `echo CODE |`.
- Python 3.8 to 3.13 as agents write it: `vetter/shells/python/python.zgram`
  over what the scanner (`scan.py`) makes of the text, Python's tokenizer's
  job: each logical line one line, indentation as marks, `\r\n` and a lone
  `\r` as newlines (`import os # \ros.system(...)` runs the second part).
  Not read (an error, asked): `match`, type parameters, `type X = ...`.
- Checked against CPython's own parser on the standard library and the
  installed packages (`python -m tools.python.pydiff`): 1584 files, every
  one accepted alike, the same statements found in each.

## How it's followed

`vetter/shells/python/resolve.py` evaluates the code abstractly. A value is
known (a str, an int, a list of values, a module, a function of the code's
own, a path) or not: **data**, plain data a computation gives (str,
numbers, lists of them), or **opaque**, anything at all. What the code does
with a value vetter can't follow is an Unknown: asked.

- **Default deny.** Each standard-library function vetter follows is named
  in `stdlib.py` with what it does (`os.remove`: deletes its argument;
  `subprocess.run`: runs a list, or a command line with `shell=True`);
  modules whose every function only computes are listed (`json`, `re`,
  `math`...), but not what's reached through them (`shlex.os.system` isn't
  shlex's). Anything else (`eval`, `exec`, `__import__`, `ctypes`,
  `pickle`, `getattr` of a name only running tells, `__dict__` and the
  other internals) is asked. A name that isn't ASCII is asked too: Python
  folds names (`ｃｍｄ` is `cmd`).
- **Every way the code can go.** Both branches of an `if` whose test
  isn't known are followed and their values joined (two strs: data); a
  loop's body until what it changes settles; a function's body at each
  call, with what it's given (its returns joined; a recursion followed
  again with anything given, until it settles). Code after a `return`,
  `break`, `raise` doesn't run, and what follows a branch that may have
  left has either value. An exception's handler sees every value its
  `try` gave a name, as the body may have stopped anywhere; a `with` whose
  manager may swallow exceptions the same.
- **Shared as Python shares.** Two names for one list are one list: a
  change through either is seen through both. Where vetter can't say how a
  list or dict changed (in a branch, a loop, through a copy it lost track
  of), it's widened in place: its items no longer known, for every name
  that holds it.
- **Values computed exactly or not at all.** `+`, `%`, `str.format`,
  f-strings, `join`, `split`, `strip`, `os.path.join`, `Path` and `/`,
  `shlex.quote`... give what Python gives, or data: on text that isn't
  printable ASCII (Unicode's spaces and cases are Python's tables), on
  numbers past 2^52. A test whose truth is known takes its branch for sure;
  so these have to be right, and `python -m tools.python.valuediff`
  compares random expressions' values with Python's, in both of zrun's
  modes.
- **What runs it runs.** `os.system`, `subprocess.*`, `os.exec*`,
  `os.spawn*`, `pty.spawn`: resolved as commands, with the folder the code
  moved to, the environment it set (`os.environ[...]`, `env=`), and what
  they read on stdin (`input=`, python's own stdin when the program came
  from `-c`).
- **Imports.** `python -c` puts the current folder first on the module
  path: `import json` runs a `json.py` there if there is one. Each import
  of a module Python hasn't already loaded when it starts is the project's
  code where the code runs (`-I`, `-P`, `PYTHONSAFEPATH`: not); a
  package's that isn't the standard library's, the same. Its functions
  aren't followed (asked), but importing it is allowed where running the
  project's code is (`run project-code in $project`, as `pytest` is).
- **The network.** `urllib`, `requests`, `httpx`, `socket`, `http.client`:
  a connection to its host, sent data where it sends. These are the code's,
  not python's: a rule allowing `python3` doesn't cover them (`Action.inline`),
  the network's rules decide.

## Checked

- The corpus (`corpus/bash/python.toml`, `corpus/harmless/python.toml`),
  decided in both modes (`tests/test_corpus.py`) and run for real in the
  Linux oracle's sandbox: every file, program and delete it touched decided
  no less strictly.
- `python -m tools.oracle.pyfuzz`: programs made to mislead (two names for a
  list, an early return, an exception skipping a line, a closure, a
  generator, a walrus in a comprehension, sorting...), each putting a
  harmful or a harmless value where a command, a path, a program's
  arguments are taken; each program vetter allows is run in the sandbox
  and what it did compared. None did more than vetter allowed.
