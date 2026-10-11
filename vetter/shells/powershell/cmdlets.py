"""PowerShell's tables, made when this module is imported: the cmdlets
(specs/powershell.toml: their parameters' roles, their positions, their
aliases; specs/powershell-params.toml: every parameter PowerShell has),
powershell.exe's own options, the common parameters, the .NET types and
methods that act on the system."""

import pathlib
import tomllib
from dataclasses import dataclass

from ...paths import fold

MAX_DEPTH = 8
SPEC_FILE = pathlib.Path(__file__).resolve().parents[2] / "specs" / "powershell.toml"
PARAMS_FILE = SPEC_FILE.with_name("powershell-params.toml")


@dataclass
class Cmdlet:
    name: str
    params: dict
    positional: list
    readonly: bool
    # (a parameter's aliases: -PSPath for -LiteralPath)
    param_aliases: dict


def _load():
    with open(SPEC_FILE, "rb") as f:
        data = tomllib.load(f)
    # (every parameter, as PowerShell has them: the ones without a role
    # bind their value, or none for a switch)
    with open(PARAMS_FILE, "rb") as f:
        known = tomllib.load(f)
    cmdlets = {}
    aliases = {}
    for c in data.get("cmdlet", []):
        params = dict(c.get("params", {}))
        param_aliases = {}
        for p, info in known.get(c["name"], {}).items():
            params.setdefault(p, "flag" if info["switch"] else "plain")
            for a in info["aliases"]:
                param_aliases[fold(a)] = p
        cmd = Cmdlet(c["name"], params, list(c.get("positional", [])), c.get("readonly", False), param_aliases)
        cmdlets[fold(c["name"])] = cmd
        for a in c.get("aliases", []):
            aliases[fold(a)] = fold(c["name"])
    return cmdlets, aliases


CMDLETS, ALIASES = _load()
POWERSHELLS = {"powershell", "pwsh", "powershell_ise"}
DOWNLOADING = {"Invoke-WebRequest", "Invoke-RestMethod", "curl", "wget", "Start-BitsTransfer"}

# powershell.exe's own options: their aliases, and the ones taking a value
PS_OPTIONS = ["command", "encodedcommand", "file", "executionpolicy", "noprofile", "noninteractive", "nologo",
              "noexit", "windowstyle", "workingdirectory", "version", "inputformat", "outputformat", "sta", "mta",
              "configurationname", "psconsolefile", "encodedarguments", "help"]
PS_ALIASES = {"c": "command", "e": "encodedcommand", "ec": "encodedcommand", "enc": "encodedcommand",
              "f": "file", "ep": "executionpolicy", "ex": "executionpolicy", "nop": "noprofile",
              "noni": "noninteractive", "w": "windowstyle", "wd": "workingdirectory", "v": "version",
              "if": "inputformat", "of": "outputformat", "?": "help"}
PS_VALUED = {"executionpolicy", "windowstyle", "workingdirectory", "version", "inputformat", "outputformat",
             "configurationname", "psconsolefile", "encodedarguments"}


# Every cmdlet's common parameters: their values aren't positional arguments
COMMON_PARAMS = {
    "ErrorAction": "plain", "WarningAction": "plain", "InformationAction": "plain", "ErrorVariable": "plain",
    "WarningVariable": "plain", "InformationVariable": "plain", "OutVariable": "plain", "OutBuffer": "plain",
    "PipelineVariable": "plain", "Verbose": "flag", "Debug": "flag", "WhatIf": "flag", "Confirm": "flag",
}
COMMON_ALIASES = {"ea": "ErrorAction", "wa": "WarningAction", "infa": "InformationAction", "ev": "ErrorVariable",
                  "wv": "WarningVariable", "iv": "InformationVariable", "ov": "OutVariable", "ob": "OutBuffer",
                  "pv": "PipelineVariable", "vb": "Verbose", "db": "Debug", "wi": "WhatIf", "cf": "Confirm"}

# .NET: the types whose static methods act on the system, and the methods
# that do, whatever they're called on
RISKY_TYPES = ("io.file", "io.directory", "io.fileinfo", "io.directoryinfo", "net.", "diagnostics.process",
               "reflection.", "scriptblock", "management.automation.", "activator", "runtime.interopservices",
               "microsoft.win32.registry", "environment", "appdomain", "type")
RISKY_METHODS = {
    "invoke", "invokereturnasis", "begininvoke", "create", "addscript", "downloadstring", "downloadfile",
    "downloaddata", "uploadstring", "uploadfile", "uploaddata", "openread", "openwrite", "getresponse", "send",
    "sendasync", "getasync", "postasync", "start", "delete", "writealltext", "writeallbytes", "writealllines",
    "appendalltext", "appendalllines", "copy", "move", "replace", "kill", "load", "loadfile", "loadfrom",
    "createinstance", "invokemember", "getdelegateforfunctionpointer", "setvalue", "createsubkey", "deletesubkey",
    "deletesubkeytree", "deletevalue", "setenvironmentvariable", "shellexecute", "run", "exec", "createobject",
    "invokescript", "newscriptblock", "expandstring", "invokeasync",
}
