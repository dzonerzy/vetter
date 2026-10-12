# Analyzer remediation guide

> Audit snapshot: 2026-10-12, repository `d07e6fa` plus the working-tree
> changes present during the review. Target: `vetter`
> (`aa34ffe1-dc4f-4f27-a26b-712019bd95ac`).

This document turns the current audit results into implementation and
regression-test requirements. It covers Bash, `cmd.exe`, PowerShell, native
command specifications, build tools, environment variables, and provenance.

The current active set is **49 analyzer/library defects: 29 critical and 20
high**. Five older cases were rechecked and are fixed; they are listed at the
end so their regressions remain visible without being counted as open.

These are analyzer defects, not merely missing stock-policy rules. In every
active case, the runtime can perform an action which is absent from or
misrepresented in Vetter's action graph. Adding a deny rule for the literal
proof-of-concept command is only a temporary containment measure.

## Threat model and test oracle

Assume an agent-controlled command can also control its environment, current
directory, stdin, and files it has previously created in the project or a
temporary directory. `/flag` and `C:\flag` are stand-ins for any protected
file outside those locations.

The soundness requirement is:

```text
runtime actions(command, state) <= modeled actions(command, abstract_state)
```

If Vetter cannot enumerate a runtime action precisely, it must emit an
`Unknown`/configured-code action and reach the policy's `unknown` decision
(normally `ask`). It must never silently omit an action because parsing,
unrolling, recursion, or state tracking reached a limit.

A fix is complete only when a regression test asserts both:

1. the resolver's action/execution graph contains the protected read, write,
   child execution, or an appropriately conservative `Unknown`; and
2. the stock policy does not return `allow`.

Checking only the final policy decision can hide another analyzer omission
behind an unrelated deny rule. Each proof should also be run against the real
shell/tool in an isolated container or Windows VM with a sentinel flag file.

## Recommended order of work

| Priority | Work | Why |
|---|---|---|
| P0 | Fail closed on truncated loops, unrecognized sensitive options, external/generated code, reflection handles, and unread config/list files | Removes broad bypass classes quickly |
| P1 | Add recursive interpretation for environment option vectors, config files, manifests, response/list files, and discovered code | Fixes most toolchain and indirect-read findings |
| P1 | Introduce explicit mutable state for cwd stacks, link aliases, PowerShell defaults, arrays, and loop variables | Fixes state-desynchronization findings |
| P1 | Replace lexical build-tool trust with artifact provenance | Prevents generated code becoming trusted merely because a compiler produced it |
| P2 | Implement runtime-accurate option matching, forwarded-option grammars, and version profiles | Fixes abbreviation, compiler forwarding, and version-specific semantics |
| P2 | Expand the differential matrix across Bash 5.1/latest, PowerShell 5.1/7, and native `cmd.exe` | Prevents fixes for one runtime from becoming unsound on another |

## Architectural changes that address whole bug families

### 1. Make provenance first-class

Every string, file, config entry, and produced artifact should carry a
provenance such as `literal`, `trusted_project`, `generated`, `downloaded`,
`external`, or `unknown`. Joining two states must keep the less trusted one.
Compilation must transfer provenance from all source, plugin, manifest,
config, and environment inputs to the output.

In particular, remove the effective trust upgrade created by the
`BUILD_TOOLS` carve-outs in `vetter/policy/actions.py` and
`vetter/agents/written.py`. A file is not trusted because `gcc`, `javac`,
`go`, `cargo`, `zig`, or another familiar tool produced it. It is trusted
only if every code-bearing input and build hook was trusted.

### 2. Use one bounded recursive interpreter

The same machinery should interpret nested command-bearing inputs from:

- shell options and environment variables;
- response files, config files, manifests, and file lists;
- compiler-forwarded options;
- source-discovery hooks such as `conftest.py`;
- data that a runtime expands again, such as Bash prompt strings.

The interpreter needs cycle detection and a budget. Exhausting either must
produce `Unknown`, never an empty result. Known files created earlier in the
same command/session can be parsed; unreadable or dynamic files must remain
conservative.

### 3. Model mutable shell state explicitly

State should include at least current directory, directory stack, environment,
known variables, arrays/maps, path aliases (symlink/junction/hard-link), and
PowerShell preference/default tables. Each control-flow join should merge
states conservatively. A value which differs across branches becomes a set or
unknown; it must not retain the value from a single convenient branch.

### 4. Separate option syntax from option semantics

`vetter/specs/__init__.py` currently recognizes declared spellings, while
several GNU programs accept unique long-option prefixes and compilers have
nested option languages. Add program-specific matching modes:

- exact long options;
- GNU unique-prefix long options, rejected/unknown when ambiguous;
- single-dash long options;
- attached values;
- forwarded option/value pairs;
- response/config-file option vectors.

The resolver should return the canonical option plus its consumed tokens.
This prevents each command spec from reimplementing subtly different token
consumption.

### 5. Replace PowerShell method-name denylisting with capabilities

`vetter/shells/powershell/cmdlets.py` and `resolve.py` currently depend on
`RISKY_TYPES` and `RISKY_METHODS`. That misses constructors, inherited
methods, reflection, delegates, and stateful object methods. Track abstract
capabilities instead: `file_reader`, `file_writer`, `process_launcher`,
`location_mutator`, `reflection_handle`, `delegate`, and `script_executor`.
Constructors and method calls consume or return these capabilities; an
unresolved call on a sensitive capability yields `Unknown`.

### 6. Add runtime/version profiles

Semantics differ across Bash 5.1/latest and PowerShell 5.1/7. Store the
selected runtime profile in resolver context. If the runtime is not known,
use the union of supported behaviors. A command safe only on a newer runtime
cannot be assumed safe on an unspecified host.

## Bash and Unix command findings

### B01 — Exported Bash functions bypass `env` handling (critical)

- **Tracking ID:** `75824200-a483-434d-9933-bbcd6c7ab829`
- **Code:** `vetter/shells/bash/resolve.py`, `wrap_env`; missing semantics in
  `vetter/specs/env.toml`.
- **Proof:** `env 'BASH_FUNC_true%%=() { cat /flag; }' bash -c true`
- **Mismatch:** Bash imports the encoded function and `bash -c true` invokes
  it, while Vetter does not decode the `BASH_FUNC_<name>%%` ABI and omits the
  body execution.
