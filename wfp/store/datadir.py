"""データ置き場の場所と、ファイルを途中で壊さずに書く write_atomic"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

# os.replace が PermissionError になったとき(Windows で別のスレッドが読んでいる最中など)に試し直す回数と間隔(秒)
ATOMIC_RETRIES = 5
ATOMIC_RETRY_WAIT = 0.1


def data_dir(arg: str | None = None) -> Path:
    p = Path(arg or os.environ.get("WFPORTAL_DIR") or Path.home() / ".wfportal")
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_atomic(path: Path, data: str | bytes, newline: str | None = None) -> None:
    """ファイルを途中で壊さずに書く: 同じフォルダの一時ファイル(.<名前>.<乱数>.tmp)に書いて fsync → os.replace で置き換える。

    data が str なら utf-8 で書く(newline は open と同じ。None なら OS の改行)。途中で落ちても元のファイルはそのまま残り、
    失敗したときは一時ファイルを消して例外をそのまま投げる。os.replace の PermissionError は ATOMIC_RETRIES 回まで試し直す
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        if isinstance(data, str):
            f = os.fdopen(fd, "w", encoding="utf-8", newline=newline)
        else:
            f = os.fdopen(fd, "wb")
        with f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for i in range(ATOMIC_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == ATOMIC_RETRIES - 1:
                    raise
                time.sleep(ATOMIC_RETRY_WAIT)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
