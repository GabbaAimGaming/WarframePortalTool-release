"""CLI の表示(全角を2として列幅をそろえる)"""
from __future__ import annotations

import unicodedata


def disp_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, n: int, right: bool = False) -> str:
    gap = " " * max(0, n - disp_width(s))
    return gap + s if right else s + gap


def print_table(header: list[str], rows: list[list[str]], right_cols: tuple[int, ...] = ()) -> None:
    widths = [max(disp_width(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    line = lambda r: "  ".join(pad(str(c), widths[i], i in right_cols) for i, c in enumerate(r)).rstrip()
    print(line(header))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))
