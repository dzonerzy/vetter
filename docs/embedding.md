# Embedding and native builds

vetter is written in [zrun](https://github.com/dzonerzy/zsuite)'s strict
subset of Python. The same code runs three ways:

| Form | Used by | Speed |
|---|---|---|
| Python (zrun's reference mode) | the `vetter` CLI, `python -m vetter hook` | about 70 ms per hook call, most of it Python starting |
| A standalone executable | agents' hooks | about 1.7 ms per call |
| A shared library with a C API | your own harness | about 90 µs per decision |

The executable and the library are compiled ahead of time by
`zrun.build_native`, and have no Python in them.

## Building

Building needs Zig, through the `ziglang` package:

```console
$ pip install '.[build]'
$ python -m vetter.build vetter-hook     # ./vetter-hook claude [--policy FILE]
$ python -m vetter.build libvetter       # libvetter.so and libvetter.h
```

`vetter.build.build(output, target="x86_64-windows")` builds a Windows one
from Linux.

## The standalone hook

`vetter-hook AGENT [--policy FILE]` behaves exactly like `vetter hook
AGENT`: the agent's request on standard input, its answer on standard
output. It's one executable of about 11 MB. On Windows it reads the system
as Windows does (`USERPROFILE`, PowerShell as the agents' shell). It logs
as the Python hook does, with the same masking.

To use it, point the agent's hook command at the executable instead of
`python -m vetter hook`.

## The C library

`libvetter` exposes zrun's C API (the header `libvetter.h` beside the
library). It has one function, `vet`, taking the command, its shell, the
working directory and a policy file. Each but the command can be `""` for
its default: the system's shell, the current directory, your policy (else
the stock one).

```c
#include <stdio.h>
#include <string.h>
#include "libvetter.h"

static zrun_value str(const char *s) {
    zrun_value v = {ZRUN_STR};
    v.as.s.ptr = s;
    v.as.s.len = strlen(s);
    return v;
}

int main(void) {
    if (zrun_init(0, NULL) != 0) return 1;          /* once per process */
    zrun_value args[4] = {str("rm -rf ~"), str("bash"), str("/home/u/project"), str("")};
    zrun_value out;
    if (zrun_call("vet", args, 4, &out) != 0) {
        fprintf(stderr, "%s\n", zrun_error());
        return 1;
    }
    printf("%.*s\n", (int)out.as.s.len, out.as.s.ptr);
    return 0;
}
```

The result is a JSON string: `{"decision", "reason", "rule", "by",
"span"}`. Calls must come from one thread at a time.

## Performance

Compiled, a command is read, resolved and decided by the stock policy in
about 90 µs for bash, 90 µs for cmd and 65 µs for PowerShell. The policy
loads in about 0.18 ms.

A hook call takes about 1.6 ms in all, of which the decision is 0.02 ms.
The rest is the executable starting (an empty one takes 0.6 ms) and building
its tables (about 1 MB of specs, cmdlets and built-in policies), mostly the
kernel's page faults.

## How it's checked

Every test runs its part in both of zrun's modes, as Python and compiled,
and compares with recorded answers (`tests/golden/`). `pytest --build`
builds the executable and the library and asks them the same questions. See
[Development](development.md#tests).
