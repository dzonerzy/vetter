# The policy language

A vetter policy is a list of rules that say what an agent may do, written
about **what a command does** rather than how it's spelled. A rule fits on a
line and reads like a sentence:

```
deny  "deleting outside the project"   delete outside $project, $temp
allow "git, locally"                   git status, log, diff, commit
ask   "network"                        network
```

The same policy decides bash, PowerShell and cmd.exe commands, and the
Python code given to `python -c`.

## A whole policy

```
policy mine

default ask                 # what no rule decides
unknown ask                 # what vetter can't see, if no rule names it

let deploy_hosts = deploy.example.com, *.deploy.example.com

deny  "production"           network to prod.example.com
allow "our deploy script"    run $project/scripts/deploy.sh
allow "deploying"            network to deploy_hosts
ask   "containers"           docker, podman

use stock                    # the stock policy's rules, lists and tests

tests
  deny   curl -s https://prod.example.com/x
  allow  ./scripts/deploy.sh --dry-run
  ask    docker ps
  deny   [powershell] Remove-Item -Recurse -Force ~/project
```

The pieces, in any order:

| Statement | Meaning |
|---|---|
| `policy NAME` | the policy's name |
| `default allow\|ask\|deny` | the decision for an action no rule matches (default: `ask`) |
| `unknown allow\|ask\|deny` | the decision for what vetter can't see, when no rule names it (default: `ask`) |
| `log on\|off` | whether the hook logs its decisions (default: `on`) |
| `let NAME = PLACE, ...` | a named list of places or hosts |
| `use NAME` | another policy's rules, lists and tests (`stock`) |
| `drop "REASON"` | removes a used policy's rule, by its reason |
| `DECISION ...` | a rule |
| `tests` | test commands, one per line, until the end |

Comments start with `#`.

## Rules

```
DECISION ["REASON"] MATCH [unless CONDITION, ...] [with CONDITION, ...]

DECISION ["REASON"] {
  MATCH [unless ...]        # one per line: any of them
  MATCH ...
}
```

`DECISION` is `allow`, `ask` or `deny`. The reason is what the agent and you
read when the rule decides. Without one, the rule's text is used.

## What a rule matches

### Actions

