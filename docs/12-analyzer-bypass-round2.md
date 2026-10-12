# Analyzer bypass audit, round 2

Date: 2026-10-12

Target: Vetter 0.0.1, commit 2c358af

Policy: built-in stock policy
Result: 40 runtime-verified bypass families: 39 critical and 1 high

This is a fresh audit of the tree after the remediation recorded in
11-analyzer-remediation.md. Every entry below still returns allow on commit
2c358af and has a matching real-runtime oracle. The general test suite was not
used as evidence: each result is a differential between Vetter's action graph
and Bash 5.1, native cmd.exe, Windows PowerShell 5.1, or the named tool.

The fixed env -C/--chdir and hash -p cases are intentionally excluded. Vetter
now sees /flag for the former and the bound executable for the latter.

## Evidence convention

Linux proofs used a sentinel file containing:

    ROUND2_SENTINEL_4f8d3a91

Commands below use /flag to show the exploit shape. The runtime oracle replaced
/flag with the sentinel path. Windows proofs use C:\flag in exploit form and
C:\Windows\win.ini as the harmless oracle. An allow means the exact current CLI
returned decision=allow; it does not merely mean that a parser helper accepted
the input.

Reusable wrapper payloads have this shape:

    #!/bin/sh
    cat /flag
    exec "$@"

For JVM and compiler-agent proofs, a shared object constructor read the oracle
before the runtime rejected the intentionally minimal agent. Thus code
execution was observed even where the enclosing build later exited nonzero.

Runtime versions used include Bash 5.1.16, Python 3.12.15, GNU Make 4.3,
Cargo/rustc 1.90.0, Go 1.25.1, CMake 3.30.5, Clang 19.1.6, OpenJDK 17,
javac 11, Gradle 4.4.1, gawk 5.1.0, mawk 1.3.4, Info-ZIP 3.0/UnZip 6.0,
7-Zip 16.02, xz 5.2.5, uv 0.12.23, pytest 9.1.1, npm 11.13.0,
Windows PowerShell 5.1.22621.4249, and cmd.exe 10.0.22621.4317.

## Summary

| ID | Severity | Bypass |
|---|---|---|
| B01 | Critical | Bash pushd +N stack rotation desynchronizes cwd |
| B02 | Critical | Bash declare -n nameref redirects later assignments |
| B03 | Critical | export NAME does not export the tracked value |
| B04 | Critical | set -a/allexport is not stateful |
| B05 | Critical | BASH_CMDS and BASH_ALIASES bypass lookup tracking |
| B06 | Critical | GNUMAKEFLAGS injects Make options and makefile code |
| B07 | Critical | GNU time -o hides a protected startup-code write |
| C01 | Critical | cmd /K consumes unanalyzed stdin |
| C02 | Critical | cmd current-directory search runs generated git.cmd |
| C03 | Critical | COMSPEC replacement executes through FOR /F |
| C04 | Critical | delayed !CD! remains stale after cd |
| P01 | Critical | PowerShell -NoExit consumes unanalyzed stdin |
| P02 | Critical | named location stacks collapse into one stack |
| P03 | Critical | aliased PSDefaultParameterValues mutations are missed |
| P04 | Critical | WMI InvokeMethod launches an arbitrary process |
| P05 | Critical | AppDomain.ExecuteAssembly runs an untracked assembly |
| P06 | Critical | MemoryMappedFile reads/writes bypass file capabilities |
| T01 | Critical | RUSTFLAGS and CARGO_ENCODED_RUSTFLAGS inject linker code |
| T02 | Critical | Cargo program-selector environment variables execute |
| T03 | Critical | CARGO_HOME redirects Cargo configuration |
| T04 | Critical | GOENV reintroduces hidden GOFLAGS |
| T05 | Critical | GOCACHEPROG executes an arbitrary cache helper |
| T06 | Critical | javac -J and JDK_JAVAC_OPTIONS load code |
| T07 | Critical | Gradle/JVM environment and system properties load agents |
| T08 | Critical | CMake environment hooks execute scripts and launchers |
| T09 | Critical | Git repository/global config selectors evade scanning |
| T10 | Critical | mawk -W exec and gawk -E select hidden programs |
| T11 | Critical | AWKPATH redirects trusted @include dependencies |
| T12 | Critical | Clang --config recursively injects plugin options |
| T13 | Critical | npm --prefix selects an external package script |
| T14 | Critical | npm userconfig injects script-shell |
| T15 | Critical | UV_PYTHON selects an untracked interpreter executable |
| T16 | Critical | pytest external roots autoload conftest.py |
| T17 | Critical | generated implicit project files lose provenance |
| T18 | High | Java -Xlog:file hides an arbitrary write |
| F01 | Critical | zip -@ hides input files in stdin |
| F02 | Critical | 7z @listfile hides archived inputs |
| F03 | Critical | xz --files/--files0 hides compressed inputs |
| F04 | Critical | ZIPOPT injects zip -TT shell execution |
| F05 | Critical | extracted ZIP symlink aliases a protected tree |

## Bash state and wrapper findings

### B01 — pushd stack rotation is treated as a literal path (critical)

Proof:

    pushd / >/dev/null
    pushd /home/dzonerzy/ZigProjects/zsuite/vetter >/dev/null
    pushd +1 >/dev/null
    cat flag

Vetter models the final read as $project/+1/flag and allows it. Bash interprets
+1 as a directory-stack rotation, returns to /, and reads /flag. The safe
oracle rotated to the sentinel directory and printed the sentinel.

Root cause: builtin_effects in vetter/shells/bash/resolve.py:1144-1168 has no
directory-stack state. It treats the first non-dash pushd operand as a path;
+N and -N are not dash options and are joined to cwd.

Required fix:

- add an explicit Bash directory stack;
- implement pushd with no operand, -n, +N, and -N, plus dirs -c/-p/-v;
- make DIRSTACK a magic array tied to that state;
- merge divergent stacks conservatively and make underflow/unknown indices
  invalidate cwd rather than inventing a lexical path.

