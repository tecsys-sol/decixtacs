"""Module 5 - config diffs: unified (git style), inline and side-by-side structures for the UI."""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class DiffStats:
    added: int
    removed: int


def unified(old: str, new: str, old_label: str = "a", new_label: str = "b", context: int = 3) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), old_label, new_label, n=context
        )
    )


def stats(old: str, new: str) -> DiffStats:
    added = removed = 0
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return DiffStats(added, removed)


def side_by_side(old: str, new: str, context: int | None = 3) -> list[dict]:
    """Rows of {type, left_no, left, right_no, right}; type in equal|added|removed|modified|skip."""
    a, b = old.splitlines(), new.splitlines()
    rows: list[dict] = []
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            span = range(i2 - i1)
            keep = set(span)
            if context is not None:
                first, last = i1 == 0, i2 == len(a)
                head = set() if first else set(range(min(context, len(span))))
                tail = set() if last else set(range(max(0, len(span) - context), len(span)))
                if len(span) > len(head | tail) and not (first and last and len(span) == 0):
                    keep = head | tail
            skipped = False
            for k in span:
                if k in keep:
                    rows.append({"type": "equal", "left_no": i1 + k + 1, "left": a[i1 + k],
                                 "right_no": j1 + k + 1, "right": b[j1 + k]})
                elif not skipped:
                    rows.append({"type": "skip", "count": len(span) - len(keep)})
                    skipped = True
        elif tag == "replace":
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                li, rj = i1 + k, j1 + k
                left = a[li] if li < i2 else None
                right = b[rj] if rj < j2 else None
                typ = "modified" if left is not None and right is not None else ("removed" if right is None else "added")
                rows.append({"type": typ, "left_no": li + 1 if left is not None else None, "left": left,
                             "right_no": rj + 1 if right is not None else None, "right": right})
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append({"type": "removed", "left_no": k + 1, "left": a[k], "right_no": None, "right": None})
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append({"type": "added", "left_no": None, "left": None, "right_no": k + 1, "right": b[k]})
    return rows


def inline(old: str, new: str) -> list[dict]:
    """Inline diff rows: {type: equal|added|removed, text} over the whole file."""
    out = []
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        code, text = line[:2], line[2:]
        if code == "? ":
            continue
        out.append({"type": {"  ": "equal", "+ ": "added", "- ": "removed"}[code], "text": text})
    return out
