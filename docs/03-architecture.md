# 3. How it works

```
 agent hook (JSON)          CLI             libvetter.so (C ABI)
        \                    |                     /
         +---------- request: tool, command, cwd, env ----------+
                                   |
                      1. parse      zgram: bash grammar -> exact tree
                                   |
                      2. resolve    executions: what will run, with what
                                   |   (wrappers unwrapped, sh -c recursed,
                                   |    expansions classified, redirections)
                                   |
                      3. decide     compiled policy (zrun, native code)
                                   |
                      4. answer     allow | ask | deny + rule + span
```

## 1. Parse

A zgram grammar of bash (see [04-shell-semantics.md](04-shell-semantics.md)).
The tree keeps every token's position, so a decision can point at the exact
part of the command. What the grammar can't parse exactly is an **unknown**
node, never a guess.

## 2. Resolve

The tree becomes a list of **executions**: each program the command would
start, with its arguments as far as they're known, its working directory,
its environment changes and the files it reads and writes through
redirections.

- `a && b`, `a; b`, `a | b`, `( a )`, `{ a; }`, `if`, `for`, `while`, `case`,
  functions: every simple command inside is an execution.
- Wrappers are unwrapped from a table of known programs: `sudo`, `env`,
  `nice`, `timeout`, `nohup`, `xargs`, `find -exec/-execdir/-ok`,
  `git -c ...`, `bash -c`/`sh -c`/`zsh -c` (parsed again, recursively, with
  a depth limit), `eval` (its argument parsed if it's known).
- `cd`, `pushd` change the working directory of what follows; relative paths
  are resolved against it.
- Expansions are classified: **static** (the word is known: quotes,
  `~`, known variables), **dynamic** (`$(...)`, backticks, unknown variables,
  globs, brace expansion over unknown parts). A substitution is itself a
  command: its executions are checked too.
- Each argument gets a **role** from the command's spec (see 8 in
  [02-goals.md](02-goals.md)): path read, path written, URL, sub-command,
  program to run, option value, plain.

## 3. Decide

The policy ([05-policy-language.md](05-policy-language.md)) is compiled by
zrun into native code, the rules matched against each execution. The
command's decision is the strictest of its executions' (deny > ask > allow);
an unknown part takes the policy's `unknown` decision (ask by default).

## 4. Answer

```json
{"decision": "deny",
 "reason": "no piping downloads into a shell",
 "rule": {"name": "...", "file": "policy.vet", "line": 12},
 "span": {"start": 14, "end": 37},
 "executions": [...]}
```

Each agent adapter turns this into the agent's own format (exit code 2 and
stderr, or its JSON).

## What each zsuite part does

| Part | Role in vetter |
|---|---|
| zgram | the bash grammar; the policy language's grammar |
| zrules | checking policies: types, unknown commands/flags, dead and shadowed rules, conflicts; running a policy's tests at load time |
| zrun | compiling the policy and the resolver to native code; the CLI, `libvetter.so` and the hooks as standalone binaries with no Python (`build_native(shared=True)`) |
| zlsp | the policy editor: errors as you type, completion of commands and flags from the specs, hover showing what a rule matches |

## Deliverables

- `vetter` — CLI: `check`, `explain`, `test`, `lint`, `hook <agent>`,
  `import <claude|codex>`.
- `libvetter.so` / `vetter.dll` — C API (`vetter_load`, `vetter_check`,
  `vetter_free`), bindings for Python, Node, Go, Rust.
- Hook binaries per agent, installed by `vetter install <agent>`.
- A stock policy that's useful on day one.