Regression: assert that the final path is /flag for the proof and cover +1,
-1, no-operand swaps, -n, direct DIRSTACK mutation, and popd.

### B02 — declare -n namerefs desynchronize variables (critical)

Proof:

    x=.
    declare -n r=x
    r=/
    cat "$x/flag"

Vetter keeps x=. and authorizes $project/flag. Bash makes r a reference to x,
so r=/ changes x and the final read is /flag.

Root cause: vetter/shells/bash/resolve.py:1185-1238 records integer, indexed,
associative, and export attributes, but not the n nameref attribute. Ordinary
assignment always updates the textual left-hand variable.

Required fix: represent variable cells and references separately; resolve
nameref chains for assignment, expansion, unset, read, printf -v, arithmetic,
and array access; detect loops; respect local/typeset scope and unset -n.

Regression: declare/typeset/local -n, chained references, array elements,
reference cycles, unset -n, and assignment through read/printf -v.

### B03 — export NAME omits the existing value (critical)

Proof:

    BASH_ENV=/tmp/payload
    export BASH_ENV
    bash -c true

The analyzer allows the command and sees only true in the child. Bash exports
the existing BASH_ENV value and the child sources payload, which read the
sentinel.

Root cause: vetter/shells/bash/resolve.py:1185-1238 updates ctx.exported only
inside the branch containing an equals sign. export NAME, declare -x NAME, and
typeset -x NAME never copy the current value into exported state.

Required fix: for each name-only export form, resolve the current cell and add
it to exported state. Preserve unknown values as unknown exported values.
Implement export -n as removal and respect function-local attributes.

Regression: export NAME, declare -x NAME, typeset -x NAME, export -n NAME, and
both known and dynamic values for BASH_ENV, PATH, RUSTC_WRAPPER, and LD_PRELOAD.

### B04 — set -a/allexport is ignored (critical)

Proof:

    set -a
    BASH_ENV=/tmp/payload
    bash -c true

This is also allow, while Bash exports every later assignment and sources the
payload. A second verified form used RUSTC_WRAPPER and Cargo.

Root cause: set handling at vetter/shells/bash/resolve.py:1241-1246 only
handles positional parameters after --. Shell option state is absent, so
allexport never affects assignments.

Required fix: track set -a/+a and set -o/+o allexport as shell state. Every
subsequent assignment must update ctx.exported while the option is set,
including assignments performed by builtins and functions.

Regression: both spellings, option toggles, subshell isolation, functions, and
modeled dangerous environment variables.

### B05 — BASH_CMDS and BASH_ALIASES bypass the new lookup model (critical)

Proof variants:

    BASH_CMDS[git]=/tmp/fake-git
    git status

    shopt -s expand_aliases
    BASH_ALIASES[git]='/tmp/fake-git'
    git status

Both commands are allowed as ordinary git status. Bash executes fake-git,
which printed the sentinel. This is a bypass of the hash -p and alias fixes in
commit 2c358af, not a duplicate of those fixed spellings.

Root cause: name lookup at vetter/shells/bash/resolve.py:909-928 consults
ctx.names, and alias/hash builtins update it at 1271-1303. Assignments to the
two magic associative arrays only update ordinary variable state.

Required fix: route known BASH_CMDS and BASH_ALIASES element writes, unsets,
compound assignments, and clears into ctx.names. Dynamic indices must
invalidate the relevant lookup table. Track expand_aliases parse boundaries.

Regression: direct element assignment, unset, compound array assignment,
dynamic keys, quoted aliases, multiline parse boundaries, and both tables.

### B06 — GNUMAKEFLAGS injects makefile code (critical)

Proof:

    GNUMAKEFLAGS='--eval=x:;cat</flag' make x

Vetter emits only run make and run project-code and allows it. GNU Make 4.3
executes the injected recipe and prints the flag. MAKEFLAGS and MFLAGS are now
modeled, but GNUMAKEFLAGS is absent from vetter/specs/env.toml.

Required fix: give GNUMAKEFLAGS the same options:make role, while preserving
GNU Make's precedence and recursive-make semantics.

Regression: --eval, -f, -C, harmless job flags, and conflicts among
GNUMAKEFLAGS, MAKEFLAGS, MFLAGS, and explicit command-line options.

### B07 — GNU time -o hides a protected startup-code write (critical)

Proof:

    /usr/bin/time -o ~/.bashrc -f 'cat /flag' true

Vetter skips -o and -f to find true, emits no write, and allows the command.
GNU time creates or truncates the selected output file; the safe oracle wrote
the exact attacker-controlled format text to the requested path. In the proof,
the resulting .bashrc contains a valid cat /flag shell command, so the next
interactive shell turns the hidden write into code execution/data disclosure.

Root cause: simple_wrapper in vetter/shells/bash/resolve.py:1638-1670 treats
time's valued options only as wrapper syntax.

Required fix: attach write semantics to -o/--output, account for -a/--append,
and keep -f/--format as data rather than shell code.

Regression: attached/separate short options, long forms, append mode, and
startup/temporary/project destinations.

## cmd.exe findings

### C01 — cmd /K consumes commands from unanalyzed stdin (critical)

Proof:

    printf 'type C:\flag\r\nexit\r\n' | cmd /d /k echo ok

Vetter records printf, cmd, and echo ok and returns allow. Native cmd.exe runs
echo ok, remains interactive because of /K, then executes type C:\flag from
the pipe. The oracle printed win.ini.

Root cause: vetter/shells/cmd/resolve.py:923-944 intentionally accepts /C and
/K through the same path, analyzes only the argument tail, and returns.

Required fix: distinguish /C from /K. For /K, parse known remaining stdin as
additional cmd source after the initial command; dynamic stdin is unknown code.
Carry CRLF, EOF, delayed-expansion, and child environment semantics.