Every command is broken into actions (see
[How vetter works](how-it-works.md#3-decide)):

| Match | Matches |
|---|---|
| `read`, `write`, `delete` | reading, writing or deleting a file |
| `run` | running a program |
| `network` | talking to a host in any way: covers `download` and `send` |
| `download` | fetching from a host |
| `send` | sending local data to a host (a file, a pipe, the environment) |
| `any` | any action |

An action alone matches it anywhere. Add **places** to say where:

```
deny  write startup                       # anywhere in the startup list
allow write in $project, $temp            # in the project or a temp dir
deny  delete outside $project, $temp      # anywhere else
deny  delete exactly $project, $home, /   # those folders themselves
deny  run in $temp                        # a program or script from a temp dir
```

- `in X` (or just `X`): X or anything under it.
- `outside X`: neither X nor anything under it.
- `exactly X`: X itself, not what's in it.

For the network, name hosts with `to` and `from`:

```
allow network to api.example.com
allow download from registries
deny  send unless host registries
```

### What vetter can't see

`run` with a kind matches the parts vetter can't see into:

| Match | Matches |
|---|---|
| `run unknown` | a command only running tells (`eval "$CMD"`, `$(cat cmd)`) |
| `run script` | a script file run (`bash deploy.sh`, `python3 tools/gen.py`) |
| `run inline` | code in a language vetter doesn't read (`node -e '...'`) |
| `run package` | a package fetched and run (`npx tool`) |
| `run project-code` | the project's own code run by a tool (`make`, `npm test`, `pytest`) |
| `run downloaded` | a file the command downloaded, then ran |
| `run generated` | a file the agent wrote (in this command, an earlier one, or with its editing tools), then ran |
| `run configured` | something set up to run later (`git config core.pager ...`) |
| `run injected` | code put in through the environment (`LD_PRELOAD`, `BASH_ENV`) |

These take places too: `run script in $project`.

### Programs

A program's name, then its subcommands, as many levels as needed. Commas
list alternatives at a level:

```
allow git status, log, diff
allow npm run test, lint
allow az account show, list
ask   docker
```

A program allowed by name is allowed to run, and to use the network on its
own (`git fetch`). What it reads, writes and deletes is still decided by
the rules about places: `allow gcc` doesn't allow `gcc -E /etc/shadow` to
read `/etc/shadow`. The network that Python code asks for (`python -c`) isn't
python's own: the network rules decide it. A `deny` or `ask` naming a
program covers everything it does.

Programs are matched by name whatever their path (`/usr/bin/git` is
`git`), and Windows names as Windows compares them (`Remove-Item`,
`remove-item`).

### Groups

A list's name stands for its programs. The built-in groups
(`vetter/policy/builtin/prelude.vet`):

| Group | Programs |
|---|---|
| `shell` | sh, bash, zsh, dash, ksh, fish, pwsh, powershell, cmd, Invoke-Expression |
| `builtin` | cd, echo, export, test, read, Set-Location, Write-Output, ... |
| `wrapper` | env, command, exec, eval, time, timeout, nice, nohup, xargs, watch, Start-Process, ... |
| `text` | sed, awk, grep, jq, head, tail, sort, diff, wc, sha256sum, ... |
| `elevated` | sudo, doas, su, pkexec, runas, gsudo |
| `interpreter` | python, python3, node, deno, bun, perl, ruby, php, lua, cscript, wscript, mshta |
| `downloader` | curl, wget, fetch, aria2c, Invoke-WebRequest, Invoke-RestMethod, bitsadmin, certutil |

### Pipelines

`A | B` matches B when A's output is piped into it, directly or through
other commands (`curl ... | tee log | sh`):

```
deny "a download piped into a shell"   downloader | shell, interpreter, source
```

`python -c CODE` doesn't count as running what's piped into it: its program
is the code, which vetter reads, and what the code does with its input is
decided on its own.

## Places

| Place | Meaning |
|---|---|
| `$project` | the project the agent works in |
| `$home` or `~` | your home folder |
| `$temp` | the temporary folders: `/tmp`, `/var/tmp`, `C:/Windows/Temp`, `~/AppData/Local/Temp`, and `TMPDIR`, `TEMP`, `TMP` |
| a list's name | a `let` in your policy, the stock policy or the prelude |
| a path | `~/.ssh`, `/etc`, `C:/Windows`, `HKCU:/Software/...` |
| a pattern | `$project/{build,dist}`, `*.log`, `$project/*/__pycache__` |

**The project** is the workspace the agent was opened in, when the agent
tells its hook (Claude Code's `CLAUDE_PROJECT_DIR`, Cursor's and Copilot's
workspace roots) and the command runs inside it. Otherwise it's the nearest
folder up from the working directory that has a `.git` or a `.vetter.vet`,
never the home folder itself. Failing that, it's the working directory.

A path vetter can't know before the command runs (`rm -rf "$X"`) is in no
place. It counts as outside every place only where that keeps an allow from
applying (`allow download unless outside $project`). So a rule never denies
on a guess: the action is asked instead.

A bare relative path is an error (`project/x` is ambiguous: write
`./project/x` if you mean a folder named project).

## Conditions

`unless` takes a rule's exceptions, `with` its requirements:

```
allow git log unless --output, --ext-diff
allow git branch with --list
```

| Condition | True when |
|---|---|
| `--flag`, `-r` | the command has that option (`-rf` has `-r`; `--del` is `--delete`) |
| `host X` | every host it talks to is X, or in list X |
| `via X` | it runs through that wrapper or shell (`via sudo`) |
| `dynamic` | one of its arguments is only known when it runs |
| `in X`, `outside X`, `exactly X` | every path it touches is (not) in X |

## How a command is decided

1. vetter breaks the command into **parts**: each program it runs, and each
   thing vetter can't see. Each part is a list of **actions**.
2. **Each action goes down the rules; the first rule that matches it
   decides.** A rule about `read` can't decide a `delete`.
3. An action no rule matches gets the `default` decision (`unknown` for what
   vetter can't see).
4. A program vetter has a spec for, which no rule names, is decided by what
   it does: `ls` is allowed by `allow read in $project`, `rm x` by the rules
   about deleting `x`.
5. A part takes its strictest action's decision, and the command takes its
   strictest part's: deny, then ask, then allow. The reason shown is that
   action's rule, pointing at its place in the command.

A command vetter can't read exactly (it isn't valid in its shell, or its
reading isn't certain) gets the `unknown` decision.

## Composing policies

```
policy mine
allow "our deploy script"  run $project/scripts/deploy.sh
use stock
```

`use` puts the used policy's rules where it stands, but **a used policy's
deny rules always come first**, so a rule written before `use` can't weaken
them by accident. To remove one, name it after the `use`:

```
use stock
drop "programs from temporary dirs"
```

Which policy is used: `--policy FILE` if given, else
`~/.config/vetter/policy.vet`, else the stock policy.

### A project's `.vetter.vet`

A project can add rules in a `.vetter.vet` at its root, or in a folder above
it (not past your home). Its deny rules go before everything, its ask rules
right after the used policies' denies. **Its allow rules are ignored** and
reported: the agent can write that file, so it mustn't be able to allow
itself anything.

## Tests

Test lines go at the end, after `tests`: a decision, then a command. A
`[powershell]` (or `[ps]`) or `[cmd]` tag reads the command as that shell:

```
tests
  allow  git status && npm test
  deny   x=rm; $x -rf ~/work
  ask    rm notes.txt
  deny   [cmd] rd /s /q %USERPROFILE%\project
```

`vetter test` runs them, and the used policies' tests too. `vetter test
--coverage` lists the rules no test reaches.

## Checked when it loads

A policy that has any of these doesn't load (the hook then asks about
everything, saying why):

- a rule an earlier one hides (it can never decide anything);
- a list that isn't defined;
- a `drop` of a rule that isn't there;
- a syntax error.

`vetter lint` also reports likely mistakes without failing: programs,
subcommands and options no spec knows (`git stauts`), and lists defined but
never used.

## Debugging

- `vetter why COMMAND`: how the command was read (what each word became),
  each part's actions, and the rule that decided each.
- `vetter why --all COMMAND`: every rule tried before, and why it didn't
  match. The answer to "why didn't my rule fire?".
- `vetter why --rule LINE COMMAND`: only that rule, and which piece of it
  fails.
- `vetter replay --policy new.vet`: the commands in your log decided by
  another policy, listing what would change.

A failing test shows its full trace.
