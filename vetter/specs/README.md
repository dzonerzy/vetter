# Command specs

What a program's arguments are, so vetter knows what a command does with
them: one TOML file per program (or family).

```toml
name = ["git"]                 # the program's names
values = ["-C", "-c"]          # options taking a value (the rest are flags): this program's own, never
                               # one whose value is optional (--color[=WHEN]): a flag listed hides the
                               # operand after it (cat -n /flag read as -n's value)
operands = "plain"             # what its operands are (see roles)
subcommands = true             # the first operand selects a [sub.NAME]
commands = ["status", "log"]   # every subcommand it has (the policies' checks: `git pussh`)
stop_at_operand = false        # options end at the first operand (`ssh host cmd -x`)
slash_options = false          # Windows' /i, /G:file are options
stdin_program = false          # with no program operand, it runs its stdin (python, node, perl)
attached = ["-o"]              # options whose value can be glued on (-oapp, -javaagent:x.jar)
response_files = false         # @file is more arguments, read from it
pattern_options = ["-e", "-f"] # given one, the first operand isn't a pattern: all have the role after it (grep)
[anywhere]                     # options before or after the subcommand (cargo --config)
"--config" = "configured"

[roles]                        # the role of an option's value
"-c" = "git_config"
"-C" = "cwd"

[flags]                        # flags that make it run something set elsewhere
"--ext-diff" = "runs diff.external or GIT_EXTERNAL_DIFF"

[sub.log]                      # a subcommand: the same keys
values = ["--output"]
[sub.log.roles]
"--output" = "write"
```

## Roles

| Role | The value is | vetter does |
|---|---|---|
| `write` / `read` / `delete` | a file it writes / reads / deletes | the policy sees it (`writes`, `reads`, `deletes`) |
| `url` | a URL it talks to | the policy sees it (`urls`) |
| `cwd` | the directory it works in | relative paths resolved there |
| `shell` | a shell command it runs (`sh -c`) | read and resolved like one |
| `cmdline` | a command line it runs, split into words | read and resolved like one |
| `program` | a program it runs | an execution of it |
| `code_file` | a file whose code it runs | an Unknown (its content isn't known) |
| `package` | a package it fetches and runs | an Unknown |
| `git_config` | `key=value`: what the key does (`[config]`) | as the key's role |
| `sed_script` | a sed script (`e`, `s///e` run commands) | the commands read, or an Unknown |
| `source` | a URL or UNC share, else a file it reads (certutil, bitsadmin) | as `url` or `read` |
| `code_source` | code it runs, from a file or a URL (mshta, regsvr32 `/i:`) | an Unknown; from a URL, run what it downloads |
| `reg_write` / `reg_delete` | a registry key (`HKCU\...`) | as `write` / `delete` of `HKCU:/...` |
| `comma_program` | `prog,arg,...` it runs (gcc `-wrapper`) | an execution of it |
| `program_dir` | a directory it runs programs from (gcc `-B`) | an Unknown |
| `linker` | a linker by name or path (`-fuse-ld`) | a path: an execution of it |
| `rustc_codegen` | `-C key=value` | `linker=`: an execution of it |
| `agent_file` | a Java agent, `-javaagent:x.jar` | an Unknown |
| `configured` | something that changes what runs later (cargo `--config`) | an Unknown (`run configured`) |
| `file_list` | a file listing files it reads (`tar -T`, `sort --files0-from`) | the list read; the files in it an Unknown |
| `config_file` | a file of more options (`curl -K`) | read; what it sets an Unknown (`run configured`) |
| `classpath` | a class path (`java -cp a:b`) | each entry's code an Unknown |
| `cmake_define` | `-DKEY=VALUE` | a script key (`CMAKE_PROJECT_INCLUDE`): code; a compiler or launcher: a program |
| `java_main` | java's main class, or a `.java` source | a source: code |
| `plain` | nothing vetter needs | — |

`operands` is a role for all operands, or a list for each in order where
`ROLE*` takes the rest but the ones after it (`["read*", "write"]`: cp).
A long option is also matched by a unique prefix of it (GNU's getopt_long:
`make --ev` is `--eval`); a prefix of several, one of them with a role, is an
Unknown.

The environment's roles (`env.toml`) are these, and `options:PROGRAM` (more
options, read with that program's spec: `MAKEFLAGS`, `GOFLAGS`,
`JAVA_TOOL_OPTIONS`), `code_file_list` (`MAKEFILES`), `shell_expanded` (a
value a shell expands again: `PS0`-`PS4`); `BASH_FUNC_f%%` defines a bash
function.

`program_args` is a command to run (the wrapper's). `ln`: each link written,
what it points to read and written too (what's done through it is done to
it). `make`: targets, and `VAR=value` (`SHELL=`, a value with shell code: an
Unknown; `CC=./x`: an execution of it).