Regression: pipes, redirected files, known here-documents, dynamic producers,
/V:on, an explicit exit, and /C as the non-continuing control.

### C02 — current-directory search executes generated git.cmd (critical)

Self-contained proof:

    (echo @type C:\flag)>git.cmd&git status

The graph contains an allowed project write followed by allowed git status.
Native cmd searches cwd before PATH, finds the just-created git.cmd through
PATHEXT, and runs it.

Root cause: simple in vetter/shells/cmd/resolve.py:637-708 dispatches the
lexical basename directly into the Git/tool specs. It does not resolve
Windows command search order or correlate the selected .cmd/.bat/.com/.exe
with earlier writes.

Required fix:

- resolve explicit and implicit extensions using the effective PATHEXT;
- search cwd before PATH according to the supported Windows profile;
- represent every possible candidate if filesystem state is ambiguous;
- feed the resolved path and provenance into generated/downloaded checks.

Regression: all PATHEXT types, extension order, an existing project shadow,
a generated same-command shadow, quoted paths, PATH changes, and an internal
command which must retain precedence.

### C03 — COMSPEC replacement executes through FOR /F (critical)

Proof:

    set COMSPEC=C:\path\payload.exe&for /f %A in ('echo ok') do @echo %A

Vetter allows the set and analyzes only echo ok as the FOR /F producer. Native
cmd invokes the replacement COMSPEC; the oracle executable printed win.ini
and its lines became loop records.

Root cause: set_env in vetter/shells/cmd/resolve.py:711-719 forwards changed
variables generically, while for_command models the backquoted text directly.
COMSPEC has no program role and no edge to the nested command processor.

Required fix: make COMSPEC a program-valued cmd state variable and resolve it
whenever cmd creates a command processor: FOR /F, pipes where applicable,
CALL/START shell fallbacks, and nested cmd launches. Unknown values are
unknown execution.

Regression: default and replaced COMSPEC, mixed-case names, quoted paths,
FOR /F, START, and restoration in child/local scopes.

### C04 — delayed !CD! is stale after cd (critical)

Proof:

    cmd /v:on /d /c "cd /d C:\ & type !CD!\flag"

With project cwd C:\Temp\vetter-project, Vetter expands !CD! to the initial
project and allows project\flag. Native cmd updates the dynamic CD
pseudo-variable and reads C:\flag.

Root cause: default_env at vetter/shells/cmd/resolve.py:38-54 initializes CD.
internal at 771-820 changes w.cwd for cd/chdir/pushd/popd but never updates
the pseudo-variable used by delayed expansion.

Required fix: derive CD from current cwd at each expansion rather than store
it as an ordinary environment value. Do the same audit for ERRORLEVEL,
CMDEXTVERSION, drive-current-directory variables, DATE, TIME, and RANDOM.

Regression: percent versus delayed expansion on one compound line, /D drive
changes, pushd/popd, nested cmd, and branch joins.

## PowerShell findings

### P01 — -NoExit consumes commands from unanalyzed stdin (critical)

Proof:

    printf 'Get-Content C:\flag\nexit\n' |
      powershell -NoProfile -NoExit -Command 'Write-Output ok'

The trusted-file variant is also affected:

    printf 'Get-Content C:\flag\nexit\n' |
      powershell -NoProfile -NoExit -File C:\project\trusted.ps1

Vetter analyzes only the safe command or trusted file. Windows PowerShell 5.1
then enters its prompt, consumes stdin, and prints the protected file.

Root cause: powershell in vetter/shells/powershell/resolve.py:1090-1147
recognizes noexit as a flag but immediately returns after -Command/-File.

Required fix: persist the NoExit mode while parsing launcher options. After
the startup payload, analyze known stdin as PowerShell source; dynamic stdin
is unknown inline code. Account for -NonInteractive and version-specific
Windows PowerShell/pwsh behavior.

Regression: -Command, -EncodedCommand, -File, safe/dynamic pipes, explicit
exit, -NonInteractive, PS 5.1, and supported pwsh versions.

### P02 — named location stacks collapse into one list (critical)

Proof shape:

    Set-Location 'C:\'
    Push-Location 'C:\Temp\vetter-project' -StackName A
    Push-Location 'C:\Temp\vetter-project' -StackName B
    Pop-Location -StackName A
    Get-Content flag

Vetter authorizes project\flag. PowerShell pops stack A back to C:\ and reads
C:\flag.

Root cause: vetter/shells/powershell/resolve.py:920-926 has one pw.locations
list and never binds StackName.

Required fix: store a map from normalized stack name to stack, bind the
parameter before state transition, and preserve provider/cwd per entry.
Unknown names must invalidate possible stacks.

Regression: two interleaved names, default stack, aliases pushd/popd,
underflow, provider-qualified locations, and control-flow joins.

### P03 — aliasing PSDefaultParameterValues hides mutation (critical)

Proof:

    $d=$PSDefaultParameterValues
    $d.Add('Get-Content:Path','C:\flag')
    Get-Content

Vetter models a default project read and allows it. PowerShell preserves
hashtable object identity, so Add changes the real preference table and
Get-Content reads C:\flag.

Root cause: method_effects at
vetter/shells/powershell/resolve.py:411-439 requires the receiver text to be
exactly $PSDefaultParameterValues.

Required fix: introduce object identities/capabilities for mutable preference
objects and propagate them through assignment, arrays, properties, arguments,
and return values. Model Add, set_Item, Remove, Clear, and unknown mutations.

Regression: one and multiple aliases, Get-Variable -ValueOnly, collection
containers, wildcard keys, explicit-parameter override, and mutation through
a helper function.

### P04 — WMI InvokeMethod launches arbitrary processes (critical)

