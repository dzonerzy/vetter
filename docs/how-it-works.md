# How vetter works

```
  agent hook (JSON)          vetter CLI            libvetter (C ABI)
          \                      |                      /
           +-------- command, shell, working directory ---------+
                                 |
                  1. read        the shell's grammar: an exact tree
                                 |
                  2. resolve     what will run, with which arguments,
                                 |  where, with what environment and input
                                 |
                  3. decide      each action through the policy's rules
                                 |
                  4. answer      allow | ask | deny, the rule, the span
```

## 1. Read

The command is parsed with a grammar of its shell: bash, PowerShell or
cmd.exe. Each grammar is written for [zgram](https://github.com/dzonerzy/zsuite)
and checked against the real shell: differential testing against bash 5.2,
PowerShell's own parser, and commands run on cmd.exe (see
[Reading commands](reading-commands.md)).

The tree keeps every token's position, so a decision can point at the exact
part of the command it's about. A command vetter can't read exactly is
never guessed at: it is *unknown*, and the policy decides (ask, by
default).

## 2. Resolve

The tree becomes a list of **executions**: each program, builtin or
function the command would run, with its arguments as far as they're
known, its working directory, its environment and its standard input.

- **Every command inside.** `a && b`, `a; b`, `a | b`, subshells, groups,
  `if`, `for`, `while`, `case` and functions are walked, each simple command
  an execution.
- **Wrappers unwrapped.** `sudo`, `env`, `timeout`, `nice`, `nohup`, `xargs`,
  `find -exec`, `git -c core.pager=...`, and others, from the command specs.
- **Code run from strings, read again.** `bash -c`, `sh -c`, `eval`,
  `source`, here-documents and here-strings fed to a shell, PowerShell's
  `-EncodedCommand` and `Invoke-Expression`, `cmd /c`, and Python's
  `python -c` code: each is read as its own command, recursively.
- **The shell's state followed.** `cd`, `pushd` and `popd` move later
  commands; variables, `export`, `alias`, `hash -p` and `set -a` change what
  later commands mean.
- **Expansions classified.** A word is *known* (quotes, `~`, variables set
  earlier) or *dynamic* (`$(...)`, unknown variables, globs). A substitution
  is itself a command, decided too.
- **Arguments given roles.** A [command spec](../vetter/specs/README.md)
  says what each program does with its arguments: which are files it reads,
  writes or deletes, which are URLs, which are programs or code it runs
  (`git --output`, `find -delete`, `tar --to-command`, `rsync -e`).

## 3. Decide

Each execution becomes a **part** made of **actions**:

| Action | Meaning |
|---|---|
| `run` | the program itself |
| `read`, `write`, `delete` | each file, as an absolute path |
| `network`, `download`, `send` | each host it talks to |

What vetter can't see is a part of its own, a `run` of a named kind:

| Kind | Example |
|---|---|
| `unknown` | `eval "$CMD"`, a command name only running tells |
| `script` | `bash deploy.sh`, `python3 tools/gen.py` |
| `inline` | code in a language vetter doesn't read (`node -e`) |
| `package` | `npx some-package`, `uvx tool` |
| `project-code` | `make`, `npm test`, `pytest`: the project's own code |
| `downloaded` | a file this command downloaded, then ran |
| `generated` | a file the agent wrote, then ran |
| `configured` | something configured to run later (`git config core.pager`) |
| `injected` | code put in through the environment (`LD_PRELOAD`, `BASH_ENV`) |

Each action goes down the policy's rules, and the first that matches it
decides. A part takes its strictest action's decision, and the command its
strictest part's: deny, then ask, then allow. See
[The policy language](policy-language.md#how-a-command-is-decided).

### On the machine it runs on

When vetter decides inside an agent's hook, it also looks at the machine:

- **Symbolic links are followed.** `cat keys/id_rsa`, where `keys` links to
  `~/.ssh`, reads `~/.ssh/id_rsa`.
- **Tools' configuration files are read.** A repository's `.git/config`
  naming a pager or an fsmonitor, `.cargo/config.toml` naming a
  `rustc-wrapper`, `.npmrc`'s `script-shell`, `.yarnrc.yml`'s `yarnPath`:
  what they make the command run is decided as part of it.
- **What the agent wrote is remembered.** A script or a `Makefile` the agent
  wrote with its editing tools, or in an earlier command, is `generated`
  when something runs it later.

## 4. Answer

The decision comes back with its reason, the rule that made it, and the
span of the command it's about:

```json
{"decision": "deny",
 "reason": "deleting outside the project: /home/u is outside $project, $temp",
 "rule": {"file": ".../stock.vet", "line": 35},
 "by": "rule",
 "span": {"start": 0, "end": 8},
 "parts": [ ... ]}
```

Each agent's hook turns it into that agent's format. Agents whose hooks
can't ask get an ask as a deny, with a reason that says so (see
[Agents](agents.md)).

## Built on zsuite

| Part | What it does for vetter |
|---|---|
| [zgram](https://github.com/dzonerzy/zsuite) | the grammars: bash, PowerShell, Python, the policy language, JSON |
| [zrules](https://github.com/dzonerzy/zsuite) | `vetter lint`: checks over policies |
| [zrun](https://github.com/dzonerzy/zsuite) | runs vetter's code: as Python for the CLI, compiled to native code for the hook and the library |
| [zlsp](https://github.com/dzonerzy/zsuite) | the policy editor (planned) |

vetter is written in zrun's strict subset of Python, so the same code runs
as Python and compiles ahead of time into a standalone executable and a
shared library with no Python in them. Compiled, a command is read,
resolved and decided in about 90 µs. See
[Embedding and native builds](embedding.md).
