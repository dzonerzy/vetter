"""A decision, shown: how the command was read (the words that changed), and
for each thing it does the rule that decided and why; with every_rule, the
rules tried before and why each didn't match (a decision of a policy whose
`trace` is on: its steps say why).
"""

from .actions import action_text
from .language import where


def _rule_ref(rule):
    return where(rule) if rule is not None else ""


def caret(command, span):
    """The command's line holding the span, and a mark under it."""
    start, end = span
    if end <= start:
        return ""
    line_start = command.rfind("\n", 0, start) + 1
    line_end = command.find("\n", start)
    line_end = len(command) if line_end < 0 else line_end
    end = min(end, line_end)
    return f"   {command[line_start:line_end]}\n   {' ' * (start - line_start)}{'^' * max(1, end - start)}"


def reading(decision):
    """The words that changed while reading, quote removal aside: (as
    written, what it became)."""
    out = []
    for p in decision.parts:
        for written, became in getattr(p.part, "words", []) or []:
            now = " ".join(became)
            plain = written.replace("'", "").replace('"', "").replace("\\", "")
            if now != written and now != plain:
                out.append((written, now if became else "(nothing)"))
    return out


def _other_action(step):
    """A rule about another action than this one (folded in --all)."""
    return step.why.startswith("it's ") or step.why.startswith("it runs ")


def show(decision, command, every_rule=False, only_rule=None):
    lines = []
    changed = reading(decision)
    if changed:
        lines.append("read")
        width = min(40, max(len(w) for w, _ in changed))
        for w, now in changed:
            lines.append(f"  {w:<{width}}  ->  {now}")
        lines.append("")
    for p in decision.parts:
        part = p.part
        via = f"   (via {' <- '.join(part.via)})" if part.via else ""
        lines.append(f"{part.label}{via}")
        for a in p.actions:
            head = f"  {action_text(a.action):<34}"
            if only_rule is not None:
                step = next((s for s in a.steps if s.rule.line == only_rule), None)
                if step is None:
                    lines.append(f"{head} rule {only_rule} isn't reached: decided before by "
                                 f"{_rule_ref(a.rule) or a.by}")
                else:
                    lines.append(f"{head} {_rule_ref(step.rule)}: {'YES' if step.matched else 'no'}: {step.why}")
                continue
            if every_rule:
                lines.append(head.rstrip())
                folded = 0
                for s in a.steps:
                    if not s.matched and _other_action(s):
                        folded += 1
                        continue
                    mark = "YES" if s.matched else "no "
                    lines.append(f"      {where(s.rule):<14} {s.rule.decision:<5} {mark} {s.rule.reason}: {s.why}")
                if folded:
                    lines.append(f"      ({folded} rules about other actions)")
                if a.rule is None:
                    lines.append(f"      {'(none)':<14} {a.decision:<5} {a.by}: {a.reason}")
                continue
            if a.rule is not None:
                lines.append(f"{head} {a.decision:<5} {a.reason}   [{where(a.rule)}]")
            else:
                lines.append(f"{head} {a.decision:<5} {a.reason}   [{a.by}]")
    lines.append("")
    ref = f" [{where(decision.rule)}]" if decision.rule is not None else f" [{decision.by}]"
    lines.append(f"=> {decision.decision}: {decision.reason}{ref}")
    mark = caret(command, decision.span)
    if mark:
        lines.append(mark)
    return "\n".join(lines)
