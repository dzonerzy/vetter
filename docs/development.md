# Development

## Layout

```
vetter/                  the package, in zrun's strict subset of Python
  cli.py                 the command line (plain Python)
  engine.py              runs vetter's code through zrun: as Python (the CLI), compiled (tests, builds)
  build.py               the standalone hook and libvetter
  check.py               a command: read, resolve, decide
  places.py              the home, the policy, the project, $temp on this machine
  gitconfig.py           what a repository's git config makes git run
  toolconfig.py          what a tool's config in the project makes it run
  paths.py, glob.py      POSIX and Windows paths; fnmatch's patterns
  jsontext.py            JSON read and written
  shells/bash/           bash.zgram, scan.py (here-documents), syntax.py, expand.py, resolve.py
  shells/powershell/     grammar.py, syntax.py, values.py, cmdlets.py, resolve.py
  shells/cmd/            syntax.py, resolve.py
  shells/python/         python.zgram, scan.py, syntax.py, resolve.py, stdlib.py
  specs/                 what programs do with their arguments: *.toml, load.py, the engine
  policy/                policy.zgram, language.py, actions.py, checks.py (lint), trace.py; builtin/
  agents/                hook.py, log.py, install.py, importing.py, learn.py, written.py
corpus/                  the bypass corpus: bash/, powershell/, cmd/, harmless/
tests/                   pytest; golden/ holds the recorded answers
tools/                   run with python -m tools.<dir>.<tool>
  corpus/                the corpus decided and resolved
  oracle/                commands run for real: Linux (bubblewrap, strace), Windows (from WSL); fuzzers
  bash/, powershell/     differential testing and fuzzing against the real shells
  python/                Python's grammar against CPython's; computed values against Python's
  compare/               dcg, cc-safety-net and tree-sitter-bash on the same commands
docs/                    this documentation
```

## The strict subset

vetter runs as Python for the CLI and compiles to native code for the hook
and the library, through [zrun](https://github.com/dzonerzy/zsuite). Code
under `vetter/` (except `cli.py`, `policy/checks.py`, `policy/trace.py`,
`agents/install.py`, `agents/importing.py` and `agents/learn.py`, which only
the CLI runs) must stay in zrun's strict subset:

| Python has | vetter uses |
|---|---|
| `re` | hand-written scanners and matchers |
| `fnmatch` | `glob.py` |
| `json` | `jsontext.py`: read with `rt.parse` and a JSON grammar |
| `pathlib` | `paths.py`, `places.py` |
| classes with behavior | records (dataclasses) and module functions |
| grammars' Python node API | zrun's nodes: `rule`, `text`, `children`, `find()` |

In practice:

- `rt`, the runtime, is passed as the first parameter to any function that
  parses.
- Function-level imports go at the top of the function, not inside a branch.
- Module-level tables are literals or built when the module is imported.
  They're constants of the compiled code.
- Prefer the constructs the codebase already uses. zrun reports anything
  outside the subset when it compiles, with the place and the reason.

The tests run every part in both of zrun's modes, so a compile error or a
difference between Python and compiled code shows up as a test failure.

Don't edit sources while a compile is running in the background (for
example `pytest --build`): it compiles a half-edited tree and fails with a
spurious `zrun.CompileError`.

## Tests

```console
$ pip install '.[test]'
$ pytest                  # in parallel; both of zrun's modes
$ pytest tests/test_check.py
$ pytest --build          # also the standalone hook and libvetter (minutes; Zig needed)
$ pytest --oracle         # also the oracles (bubblewrap, strace; Windows from WSL)
```

Most tests compare what vetter gives with **recorded answers** in
`tests/golden/`: the reading, expansion and resolution of each shell, every
decision and traced step, every agent's answer byte for byte, the log's
masks, and the CLI's output. Each test asks the compiled code and the Python
code the same questions.

When a change is meant to change answers:

1. Run `pytest --update-golden` to record what vetter gives now.
2. Review what changed. Decisions that flipped matter most: a deny becoming
   an allow needs a reason.
3. `--update-golden` rewrites every file (gzip timestamps). Restore the ones
   whose content didn't change with `git checkout`.

The CLI's recorded output (`tests/golden/cli.json.gz`) is checked by
`tests/test_cli.py`.

`tests/test_corpus.py` decides the whole corpus in both modes, checking
every case against its `expect` and that the two modes agree.

## Adding a corpus case

Add a `[[case]]` to the file for its family under `corpus/`:

```toml
[[case]]
id = "unique-id"
shell = "bash"
command = "the command"
runs = ["the", "programs", "it", "runs"]
expect = "deny"            # allow, ask or deny, with the stock policy
why = "what it shows"
source = "https://..."     # or "derived"
```

Then:

```console
$ python -m tools.corpus.decide_corpus          # ALLOWED and noise must stay 0
$ python -m tools.corpus.resolve_corpus         # every program in `runs` found
$ python -m tools.oracle.linux --only unique-id --all
```

## Adding a command spec

Programs' arguments are described in `vetter/specs/*.toml`; see
[`vetter/specs/README.md`](../vetter/specs/README.md) for every key and
role. A new spec should be `strict` where the program has options that run
code or write files, so an option the spec doesn't list is unknown instead
of being assumed harmless.

## Changing the stock policy

`vetter/policy/builtin/stock.vet` has its tests at the end. Add a test for
each behavior you change, then:

```console
$ vetter test --policy vetter/policy/builtin/stock.vet
$ python -m tools.corpus.decide_corpus
$ python -m tools.compare.guards --dcg PATH --ccsn PATH --dcg-corpus DCG_TREE
```

The comparison shows the change's effect on attacks stopped and harmless
commands asked about, on dcg's corpus as well as vetter's.

## Before a release

- `pytest`, `pytest --build`, `pytest --oracle`
- `python -m tools.corpus.decide_corpus`: no `ALLOWED`, no noise
- `python -m tools.oracle.linux --all` and `--mutate`
- `python -m tools.oracle.pyfuzz -n 1500`
- `python -m tools.python.pydiff` after a change to the Python grammar
