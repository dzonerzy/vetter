"""bash's lexer (vetter/shells/bash/scan.py): here-documents, $'...',
backticks' text, as recorded (tests/golden), on the corpus and on
generated commands."""

from golden import UPDATE, load_golden, save_golden
from vetter.shells.bash import scan


def heredocs(text):
    try:
        docs = scan.heredocs(text)
    except ValueError as e:
        return [["unreadable", str(e).removeprefix("unreadable: ")], None]
    return [[[d.op_start, d.delimiter, d.expanded, d.strip_tabs, d.body_start, d.body_end, d.end] for d in docs],
            scan.mask(text, docs)]


def test_heredocs_as_recorded():
    cases = load_golden("bash_scan_heredocs")
    got = [heredocs(c["in"][0]) for c in cases]
    if UPDATE:
        save_golden("bash_scan_heredocs", [{"in": c["in"], "out": g} for c, g in zip(cases, got)])
        return
    for c, g in zip(cases, got):
        assert g == c["out"], c["in"]


def test_ansi_and_backticks_as_recorded():
    cases = load_golden("bash_scan_escapes")
    got = [[scan.ansi_decode(s), scan.unescape_backtick(s, False), scan.unescape_backtick(s, True)]
           for s in (c["in"][0] for c in cases)]
    if UPDATE:
        save_golden("bash_scan_escapes", [{"in": c["in"], "out": g} for c, g in zip(cases, got)])
        return
    for c, g in zip(cases, got):
        assert g == c["out"], c["in"]
