"""The command specs (the *.toml here, see README.md) read when this
module is imported: each program's spec, by every name it has, and the
environment variables that run code. specs/__init__.py makes its records
of them."""

import pathlib
import tomllib

SPEC_DIR = pathlib.Path(__file__).resolve().parent


class Spec:
    def __init__(self, data, names=None):
        self.names = names or data.get("name", [])
        self.roles = dict(data.get("roles", {}))
        self.values = set(data.get("values", [])) | set(self.roles)
        self.flags = dict(data.get("flags", {}))
        self.operands = data.get("operands", "plain")
        self.subcommands = data.get("subcommands", False) or bool(data.get("sub"))
        self.stop_at_operand = data.get("stop_at_operand", self.subcommands)
        self.single_dash_long = data.get("single_dash_long", False)
        # (Windows programs: /i, /G:file are options, not paths)
        self.slash_options = data.get("slash_options", False)
        # (it only reads: with no path named, what it reads is where it runs)
        self.readonly = data.get("readonly", False)
        # (an interpreter: with no program given, its program is on stdin)
        self.stdin_program = data.get("stdin_program", False)
        # (options whose value may be glued to them: -B/dir, -ofile)
        self.attached = list(data.get("attached", []))
        # (options taken wherever they are, before a subcommand or after:
        # their roles)
        self.anywhere = dict(data.get("anywhere", {}))
        # (an operand @file: more options read from the file)
        self.response_files = data.get("response_files", False)
        # (options giving what the first operand is otherwise: grep -e)
        self.pattern_options = list(data.get("pattern_options", []))
        # (strict: an option not listed is an Unknown; switches: options
        # with no value known to change nothing; families: prefixes whose
        # options do (-W..., -Xmx...))
        # (true: for each of its names; a list: for those)
        strict = data.get("strict", False)
        self.strict = set(self.names) if strict is True else set(strict or [])
        self.switches = set(data.get("switches", []))
        self.families = list(data.get("families", []))
        # (options after which the rest are the code's arguments: python -m)
        self.final = list(data.get("final", []))
        self.config = {k.lower(): v for k, v in data.get("config", {}).items()}
        self.sub = {k: Spec(v) for k, v in data.get("sub", {}).items()}
        # (every subcommand it has, those with roles or not: for the
        # policies' checks; empty: not known)
        self.commands = set(data.get("commands", [])) | set(self.sub)


def _load():
    specs = {}
    env = {}
    for path in sorted(SPEC_DIR.glob("*.toml")):
        with open(path, "rb") as f:
            data = tomllib.load(f)
        env.update(data.get("env", {}))
        entries = data.get("spec", [])
        if "name" in data:
            entries = [data] + entries
        for entry in entries:
            spec = Spec(entry)
            for n in spec.names:
                specs[n] = spec
    return specs, env


SPECS, ENV = _load()
