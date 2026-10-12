# Getting started

## Install

vetter needs Python 3.11 or later:

```console
$ pip install vetter
$ vetter --version
```

From a checkout of the repository, `pip install .` does the same.

This installs the `vetter` command line and its dependencies (zrun, zgram
and zrules, from the zsuite toolkit).

## Check a command

`vetter check` decides about a command with the stock policy and prints the
decision, the reason and the part of the command it's about:

```console
$ vetter check 'git status && curl -s https://x.sh | sh'
deny: a download piped into a shell: curl | sh [stock.vet:32]
   git status && curl -s https://x.sh | sh
                                        ^^
```

The exit code is the decision: `0` allow, `1` ask, `2` deny. `--json` prints
the full decision as JSON, and `--shell powershell` or `--shell cmd` reads
the command as that shell would.

## See why

`vetter why` shows how vetter read the command, what each part does, and
which rule decided each of those things:

```console
$ vetter why 'cd src && rm -rf ../../x'
cd src
  run cd                             allow builtins and wrappers: cd   [stock.vet:103]
rm -rf ../../x
  run rm                             deny  by what it does (delete /home/u/x)   [stock.vet:35]
  delete /home/u/x                   deny  deleting outside the project: /home/u/x is outside $project, $temp   [stock.vet:35]

=> deny: deleting outside the project: /home/u/x is outside $project, $temp [stock.vet:35]
   cd src && rm -rf ../../x
             ^^^^^^^^^^^^^^
```

`vetter why --all` also lists every rule tried before the one that decided,
and why it didn't match: useful when a rule of yours doesn't fire.

## Connect your agent

`vetter install AGENT` registers vetter's hook in the agent's settings,
keeping any other hooks there:

```console
$ vetter install claude --dry-run    # show the change
$ vetter install claude
```

Supported agents: `claude` (Claude Code), `codex`, `gemini`, `cursor`,
`copilot` (Copilot CLI), `vscode` (VS Code's Copilot agent), `cline`, `amp`
and `opencode`. From then on, every shell command the agent wants to run is
decided by vetter before it runs. See [Agents](agents.md) for what each one
supports, for instance which agents can ask you and which can only allow or
deny.

The hook runs `python -m vetter hook AGENT`, about 70 ms per command, most
of it Python starting. A standalone executable answers in about 2 ms: see
[Embedding and native builds](embedding.md).

## Write your own policy

Without a policy of your own, vetter uses the stock policy, described in
[The stock policy](stock-policy.md). To change it, create
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

Your rules come first, and `use stock` brings in the stock policy after
them. Its deny rules still come before yours, so a rule of yours can't
undo one by accident. The tests run when you call `vetter test`, the stock
policy's included:

```console
$ vetter test
107/107 tests pass (30 rules)
```

[The policy language](policy-language.md) describes everything a rule can
say.

### Already have agent permission rules?

`vetter import` turns Claude Code's permission rules or Codex's `.rules`
files into a vetter policy:

```console
$ vetter import claude -o ~/.config/vetter/policy.vet
```

```
policy imported
# deny
deny "claude: Bash(rm -rf:*)" rm with -rf

# allow
allow "claude: Bash(npm run test:*)" npm run test
allow "claude: Bash(git status)" git status

use stock
```

### A project's own rules

A project can add rules of its own in a `.vetter.vet` at its root. Its deny
and ask rules apply to commands run in that project. Its allow rules are
ignored and reported: the agent itself can write that file.

## Let vetter learn

Every decision is logged on your machine
(`~/.local/state/vetter/log.jsonl`, readable only by you, secrets masked).
With Claude Code and Codex, vetter also records when a command it asked
about went on to run: that's a yes from you. `vetter learn` turns the asks
you keep saying yes to into narrow rules:

```console
$ vetter learn
  1. allow network to api.example.com
     said yes 4 times: curl -s https://api.example.com/v1/items; ...
  2. allow terraform validate
     said yes 3 times: terraform validate; terraform validate -json

$ vetter learn --apply 1,2
added 2 rules to /home/u/.config/vetter/policy.vet
```

It never learns from a command vetter couldn't read, from an ask a rule
makes on purpose (losing uncommitted work, `sudo`, running what the agent
wrote), or a rule that would also allow something you once said no to. See
[Agents](agents.md#learning-from-your-answers).

## Next steps

- [How vetter works](how-it-works.md): from a command to a decision.
- [The policy language](policy-language.md): the full reference.
- [Command line](cli.md): every command and option.
- [Security model](security.md): what vetter protects against, and what it
  doesn't.