- **Required fix:** recognize this name form before ordinary shell-identifier
  validation; parse the value as a function definition with the Bash parser;
  attach it to the child Bash state and honor function-over-command lookup.
  If the body or child-shell identity is unknown, emit `Unknown`.
- **Regression:** the graph must include `cat` reading `/flag` (or unknown
  imported Bash code), and a non-Bash child must not be treated as importing
  the function.

### B02 — `${parameter@P}` performs an unmodeled second expansion (critical)

- **Tracking ID:** `fe2c9e34-c966-4b52-a2b5-4e54cc4fead5`
- **Code:** `vetter/shells/bash/expand.py`, parameter transformation handling.
- **Proof:** `x='$(cat /flag)'; echo "${x@P}"`
- **Mismatch:** Bash treats the value as a prompt string and executes the
  command substitution. Vetter returns it as data.
- **Required fix:** make `@P` an explicit expanded-later operation. Feed a
  known value back through prompt expansion, including parameter, arithmetic,
  and command substitutions; a dynamic value becomes `Unknown`.
- **Regression:** include the nested `cat` read and retain harmless prompt
  escapes as harmless.

### B03 — Bash 5.1 re-expands associative-array subscripts (critical)

- **Tracking ID:** `f4b8995c-10f6-4987-8732-13089d122639`
- **Code:** `vetter/shells/bash/resolve.py`, `cond_arithmetic` and
  `named_subscript`.
- **Proof:** `declare -A h; k='$(cat /flag >&2)'; [[ -v h[$k] ]] || :`
- **Mismatch:** Bash 5.1.16 evaluates the command substitution while Vetter
  treats the key as a plain known value. This behavior is version-sensitive.
- **Required fix:** in affected runtime profiles, feed associative keys in
  arithmetic/conditional subscript contexts through the second expansion.
  With an unknown Bash version, conservatively include that behavior.
- **Regression:** run on Bash 5.1 and the newest supported Bash; assert the
  profile-specific graph rather than normalizing the versions together.

### B04 — Interactive `PS0` and `PS1` execute hidden substitutions (critical)

- **Tracking ID:** `ca8422b2-66df-4aa7-913f-511ad43da911`
- **Code:** `vetter/specs/env.toml` and interactive Bash startup/prompt state.
- **Proof:** `PS0='$(cat /flag)' bash --noprofile --norc -i <<< true`
- **Also verified:** the equivalent payload in `PS1` executes when a prompt is
  displayed.
- **Mismatch:** only `PS4`/`PROMPT_COMMAND` have related semantics today.
- **Required fix:** add `PS0` and `PS1` as prompt-expanded environment roles,
  but trigger them only at the correct interactive prompt events. Unknown
  prompt text must be unknown shell execution.
- **Regression:** cover `PS0`, `PS1`, `PS4`, interactive/non-interactive mode,
  and `--noprofile --norc` so startup files do not mask the result.

### B05 — `less +!` runs a shell command (critical)

- **Tracking ID:** `e3a7e797-edcf-42f7-937e-af6a2cdb1471`
- **Code:** the `less` entry in `vetter/specs/files.toml`.
- **Proof (PTY required):**
  `TERM=xterm less -X $'+!cat /flag;pkill -x less\n' /etc/os-release`
- **Mismatch:** the `+cmd` initial-command language is treated as an ordinary
  argument, but `+!cmd` invokes a shell from `less`.
- **Required fix:** add a `less` initial-command parser. Classify `+!` payloads
  as shell, recognize safe built-in navigation commands, and fail closed for
  unrecognized command forms. Account for `LESS` carrying default options.
- **Regression:** use a pseudo-terminal and assert the nested shell execution,
  not merely the presence of the input file.

### B06 — GNU Make long-option abbreviation hides `--eval` (critical)

- **Tracking ID:** `aecf8b13-4a99-452a-b1ce-29a9f4d2ff73`
- **Code:** `vetter/specs/dev.toml` and option matching in
  `vetter/specs/__init__.py`.
- **Proof:** `make --ev='x:;cat</flag' x`
- **Mismatch:** GNU Make resolves the unique prefix to `--eval`; Vetter does
  not apply the `shell`/makefile-fragment semantics.
- **Required fix:** enable GNU unique-prefix resolution for Make, canonicalize
  to `--eval`, and mark ambiguous or unknown prefixes as `Unknown` rather than
  operands.
- **Regression:** generate every unique prefix of dangerous Make options and
  every ambiguous prefix from the installed Make's option table.

### B07 — Zip long-option abbreviation hides `--unzip-command` (critical)

- **Tracking ID:** `a3cbf3f8-a0eb-4af2-a41c-763ce9cea8cb`
- **Code:** Zip entry in `vetter/specs/files.toml`; generic option matching.
- **Proof:** after creating a valid `/tmp/a.zip`, run
  `zip -T --unzip-c='sh -c "cat /flag"' /tmp/a.zip`.
- **Mismatch:** Zip accepts the unique prefix and executes it during the test;
  Vetter does not attach the declared shell role.
- **Required fix:** use the same canonical GNU-prefix resolver as B06 and then
  process the value under `--unzip-command`'s shell role.
- **Regression:** assert the `sh -c` execution and include an ambiguous prefix
  which must become unknown.

### B08 — `CDPATH` desynchronizes the modeled cwd (high)

- **Tracking ID:** `70d7a719-fec3-498d-9b9d-6c608ddb1b08`
- **Code:** `vetter/shells/bash/resolve.py`, `cd`/cwd state.
- **Proof:** `CDPATH=/ cd etc && cat hostname`
- **Runtime result:** the read is `/etc/hostname`; Vetter models a project
  path. A flag-shaped form is `CDPATH=/ cd proc/self/root && cat flag`.
- **Required fix:** resolve relative `cd` operands against each known `CDPATH`
  entry, preserving possible results. If `CDPATH` or filesystem matching is
  unknown, set cwd to unknown. Absolute operands and `./`/`../` exceptions
  must follow Bash behavior.
- **Regression:** assert the final absolute read, including empty `CDPATH`
  entries and multiple possible directories.

### B09 — AWK `split(..., ARGV)` injects input files (high)

