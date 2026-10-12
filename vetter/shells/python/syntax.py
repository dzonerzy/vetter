"""Python's syntax, for the code a command gives an interpreter (python -c,
python - <<EOF): its zgram grammar (python.zgram) over what the scanner
(scan.py) makes of the text. Nodes are zrun's: `rule`, `text`, `start`,
`end`, `children`, `find()`.
"""

import pathlib

import zgram

from .scan import mark

GRAMMAR = (pathlib.Path(__file__).resolve().parent / "python.zgram").read_text(encoding="utf-8")
PYTHON = zgram.compile(GRAMMAR)


def parse(rt, text):
    """The code's tree. zgram.ParseError when it isn't Python vetter reads;
    ValueError("unreadable: ...") when the scanner can't."""
    return rt.parse(PYTHON, mark(text))
