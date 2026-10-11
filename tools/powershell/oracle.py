"""PowerShell's own reading of commands: its parser
(System.Management.Automation.Language.Parser), run in one PowerShell
process for a whole batch.

For each command: the parse errors, and every command the parser finds
(CommandAst, nested ones too: in script blocks, subexpressions), in source
order: its invocation operator (& or . or none), its elements (type, the
text as written, the value for a constant string, the name for a
parameter), its redirections.

    from tools.powershell.oracle import Oracle
    Oracle().read(["Remove-Item -Recurse x", "& $p a"])
"""

import base64
import json
import subprocess

POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"

# (one PowerShell for every batch: a JSON array of commands a line in, a JSON
# array of readings a line out; starting PowerShell costs ~0.4s, a batch ms)
_SCRIPT = r"""
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
while ($true) {
$line = [Console]::In.ReadLine()
if ($line -eq $null) { break }
$all = ConvertFrom-Json $line
$out = New-Object System.Collections.ArrayList
foreach ($text in $all) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
    $cmds = New-Object System.Collections.ArrayList
    $found = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)
    foreach ($c in $found) {
        $els = New-Object System.Collections.ArrayList
        foreach ($e in $c.CommandElements) {
            $t = $e.GetType().Name
            $item = @{ type = $t; text = $e.Extent.Text; start = $e.Extent.StartOffset }
            if ($t -eq 'StringConstantExpressionAst') { $item.value = $e.Value; $item.quote = $e.StringConstantType.ToString() }
            if ($t -eq 'CommandParameterAst') {
                $item.name = $e.ParameterName
                if ($e.Argument -ne $null) { $item.arg = $e.Argument.Extent.Text }
            }
            [void]$els.Add($item)
        }
        $reds = New-Object System.Collections.ArrayList
        foreach ($r in $c.Redirections) {
            $ri = @{ type = $r.GetType().Name; text = $r.Extent.Text; from = $r.FromStream.ToString() }
            if ($r -is [System.Management.Automation.Language.FileRedirectionAst]) { $ri.append = $r.Append; $ri.target = $r.Location.Extent.Text }
            [void]$reds.Add($ri)
        }
        $inv = $c.InvocationOperator.ToString()
        [void]$cmds.Add(@{ invocation = $inv; elements = $els; redirections = $reds; start = $c.Extent.StartOffset; text = $c.Extent.Text })
    }
    $errs = New-Object System.Collections.ArrayList
    foreach ($e in $errors) { [void]$errs.Add(@{ id = $e.ErrorId; at = $e.Extent.StartOffset }) }
    [void]$out.Add(@{ errors = $errs; commands = $cmds })
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject $out -Depth 8 -Compress))
[Console]::Out.Flush()
}
"""


class Oracle:
    def __init__(self, powershell=POWERSHELL):
        self.powershell = powershell
        self._encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode()
        self._proc = None

    def _start(self):
        self._proc = subprocess.Popen(
            [self.powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", self._encoded],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def close(self):
        if self._proc is not None:
            self._proc.stdin.close()
            self._proc.wait()
            self._proc = None

    def read(self, commands):
        """PowerShell's reading of each command (a list of dicts: errors,
        commands)."""
        if not commands:
            return []
        if self._proc is None or self._proc.poll() is not None:
            self._start()
        self._proc.stdin.write(json.dumps(list(commands)).encode("utf-8") + b"\n")
        self._proc.stdin.flush()
        out = self._proc.stdout.readline().decode("utf-8", "replace").strip().lstrip("﻿")
        if not out:
            self.close()
            raise RuntimeError("PowerShell gave no answer")
        result = json.loads(out)
        # (one command: PowerShell 5.1 unwraps a one-item array)
        if isinstance(result, dict):
            result = [result]
        for r in result:
            for key in ("errors", "commands"):
                if isinstance(r.get(key), dict):
                    r[key] = [r[key]]
                r[key] = r.get(key) or []
            for c in r["commands"]:
                for key in ("elements", "redirections"):
                    if isinstance(c.get(key), dict):
                        c[key] = [c[key]]
                    c[key] = c.get(key) or []
        return result