- **Tracking ID:** `7fd613ce-c97c-463e-8743-41a391900e5a`
- **Code:** `awk_effects` in `vetter/specs/__init__.py`.
- **Proof:** `awk 'BEGIN{split("/flag",ARGV)} {print}' README.md`
- **Mismatch:** AWK mutates its runtime input-file vector and reads `/flag`;
  Vetter only considers command-line file operands.
- **Required fix:** model assignments and mutating built-ins whose destination
  is `ARGV`, including `split`, `patsplit`, indexed writes, and deletes. If the
  resulting array cannot be enumerated, emit an unknown read set.
- **Regression:** assert the injected read and add harmless `split` calls into
  ordinary arrays.

### B10 — AWK octal string escapes are decoded as path text (high)

- **Tracking ID:** `120c468d-c438-43d6-91a1-2e76e9ea2db7`
- **Code:** the AWK lexer/effect parser in `vetter/specs/__init__.py`.
- **Proof:** `awk 'BEGIN{getline x < "\057flag"; print x}'`
- **Mismatch:** AWK decodes `\057` to `/`; Vetter models a different relative
  path.
- **Required fix:** implement the runtime's string decoder before semantic
  analysis: octal, hexadecimal, standard escapes, escaped newlines, and
  implementation/version edge cases. Unsupported escapes must not be assumed
  literal when they can affect a sensitive token.
- **Regression:** table-test every escape form in filenames and shell-bearing
  AWK strings.

### B11 — Curl config files inject unmodeled URLs and file actions (high)

- **Tracking ID:** `12fb53db-9486-45e8-b02a-27138005e0f3`
- **Code:** Curl entry in `vetter/specs/network.toml`.
- **Proof:** `printf 'url = "file:///flag"\n' >/tmp/c && curl -sK /tmp/c`
- **Mismatch:** Vetter records only the config-file read. Curl parses it as
  more options and reads the flag; config can similarly hide `upload-file`,
  output paths, credentials, and command-relevant URLs.
- **Required fix:** give `--config`/`-K` a recursive curl-config role, parse
  quoting/comments/one-option-per-line syntax, and feed recovered options
  through the normal curl option semantics. Support `-K -` from stdin and
  account for implicit startup config; unreadable config becomes unknown.
- **Regression:** cover file URL reads, uploads, output writes, nested config
  behavior, stdin, and `--disable`/startup-config behavior.

### B12 — Tar `--files-from` hides archived reads (high)

- **Tracking ID:** `918ab76e-10d6-47e2-a608-f9c17c2464d8`
- **Code:** Tar entry in `vetter/specs/files.toml`.
- **Proof:**
  `printf '/flag\n' >/tmp/l && tar --create --file=/tmp/a.tar --files-from=/tmp/l`
- **Mismatch:** Vetter records the list read, not the listed `/flag` read, and
  does not consistently make `--file` a mode-sensitive archive write.
- **Required fix:** parse Tar mode first, then recursively interpret newline
  or NUL lists with Tar quoting and `-C` state. Unknown list contents imply
  unknown input reads. Assign archive read/write semantics from create,
  append, update, extract, and list mode.
- **Regression:** assert `/flag` read and `/tmp/a.tar` write; cover `--null`,
  embedded `-C`, extraction, and list files generated earlier in the command.

### B13 — Zstd `--filelist` hides compressed reads (high)

- **Tracking ID:** `521d56b7-814b-4b71-a169-9a09ad6eae95`
- **Code:** Zstd entry in `vetter/specs/files.toml`.
- **Proof:**
  `printf '/flag\n' >/tmp/l && zstd -q -c --filelist=/tmp/l >/tmp/a.zst`
- **Mismatch:** only the list itself is modeled as read.
- **Required fix:** add a recursive file-list role with zstd's delimiter and
  escaping rules; listed files are reads and unresolved contents become an
  unknown read set.
- **Regression:** assert `/flag` read and redirected archive write.

### B14 — Sort `--files0-from` hides input reads (high)

- **Tracking ID:** `b5a35ca9-e42a-4690-8414-5d3629165d11`
- **Code:** Sort entry in `vetter/specs/files.toml`.
- **Proof:** `printf '/flag\0' >/tmp/l && sort --files0-from=/tmp/l`
- **Mismatch:** the NUL-delimited list is read but its entries are omitted.
- **Required fix:** parse known NUL-delimited contents into ordinary sort input
  reads. Dynamic contents imply unknown reads.
- **Regression:** include spaces/newlines in listed filenames and a list
  produced earlier in the same shell sequence.

### B15 — File long-option abbreviation bypasses fixed `-f` handling (high)

- **Tracking ID:** `2f6ba0a7-07eb-483b-b4b2-8a4499e0a1b1`
- **Code:** File entry in `vetter/specs/files.toml`; generic option matching.
- **Proof:** `file --files-f=/flag`
- **Mismatch:** exact `file -f /flag` is fixed, but GNU File accepts the
  abbreviated `--files-from` while Vetter misses the role.
- **Required fix:** canonical GNU unique-prefix matching as in B06/B07.
- **Regression:** retain the exact-option test and add all accepted unique
  prefixes so this is not patched as another literal spelling.

## `cmd.exe` findings

### C01 — `FOR /F` file sets have no file-read effect (high)

- **Tracking ID:** `b3015884-f564-4965-837d-ce8579ab7bbb`
- **Code:** `for_command` in `vetter/shells/cmd/resolve.py`.
- **Proof:** `for /f "usebackq delims=" %A in ("C:\flag") do @echo %A`
- **Mismatch:** command-substitution forms are handled, but the file-set form
  reads the flag without a corresponding action.
- **Required fix:** parse the `FOR /F` set according to `usebackq`: filenames,
  literal strings, and backquoted commands have different meanings. Add reads
  for every file and preserve tokenization options such as `delims`, `tokens`,
  `skip`, and `eol`.
- **Regression:** cover all three set forms with and without `usebackq`, plus
  multiple filenames.

### C02 — `FOR /R` leaves loop-variable paths literal (high)

- **Tracking ID:** `e29ce763-12be-44e9-a5b5-ac01f1a6ec3c`
- **Code:** `for_command` and variable substitution in
  `vetter/shells/cmd/resolve.py`.
