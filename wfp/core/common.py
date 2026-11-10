"""共通: 検索の一致度(rank)・書式(pct fmt_clock fmt_dur など)・ツールの版(app_version)・画面の言語コード(export_lang)。

テキスト指定と日本語の文は core/i18n、進み具合のログは core/log、テキスト指定の例外は core/errors(2026-11-10 に分けた。D2)。
定数は core/const。import してよい wfp は core.const・core.ocr_chars・core.text・core.i18n・core.log・core.errors
"""
from __future__ import annotations

import json

from wfp.core import const
from wfp.core.const import EXPORT_EXTRA_LANGS, EXPORT_LANG_ALIAS
from wfp.core.text import norm


def export_lang(code: str) -> str | None:
    """画面の言語コードを、日英のほかに取る Export の言語コードにする。ja・en・Export に無い言語は None

    別名(EXPORT_LANG_ALIAS)を先に見て、無ければ地域を外したコード(ko-KR → ko)で探す。
    """
    low = code.strip().lower()
    lang = EXPORT_LANG_ALIAS.get(low) or low.split("-")[0]
    return lang if lang in EXPORT_EXTRA_LANGS else None


def app_version() -> str:
    """ツールのバージョン (version.json の "version"。例: 1.00)。読めなければ "?" """
    try:
        return str(json.loads((const.APP_DIR / "version.json").read_text(encoding="utf-8-sig"))["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return "?"


def rank(query: str, names: list[str]) -> int | None:
    """0=完全一致 1=前方一致 2=部分一致 None=不一致"""
    q = norm(query)
    if not q:
        return None
    best = None
    for n in names:
        t = norm(n)
        r = 0 if t == q else 1 if t.startswith(q) else 2 if q in t else None
        if r is not None and (best is None or r < best):
            best = r
    return best


def to_float(v) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def pct(x: float | None) -> str:
    """確率の表示。確率の無い入手先(クラン研究)は「—」"""
    return "—" if x is None else f"{x:.2f}%"


def parse_remaining(s: str) -> int:
    parts = [int(x) for x in s.split(":")]
    if len(parts) == 1:
        return parts[0] * 60  # 数字だけなら分
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt_clock(sec: float) -> str:
    """秒数を「h:mm:ss」(1時間未満は「mm:ss」)にする(言語によらない書き方。画面の dur と同じ)"""
    sec = max(0, int(sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_dur(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}時間{m:02d}分{s:02d}秒" if h else f"{m}分{s:02d}秒"
