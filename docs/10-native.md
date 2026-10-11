# 10. vetter, native

The hook runs before every command an agent runs, and `libvetter` is meant
to be embedded: vetter must be native code, with no Python. It is written
in zrun's strict subset of Python, one codebase run three ways:

- **the CLI** (`vetter check`, `why`, `test`, `lint`, `replay`, `hook`) runs
  it as Python: zrun's reference mode (`engine.py`), nothing compiled, as
  quick to start as Python;
- **the agents' hook and `libvetter`** are compiled ahead of time by
  `zrun.build_native` (`build.py`): no Python in them;
- **the tests** run each part both ways and compare with what's recorded.

## The shape

- **The shells are read at run time** with `rt.parse`: bash and PowerShell
  with their zgram grammars (`shells/bash/bash.zgram`,
  `shells/powershell/grammar.py`), cmd with its scanner written in the
  subset; here-documents, backticks, `--%` by the scanners.
- **The policy is read at run time**: its text (the user's, a project's
  `.vetter.vet`) parsed with `rt.parse` and the language's grammar
  (`policy/policy.zgram`), the prelude and the `use`d policies built in.
  (Compiling each policy into the program, its rules specialized, is left
  for later: deciding is already a few microseconds.)
- **The tables are made when a module is imported** (Python: `tomllib`
  over the specs and cmdlets, the PowerShell grammar's template): constants
  of the compiled code, carried in an executable's image.

## The subset's limits, and what replaces what

| Python has | vetter uses |
|---|---|
| `re` | hand-written scanners and matchers (the log's masks among them: log.py) |
| `fnmatch` | a glob matcher (`glob.py`: `*`, `?`, `[...]`) |
| `json` | `jsontext.py`: read with rt.parse and a JSON grammar, written as `json.dumps` |
| `base64` (`-EncodedCommand`) | a decoder |
| `pathlib` | `paths.py`, `places.py` |
| zgram's `Node` API (`rule()`, `find()`) | zrun's nodes (`rule`, `text`, `children`, `find()`, labelled fields) |
| classes with state | records (dataclasses) and module functions |

What stays Python, the command line's own: its options and output
(`cli.py`), `vetter why`'s display (`policy/trace.py`), `vetter lint`'s
warnings (`policy/checks.py`, zrules over the policy's text), `install`,
`import`. Lint's errors (a place no list names, a `$var` vetter doesn't
know, a list defined twice) are checked natively when a policy loads
(`policy/language.py`), the user's and a project's `.vetter.vet`: such a
policy doesn't load in the CLI, and the hook, compiled too, asks, saying
what's wrong.

Deciding on the machine it runs on (`places.load_policy`), the hook follows
symbolic links that exist (`Policy.follow_links`): `cat keys/id_rsa`, keys
a link to `~/.ssh`, is reading `~/.ssh/id_rsa`.

## Checked

Each test runs its part in both of zrun's modes (the reference and
compiled, strict) and compares with `tests/golden/`: each case's inputs
and the answer, recorded from the Python vetter that came before (the
corpus, the shells' fuzzers' commands, hand-written cases): bash's reading,
expansion and resolution, PowerShell's, cmd's, every decision and every
traced step, every agent's answer byte for byte, the log's masks, paths;
the CLI's output too. `pytest --update-golden` records what vetter gives
now, after a change meant to change it. The hook's test builds the
executable and the library and asks them the same.

## Building

```
python -m vetter.build vetter-hook     # ./vetter-hook claude [--policy FILE]
python -m vetter.build libvetter       # libvetter.so and libvetter.h
```

`build.build(output, target="x86_64-windows")` makes a Windows one from
Linux (zrun.build_native's options; Zig needed: `pip install vetter[build]`).
The hook is one executable of about 11 MB, answering in about 1.7 ms (the
Python one: 74 ms, most of it Python starting); on Windows it reads the
system as Windows does (`USERPROFILE`, PowerShell the agents' shell:
`os.name` read where it runs). It logs as the Python one did (mask() of
log.py, the file 600 in a directory 700).

`libvetter` has zrun's C API (`zrun.h`): `zrun_init(0, NULL)` once, then
`zrun_call("vet", args, 4, &out)` with the command, the shell, the
working directory and the policy file (`""`: the defaults), `out` a str
of JSON: `{"decision", "reason", "rule", "by", "span"}`.

## Notes

Names on Windows compare as Windows and .NET compare them, by each
character's uppercase (`paths.case_key`; PowerShell's `syntax.fold`):
`Remove-ıtem` is Remove-Item, `C:/Wındows` is C:\Windows. zrun's native
`str.upper()` covers all of Unicode, Python's tables.

Compiled, a command is checked (read, resolved, decided by the stock
policy) in about 90 µs for bash (the Python vetter: 250), 90 for cmd
(200), 65 for PowerShell (160); the policy loads in 0.18 ms (0.86). What
made it so, found with `zrun.configure(perf_map=True)` and perf: matching
makes only the matching rule's reason (`Policy.trace` for `vetter why`'s),
resolves each place once a decision and folds program names once; trees
are searched with `node.find` (one pass, natively); a cmdlet's parameter
names are folded once; zrun dispatches methods by number.

A hook's answer takes about 1.6 ms, of which the decision is 0.02: the
rest is the executable starting (an empty one: 0.6 ms) and building its
tables (about 1 MB: the specs, the cmdlets, the built-in policies), most
of it the kernel's page faults. Building them faster didn't help; laying
them out built in the executable would.

Porting found bugs in the Python vetter, fixed then (each a corpus case):
a here-document after `eval` (`eval true; bash <<E`) read in eval's text,
so the shell's input went unseen; an `if`'s condition walked twice (`if cd
src; then rm ../../x; fi` resolved in src/src); byte and character offsets
mixed (any non-ASCII character before a here-document made the command
unreadable); `"$@"` outside word splitting (assignments, here-documents,
`<<<`) joined without spaces, or crashed.