- **Proof:** `for /r C:\ %A in (flag) do @type %A`
- **Mismatch:** cmd traverses from `C:\` and substitutes concrete paths;
  Vetter models a project-relative `%A` path.
- **Required fix:** represent the traversal root and filename pattern in the
  variable's abstract value. Enumerate only when safely bounded by a known
  filesystem snapshot; otherwise the body path is an external/dynamic path
  and must produce an unknown read.
- **Regression:** assert the body cannot resolve `%A` under the project when
  the traversal root is external.

### C03 — `FOR` silently drops iterations after eight values (high)

- **Tracking ID:** `81e14b9b-db0b-41a2-89de-c9a37b0cb133`
- **Code:** `MAX_ROUNDS` and `rounds[:MAX_ROUNDS]` in
  `vetter/shells/cmd/resolve.py`.
- **Proof:**
  `for %A in (README.md x x x x x x x x C:\flag) do @type %A`
- **Mismatch:** the protected read is after the unroll limit and disappears
  from the graph.
- **Required fix:** analyze the bounded prefix and add a summary iteration for
  all remaining values. Known remaining literals can be joined exactly;
  otherwise invalidate affected state and emit unknown body effects.
- **Regression:** put a sensitive action at `MAX_ROUNDS + 1`, and test nested
  loops and numeric `/L` ranges which exceed the bound.

### C04 — Slash-rooted paths are discarded as internal-command options (high)

- **Tracking ID:** `30c1e956-374b-4e57-b10f-87e6716d9b55`
- **Code:** `internal` in `vetter/shells/cmd/resolve.py`.
- **Proof:** `cd / & type flag`
- **Also verified:** `cd /Windows & type win.ini`.
- **Mismatch:** generic filtering drops every word beginning with `/`, although
  a slash-rooted word can be a Windows path. The following cwd is wrong.
- **Required fix:** remove generic slash filtering. Give every internal command
  its own switch grammar (`cd` recognizes `/d`, for example) and treat all
  other slash words according to that command's operand rules.
- **Regression:** combine `/d`, `/`, `/Windows`, quoted paths, and actual
  switches for each internal command.

### C05 — COPY's glued `+` sources hide a protected input (high)

- **Tracking ID:** `62faa2c6-6919-40a5-aec5-0743b01587a4`
- **Code:** `split_args` and COPY handling in
  `vetter/shells/cmd/resolve.py`.
- **Proof:** `copy /b NUL+C:\flag %TEMP%\f & type %TEMP%\f`
- **Mismatch:** cmd treats `+` as COPY source concatenation even without
  surrounding spaces; Vetter does not split it and misses `C:\flag`.
- **Required fix:** implement COPY-specific source/destination grammar,
  including glued/quoted `+`, `/a` and `/b` modifiers, devices such as `NUL`,
  wildcard sources, and destination inference.
- **Regression:** assert both the protected source read and destination write;
  do not make global cmd tokenization split `+` for unrelated commands.

### C06 — `popd` does not restore cwd (high)

- **Tracking ID:** `ea7a01f3-cfcd-4d88-9254-2f46a1ac4b4a`
- **Code:** internal-command state in `vetter/shells/cmd/resolve.py`.
- **Proof:**
  `cd /d C:\ & pushd %CD% & popd & type flag`
- **Mismatch:** Vetter models `pushd`/cwd incompletely and has no directory
  stack restoration for `popd`, so the final read is assigned the wrong path.
- **Required fix:** add an explicit cmd directory stack, drive-specific current
  directories, and UNC temporary-drive mappings. An underflow or divergent
  control-flow stack becomes unknown.
- **Regression:** cover nested pushes, `/d`, UNC paths, stack underflow, and
  branch joins.

## PowerShell findings

### P01 — Reflection/delegates bypass `Process.Start` detection (critical)

- **Tracking ID:** `d578df6e-31f4-412f-9ad8-448079842bfb`
- **Code:** `dotnet` in `vetter/shells/powershell/resolve.py` and the risky
  type/method tables in `cmdlets.py`.
- **Proof:**

  ```powershell
  $m=[Diagnostics.Process].GetMethod('Start',[type[]]@([string],[string]))
  $d=$m.CreateDelegate([Func[string,string,Diagnostics.Process]])
  $p=$d.DynamicInvoke('cmd.exe','/c type C:\flag')
  $p.WaitForExit()
  ```

- **Mismatch:** the runtime launches cmd, but the sensitive method name is
  carried through `MethodInfo` and a delegate, outside the static denylist.
- **Required fix:** taint reflection results with their declaring type and
  member when known; carry a process-launch capability through delegates;
  parse known `DynamicInvoke` arguments as a child process. Unknown reflected
  members on sensitive types must emit `Unknown`.
- **Regression:** cover `MethodInfo.Invoke`, `CreateDelegate`,
  `Delegate.DynamicInvoke`, overload selection, and harmless reflection.

### P02 — `New-Item` junctions create unmodeled path aliases (critical)

- **Tracking ID:** `ad255386-cff7-4521-a6ae-49ba51dc3522`
- **Code:** `New-Item` spec in `vetter/specs/powershell.toml`, cmdlet effects,
  and path authorization.
- **Proof:**
  `New-Item -ItemType Junction -Path root -Target 'C:\'; Get-Content root\flag`
- **Mismatch:** a project-local pathname aliases an external tree, while the
  final read remains classified as project-local.
- **Required fix:** model `SymbolicLink`, `Junction`, and `HardLink` creation as
  alias effects with source and target. Resolve subsequent paths through known
  aliases, detect cycles, and mark unresolved/reparse-point traversal unknown.
  Authorization should use resolved identity, not only lexical containment.
- **Regression:** include directory junctions, file hard links, relative
  targets, alias chains, deletion/recreation, and a harmless ordinary file.

### P03 — `$PSDefaultParameterValues.Add` injects hidden parameters (critical)

- **Tracking ID:** `73f43da5-39a6-4e0c-ba1b-0bd0679d4f31`
- **Code:** `effects`/`default_key` in
  `vetter/shells/powershell/resolve.py`.