Proof:

    $p=[wmiclass]'Win32_Process'
    $p.InvokeMethod('Create',@(
      'cmd.exe /c type C:\flag > C:\Temp\vetter-project\o',
      $null,$null))
    [Threading.Thread]::Sleep(500)
    Get-Content .\o

The analyzer sees no WMI effect and only the allowed project read of o.
PowerShell launches cmd, which copies the flag into o.

Root cause: dotnet at vetter/shells/powershell/resolve.py:252-271 recognizes
literal static receiver types and a flat risky method-name list. The wmiclass
accelerator and ManagementObject capability are untyped, and InvokeMethod is
not classified.

Required fix: use capability propagation, not a global method denylist.
WMI/CIM objects for Win32_Process must carry process-launch capability;
InvokeMethod with known Create arguments should be parsed as a child command.
Unknown instance calls on process/WMI capabilities become unknown execution.

Regression: wmiclass, Get-WmiObject, ManagementClass, ManagementObject,
InvokeMethod overloads, CIM equivalents, and a harmless query.

### P05 — AppDomain.ExecuteAssembly is invisible (critical)

Proof:

    $d=[AppDomain]::CurrentDomain
    $d.ExecuteAssembly('C:\path\payload.exe')

Vetter returns allow with no actions. PowerShell executed the managed oracle,
which printed win.ini.

Root cause: appdomain in RISKY_TYPES only helps when AppDomain is the literal
static receiver. CurrentDomain is a property, its instance loses type, and
ExecuteAssembly is absent from RISKY_METHODS in
vetter/shells/powershell/cmdlets.py:77-98.

Required fix: type/capability-tag the CurrentDomain property and model
ExecuteAssembly, ExecuteAssemblyByName, CreateInstance*, and unwrap variants
as code execution.

Regression: direct chaining, assignment, property aliases, overloads, and
dynamic assembly paths.

### P06 — MemoryMappedFile bypasses file capabilities (critical)

Proof:

    $m=[IO.MemoryMappedFiles.MemoryMappedFile]::CreateFromFile(
      'C:\flag',[IO.FileMode]::Open,'x',0,
      [IO.MemoryMappedFiles.MemoryMappedFileAccess]::Read)
    $s=$m.CreateViewStream()
    while(($b=$s.ReadByte()) -ne -1){[Console]::Write([char]$b)}

Vetter returns allow with no actions. Native PowerShell printed every byte of
win.ini. Read-write maps similarly permit protected writes.

Root cause: RISKY_TYPES includes io.file but that prefix does not match
io.memorymappedfiles. FILE_READERS/FILE_WRITERS in cmdlets.py only cover
StreamReader, BinaryReader, StreamWriter, BinaryWriter, and FileStream.

Required fix: represent MemoryMappedFile as a file capability created from
the first path and access mode; propagate it to view streams/accessors and
emit reads/writes for their lifetime. Audit other alternate System.IO
namespaces rather than broadening a brittle string prefix alone.

Regression: CreateFromFile overloads, read/write maps, view streams,
accessors, aliases, and dynamic paths.

## Toolchain, environment, and discovery findings

### T01 — Rust flag environments inject a linker (critical)

Proof variants:

    RUSTFLAGS='-C linker=/tmp/payload' cargo build

    CARGO_ENCODED_RUSTFLAGS=$'-C\x1flinker=/tmp/payload' cargo build

Both are allowed as cargo plus project-code. Cargo/rustc invoked the selected
linker; the safe wrapper copied the sentinel before delegating to cc.

Root cause: vetter/specs/env.toml models Rust wrapper variables but omits
RUSTFLAGS and CARGO_ENCODED_RUSTFLAGS. The direct rustc -C role at
vetter/specs/toolchains.toml:44-54 is never applied to environment-supplied
arguments.

Required fix: add Rust option-vector roles for both formats. The encoded form
uses unit-separator delimiters, not shell splitting. Feed recovered -C/
--codegen pairs through rustc_codegen, including linker, link-arg, llvm-args,
linker-plugin-lto, and unstable options conservatively.

Regression: text and encoded vectors, multiple -C forms, precedence, malformed
encoding, harmless optimization flags, and build-script inheritance.

### T02 — Cargo program selectors execute hidden tools (critical)

Verified allow/runtime variants:

    CARGO_BUILD_RUSTC=/tmp/rustc-proxy cargo build
    CARGO_BUILD_RUSTDOC=/tmp/rustdoc-proxy cargo doc
    CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=/tmp/linker cargo build
    CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER=/tmp/runner cargo run

Each proxy printed the sentinel. The existing RUSTC_WRAPPER and
RUSTC_WORKSPACE_WRAPPER fix does not cover these Cargo configuration
environment variables.

Root cause: environment semantics are an exact-name table. Cargo has both
fixed keys and target-triple-derived keys that map directly to executable
programs.

Required fix:

- add CARGO_BUILD_RUSTC and CARGO_BUILD_RUSTDOC program roles;
- parse CARGO_TARGET_<normalized-triple>_LINKER and _RUNNER as program or
  command-line values according to Cargo's splitting rules;
- cover corresponding configuration and command-line sources with one
  canonical Cargo configuration model.

Regression: host/target triples, hyphen-to-underscore normalization, runner
arguments, aliases, cross compilation, and missing/dynamic executable paths.

### T03 — CARGO_HOME redirects executable configuration (critical)

Proof:

    CARGO_HOME=/tmp/cargo-home cargo build

The external config.toml contained:

    [build]
    rustc = "/tmp/rustc-proxy"

Vetter allows only cargo/project-code. Cargo loads the redirected config and
executes the proxy, which printed the sentinel.

Root cause: CARGO_HOME is absent from vetter/specs/env.toml and Cargo's layered
configuration discovery is not tied to the invocation.

Required fix: make CARGO_HOME a configured-root role, discover
config/config.toml from that root and ancestor project directories, merge
layers with Cargo precedence, and apply roles to build.rustc, rustdoc,
rustc-wrapper, target linker/runner, aliases, credential-process, and future
program-bearing keys. Unknown configs are configured-code unknowns.

