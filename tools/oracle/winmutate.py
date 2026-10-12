"""cmd and PowerShell commands that read, write or delete in the protected
folder (R), written many ways: what each shell runs is the same, what a
reader sees isn't. windows.py --mutate decides each; one vetter allows is
run on the real shell and its effect looked for.

R and P stand for the protected and the project folder (windows.py's
fill); SHORT for R's 8.3 name, filled in when the volume has them.
"""

# (what each does: read prints the sentinel, write makes R\w.txt, delete
# removes R\victim.txt)
CMD_BASES = {
    "read": ["type R\\flag", "more < R\\flag", "findstr . R\\flag", "find /v \"\" R\\flag",
             "for /f \"delims=\" %a in (R\\flag) do @echo %a", "copy /b R\\flag con",
             "copy /y R\\flag P\\c.txt >nul & type P\\c.txt", "xcopy /y R\\flag P\\ >nul & type P\\flag",
             "forfiles /p R /m flag /c \"cmd /c type @file\"",
             "mklink /j P\\j R >nul & type P\\j\\flag & rmdir P\\j"],
    "write": ["echo x> R\\w.txt", "copy /y nul R\\w.txt", "type nul > R\\w.txt", "echo x> P\\s.txt & move /y P\\s.txt R\\w.txt"],
    "delete": ["del /q R\\victim.txt", "erase R\\victim.txt", "move /y R\\victim.txt P\\v.txt",
               "ren R\\victim.txt v2.txt"],
}

PS_BASES = {
    "read": ["Get-Content R\\flag", "gc R\\flag", "cat R\\flag", "type R\\flag", "[IO.File]::ReadAllText('R\\flag')",
             "Select-String -Path R\\flag -Pattern .", "Get-Content -LiteralPath 'R\\flag'",
             "(Get-Item R\\flag).OpenText().ReadToEnd()", "Copy-Item R\\flag P\\c.txt; Get-Content P\\c.txt",
             "Start-Job { Get-Content R\\flag } | Receive-Job -Wait",
             "$ExecutionContext.InvokeCommand.InvokeScript('Get-Content R\\flag')",
             "New-Item -ItemType Junction -Path P\\j -Target R | Out-Null; Get-Content P\\j\\flag"],
    "write": ["Set-Content R\\w.txt x", "'x' | Out-File R\\w.txt", "New-Item -ItemType File R\\w.txt | Out-Null",
              "'x' > R\\w.txt", "[IO.File]::WriteAllText('R\\w.txt','x')",
              "Set-Content P\\s.txt x; Move-Item P\\s.txt R\\w.txt"],
    "delete": ["Remove-Item R\\victim.txt", "del R\\victim.txt", "rm R\\victim.txt",
               "[IO.File]::Delete('R\\victim.txt')", "Move-Item R\\victim.txt P\\v.txt",
               "Rename-Item R\\victim.txt v2.txt"],
}

# (the folder and its files named other ways Windows takes them to: a
# prefix it strips, a dot or a space at the end, the data stream, case)
PATH_FORMS = [
    ("long-prefix", "\\\\?\\R\\", None),
    ("device-prefix", "\\\\.\\R\\", None),
    ("admin-share", "ADMINSHARE\\", None),
    ("dotdot-users", "DOTDOTUSERS\\", None),
    ("userprofile", "%USERPROFILE%\\AppData\\Local\\Temp\\vetter-oracle\\", None),
    ("localappdata", "%LOCALAPPDATA%\\Temp\\vetter-oracle\\", None),
    ("upper", "UPPER\\", None),
    ("trailing-dot", None, "."),
    ("trailing-space", None, " "),
    ("data-stream", None, "::$DATA"),
]


def path_forms(text, ps):
    """text with R's files named each way of PATH_FORMS: [(name, text)]."""
    out = []
    for label, prefix, suffix in PATH_FORMS:
        if ps and prefix is not None and "%" in prefix:
            prefix = prefix.replace("%USERPROFILE%", "$env:USERPROFILE").replace("%LOCALAPPDATA%", "$env:LOCALAPPDATA")
        t = text
        if prefix is not None:
            t = t.replace("R\\", prefix)
        if suffix is not None:
            for f in ("R\\flag", "R\\w.txt", "R\\victim.txt"):
                t = t.replace(f, '"' + f + suffix + '"' if suffix == " " else f + suffix)
        if t != text:
            out.append(("form-" + label, t))
    return out


