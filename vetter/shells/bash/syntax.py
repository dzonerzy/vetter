"""bash's syntax, read exactly (non-interactive bash 5): its zgram
grammar (bash.zgram) parsed with rt.parse, here-documents found by the
scanner (scan.py) and checked against the grammar's, expanded bodies and
backticks' commands read too. Nodes are zrun's: `rule`, `text`, `start`,
`end`, `children`, `find()`.
"""

import pathlib
from dataclasses import dataclass

import zgram

from .scan import heredocs, mask, skip_parens, unescape_backtick, unreadable

GRAMMAR = (pathlib.Path(__file__).resolve().parent / "bash.zgram").read_text(encoding="utf-8")
BASH = zgram.compile(GRAMMAR)


@dataclass
class Doc:
    """A here-document (scan.Heredoc) and its expanded body's tree
    (None: not expanded, or empty), its positions from the body's start."""

    heredoc: object
    body: object


@dataclass
class Backtick:
    """A `...` substitution: its node, the command in it read (a Parsed),
    where that command's text starts in the outer command's."""

    node: object
    command: object
    start: int


@dataclass
class Parsed:
    """A command read: its tree, its text, its here-documents (Doc), and
    the commands of its backticks (nested ones in theirs); `source`: the
    text the tree was parsed from (bodies masked: offset() of its nodes)."""

    tree: object
    text: str
    docs: list
    backticks: list
    source: str


def nodes_of(node, rule_name, out):
    """The nodes of a rule under node, in order (out: appended). (find: one
    pass over the subtree, which gives the node itself too, first.)"""
    found = node.find(rule_name)
    if len(found) > 0 and node.rule == rule_name:
        found = found[1:]
    out += found
    return out


def nodes_in_dq(node, rule_name, in_dq, out):
    """The nodes of a rule under node, each with whether it's in double
    quotes: (node, in_dq) appended to out. (The nearest quote or
    substitution between them says: in "..." or $"...", in; in $(...) or
    <(...), out.)"""
    for c in node.find(rule_name):
        if c == node:
            continue
        q = in_dq
        p = c.parent
        while p is not None and p != node:
            r = p.rule
            if r == "dq" or r == "locale":
                q = True
                break
            if r == "cmdsub" or r == "procsub":
                q = False
                break
            p = p.parent
        out.append((c, q))
    return out


def offset(text, node):
    """Where a node of text's tree starts in it, in characters (the tree's
    offsets are bytes)."""
    b = node.start
    if len(text.encode()) == len(text):
        return b
    n = 0
    i = 0
    while n < b:
        c = ord(text[i])
        n += 1 if c < 0x80 else (2 if c < 0x800 else (3 if c < 0x10000 else 4))
        i += 1
    return i


def parse(rt, text):
    """The command read. zgram.ParseError when it isn't bash; ValueError
    ("unreadable: ...") when bash's reading of it isn't certain."""
    found_docs = heredocs(text) if "<<" in text else []
    masked = mask(text, found_docs)
    tree = rt.parse(BASH, masked)
    # (the operators the grammar found must be the scanner's)
    ops = nodes_of(tree, "heredoc_op", [])
    if len(ops) != len(found_docs):
        raise unreadable("here-documents read differently by the grammar and the lexer")
    for k in range(len(ops)):
        if offset(masked, ops[k]) != found_docs[k].op_start:
            raise unreadable("here-documents read differently by the grammar and the lexer")
    check_dparen_cmdsubs(tree, masked)
    docs = []
    for d in found_docs:
        body = None
        if d.expanded and d.body_end > d.body_start:
            try:
                body = rt.parse(BASH, text[d.body_start : d.body_end], start="heredoc_body")
            except zgram.ParseError as e:
                # (bash finds out when it runs it)
                raise unreadable("a here-document body that isn't bash: " + str(e))
            # (a here-document in a body's $(...): not scanned)
            if len(nodes_of(body, "heredoc_op", [])) > 0:
                raise unreadable("a here-document inside a here-document's body")
        docs.append(Doc(d, body))
    ticks = []
    roots = [(tree, masked, 0)]
    for doc in docs:
        if doc.body is not None:
            h = doc.heredoc
            roots.append((doc.body, text[h.body_start : h.body_end], h.body_start))
    for root, source, base in roots:
        for node, in_dq in nodes_in_dq(root, "backtick", False, []):
            t = node.text
            inner = unescape_backtick(t[1 : len(t) - 1], in_dq)
            try:
                ticks.append(Backtick(node, parse(rt, inner), base + offset(source, node) + 1))
            except zgram.ParseError as e:
                # (bash finds out when it runs it)
                raise unreadable("a backtick substitution that isn't bash: " + str(e))
    return Parsed(tree, text, docs, ticks, masked)


def check_dparen_cmdsubs(tree, masked):
    """A `$((` that isn't arithmetic is a command substitution, but out of
    double quotes bash ends it where counting parentheses ends it:
    `$((t)|case p in a)x;esac)` ends after `a`, and is wrong."""
    for node, in_dq in nodes_in_dq(tree, "cmdsub", False, []):
        start = offset(masked, node)
        if in_dq or masked[start : start + 3] != "$((":
            continue
        if skip_parens(masked, start + 2) != start + len(node.text):
            raise unreadable("a $(( substitution bash ends elsewhere")