Regression: CARGO_HOME, project .cargo, ancestor .cargo, environment-overrides,
relative paths, includes if supported, and a clean configuration.

### T04 — GOENV reintroduces hidden GOFLAGS (critical)

Proof:

    GOENV=/tmp/goenv go build ./...

The selected file set GOFLAGS=-toolexec=/tmp/payload. Vetter sees only run go;
Go loads the file and invokes payload, which printed the sentinel.

Root cause: GOFLAGS is now parsed, but GOENV—the configuration file which
supplies it—is absent from environment semantics.

Required fix: give GOENV a recursive Go-environment-config role. Parse
key=value lines, apply the same roles as direct environment variables, handle
GOENV=off, and respect direct-environment precedence.

Regression: GOFLAGS/toolexec, CC/CXX, GOCACHEPROG, off, malformed/dynamic
files, and direct overrides.

### T05 — GOCACHEPROG executes an arbitrary helper (critical)

Proof:

    GOCACHEPROG=/tmp/payload go build ./...

The analyzer allows it. Go 1.25 starts the external cache protocol helper;
the deliberately invalid helper printed the sentinel before Go reported that
it exited with pending requests.

Root cause: GOCACHEPROG is a command line with optional arguments and is
missing from vetter/specs/env.toml.

Required fix: parse it as a command/program vector, emit the helper execution,
and fail closed when quoting or the path is dynamic.

Regression: executable only, executable plus flags, quoted paths, an empty
value, a valid helper, and GOENV-sourced GOCACHEPROG.

### T06 — javac launcher and environment options load code (critical)

Direct proof:

    javac -J-agentpath:/tmp/agent.so X.java

Environment proof:

    JDK_JAVAC_OPTIONS='-processorpath /tmp/p.jar -processor P' javac X.java

Vetter allows both and records only X.java. javac loaded the native library in
the first proof. In the second, it loaded and initialized annotation processor
P, which printed the sentinel.

Root cause:

- vetter/specs/toolchains.toml:79-99 has no -J forwarding grammar;
- vetter/specs/env.toml covers JVM launcher variables but omits
  JDK_JAVAC_OPTIONS;
- recovered javac options are not recursively passed through processor/plugin
  roles.

Required fix: split -Joption from javac options and apply Java-launcher
semantics to agent/bootclasspath/module flags. Parse JDK_JAVAC_OPTIONS with the
JDK's quoting rules, then apply normal javac processor/plugin/classpath roles.

Regression: -J-agentpath, -J-javaagent, attached/separate processor paths,
response files, environment quoting, explicit override, and harmless options.

### T07 — Gradle/JVM controls load hidden agents and Java executables (critical)

Verified variants:

    GRADLE_OPTS='-agentpath:/tmp/agent.so' gradle --version
    JAVA_OPTS='-agentpath:/tmp/agent.so' gradle --version
    JAVA_HOME=/tmp/fake-java-home gradle --version
    gradle -Dorg.gradle.jvmargs=-agentpath:/tmp/agent.so help

All commands are allowed. The agent constructor or fake JAVA_HOME/bin/java
printed the sentinel. The org.gradle.jvmargs form reached the daemon JVM.

Root cause: the Gradle spec records -D as a value but does not interpret
program-bearing system properties. GRADLE_OPTS, JAVA_OPTS, and JAVA_HOME are
absent from environment roles.

Required fix:

- model JAVA_HOME as a Java executable root for wrapper scripts;
- parse GRADLE_OPTS and JAVA_OPTS as JVM option vectors;
- interpret org.gradle.jvmargs from -D, gradle.properties, and environment;
- reuse Java agent/module/bootclasspath semantics for every recovered vector.

Regression: daemon/no-daemon, wrapper/system Gradle, Java/native agents,
quoted values, project and user gradle.properties, and command-line
precedence.

### T08 — CMake environment hooks execute code (critical)

Verified variants:

    CMAKE_TOOLCHAIN_FILE=/tmp/toolchain.cmake cmake -S . -B /tmp/b

    CMAKE_C_COMPILER_LAUNCHER=/tmp/payload \
      cmake -S . -B /tmp/b && cmake --build /tmp/b

The toolchain used execute_process to print the sentinel. The compiler
launcher printed it before delegating to cc. Both commands are allowed.

Root cause: CMAKE_CODE and CMAKE_PROGRAMS in
vetter/specs/__init__.py:311-316 apply only to -D definitions. CMake also
initializes code/program variables directly from environment variables, and
language-specific launcher names require wildcard handling.

Required fix: centralize CMake variable semantics and apply them to -D,
environment, presets, cache files, and toolchain files. Include at least
CMAKE_TOOLCHAIN_FILE, project include hooks, user-rule overrides,
CMAKE_<LANG>_COMPILER_LAUNCHER, linker launchers, compilers, make program,
module paths, and prefix paths.

Regression: configure versus build phase, C/CXX variants, multiple launchers,
fresh/cached build trees, presets, and explicit overrides.

### T09 — selected Git config layers evade cwd scanning (critical)

Verified selectors:

    git -C /tmp/evil-repo status
    git --git-dir=/tmp/evil-repo/.git --work-tree=/tmp/evil-repo status
    GIT_DIR=/tmp/evil-repo/.git GIT_WORK_TREE=/tmp/evil-repo git status
    XDG_CONFIG_HOME=/tmp/xdg git status
    HOME=/tmp/fakehome git status

Each selected config contained core.fsmonitor=/tmp/payload. Vetter allowed
git status; Git invoked the hook and copied the sentinel.

This is an incomplete-remediation bypass of the cwd repository-config fix.
Although git -C has a cwd role in vetter/specs/git.toml:18-24, repo_config in
vetter/gitconfig.py:41-85 snapshots only the execution's original cwd. Global
config roots selected by HOME/XDG_CONFIG_HOME are not scanned.

