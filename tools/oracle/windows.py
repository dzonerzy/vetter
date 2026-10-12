"""The cmd and PowerShell proofs of docs/11-analyzer-remediation.md run on
the real shells (from WSL, through its Windows interop), against a sentinel
file in a scratch folder under the Windows user's %TEMP%: does the shell do
what the proof says, and does vetter, with that folder protected, not allow
it. Nothing outside the two scratch folders is touched; they are removed
after.

    python tools/oracle/windows.py      # each case: what Windows did, vetter's decision

A case "as expected": the sentinel read by the real shell, and vetter's
decision not allow. A protected folder is a policy's deny before `use
stock` (the stock policy allows reading the temporary dirs).
"""

import base64
import os
import shutil
import subprocess
import sys

VETTER = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SENTINEL = "VETTER-ORACLE-SENTINEL-7f3a"

# (proof id, command: R the sentinel's folder, P the project's)
CMD = [
    ("C01", 'for /f "usebackq delims=" %A in ("R\\flag") do @echo %A'),
    ("C02", "for /r R %A in (flag) do @type %A"),
    ("C03", "for %A in (README.md x x x x x x x x R\\flag) do @type %A"),
    ("C04", "cd /ROOTLESS & type flag"),
    ("C05", "copy /b NUL+R\\flag R\\copied & type R\\copied"),
    ("C06", "cd /d R & pushd %CD% & popd & type flag"),
    # (the semantics vetter's cmd reading assumes)
    ("delay", 'cmd /v:on /d /c "set x=type R\\flag&!x!"'),
    ("setp", 'echo type R\\flag | cmd /v:on /d /c "set /p V=&!V!"'),
    ("forf", "for /f %i in ('echo type') do %i R\\flag"),
    ("tilde", 'for %i in ("R\\flag") do type %~fi'),
]

PS = [
    ("P01", "$m=[Diagnostics.Process].GetMethod('Start',[type[]]@([string],[string]))\n"
            "$d=$m.CreateDelegate([Func[string,string,Diagnostics.Process]])\n"
            "$p=$d.DynamicInvoke('cmd.exe','/c type R\\flag > P\\p01.txt')\n$p.WaitForExit()\n"
            "Get-Content 'P\\p01.txt'"),
    ("P02", "New-Item -ItemType Junction -Path root -Target 'R\\' | Out-Null; Get-Content root\\flag"),
    ("P03a", "$PSDefaultParameterValues.Add('Start-Process:FilePath','cmd.exe')\n"
             "$PSDefaultParameterValues.Add('Start-Process:ArgumentList','/c type R\\flag')\n"
             "Start-Process -Wait -NoNewWindow"),
    ("P03b", "$PSDefaultParameterValues.Add('Get-Content:Path','R\\flag'); Get-Content"),
    ("P04", "([IO.StreamReader]::new('R\\flag')).ReadToEnd()"),
    ("P05", "$w=[IO.StreamWriter]::new('R\\written.txt');$w.WriteLine('" + SENTINEL + "');$w.Close();"
            "Get-Content 'R\\written.txt'"),
    ("P06", "$p='R\\';$p+='flag';Get-Content $p"),
    ("P07", "Set-Location 'R'; Push-Location 'P'; Pop-Location; Get-Content flag"),
    ("P08", "$ExecutionContext.SessionState.Path.SetLocation('R'); Get-Content flag"),
]


def windows_temp():
    """The Windows user's %TEMP%, and where WSL sees it."""
    out = subprocess.run(["cmd.exe", "/d", "/c", "echo %TEMP%"], capture_output=True, text=True, cwd="/mnt/c")
    win = out.stdout.strip()
    linux = subprocess.run(["wslpath", "-u", win], capture_output=True, text=True).stdout.strip()
    return win, linux


class Places:
    def __init__(self):
        win, linux = windows_temp()
        self.r = win + "\\vetter-oracle"
        self.p = win + "\\vetter-oracle-project"
        self.lr = linux + "/vetter-oracle"
        self.lp = linux + "/vetter-oracle-project"
        self.home = win.split("\\AppData\\")[0].replace("\\", "/")
        self.policy = os.path.join(self.lp, "oracle.vet")

    def fill(self, text):
        rootless = self.r[2:].replace("\\", "/")
        return text.replace("/ROOTLESS", rootless).replace("R\\", self.r + "\\").replace("P\\", self.p + "\\") \
            .replace("'R'", "'" + self.r + "'").replace("'P'", "'" + self.p + "'").replace(" R ", " " + self.r + " ") \
            .replace(" R &", " " + self.r + " &")

    def setup(self):
        self.clean()
        os.makedirs(self.lr)
        os.makedirs(self.lp)
        with open(self.lr + "/flag", "w") as f:
            f.write(SENTINEL + "\n")
        with open(self.lp + "/README.md", "w") as f:
            f.write("readme\n")
        with open(self.policy, "w") as f:
            f.write('policy oracle\nlog off\ndeny "the sentinel" read in "' + self.r.replace("\\", "/") + '"\n'
                    "use stock\n")

    def clean(self):
        if os.path.isdir(self.lp + "/root"):
            # (P02's junction: removed as a link, not what it points to)
            subprocess.run(["cmd.exe", "/d", "/c", "rmdir", self.p + "\\root"], capture_output=True, cwd=self.lp)
        shutil.rmtree(self.lr, ignore_errors=True)
        shutil.rmtree(self.lp, ignore_errors=True)


def decided(places, shell, command):
    r = subprocess.run([sys.executable, "-m", "vetter", "check", "--policy", places.policy, "--shell", shell, "--cwd",
                        places.p.replace("\\", "/"), "--home", places.home, command], capture_output=True, text=True,
                       cwd=VETTER)
    return (r.stdout or r.stderr).splitlines()[0]


def run_cmd(places, line):
    # (at a prompt, as an agent's cmd runs a line: stdin, not a batch file)
    r = subprocess.run(["cmd.exe", "/d", "/q"], input=line + "\r\nexit\r\n", capture_output=True, text=True,
                       cwd=places.lp, timeout=60)
    return r.stdout + r.stderr


def run_ps(places, script):
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                       capture_output=True, text=True, cwd=places.lp, timeout=60)
    return r.stdout + r.stderr


def main():
    places = Places()
    places.setup()
    wrong = 0
    try:
        for shell, cases, runner in (("cmd", CMD, run_cmd), ("powershell", PS, run_ps)):
            for cid, text in cases:
                command = places.fill(text)
                d = decided(places, shell, command)
                happened = SENTINEL in runner(places, command)
                ok = happened and not d.startswith("allow")
                wrong += 0 if ok else 1
                print(f"{'ok ' if ok else 'BAD'} {cid:6} windows={'read' if happened else 'no  '} vetter={d[:90]}")
    finally:
        places.clean()
    print(f"{wrong} not as expected")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