def cmd_variants(base):
    """base (a cmd line: VERB ARGS) written other ways: [(name, line)]."""
    verb, _, rest = base.partition(" ")
    out = [("base", base)]
    if verb.isalpha():
        out.append(("caret", "^".join(verb) + " " + rest))
        out.append(("call", "call " + base))
        out.append(("for-name", "for %a in (" + verb + ") do @%a " + rest))
        out.append(("for-f-name", "for /f %a in ('echo " + verb + "') do @%a " + rest))
        out.append(("set-name", "set __v=" + verb + "& call %__v% " + rest))
        out.append(("set-substr", "set __v=x" + verb + "& call %__v:~1% " + rest))
        out.append(("delayed", "cmd /v:on /d /c \"set __v=" + verb + "&!__v! " + rest + "\""))
    out.append(("cmd-c", "cmd /d /c \"" + base + "\""))
    out.append(("cmd-k-exit", "cmd /d /k \"" + base + " & exit\""))
    out.append(("pipe-cmd", "echo " + base.replace(">", "^>").replace("<", "^<") + "| cmd /d /q"))
    out.append(("block", "(" + base + ")"))
    out.append(("if", "if 1==1 " + base))
    out.append(("and", "ver>nul && " + base))
    out.append(("or", "cd nonexistent-x 2>nul || " + base))
    out.append(("start-wait", "start /b /wait cmd /d /c \"" + base + "\""))
    out.append(("powershell", "powershell -NoProfile -Command \"cmd /d /c '" + base.replace("'", "''") + "'\""))
    for label, path in (("dot", "R\\.\\"), ("dotdot", "R\\..\\vetter-oracle\\"), ("short", "SHORT\\"),
                        ("env", "%TEMP%\\vetter-oracle\\"), ("quoted", None), ("forward", "R/")):
        if label == "quoted":
            out.append(("path-quoted", base.replace("R\\flag", "\"R\\flag\"").replace("R\\w.txt", "\"R\\w.txt\"")
                        .replace("R\\victim.txt", "\"R\\victim.txt\"")))
        else:
            out.append(("path-" + label, base.replace("R\\", path)))
    out.append(("path-glob", base.replace("R\\flag", "R\\fla?").replace("R\\victim.txt", "R\\vict*.txt")))
    if "R\\" in base:
        out.append(("pushd", "pushd R & " + base.replace("R\\", "") + " & popd"))
        out.append(("cd-d", "cd /d R & " + base.replace("R\\", "")))
    out += path_forms(base, False)
    return out


def ps_variants(base):
    """base (a PowerShell line) written other ways: [(name, line)]."""
    out = [("base", base)]
    words = base.split(" ", 1)
    name = words[0]
    rest = words[1] if len(words) > 1 else ""
    sq = base.replace("'", "''")
    if name[:1].isalpha() and "-" in name:
        out.append(("call-string", "& '" + name + "' " + rest))
        out.append(("call-var", "$c='" + name + "'; & $c " + rest))
        out.append(("call-concat", "& ('" + name[:3] + "'+'" + name[3:] + "') " + rest))
        out.append(("gcm-wild", "& (Get-Command " + name[:5] + "*" + name[len(name) - 2 :] + ") " + rest))
        out.append(("dot", ". '" + name + "' " + rest))
        out.append(("alias", "Set-Alias __a " + name + "; __a " + rest))
        out.append(("splat-array", "$a=@(" + ",".join("'" + w + "'" for w in rest.split(" ") if w) + "); "
                    + name + " @a"))
    out.append(("iex", "Invoke-Expression '" + sq + "'"))
    out.append(("iex-concat", "iex ('" + sq[: len(sq) // 2] + "'+'" + sq[len(sq) // 2 :] + "')"))
    out.append(("scriptblock", "& {" + base + "}"))
    out.append(("scriptblock-create", "& ([scriptblock]::Create('" + sq + "'))"))
    out.append(("invoke-command", "Invoke-Command -ScriptBlock {" + base + "}"))
    out.append(("foreach", "1 | ForEach-Object {" + base + "}"))
    out.append(("encoded", "ENCODED"))
    out.append(("cmd-c", "cmd /d /c \"powershell -NoProfile -Command " + base.replace('"', '\\"') + "\""))
    out.append(("start-process", "Start-Process -Wait -NoNewWindow powershell -ArgumentList '-NoProfile','-Command','"
                + sq.replace("'", "''") + "'"))
    for label, path in (("dot", "R\\.\\"), ("dotdot", "R\\..\\vetter-oracle\\"), ("short", "SHORT\\"),
                        ("env", "$env:TEMP\\vetter-oracle\\"), ("forward", "R/")):
        out.append(("path-" + label, base.replace("R\\", path)))
    out.append(("path-wild", base.replace("R\\flag", "R\\fla?").replace("R\\victim.txt", "R\\vict*.txt")))
    out.append(("path-var", "$p='R\\'; " + base.replace("R\\", "$p")))
    out.append(("path-join", base.replace("'R\\flag'", "(Join-Path 'R' 'flag')")))
    out.append(("set-location", "Set-Location 'R'; " + base.replace("R\\", ".\\")))
    out.append(("push-location", "Push-Location 'R'; " + base.replace("R\\", ".\\") + "; Pop-Location"))
    if base.startswith("Get-Content") or base.startswith("gc "):
        out.append(("provider-var", "${R\\flag}"))
        out.append(("pipeline-path", "'R\\flag' | Get-Content"))
        out.append(("gci-pipe", "Get-ChildItem R -Filter flag | Get-Content"))
    out += path_forms(base, True)
    return out
