"""画面向け API: 文字認識(Windows OCR)が使えるかの確認と、呼び出しの共通部分。

ビルド画像の解析・MOD 一覧/マスター一覧のゲーム画面の読み取り(personal)・Riven の画像の読み取り(sim)で使う。
使えるかは初回だけ調べて覚えておく(テストは forget で忘れさせる)。
"""
from __future__ import annotations

import threading

import wfportal_ocr as ocr
from wfp.api.store import ApiError
from wfp.core.errors import error_text
from wfp.core.i18n import txt

_ocr_info: dict | None = None
_ocr_lock = threading.Lock()


def ocr_info() -> dict:
    """Windows の文字認識が使えるか(初回だけ調べて覚えておく)。reason は使えない理由のテキスト指定(使えるときは空)"""
    global _ocr_info
    with _ocr_lock:
        if _ocr_info is None:
            try:
                langs = ocr.ocr_languages()
                _ocr_info = {"available": bool(langs), "languages": langs,
                             "english": any(x.lower().startswith("en") for x in langs),
                             "reason": "" if langs else txt("err.ocr.nolang")}
            except ocr.OcrUnavailable as e:
                _ocr_info = {"available": False, "languages": [], "english": False, "reason": error_text(e)}
        return _ocr_info


def forget() -> None:
    """覚えている確認の結果を捨てる(テスト用。次の ocr_info で調べ直す)"""
    global _ocr_info
    with _ocr_lock:
        _ocr_info = None


def need_ocr() -> dict:
    """文字認識が使えなければ 501 で止める。使えれば ocr_info の結果を返す"""
    info = ocr_info()
    if not info["available"]:
        raise ApiError(info["reason"] or txt("err.ocr.none"), 501)
    return info


def run_ocr(data: bytes, **kw) -> dict:
    """ocr.run_ocr_bytes を呼ぶ。文字認識が失敗したら 502(引数はそのまま渡す)"""
    try:
        return ocr.run_ocr_bytes(data, **kw)
    except ocr.OcrUnavailable as e:
        raise ApiError(error_text(e), 502)


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/ocr-info"): lambda c: ocr_info(),
}