Required fix:

- resolve all global Git options and GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR
  before config discovery;
- construct Git's full system/global/XDG/local/worktree config stack from the
  effective environment;
- follow include/includeIf with cycle/depth bounds;
- apply one code-bearing-key table after precedence and command relevance.

Regression: every selector above, mixed selectors, worktrees, bare repos,
includes, override-to-safe, boolean fsmonitor, and absent configs.

### T10 — implementation-specific AWK program selectors are omitted (critical)

Proofs:

    mawk -W exec=/tmp/payload.awk README.md
    gawk -E /tmp/payload.awk README.md

Vetter sees only README.md and allows both. mawk and gawk execute the selected
AWK program, which called system and printed the sentinel.

Root cause: the shared entry at vetter/specs/files.toml:451-462 covers -f,
gawk -e, includes, and extensions, but not mawk's -W exec or gawk's
-E/--exec.

Required fix: use implementation/version profiles. Canonicalize mawk -W
suboptions and gawk -E/--exec to code_file, including attached/separate forms.
Unknown -W suboptions should not silently become inert.

Regression: both implementations, option placement, attached values,
end-of-options behavior, and benign implementation-specific switches.

### T11 — AWKPATH redirects a trusted include (critical)

Fixture in a trusted project script:

    @include "p.awk"
    { print $0 }

Proof:

    AWKPATH=/tmp/modules gawk -f tools/trusted.awk README.md

Vetter allows the trusted script and README. gawk resolves p.awk through the
external AWKPATH and executes it; the module printed the sentinel.

Root cause: AWKPATH is absent from environment semantics, and code_file trust
for the top-level -f script does not preserve dependencies discovered by the
AWK language.

Required fix: model AWKPATH as a code search path, parse @include/@include_once
in known AWK programs, resolve dependencies with gawk precedence, and mark
unknown/dynamic includes as unknown code. Apply analogous AWKLIBPATH semantics
to native extensions.

Regression: project/external modules, multiple search roots, missing modules,
nested includes, AWKLIBPATH, and explicit paths which bypass search.

### T12 — Clang --config recursively injects plugin options (critical)

Proof:

    clang --config=/tmp/evil.cfg -c /tmp/x.c

evil.cfg contained:

    -Xclang
    -load
    -Xclang
    /tmp/plugin.so

Vetter records only x.c and allows the compiler. Clang 19 loads plugin.so; its
constructor printed the sentinel.

Root cause: vetter/specs/toolchains.toml:7-28 supports response files and
forwarded options, but --config is neither a valued option nor a recursive
argument source.

Required fix: give --config a Clang-config role, parse its tokenization and
nested behavior, then feed recovered arguments back through the full driver
and forwarded-option pipeline. Dynamic/unreadable configs are configured-code
unknowns.

Regression: equals/separate forms accepted by supported Clang versions,
relative paths, nested response files, plugins, includes, linker programs,
and a harmless config.

### T13 — npm --prefix selects external lifecycle code (critical)

Proof:

    npm --prefix C:\Temp\evilpkg test

The external package.json test script was:

    type C:\flag

Vetter emits only run npm and allows it. Native npm executes the external
script and the oracle printed win.ini.

Root cause: the npm entry at vetter/specs/dev.toml:44-75 models subcommands
and explicit script-shell, but has no project-root options and does not bind
package_script to a resolved package.json.

Required fix: parse --prefix/--workspace/--workspaces and tool-specific cwd
options before subcommand resolution. Load the selected manifest, emit its
script as shell code with manifest provenance, and reject external/generated
manifests under the stock policy.

Regression: --prefix before/after subcommand, npm test/run/start, workspaces,
Windows/Linux paths, a trusted project, and a generated manifest.

### T14 — npm userconfig injects script-shell (critical)

Proof variants:

    npm --userconfig C:\Temp\evil.npmrc --prefix C:\Temp\project test

    set npm_config_userconfig=C:\Temp\evil.npmrc&&npm test

evil.npmrc set script-shell=C:\Temp\payload.exe. Both commands are allowed;
native npm launched payload.exe, which printed win.ini.

Root cause: --userconfig/--globalconfig and npm_config_userconfig are absent.
Only direct npm_config_script_shell is modeled in vetter/specs/env.toml.

Required fix: discover and merge npm configuration sources, recursively apply
roles to script-shell/node-options and other program-bearing keys, normalize
environment keys per platform, and honor command-line precedence.

Regression: command-line and environment selectors, per-project/user/global
files, Windows case-insensitivity, explicit safe override, and unreadable
config.

### T15 — UV_PYTHON executes a hidden interpreter (critical)

Proof:

    UV_PYTHON=/tmp/python-proxy uv run --no-project python --version

Vetter allows uv and the modeled child python. uv executes python-proxy while
locating/running the interpreter; the ELF proxy printed the sentinel before
delegating to /usr/bin/python3.

Root cause: direct --python receives program treatment through argument
handling, but its UV_PYTHON environment equivalent is absent from
vetter/specs/env.toml.

Required fix: add UV_PYTHON as the same interpreter/program selector used by
-p/--python. Also audit UV_PROJECT, UV_CONFIG_FILE, active virtual
environment, tool-bin, and Python-download settings as discovery inputs.

Regression: binary and symlink/script interpreters, --no-project/--isolated,
explicit override, active virtual environments, and dynamic values.

### T16 — pytest external roots autoload conftest.py (critical)

Proof:

    pytest -q /tmp/evil-tests

/tmp/evil-tests/conftest.py read /flag in pytest_configure. Vetter records only
run pytest and allows it; pytest imported the hook and printed the sentinel.

This is a still-active variant of the prior conftest finding: selecting an
external tree remains entirely unmodeled, not merely same-command generation.