- **Process proof:**

  ```powershell
  $PSDefaultParameterValues.Add('Start-Process:FilePath','cmd.exe')
  $PSDefaultParameterValues.Add('Start-Process:ArgumentList','/c type C:\flag')
  Start-Process -Wait -NoNewWindow
  ```

- **File-read proof:**
  `$PSDefaultParameterValues.Add('Get-Content:Path','C:\flag'); Get-Content`
- **Mismatch:** index assignments may be recognized, but Hashtable methods
  mutate the same preference state without being applied at parameter binding.
- **Required fix:** model `Add`, index setters, `Remove`, `Clear`, replacement,
  scoping, and wildcard command/parameter keys. Merge defaults before cmdlet
  role resolution; an unknown mutation invalidates the table.
- **Regression:** assert both child-process parsing and direct path injection,
  plus override-by-explicit-parameter and wildcard precedence.

### P04 — `System.IO.StreamReader` reads are invisible (high)

- **Tracking ID:** `7a63823d-c4e0-4b7c-9831-89ec07789658`
- **Code:** `dotnet` and `RISKY_TYPES`/`RISKY_METHODS`.
- **Proof:** `([IO.StreamReader]::new('C:\flag')).ReadToEnd()`
- **Mismatch:** constructor state and instance methods fall outside the current
  type/method list.
- **Required fix:** a StreamReader constructor creates a `file_reader(path)`
  object; read methods emit the corresponding read. Apply the same abstraction
  to `FileStream`, `TextReader` wrappers, and inherited methods. Unknown
  sensitive constructor arguments remain unknown reads.
- **Regression:** cover `new`, `OpenText`, `Read`, `ReadLine`, `ReadToEnd`, and
  disposal/chaining syntax.

### P05 — `System.IO.StreamWriter` writes are invisible (high)

- **Tracking ID:** `7433be09-61d0-47b5-ab60-c98550b5a4c3`
- **Code:** same .NET resolver path as P04.
- **Proof:**
  `$w=[IO.StreamWriter]::new($PROFILE);$w.WriteLine('payload');$w.Close()`
- **Mismatch:** the protected file write is absent.
- **Required fix:** constructors return `file_writer(path, mode)` capabilities;
  write/flush/close preserve and emit the write effect. Include `FileStream`,
  `BinaryWriter`, and factories returning writer objects.
- **Regression:** cover append/overwrite modes, chained construction, and a
  dynamic destination.

### P06 — Compound assignment `+=` is analyzed as replacement `=` (high)

- **Tracking ID:** `e949017e-5cb1-4e22-ac1e-53fa371636ff`
- **Code:** assignment handling in `effects`,
  `vetter/shells/powershell/resolve.py`.
- **Proof:** `$p='C:\';$p+='flag';Get-Content $p`
- **Mismatch:** the final value is `C:\flag`, but Vetter retains or computes a
  different value.
- **Required fix:** preserve the assignment operator in the AST effect and
  implement PowerShell's type-sensitive `+=`, `-=`, `*=`, `/=`, and `%=`.
  When operand types are not known, invalidate the variable rather than using
  simple assignment semantics.
- **Regression:** include strings, arrays, numbers, hashtables, and branch
  joins because `+=` changes meaning by type.

### P07 — `Pop-Location` does not restore cwd (high)

- **Tracking ID:** `df15da1a-e8e2-4b92-b38b-9a29a9d3d865`
- **Code:** PowerShell cmdlet specs and resolver location state.
- **Proof:**
  `Set-Location 'C:\'; Push-Location '<trusted-project>'; Pop-Location; Get-Content flag`
- **Mismatch:** the final read occurs at `C:\flag`; the action graph keeps the
  pushed project location.
- **Required fix:** implement the default and named location stacks, aliases
  (`pushd`, `popd`), provider-qualified paths, and branch merging. Unknown
  stack state makes cwd unknown.
- **Regression:** cover `-StackName`, nested stacks, underflow, aliases, and
  filesystem/non-filesystem providers.

### P08 — SessionState can change cwd through a .NET-style API (high)

- **Tracking ID:** `900d136d-8d2a-4254-8c03-3930094fc708`
- **Code:** PowerShell object/method effects in `resolve.py`.
- **Proof:**
  `$ExecutionContext.SessionState.Path.SetLocation('C:\'); Get-Content flag`
- **Mismatch:** cwd mutation through the session-state object is omitted.
- **Required fix:** assign `location_mutator` capability to the known
  `$ExecutionContext.SessionState.Path` object and map `SetLocation` to the
  same state transition as `Set-Location`. Unknown calls on that object should
  conservatively invalidate cwd.
- **Regression:** compare cmdlet and API forms and include a dynamic argument.

## Toolchain, environment, and provenance findings

The setup steps below intentionally create code outside the trusted project.
That is the attacker-controlled provenance which the analyzer must preserve.
Where a language payload is abbreviated, use a minimal program/script whose
only effect is reading `/flag`; the command under test is the invocation shown.

### T01 — Ninja accepts an executable manifest on stdin (critical)

- **Tracking ID:** `a1dcc10c-cb4f-4200-8809-c45a5f8a8dc6`
- **Code:** no complete Ninja spec/manifest semantics.
- **Proof:**

  ```bash
  ninja -f /dev/stdin <<'NINJA'
  rule leak
    command = cat /flag
  build leak: leak
  NINJA
  ```

- **Mismatch:** Ninja executes the manifest rule; Vetter does not treat the
  manifest as code or recover the child command.
- **Required fix:** give `-f` a Ninja-manifest role, correlate `/dev/stdin`
  with the known here-document, and parse rules/build/default/includes. Until
  that parser exists, every non-trusted manifest must emit configured-code
  `Unknown`.
- **Regression:** cover stdin, external files, `include`/`subninja`, variable
  expansion, and a trusted static manifest.

### T02 — `go run` trusts external source code (critical)

- **Tracking ID:** `1b14d5b1-01ab-4b1a-bd0a-48061a2ec119`
- **Code:** Go specs in `vetter/specs/dev.toml` and generated-code handling in
  `vetter/policy/actions.py`.
- **Proof:** create `/tmp/x.go` with a `main` that reads `/flag`, then run
  `go run /tmp/x.go`.
- **Mismatch:** the source operand/execution is not represented as untrusted
  code.
