"""CLI の共通処理"""
from __future__ import annotations

import sys
from pathlib import Path

from wfp.core.loader import DropsMissing, load_drops
from wfp.drops.tables import Drops


def need_drops(d: Path) -> Drops:
    """CLI 用: ドロップ表が無ければ案内を出して終了する"""
    try:
        return load_drops(d)
    except DropsMissing as e:
        sys.exit(str(e))
