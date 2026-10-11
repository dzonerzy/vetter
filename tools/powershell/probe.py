"""Show how PowerShell reads commands: each command's elements.

    python -m tools.powershell.probe 'cmd1' 'cmd2' ...
"""

import sys

from tools.powershell import oracle


def main(argv):
    for text, r in zip(argv, oracle.Oracle().read(argv)):
        errs = ", ".join(e["id"] for e in r["errors"])
        print(f"=== {text!r}" + (f"   ERRORS: {errs}" if errs else ""))
        for c in r["commands"]:
            inv = "" if c["invocation"] == "Unknown" else f"[{c['invocation']}] "
            parts = []
            for e in c["elements"]:
                t = e["type"].replace("ExpressionAst", "").replace("Ast", "")
                if "value" in e:
                    parts.append(f"{t}({e['quote']}):{e['value']!r}")
                elif "name" in e:
                    parts.append(f"Param:{e['name']}" + (f"={e['arg']!r}" if "arg" in e else ""))
                else:
                    parts.append(f"{t}:{e['text']!r}")
            reds = [r_["text"] for r_ in c["redirections"]]
            print(f"   {inv}" + "  ".join(parts) + (f"   REDIR {reds}" if reds else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