- **Required fix:** parse Go subcommands; `go run` file/package arguments are
  code inputs. Propagate their provenance through the temporary executable and
  represent its execution. External/generated sources yield `Unknown` even
  though `go` is allowlisted.
- **Regression:** distinguish trusted project packages, generated `.go` files,
  external files, remote package versions, and flags after the package list.

### T03 — Java source-file mode executes external source (critical)

- **Tracking ID:** `430261f8-f265-4863-83b2-e03580203ff7`
- **Code:** Java toolchain spec.
- **Proof:** create `/tmp/X.java` whose `main` reads `/flag`, then run
  `java /tmp/X.java`.
- **Mismatch:** Java 11+ compiles and runs source directly, but the operand is
  not treated as executed code.
- **Required fix:** recognize source-file mode after JVM options, classify the
  `.java` operand as `code_file`, and transfer its provenance to execution.
  Runtime/version profiles should handle versions without source-file mode.
- **Regression:** cover shebang source files, `--source`, source options, class
  mode, and jar mode.

### T04 — `MAKEFLAGS` injects `--eval` code (critical)

- **Tracking ID:** `246cae0d-2432-453a-b487-e106784f51fe`
- **Code:** `MAKEFLAGS = "plain"` in `vetter/specs/env.toml` and Make effects.
- **Proof:** `MAKEFLAGS='--eval=x:;cat</flag' make x`
- **Mismatch:** Make reparses the environment value as options/makefile text;
  Vetter treats it as inert.
- **Required fix:** add an environment option-vector role parameterized by the
  Make option grammar. Canonicalize `--eval`, makefile includes, directories,
  and shell-related variables exactly as command-line options.
- **Regression:** include `MAKEFLAGS`, `MFLAGS`, recursive Make inheritance,
  abbreviated options, quoting, and harmless job-control flags.

### T05 — `COMPILER_PATH` replaces GCC's internal compiler (critical)

- **Tracking ID:** `df3448c7-7920-435a-956f-1f82be824831`
- **Code:** missing GCC driver environment semantics.
- **Proof:** create executable `/tmp/cc1` containing `cat /flag`, then run
  `COMPILER_PATH=/tmp gcc -c -x c /dev/null`.
- **Mismatch:** GCC finds and executes attacker-controlled `cc1`; the graph
  contains only the trusted driver.
- **Required fix:** model GCC subprogram search and execution for
  `COMPILER_PATH`, `GCC_EXEC_PREFIX`, `-B`, target/version subdirectories, and
  related driver variables. Search results with generated/external provenance
  are program executions, not plain paths.
- **Regression:** cover `cc1`, `cc1plus`, assembler, linker, precedence among
  `-B`/environment/defaults, and a missing candidate.

### T06 — `RUSTC_WORKSPACE_WRAPPER` executes an unmodeled program (critical)

- **Tracking ID:** `8bef0fc2-f943-4ae8-92ff-03501758e6d6`
- **Code:** missing Rust/Cargo environment semantics.
- **Proof:** in a Cargo workspace, create `/tmp/w` which prints `/flag` and
  then `exec "$@"`; run `RUSTC_WORKSPACE_WRAPPER=/tmp/w cargo check`.
- **Mismatch:** Cargo invokes the wrapper before rustc but Vetter omits it.
- **Required fix:** add `RUSTC_WORKSPACE_WRAPPER` and `RUSTC_WRAPPER` program
  roles, with correct nesting and argument shape. Preserve wrapper provenance
  and treat a dynamic wrapper path as unknown execution.
- **Regression:** cover both variables together, workspace/non-workspace
  crates, and unset/empty values.

### T07 — `MAKEFILES` auto-loads external makefile code (critical)

- **Tracking ID:** `0a5f9862-701a-4bce-a8b5-4407a2161213`
- **Code:** missing/incorrect Make environment role.
- **Proof:**
  `printf 'x:\n\tcat /flag\n' >/tmp/x.mk && MAKEFILES=/tmp/x.mk make x`
- **Mismatch:** Make reads and executes the environment-selected makefile
  before ordinary makefiles; Vetter omits its code provenance.
- **Required fix:** parse `MAKEFILES` as a platform-delimited list of makefile
  code inputs, including recursive Make behavior. Parse known contents or emit
  configured-code `Unknown`.
- **Regression:** include multiple files, missing files, includes, recursive
  Make, and an empty value.

### T08 — CMake `-D` variables inject included code (critical)

- **Tracking ID:** `33389f78-4fe2-4960-801d-196e0e442542`
- **Code:** CMake command spec and `-Dkey=value` semantics.
- **Proof:** put `execute_process(COMMAND cat /flag)` in `/tmp/inject.cmake`,
  then configure a valid project with
  `cmake -S . -B /tmp/b -DCMAKE_PROJECT_INCLUDE=/tmp/inject.cmake`.
- **Affected keys:** at least `CMAKE_PROJECT_INCLUDE`,
  `CMAKE_PROJECT_TOP_LEVEL_INCLUDES`, and `CMAKE_TOOLCHAIN_FILE`.
- **Required fix:** parse attached/separate `-D` definitions, canonicalize the
  variable name, and assign code-file roles to configuration hooks. Known
  files can be recursively interpreted; all external/dynamic hooks are code
  execution unknowns.
- **Regression:** test all affected keys, semicolon lists, typed definitions,
  relative paths, presets/toolchain inputs, and a harmless scalar definition.

### T09 — Clang forwarded `-load` executes a plugin (critical)

- **Tracking ID:** `5082913d-7dbe-4185-97c6-9536bbb71734`
- **Code:** compiler option forwarding in toolchain specs.
- **Proof:** with a generated `/tmp/p.so` whose load/constructor reads
  `/flag`, run `clang -Xclang -load -Xclang /tmp/p.so -c /tmp/x.c`.
- **Mismatch:** Vetter sees independent plain `-Xclang` values and never
  recognizes the cc1 `-load`/plugin path pair.
- **Required fix:** implement a stateful Clang forwarded-option parser for
  `-Xclang`, `-mllvm`, response files, and plugin-related options. A load path
  is a code file whose provenance flows into compiler execution.
- **Regression:** cover separated and response-file forms, multiple forwarded
  options, missing values, and benign cc1 flags.

