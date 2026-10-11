# 7. The landscape

Data from 2026-10-10.

## Closest alternatives

| Project | What | How it reads commands | Traction |
|---|---|---|---|
| [destructive_command_guard (dcg)](https://github.com/Dicklesworthstone/destructive_command_guard) | pre-execution guard for ~15 agents, rule packs in TOML (Rust) | patched tree-sitter-bash + tokenizer + regex; scans heredocs, `python -c` | 6,132★, since 2026-01 |
| [cc-safety-net](https://github.com/kenryu42/cc-safety-net) | blocks destructive git/file commands, ~16 agents (TypeScript) | own tokenizer (unverified) | 1,583★, since 2025-12 |
| [Codex execpolicy](https://github.com/openai/codex/tree/main/codex-rs/execpolicy) | built into Codex, Starlark `prefix_rule`, examples checked at load | tree-sitter-bash, plain word lists only | part of Codex |
| [agentjail](https://github.com/LuD1161/agentjail) | daemon for Claude Code, Codex, Cursor; Rego rules | "structured parsing" | 96★ |
| [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit) | broad governance suite, YAML/OPA/Cedar | command denylist | 6,415★ |
| Agent built-ins | prefixes, globs, regexes, tree-sitter splits | — | — |

Further away: NeMo Guardrails, Guardrails AI, LlamaFirewall (conversation and
output, not shell); Invariant (traces; bought by Snyk); MCP gateways (Docker,
agentgateway, Claw Patrol: wire traffic); AWS Bedrock AgentCore Policy (Cedar,
tool arguments); Anthropic sandbox-runtime (an OS sandbox, complementary).

Funded companies sell enterprise agent-security platforms (Rein $25M, Geordie
$30M, Reco $55M, CodeIntegrity $4.8M in 2026; Protect AI to Palo Alto for
$634.5M, Lakera to Check Point). None is a precise command-policy engine.

## Where vetter is different

| | dcg & co | agent built-ins | vetter |
|---|---|---|---|
| Reading of bash | tree-sitter / regex | prefixes / regex | exact, checked against bash |
| Undecidable parts | guess | guess or prompt | marked, policy decides |
| Wrappers, `sh -c`, `find -exec`, `xargs` | some | few | all known ones, recursively |
| What arguments mean (`--output`, `-exec`) | pattern lists | no | command specs, argument roles |
| Policy checked when loaded | no | Codex examples only | types, dead/shadowed rules, tests |
| Explains the decision | partly | no | rule and span |
| Editor for policies | no | no | LSP |
| Embeddable library | no (binary) | no | C ABI, bindings |

## Risks

- **dcg is the "install and forget" incumbent.** vetter must win on precision
  (the bypass corpus, published) and on fewer prompts, not on features alone.
- **Agents improve their own rules** (Codex execpolicy, Copilot's tree-sitter
  split). vetter stays useful by working across all of them, and by being
  more exact than any one vendor will bother to be.
- **Exact bash is hard.** It's the moat if we do it, and the risk if we
  don't: differential testing from the first day.

## Sources

Evidence:
- claude-code issues [#28240](https://github.com/anthropics/claude-code/issues/28240), [#16561](https://github.com/anthropics/claude-code/issues/16561), [#30519](https://github.com/anthropics/claude-code/issues/30519)
- [codex #2860](https://github.com/openai/codex/issues/2860), [gemini-cli #11766](https://github.com/google-gemini/gemini-cli/issues/11766), [vscode #252496](https://github.com/microsoft/vscode/issues/252496), [Roo-Code #12292](https://github.com/RooCodeInc/Roo-Code/issues/12292)
- [Cursor forum: chained commands bypass the denylist](https://forum.cursor.com/t/chained-commands-bypass-yolo-mode-denylist/50775)
- [HiddenLayer advisory on Cursor](https://www.hiddenlayer.com/sai-security-advisory/sai-security-advisor-2025-11-cursor), [CVE-2026-22708](https://cvefeed.io/vuln/detail/CVE-2026-22708)
- [Pillar Security: GitPwned](https://www.pillar.security/blog/gitpwned-allowlist-to-rce), [CVE-2026-19591](https://www.sentinelone.com/vulnerability-database/cve-2026-19591/)
- [Gemini CLI stealthy execution](https://bleepingcomputer.com/news/security/flaw-in-gemini-cli-ai-coding-assistant-allowed-stealthy-code-execution)
- [CVE-2025-55284](https://nvd.nist.gov/vuln/detail/cve-2025-55284), [CVE-2026-24887](https://cvefeed.io/vuln/detail/CVE-2026-24887), [CVE-2026-24053](https://osv.dev/vulnerability/CVE-2026-24053), [CVE-2026-63108](https://cveawg.mitre.org/api/cve/CVE-2026-63108)
- [Trail of Bits: prompt injection to RCE](https://blog.trailofbits.com/2025/10/22/prompt-injection-to-rce-in-ai-agents/), [arXiv 2509.24240](https://arxiv.org/pdf/2509.24240), [APIsec: catfishing the allowlist](https://labs.apisec.ai/research/articles/catfishing-the-allowlist-mcp-argument-injection)
- HN: ["Continue? Y/N"](https://news.ycombinator.com/item?id=48308376), ["Humans missed 1 in 3 threats"](https://news.ycombinator.com/item?id=49195468)

Market: [Rein](https://prnewswire.com/news-releases/rein-security-raises-25-million-to-secure-the-ai-agents-enterprises-build-and-stop-the-ones-that-attack-them-302901591.html), [Reco](https://techcrunch.com/2026/09/29/reco-raises-55m-as-ai-agent-security-startups-crowd-the-market/), [Geordie](https://fortune.com/2026/05/28/geordie-security-governance-ai-agents/), [CodeIntegrity](https://www.geekwire.com/2026/codeintegrity-raises-4-8m-to-put-permanent-guardrails-on-unpredictable-ai-agents/).

Some items come from aggregators or search summaries and are worth checking at
the source before quoting them publicly (CVE details from cvefeed and
SentinelOne, the Lakera price, cc-safety-net's and agentjail's parsers).
