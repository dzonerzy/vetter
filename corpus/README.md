# The bypass corpus

Every known way a command got past an AI agent's command rules, as data.
Each file holds cases of one family; each case:

| Field | Meaning |
|---|---|
| `id` | unique, `<family>-<n>` or `<agent>-<cve>` |
| `shell` | `bash` (later `powershell`, `cmd`, `zsh`) |
| `command` | the command as the agent would run it |
| `allowed_by` | the allow rule the bypass hid behind, in plain words |
| `runs` | the programs it actually runs, in order (what vetter's resolver must find) |
| `expect` | vetter's decision with the stock policy: `deny` or `ask` |
| `why` | one line |
| `source` | where it comes from (CVE, advisory, issue, post); `derived` for variants we wrote |

`runs` lists every program started, builtins that run code (`eval`,
`source`) included, wrappers too (`sudo`, `env`): the policy decides about
each.

Harmless commands that agents ask about needlessly are in `harmless/`: there,
`expect` is `allow` and the measure is prompts saved.
