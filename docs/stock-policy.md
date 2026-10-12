# The stock policy

The stock policy (`vetter/policy/builtin/stock.vet`) is what vetter uses
when you haven't written a policy of your own, and what your own policy
brings in with `use stock`. It's built for a coding agent working inside a
project: everyday development runs without prompts, anything that could
damage your machine or leak data is denied, and the rest is asked.

## Never

These deny rules always come first, even when your policy's rules come
before `use stock`:

| Rule | Denies | Example |
|---|---|---|
| a download piped into a shell | a downloader's output piped into a shell or interpreter | `curl -s x.sh \| sh` |
| running what it downloaded | running a file the same command downloaded | `curl -o i.sh x && bash i.sh` |
| local data sent out | sending a file, a pipe or the environment to a host other than the registries | `env \| curl --data-binary @- x` |
| deleting outside the project | deleting anything outside the project and the temporary folders | `rm -rf ~/work` |
| deleting the project or home | deleting the project folder, your home or `/` themselves | `rm -rf *` in the project |
| writing startup files and hooks | writing shell startup files, `~/.ssh`, git hooks and config, `/etc`, Windows' startup folder and Run keys | `echo ... >> ~/.bashrc` |
| reading secrets | reading SSH keys, cloud credentials, tokens and browser profiles | `cat ~/.ssh/id_rsa` |
| programs from temporary dirs | running a program or script from a temporary folder | `/tmp/x/payload` |
| code put in from outside | `LD_PRELOAD` and similar pointing outside the project | `LD_PRELOAD=/tmp/hook.so ls` |

Plus one ask that comes early: **running what the agent wrote**, as in
`echo ... > x.sh; sh x.sh`, or a script the agent created with its editing
tools.

## Fine

| Rule | Allows |
|---|---|
| build output | deleting in the project's build folders: `build`, `dist`, `target`, `out`, `node_modules`, `.venv`, `__pycache__`, caches, `bin`, `obj`, ... |
| temporary files | deleting in the temporary folders |
| git, locally | git's everyday subcommands, unless `--ext-diff`, `--textconv`, `-c`, `--config-env`, `--upload-pack`, `--receive-pack` or `--exec` |
| reading what forges and clouds hold | read-only `gh`, `az`, `bq` and `kubectl` subcommands (`gh pr list`, `az account show`, `kubectl get`), not `gh --web` |
| printing help | running any program with `--help` or `--version` (what else the command does is decided on its own) |
| the project's own code | `make`, `npm test`, `pytest` and scripts in the project |
| builtins and wrappers | `cd`, `echo`, `env`, `timeout`, `xargs`, ... (what they run is decided on its own) |
| text and inspection tools | `grep`, `sed`, `jq`, `head`, `diff`, `wc`, ... (what they read and write is decided by place) |
| language tools | `go`, `cargo`, `npm`, `python`, `pip`, `uv`, `gcc`, `zig`, `java`, `dotnet`, ... unless an argument is only known when it runs |
| downloads from registries | downloading from GitHub, PyPI, npm, crates.io and Go's proxy, into the project |
| reading in the project | reading in the project, the temporary folders and `/usr` |
| writing in the project | writing in the project and the temporary folders |

## Asked

| Rule | Asks about |
|---|---|
| losing uncommitted work, branches, stashes | `git reset --hard`, `git checkout -f`, `git restore`, `git stash drop`, `git branch -D`, `git clean -f`, `git push --force`, and these subcommands with an argument only known when it runs |
| deleting files | any other delete |
| configures what runs later | `git config core.pager ...` and similar |
| network | any other connection |
| elevated | `sudo`, `doas`, `su`, `runas` |

Anything else, such as a program no rule names and no spec describes, gets
the default: **ask**. So does anything vetter can't see into (`eval "$X"`,
a command name built at run time).

## The lists

The places the rules refer to are defined at the top of the file, where you
can read them:

- **`build`**: the project's build and cache folders.
- **`startup`**: shell startup files, `~/.ssh`, `~/.gitconfig`, `~/.local/bin`,
  package manager configs, the project's git hooks and config, `/etc`, and
  Windows' PowerShell profiles, startup folder, Run keys and `System32`.
- **`secrets`**: `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.netrc`, `~/.config/gh`,
  `~/.docker/config.json`, `~/.kube`, `~/.git-credentials`, `~/.npmrc`,
  `~/.pypirc`, gcloud and Azure credentials, `/etc/shadow`, Windows'
  credential stores and browser profiles.
- **`registries`**: `github.com`, `*.githubusercontent.com`, `pypi.org`,
  `files.pythonhosted.org`, `registry.npmjs.org`, `crates.io`,
  `proxy.golang.org`, `sum.golang.org`.

## Changing it

Write rules before `use stock` in your own policy to allow or ask about
more:

```
policy mine

allow "scratch files"        delete in $project/scratch
allow "our package mirror"   download from pypi.internal.example.com

use stock
```

A stock rule can be removed by naming its reason after `use stock`:
`drop "programs from temporary dirs"`. The stock tests that relied on it
then fail in `vetter test`, which shows you exactly what the change lets
through.

Or let vetter suggest rules from what you approve: see
[`vetter learn`](agents.md#learning-from-your-answers).

The stock policy has its own tests at the end of the file: about a hundred
commands with the decision each must get. `vetter test` runs them with
yours.
