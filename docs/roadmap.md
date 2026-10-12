# Roadmap

## Done

- **Exact reading** of bash, PowerShell and cmd.exe, each checked against
  the real shell; Python given to `python -c` read and followed.
- **The policy language**: actions and places, program rules, pipelines,
  kinds of what can't be seen, tests beside the rules, `use`, `drop`, project
  policies, checks when a policy loads, `vetter lint`.
- **The stock policy**, with about a hundred tests across the three shells.
- **Every agent with a hook**: Claude Code, Codex, Gemini CLI, Cursor, Copilot
  CLI, VS Code, Cline, Amp, opencode, and a JSON hook for other harnesses.
- **Native builds**: the hook as a standalone executable (Linux, Windows)
  and `libvetter` with a C API.
- **Learning from your answers** (`vetter learn`).
- **Verification**: the bypass corpus, two audits, oracles on Linux and
  Windows, fuzzers, a comparison with dcg and cc-safety-net.

## Next

- **Observe mode**: install the hook so it only logs what it would ask, for a
  few days, to see the noise before it interrupts anything.
- **Inline code in other languages**: `node -e`, `perl -e`, `ruby -e`, read
  as Python's is.
- **Starter policies**: `vetter init` writing a project policy from its
  build files (package.json, Cargo.toml, pyproject.toml, Makefile, CI).
- **The editor**: errors, completion and hover for `.vet` files, through
  zlsp.
- **Shipping**: wheels carrying the standalone hook, `vetter install`
  pointing at it; macOS when zrun's toolchain supports it.
- **A public benchmark**: the corpus and the comparison, published and kept
  current.

## Later

- zsh and POSIX sh differences in full.
- File edits and MCP tool calls decided by the same language.
- Shared policy packs per stack (node, python, rust, infra).
- A shell wrapper on `PATH` for agents without hooks.