### T10 — `javac` output loses provenance before `java -cp` (critical)

- **Tracking ID:** `6574b192-124e-4deb-aaef-e68c62c4e182`
- **Code:** javac source/output spec, generated-artifact correlation, and Java
  classpath resolution.
- **Proof:** compile an external/generated `/tmp/X.java` which reads `/flag`
  using `javac -d /tmp/classes /tmp/X.java`, then run
  `java -cp /tmp/classes X`.
- **Mismatch:** source and class output relationships are not modeled, so the
  generated class is treated like an ordinary trusted Java invocation.
- **Required fix:** model javac sources, `-d`, processors/plugins, classpath,
  and produced classes. `java` classpath/main-class resolution must consume
  that artifact provenance. Any untrusted source or processor taints output.
- **Regression:** cover directory and jar classpaths, annotation processors,
  multiple output roots, and trusted project compilation.

### T11 — Gradle init scripts execute before the build (critical)

- **Tracking ID:** `7f1fed35-77b7-4e64-aa9d-0511b9f739fd`
- **Code:** missing Gradle spec/configuration hooks.
- **Proof:** create `/tmp/init.gradle` whose initialization callback reads
  `/flag`, then run `gradle -I /tmp/init.gradle help`.
- **Mismatch:** `-I`/`--init-script` input is executed configuration code but
  is treated as an ordinary argument.
- **Required fix:** add Gradle subcommand/global option semantics. Init scripts,
  settings/build scripts, plugins, and relevant environment/config locations
  are code-bearing inputs; external/generated inputs emit unknown execution.
- **Regression:** cover `-I`, `--init-script=`, multiple scripts, user-home
  init scripts, Kotlin DSL, and a trusted build.

### T12 — `zig run` executes external/generated source (critical)

- **Tracking ID:** `93f71fcd-511a-4e96-a8c6-6c5ba6e5c859`
- **Code:** missing Zig command spec.
- **Proof:** create `/tmp/x.zig` whose `main` reads `/flag`, then run
  `zig run /tmp/x.zig`.
- **Mismatch:** Vetter does not classify the source or resulting execution.
- **Required fix:** model Zig subcommands (`run`, `build-exe`, `test`, `build`,
  and relevant `-M`/dependency/module arguments), code inputs, output paths,
  build scripts, and the executed artifact's provenance.
- **Regression:** distinguish `zig run` arguments after `--`, external modules,
  generated source, and trusted project source.

### T13 — Pytest automatically imports generated `conftest.py` (critical)

- **Tracking ID:** `03a2592d-d7a6-4d21-9cfb-aac3fefcd836`
- **Code:** Python/pytest implicit discovery and generated-file provenance.
- **Proof:** create a `conftest.py` in the selected test tree containing
  `def pytest_configure(config): print(open('/flag').read())`, then run
  `pytest -q`.
- **Mismatch:** no explicit source operand names the executed hook.
- **Required fix:** a pytest invocation must discover `conftest.py`, configured
  plugins, `pytest.ini`/`pyproject.toml`/`tox.ini` options, and startup paths.
  Known generated hooks are executed code; incomplete discovery is unknown.
- **Regression:** cover parent-directory discovery, `--confcutdir`,
  `--noconftest`, `-p`, `PYTEST_PLUGINS`, config `addopts`, and clean trees.

### T14 — Cargo trusts an external `--manifest-path` crate (critical)

- **Tracking ID:** `87e5f4f6-c264-4889-a9f7-9d0c58d3c16b`
- **Code:** Cargo manifest/source-root semantics and build provenance.
- **Proof:** create `/tmp/p/Cargo.toml` and `src/main.rs` whose binary reads
  `/flag`, then run `cargo run --manifest-path /tmp/p/Cargo.toml`.
- **Mismatch:** a known tool invocation masks code chosen by an external
  manifest.
- **Required fix:** treat the manifest as configuration code, derive package
  roots/targets/build scripts, and propagate every code/config dependency to
  build artifacts and `cargo run` execution. External manifests cannot inherit
  project trust.
- **Regression:** cover workspace manifests, `build.rs`, target config,
  relative manifest paths, and a trusted workspace.

### T15 — `GOFLAGS=-toolexec` injects a compiler wrapper (critical)

- **Tracking ID:** `ddb219b2-c550-4e9b-96a7-577a3d9537f7`
- **Code:** missing Go environment option-vector semantics.
- **Proof:** create `/tmp/w` which reads `/flag` and then `exec "$@"`; in a Go
  module run `GOFLAGS='-toolexec=/tmp/w' go build ./...`.
- **Mismatch:** the Go driver reparses `GOFLAGS` and executes the wrapper;
  Vetter treats the environment value as inert.
- **Required fix:** parse `GOFLAGS` with the Go command's option grammar and
  apply the `-toolexec` program role, including its optional import-path
  environment. Unknown quoting or wrapper paths become unknown execution.
- **Regression:** cover attached/separate values, multiple GOFLAGS, subcommand
  applicability, and harmless build flags.

### T16 — JVM environment options inject a native agent (critical)

- **Tracking ID:** `1b96e10f-1edc-48d9-b86d-dd16fd6facaa`
- **Code:** missing `JAVA_TOOL_OPTIONS` and `_JAVA_OPTIONS` semantics.
- **Proof:** build `/tmp/a.so` with a load-time constructor/`Agent_OnLoad` that
  reads `/flag`, then run
  `JAVA_TOOL_OPTIONS=-agentpath:/tmp/a.so java -version || :`.
- **Mismatch:** the launcher prepends environment-supplied JVM options and
  loads native code; the graph contains no code-file execution.
- **Required fix:** parse both environment variables with JVM launcher rules.
  Handle `-agentpath`, `-agentlib`, `-javaagent`, boot classpaths, and option
  precedence; loaded native/JAR agents carry their provenance.
- **Regression:** cover both variables, quoted values, Java agents, native
  agents, invalid agents which still execute a library initializer, and an
  empty value.

### T17 — `PYTHONUSERBASE` redirects automatic `usercustomize` import (critical)

- **Tracking ID:** `6a794df5-66a9-4a15-a363-827507b501b8`
- **Code:** Python startup/environment semantics.
- **Proof:** place a `usercustomize.py` that reads `/flag` under
  `/tmp/u/lib/pythonX.Y/site-packages`, then run
  `PYTHONUSERBASE=/tmp/u python -c pass`.
