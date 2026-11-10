"""CLI の共通処理"""
from __future__ import annotations

import sys
from pathlib import Path

from wfp.core.common import rank
from wfp.core.loader import DropsMissing, load_drops
from wfp.core.text import norm
from wfp.drops.tables import Drops


def need_drops(d: Path) -> Drops:
    """CLI 用: ドロップ表が無ければ案内を出して終了する"""
    try:
        return load_drops(d)
    except DropsMissing as e:
        sys.exit(str(e))


def split_action(words, actions: tuple[str, ...]) -> tuple[str, list[str]]:
    """先頭の語が actions(または list)なら (その語, 残り)、違えば ("list", 全部)。例: mods own Serration"""
    words = list(words)
    if words and words[0] in ("list",) + tuple(actions):
        return words[0], words[1:]
    return "list", words


def find_hits(rows: list, q: str, keys) -> list:
    """名前で探す: keys(行 → 名前の一覧)のどれかと完全に一致(norm)する行。無ければあいまい一致(rank)の行。
    件数の検査と止め方はコマンドごとに違うので呼ぶ側で行う"""
    nq = norm(q)
    return [r for r in rows if nq in [norm(k) for k in keys(r)]] or match_rows(rows, q, keys)


def match_rows(rows: list, q: str, keys) -> list:
    """一覧の絞り込み: keys(行 → 名前の一覧)のどれかにあいまい一致(rank)する行(並びはそのまま)"""
    return [r for r in rows if rank(q, keys(r)) is not None]