Required fix: add a pytest spec that resolves test roots, config roots,
conftest discovery up the parent chain, plugin options/environment, and
PYTHONPATH/import dependencies. External or generated hooks are code inputs.

Regression: external/trusted roots, parent conftest, --confcutdir,
--noconftest, -p, PYTEST_PLUGINS, addopts, and no-test collections which still
run hooks.

### T17 — generated implicit project files lose provenance (critical)

Seven same-command families were verified:

1. write .r2make/Makefile with a flag-reading recipe, then make -C .r2make x;
2. write .r2ninja/build.ninja, then ninja -C .r2ninja;
3. write .r2cmake/CMakeLists.txt, then cmake -S .r2cmake -B ...;
4. write .r2pytest/conftest.py, then pytest -q .r2pytest;
5. write .r2npm/package.json, then npm --prefix .r2npm test;
6. write Cargo.toml/src/main.rs, cd into the crate, then cargo run;
7. write .git/config with core.fsmonitor, then git -C that repo status.

Every command is allow and every runtime executes the generated code/hook.

Root cause: generated in vetter/policy/actions.py:130-157 compares explicit
write paths only to explicit run paths. Implicit discovery produces a generic
run project-code or no code path at all, so there is no producer/consumer edge.
Some config scanning also occurs against the pre-command filesystem snapshot.

Required fix:

- make tool actions name every consumed project/config/code path;
- represent directory/tree outputs and implicit descendants;
- maintain same-command virtual filesystem/provenance state;
- delay filesystem-backed discovery until preceding modeled writes are
  applied, or conservatively mark the discovered input generated/unknown;
- propagate source/config provenance to build output and execution.

Regression: all seven families in one-command form, preexisting trusted files,
overwrite/rename/symlink creation, nested project roots, and branch/pipeline
ordering.

### T18 — Java unified logging hides a protected write (high)

Proof:

    java -Xlog:all:file=~/.bashrc -version

Vetter emits only run java and allows it. OpenJDK created the selected file;
the safe oracle wrote about 79 KB of logs.

Root cause: vetter/specs/toolchains.toml:56-76 models code-loading Java
options but not output-bearing -Xlog syntax.

Required fix: parse -Xlog output clauses, including file= paths, rotation
options, stdout/stderr, quoting, and disable/reconfiguration forms. Emit write
or append/truncate effects according to the runtime profile.

Regression: protected/project/temp destinations, file rotation, multiple
-Xlog options, stdout/stderr, and JDKs before unified logging.

## Indirect file and archive findings

### F01 — zip -@ hides files read from stdin (critical)

Proof:

    printf '/flag\n' |
      zip -q /tmp/a.zip -@ &&
      unzip -p /tmp/a.zip

Vetter records the archive write/read but no /flag read and returns allow.
Info-ZIP reads newline-delimited filenames from stdin, archives /flag, and the
second command prints it.

Root cause: the zip spec at vetter/specs/files.toml:505-518 omits -@ and has no
stdin file-list role.

Required fix: model -@ as a newline filename list sourced from the execution's
stdin. Parse known stdin into read actions; dynamic stdin is an unknown input
set. Preserve path decoding and the interaction with ordinary operands.

Regression: pipe/here-string/redirected list, spaces, dash-leading names,
mixed explicit/list inputs, empty input, and dynamic producers.

### F02 — 7z @listfile hides archived inputs (critical)

Proof:

    printf '/flag\n' >/tmp/l
    7z a -y /tmp/a.7z @/tmp/l
    7z x -so /tmp/a.7z

Vetter treats @/tmp/l as a literal project-relative input and also assigns
mode-insensitive archive roles. It never emits read /flag, so the sequence is
allow. 7-Zip archives and prints the flag.

Root cause: vetter/specs/files.toml:528-535 has only attached output/options
and a single operands layout. 7-Zip listfile expansion and subcommand-specific
archive/input/output roles are absent.

Required fix: parse the 7z subcommand first; recursively process @listfile and
-i@/-x@ forms with charset switches; apply archive read/write and extracted
tree effects per mode. Unknown lists imply unknown input sets.

Regression: a/u/x/e/l/t modes, UTF list encodings, nested/list switches,
wildcards, exclusions, and generated list files.

### F03 — xz --files and --files0 hide compressed inputs (critical)

Proof:

    printf '/flag\n' >/tmp/l
    xz -c --files=/tmp/l >/tmp/a.xz
    xzcat /tmp/a.xz

Vetter emits only write /tmp/a.xz for xz and read /tmp/a.xz for xzcat. xz
reads every name in the list, so the oracle prints the sentinel.

Root cause: the shared gzip/bzip2/xz entry at
vetter/specs/files.toml:485-491 omits xz-specific --files and --files0.

Required fix: split implementation-specific compressor profiles or add the
two options with newline/NUL file-list roles. Known list entries are reads;
dynamic contents are an unknown read set.

Regression: optional =FILE, stdin list when omitted, --files0, odd filenames,
compress/decompress/list modes, and explicit operands.

### F04 — ZIPOPT injects a hidden test command (critical)

Proof:

    ZIPOPT='-T -TT /tmp/payload' \
      zip -q /tmp/a.zip README.md

Vetter sees a normal allowed archive write and project read. Info-ZIP reparses
ZIPOPT, enables archive testing, and executes payload as the replacement
unzip command. The oracle printed the sentinel.

Root cause: ZIPOPT is absent from vetter/specs/env.toml, despite the zip spec
already assigning -TT/--unzip-command a shell role.

Required fix: parse ZIPOPT through the same versioned zip option grammar as
the command line, then apply every recovered role. Unknown splitting is
unknown configured execution.

Regression: -TT attached/separate, -T ordering, explicit override, harmless
defaults, long-option abbreviations, and an empty value.

### F05 — ZIP extraction creates an untracked symlink alias (critical)