- **Mismatch:** Python's `site` initialization imports code from the redirected
  user site even though no explicit code path appears.
- **Required fix:** derive the user-site path for the runtime/platform and
  model automatic imports of `sitecustomize`, `usercustomize`, `.pth` import
  lines, and relevant startup toggles. If environment changes discovery and
  contents are not known, emit unknown startup code.
- **Regression:** cover `-S`, `-s`, `PYTHONNOUSERSITE`, virtual environments,
  versioned directories, `.pth` files, and normal startup.

### T18 — `RIPGREP_CONFIG_PATH` injects a `--pre` executable (critical)

- **Tracking ID:** `05a818e8-8a99-41bc-a997-7dd59eb9d657`
- **Code:** ripgrep environment/config semantics.
- **Proof:** create executable `/tmp/w` which reads `/flag`, put
  `--pre=/tmp/w` in `/tmp/rg.conf`, and run
  `RIPGREP_CONFIG_PATH=/tmp/rg.conf rg needle .`.
- **Mismatch:** ripgrep reads the config as arguments and executes the
  preprocessor; Vetter omits both semantics.
- **Required fix:** give the environment variable a recursive rg-config role,
  parse one-argument-per-line escaping, and apply normal rg option roles.
  `--pre` is a program execution and `--pre-glob` affects where it runs.
- **Regression:** cover known/dynamic configs, disabled config behavior,
  command-line override, and harmless search settings.

### T19 — Git repository config executes `core.fsmonitor` (critical)

- **Tracking ID:** `181c80a4-bf92-4cdd-8a01-54b9383f8f21`
- **Code:** Git repository/config discovery and code-bearing config keys.
- **Proof:** initialize a temporary repository, set
  `core.fsmonitor=/tmp/w` where `/tmp/w` reads `/flag`, then run `git status`.
- **Mismatch:** Vetter handles some explicit `git -c` keys but does not bind
  discovered repository config to the later subcommand execution.
- **Required fix:** resolve the selected repository/worktree and layered Git
  configs, then apply a central table of code-bearing keys to the subcommands
  which consume them. Include `core.fsmonitor` and preserve provenance of the
  config and hook executable. Unknown config layers imply configured-code
  `Unknown` for affected operations.
- **Regression:** cover local/global/system/worktree config, `-C`,
  `GIT_CONFIG_*`, boolean fsmonitor forms, override precedence, and a repository
  with no hook.

### T20 — GCC forwarded preprocessor options hide an include read (high)

- **Tracking ID:** `5f2b7bf2-8136-474c-bcac-438c8613e727`
- **Code:** GCC forwarded-option handling in toolchain specs.
- **Proof:**
  `gcc -E -x c - -Xpreprocessor -include -Xpreprocessor /flag <<< ''`
- **Mismatch:** GCC passes `-include /flag` to the preprocessor, which reads the
  file; Vetter sees disconnected plain arguments.
- **Required fix:** use a state machine for `-Xpreprocessor` tokens and apply
  the preprocessor option grammar after reconstruction. Model `-include`,
  `-imacros`, response files, plugin loads, and other file-bearing forwarded
  options. A dangling/unknown forwarded sequence becomes unknown.
- **Regression:** cover direct and forwarded forms, multiple pairs, attached
  values, response files, and missing values.

## Regression suite layout

Add one minimal entry per proof to the relevant corpus family:

- Bash/Unix: `corpus/bash/{expansion,comments-env,arguments,options}.toml` and
  a new indirect-input/toolchain family if that keeps cases clearer;
- cmd: `corpus/cmd/{arguments,expansion}.toml`;
- PowerShell: `corpus/powershell/{arguments,expansion}.toml`;
- cross-toolchain provenance: `corpus/harmless/toolchains.toml` plus a new
  malicious toolchain corpus rather than mixing expected-deny cases into the
  harmless file.

For every case, add resolver golden coverage in addition to corpus decision
coverage. Tests which need a generated file should create it in a fresh
temporary directory and pass its known content/provenance into the resolver.
Tests for `less`, Windows shells, and runtime/version differences should be
marked as integration/oracle tests rather than weakened to parser assertions.

The minimum CI matrix is:

| Platform/runtime | Purpose |
|---|---|
| Bash 5.1 | Associative-subscript and older expansion behavior |
| Latest supported Bash 5.x | Current behavior and non-regression |
| GNU userland matching production baseline | option abbreviations, file-list/config semantics |
| Native Windows `cmd.exe` | cmd expansion, FOR, COPY, drive/stack behavior |
| Windows PowerShell 5.1 | agent-default compatibility |
| PowerShell 7.x | current PowerShell behavior |
| At least one JDK 11+ | Java source mode and launcher environment |
| Representative Go/Rust/C/C++/Zig toolchains | wrapper, plugin, and artifact provenance |

For tools whose versions differ, query and save the version beside an oracle
result. A version-dependent pass must not silently become a global semantic
assumption.

## Definition of done

A remediation release is ready when all of the following are true:

- all 49 active proofs produce the real sensitive action or `Unknown`;
- no proof is allowed by the stock policy;
- each fix has a harmless counterpart which remains allowed when its behavior
  is fully known;
- recursion, unroll, and parse budgets have explicit conservative fallbacks;
- generated/downloaded/external provenance survives every compiler/build step;
- Windows path identity includes cwd stacks and reparse-point aliases;
- Bash/PowerShell/cmd runtime differences are selected by profile or unioned;
- the five fixed historical cases below remain covered.

## Historical cases verified fixed

These are not part of the 49 active findings, but must stay in regression
coverage:

1. `cat -n /flag` — option/operand consumption now preserves the read.
2. `xargs -a /flag` — the argument file is modeled as a read.
3. `file -f /flag` — the exact option spelling is modeled as a read. B15 is
   the remaining abbreviation variant.
4. Grouped GNU sed `e` commands — embedded shell execution is recovered.
5. Direct AWK `getline` — direct file input is recovered. B09/B10 are distinct
   mutation and escape-decoding variants.

Do not close an active item solely because one of these literal commands is
blocked; the active findings exercise a different semantic path.
