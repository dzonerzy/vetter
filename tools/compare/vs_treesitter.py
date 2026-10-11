"""vetter's reading against tree-sitter-bash's, on the corpus, the built-in
cases of bashdiff and generated commands: which commands each finds (the
command names, by position and text, here-document bodies included), and
whether it takes the command as bash at all (as bash 5.2 does: --bash).
vetter's reading is checked
against bash's (tools/bash/bashdiff.py, bashfuzz.py): where they differ,
tree-sitter-bash misreads.

    python -m tools.compare.vs_treesitter [--generated N] [--bash PATH]
    (tree-sitter and tree-sitter-bash installed)
"""

import argparse
import collections
import random
import sys

import tree_sitter
import tree_sitter_bash
import zgram

from tools.bash import bashdiff, bashfuzz
from tools.corpus import corpus
from vetter import engine
from vetter.shells.bash import syntax as bash

TS = tree_sitter.Parser(tree_sitter.Language(tree_sitter_bash.language()))


def vetter_commands(text):
    """The command names vetter finds ((position, text) in order), or None
    when it doesn't read the command."""
    try:
        p = engine.run(bash.parse, text)
    except (zgram.ParseError, ValueError):
        return None
    return sorted(_names(p, 0))


def _names(p, offset):
    # (positions in characters: the trees' are bytes)
    found = [(offset + bash.offset(p.source, n), n.text) for n in p.tree.find("cmd_name")]
    for d in p.docs:
        if d.body is not None:
            h = d.heredoc
            body = p.text[h.body_start:h.body_end]
            found += [(offset + h.body_start + bash.offset(body, n), n.text) for n in d.body.find("cmd_name")]
    for t in p.backticks:
        # (exact while no backslash was removed before it: the usual case)
        found += _names(t.command, offset + t.start)
    return found


def ts_commands(text):
    """tree-sitter-bash's command names, and whether it found errors."""
    data = text.encode()
    tree = TS.parse(data)
    found = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "command_name":
            start = len(data[: node.start_byte].decode())
            found.append((start, data[node.start_byte : node.end_byte].decode()))
        stack.extend(node.children)
    return sorted(found), tree.root_node.has_error


def compare(text):
    """What tree-sitter-bash gets wrong about one command bash accepts
    (None: nothing)."""
    ours = vetter_commands(text)
    theirs, error = ts_commands(text)
    if ours is None:
        return None
    if error:
        return "error: valid bash it can't parse"
    # (by text: in backticks vetter's positions are approximate)
    ours = sorted(t for _, t in ours)
    theirs = sorted(t for _, t in theirs)
    if theirs != ours:
        missed = list((collections.Counter(ours) - collections.Counter(theirs)).elements())
        extra = list((collections.Counter(theirs) - collections.Counter(ours)).elements())
        if missed:
            return f"misses commands: {missed} (finds {extra})" if extra else f"misses commands: {missed}"
        return f"finds commands that aren't: {extra}"
    return None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--bash", default=bashdiff.BASH)
    args = ap.parse_args(argv)
    bashdiff.BASH = args.bash

    commands = [(c["id"], c["command"]) for c in corpus.load() if c["shell"] == "bash"]
    commands += [(f"extra-{i}", c) for i, c in enumerate(bashdiff.EXTRA)]
    rng = random.Random(args.seed)
    for i in range(args.generated):
        gen = (lambda r: bashfuzz.command_list(r, 2), bashfuzz.heredoc)[i % 2]
        commands.append((f"gen-{i}", gen(rng)))

    wrong = {}
    shown = 0
    total = 0
    for cid, cmd in commands:
        if not bashdiff.bash_accepts(cmd):
            continue
        total += 1
        problem = compare(cmd)
        if problem:
            kind = problem.split(":")[0]
            wrong[kind] = wrong.get(kind, 0) + 1
            if not cid.startswith("gen-") or shown < 10:
                shown += cid.startswith("gen-")
                print(f"--- {cid}: {cmd[:160]!r}\n    {problem[:300]}")
    bad = sum(wrong.values())
    print(f"\ntree-sitter-bash reads {total - bad}/{total} commands as bash does")
    for k, n in sorted(wrong.items()):
        print(f"  {n:4d}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
