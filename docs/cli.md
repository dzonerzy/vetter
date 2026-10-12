# Command line

```
vetter check | why | test | lint | import | replay | learn | hook | install
```

Commands that decide take `--policy FILE` (default:
`~/.config/vetter/policy.vet`, else the stock policy), `--cwd DIR` (where
the command runs; default: here), `--home DIR` (default: yours) and
`--shell bash|powershell|cmd` (default: bash).

## `vetter check COMMAND`

Decides about a command and prints the decision, its reason and rule, and
the part of the command it's about.

```console
$ vetter check 'rm -rf ~'
deny: deleting outside the project: /home/u is outside $project, $temp [stock.vet:35]
   rm -rf ~
   ^^^^^^^^
```

The exit code is the decision: `0` allow, `1` ask, `2` deny.

`--json` prints the whole decision: `decision`, `reason`, `rule` (file and
line), `by` (`rule`, `default`, `unknown`, or `nothing` when nothing runs),
`span` (start and end in the command), and `parts`, each with its actions
and how each was decided.

## `vetter why COMMAND`

How the command was read and decided: the words that changed while reading
it (`$x` → `rm`, `~` → `/home/u`), each part's actions, and the rule that
decided each.

- `--all`: every rule tried before the deciding one, and why it didn't
  match.
- `--rule LINE`: only the rule at that line of the policy, and which piece
  of it fails.

## `vetter test`

Runs the policy's tests, and those of the policies it uses:

```console
$ vetter test --policy mine.vet
107/107 tests pass (30 rules)
```

A failing test prints its full trace. `--coverage` lists the rules no test
reaches.

## `vetter lint`

Reports a policy's likely mistakes without running it: programs,
subcommands and options vetter doesn't know (with a suggestion), lists
never used, rules never reached.

```console
$ vetter lint --policy mine.vet
mine.vet:2:11: git has no subcommand stauts that vetter knows: did you mean status?
mine.vet:4:5: let unused is never used
```

`--project` lints this directory's project policy (`.vetter.vet`) together
with your policy.

## `vetter import claude|codex`

Turns an agent's permission rules into a vetter policy: Claude Code's
`permissions` (`Bash(npm run test:*)`), or Codex's `.rules` files. The
imported rules come first, then `use stock`.

- `--from SOURCE`: the agent's settings file (claude), or a `.rules` file
  or folder (codex). Default: the agent's user settings.
- `-o FILE`: write the policy there instead of printing it. `--force`
  replaces an existing file.

## `vetter replay`

Decides each command in the log with a policy, and lists those decided
differently from when they were logged, with both reasons:

```console
$ vetter replay --policy new.vet
ask -> allow   terraform validate
   was: default
   now: learned: terraform validate [policy.vet:4]
```

- `--log FILE`: another log. Default: `~/.local/state/vetter/log.jsonl`.
- `--limit N`: only the last N commands.

## `vetter learn`

Suggests rules from the asks you said yes to (see
[Agents](agents.md#learning-from-your-answers)).

- `--min N`: how many yeses a suggestion needs (default 2).
- `--apply all` or `--apply 1,3`: add those suggestions to the policy.
- `--policy FILE`: the policy to add them to.
- `--log FILE`: another log.

## `vetter install AGENT`

Registers vetter's hook in an agent's settings: `claude`, `codex`, `gemini`,
`cursor`, `copilot`, `vscode`, `cline`, `amp`, `opencode`.

- `--dry-run`: show the change, don't write it.
- `--settings FILE`: write another settings file.

## `vetter hook AGENT`

The hook itself, as agents run it: the agent's request on standard input,
the answer on standard output in the agent's format. `json` is vetter's own
format for other harnesses: `{"command", "cwd", "shell"}` in, `{"decision",
"reason", "default"}` out.

```console
$ echo '{"command": "rm -rf ~", "cwd": "/home/u/p"}' | vetter hook json
{"decision": "deny", "reason": "vetter: deleting outside the project: ...", "default": false}
```
