"""データ置き場の場所"""
from __future__ import annotations

import os
from pathlib import Path


def data_dir(arg: str | None = None) -> Path:
    p = Path(arg or os.environ.get("WFPORTAL_DIR") or Path.home() / ".wfportal")
    p.mkdir(parents=True, exist_ok=True)
    return p