The following base64 is a complete ZIP containing one Unix symlink entry:
proc/self/root points to /.

    UEsDBAoAAAAAAPkZTF3U0tN5AQAAAAEAAAAOABwAcHJvYy9zZWxmL3Jvb3RVVAkAA8Y0zGrGNMxqdXgLAAEE6AMAAAToAwAAL1BLAQIeAwoAAAAAAPkZTF3U0tN5AQAAAAEAAAAOABgAAAAAAAAAAAD/oQAAAABwcm9jL3NlbGYvcm9vdFVUBQADxjTManV4CwABBOgDAAAE6AMAAFBLBQYAAAAAAQABAFQAAABJAAAAAAA=

Self-contained proof:

    printf %s 'UEsDBAoAAAAAAPkZTF3U0tN5AQAAAAEAAAAOABwAcHJvYy9zZWxmL3Jvb3RVVAkAA8Y0zGrGNMxqdXgLAAEE6AMAAAToAwAAL1BLAQIeAwoAAAAAAPkZTF3U0tN5AQAAAAEAAAAOABgAAAAAAAAAAAD/oQAAAABwcm9jL3NlbGYvcm9vdFVUBQADxjTManV4CwABBOgDAAAE6AMAAFBLBQYAAAAAAQABAFQAAABJAAAAAAA=' |
      base64 -d >/tmp/rootlink.zip
    unzip -qo /tmp/rootlink.zip -d .
    cat proc/self/root/flag

Vetter returns allow. It models one write to the project directory and then a
lexically project-local read at $project/proc/self/root/flag. UnZip creates the
symlink, so the actual read is /flag. The safe oracle followed the same link
to /tmp/.../sentinel and printed the sentinel.

Root cause: the unzip spec treats extraction as an undifferentiated directory
write. No archive member, type, target, path traversal, or generated
provenance reaches later path resolution. The lexical path-alias map therefore
cannot see aliases created by extractors.

Required fix:

- for known archives, enumerate and validate member paths and types before
  extraction;
- add write effects for each materialized path and alias effects for symbolic
  links, hard links, junction/reparse analogues, and path traversal;
- taint unknown extraction destinations as generated trees whose descendants
  cannot be treated as trusted merely by lexical containment;
- resolve subsequent authorization against path identity/alias state, not
  only normalized spelling.

Apply the same model to tar, 7z, package installers, and build tools that can
materialize links.

Regression: self-contained generated archive, existing archive, relative and
absolute symlink targets, hard links, link chains, ../ entries, overwrite of
an existing directory, extraction then rename, and a regular-file archive.

## Cross-cutting repair plan

Literal additions will close individual commands but leave the same bug class
open. The shortest durable repair is:

1. **State objects with identity.** Shell variables, references, exported
   status, aliases, command hashes, cwd stacks, PowerShell hashtables, and
   typed .NET/WMI objects need explicit identities and scoped state.

2. **Recursive configuration inputs.** A selected config, option vector,
   response file, list file, manifest, or preset must be parsed into the same
   semantic pipeline as explicit arguments. Maintain a registry by tool and
   version, including wildcard environment names.

3. **Effective invocation before allowlisting.** Resolve cwd, repository or
   project selectors, config layers, executable search, wrappers, and child
   launchers before matching the convenient lexical tool name against stock
   allow rules.

4. **Persistent provenance within a command.** Model a virtual filesystem for
   prior writes, renames, links, extracted trees, and generated configs.
   Implicitly discovered code must name its source path so generated and
   downloaded provenance can propagate.

5. **Capability-based PowerShell/.NET analysis.** Constructors, properties,
   casts, WMI accelerators, aliases, and methods should consume/return
   capabilities such as file-reader(path), file-writer(path), process-launcher,
   code-loader, location-stack(name), and parameter-defaults. Unknown calls on
   a sensitive capability must become Unknown.

6. **Interactive continuation as a source.** Interpreter modes such as
   Python -i, cmd /K, and PowerShell -NoExit require a second source phase
   after the explicit safe payload. Known stdin is parsed; unknown stdin is
   unknown code.

## Minimum regression matrix

For each proof, require both:

- a resolver/action assertion showing the hidden file/program/config edge; and
- a real-runtime oracle asserting that the candidate actually executes or
  accesses the sentinel.

At minimum run:

| Runtime/tool | Required coverage |
|---|---|
| Bash 5.1 and latest supported Bash | nameref, magic arrays, pushd, export state |
| Native cmd.exe | /K, current-directory search, COMSPEC, delayed pseudo-vars |
| Windows PowerShell 5.1 and supported pwsh | NoExit, named stacks, WMI/.NET capabilities |
| GNU Make, Cargo/rustc, Go, CMake, Clang | environment/config program selectors |
| JDK 11+ and current JDK | javac -J/JDK_JAVAC_OPTIONS, Gradle, Java logging |
| npm/uv/pytest | external project/config/interpreter discovery |
| Info-ZIP, 7-Zip, xz | indirect lists, option environments, extracted aliases |

The oracle must save exact tool versions beside results. A parser-only test is
not sufficient for environment/config discovery, executable search,
interactive continuation, archive extraction, or Windows shell semantics.

## Prioritization

Suggested implementation order:

1. C02, F05, and T17: provenance/path identity failures affect many tools.
2. B03/B04, B05, C01, P01: small state/source fixes with broad bypass impact.
3. P04-P06: replace method denylisting with capabilities.
4. T01-T15 and F01-F04: central recursive config/list/option machinery.
5. B01/B02, C03/C04, P02/P03: complete mutable shell-state semantics.
6. B07/T18: protected output roles.

Until the structural work lands, a safe stopgap is to ask on:

- interpreter continuation modes;
- unmodeled environment changes before allowlisted build/package tools;
- external project/config selectors;
- archive extraction followed by access below the extraction root;
- cmd invocations when a matching cwd executable exists or was just written;
- PowerShell instance calls whose receiver/type cannot be proven harmless.
