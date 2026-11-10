"""進み具合のログ: say(1行。テキスト指定)・collect_log(画面向けの API が行を集める)。

CLI は日本語で標準出力に出し、画面向けの API は collect_log で集めて lines で返す(画面は renderLog)。
2026-11-10 に core/common から分けた(D2)。import してよい wfp は core.i18n まで
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from wfp.core.i18n import render_ja


_LOG = threading.local()


def say(text, level: int = 0) -> None:
    """進み具合の1行(テキスト指定)。collect_log の中なら行を集めるだけ(画面が表示中の言語で出す。標準出力には出さない)、
    外なら標準出力に日本語で出す(CLI・画面サーバーの起動時)。level は字下げの段(1 段 = 空白2つ)"""
    lines = getattr(_LOG, "lines", None)
    if lines is not None:
        lines.append({"level": level, "text": text})
    else:
        print("  " * level + render_ja(text))


@contextmanager
def collect_log():
    """この中で say した行を集める(画面向けの API が使う)。{"level", "text"} のリストを返す。

    行はスレッドごとに集める(threading.local)ので、画面のサーバーで別のリクエストと重なっても混ざらない。
    この中の say は標準出力に出さない(redirect_stdout はプロセス全体を差し替えるので使わない)"""
    prev = getattr(_LOG, "lines", None)
    _LOG.lines = []
    try:
        yield _LOG.lines
    finally:
        lines, _LOG.lines = _LOG.lines, prev
        if prev is not None:
            prev.extend(lines)
