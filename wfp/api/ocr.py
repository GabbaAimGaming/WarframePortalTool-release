"""画面向け API: 文字認識が使えるかの確認と、呼び出しの共通部分・高精度エンジンの設定と導入。

ビルド画像の解析・MOD 一覧/マスター一覧のゲーム画面の読み取り(personal)・Riven の画像の読み取り(sim)で使う。
エンジン(wfp/ocr)ごとに使えるかを初回だけ調べて覚えておく(テストは forget で忘れさせる)。
使うエンジンと高精度エンジンの段は利用者データ ocr_prefs(画面と CLI で同じ設定)。
"""
from __future__ import annotations

import threading

from wfp.api.store import ApiError, Store
from wfp.core.const import OCR_ENGINE_PREFS, PPOCR_TIERS
from wfp.core.errors import error_text
from wfp.core.i18n import txt
from wfp.core.log import collect_log
from wfp.ocr import engine, runtime
from wfp.ocr.engine import OcrRequest, OcrUnavailable
from wfp.ocr.result import lang_matches
from wfp.store import userdata


def use_store(store: Store) -> dict:
    """データ置き場と段をエンジンに渡し、設定 {"engine", "tier"} を返す(文字認識を使う前に呼ぶ)"""
    prefs = userdata.load_ocr_prefs(store.d)
    engine.configure(store.d, prefs["tier"])
    return prefs


def _engine_info(pref: str) -> dict:
    """使うエンジンとその言語。使えなければ available: False と理由"""
    try:
        chosen_engine, chosen = engine.select_engine(pref)
    except OcrUnavailable as e:
        return {"available": False, "languages": [], "english": False, "reason": error_text(e), "engine": None, "fallback": False}
    langs = engine.probe(chosen_engine)["langs"]
    return {"available": True, "languages": langs, "english": any(lang_matches({"lang": x}, "en") for x in langs),
            "reason": "", "engine": chosen_engine.engine_id, "fallback": chosen["fallback"]}


def ocr_info(store: Store) -> dict:
    """文字認識が使えるか。reason は使えない理由のテキスト指定(使えるときは空)。engines は全エンジンの状態、
    prefs は設定、runtime は高精度エンジンの部品の状態"""
    prefs = use_store(store)
    return {**_engine_info(prefs["engine"]), "engines": engine.engine_status(), "prefs": prefs,
            "choices": {"engine": list(OCR_ENGINE_PREFS), "tier": list(PPOCR_TIERS)},
            "runtime": runtime.status(store.d, prefs["tier"])}


def forget() -> None:
    """覚えている確認の結果を捨てる(テスト用。次の ocr_info で調べ直す)"""
    engine.forget()


def need_ocr(store: Store) -> dict:
    """文字認識が使えなければ 501 で止める。使えれば ocr_info の結果を返す"""
    info = ocr_info(store)
    if not info["available"]:
        raise ApiError(info["reason"] or txt("err.ocr.none"), 501)
    return info


def run_ocr(store: Store, data: bytes, cache_dir=None, **req) -> dict:
    """画像のバイト列を文字認識する。req は OcrRequest の項目(langs scale speed timeout)。失敗したら 502"""
    prefs = use_store(store)
    try:
        return engine.run_ocr_bytes(data, cache_dir=cache_dir, req=OcrRequest(**req), pref=prefs["engine"])
    except OcrUnavailable as e:
        raise ApiError(error_text(e), 502)


def save_prefs(store: Store, body: dict) -> dict:
    """POST /api/ocr/prefs {"engine"?, "tier"?}: 設定を変える。知らない値は 400"""
    if "engine" in body and body["engine"] not in OCR_ENGINE_PREFS:
        raise ApiError(txt("err.ocr.pref"), 400)
    if "tier" in body and body["tier"] not in PPOCR_TIERS:
        raise ApiError(txt("err.ocr.pref"), 400)
    with userdata.editing(store.d, "ocr_prefs") as prefs:
        prefs.update({k: body[k] for k in ("engine", "tier") if k in body})
    return ocr_info(store)


# 部品の導入の仕事(データ置き場ごとに1つ)。(スレッド, 進み具合)。導入は数分かかるので裏で動かし、画面は進み具合を聞く
_jobs: dict[str, tuple[threading.Thread, runtime.InstallProgress]] = {}
_jobs_lock = threading.Lock()


def _install_job(store: Store, tier: str, progress: runtime.InstallProgress) -> None:
    """裏のスレッドで部品を入れる。失敗は進み具合に書く(スレッドの外に投げない)"""
    error = None
    with collect_log() as lines:
        try:
            runtime.install(store.d, tier, progress)
        except OcrUnavailable as e:
            error = error_text(e)
        except Exception as e:  # noqa: BLE001  取得・展開の想定外の失敗も画面に出す
            error = txt("err.ocr.runtime.failed", msg=str(e))
    engine.forget()
    progress.finish(lines, error)


def install_runtime(store: Store) -> dict:
    """POST /api/ocr/runtime/install: 高精度エンジンの部品を入れ始める(すぐ返す)。戻り値は進み具合。
    もう走っていれば今の進み具合を返すだけ(2つ目は始めない)。入れられないこと(表・タグ)が分かれば 502"""
    prefs = use_store(store)
    with _jobs_lock:
        job = _jobs.get(str(store.d))
        if job and job[0].is_alive():
            return job[1].snapshot()
        try:
            runtime.plan_install(store.d, prefs["tier"])
        except OcrUnavailable as e:
            raise ApiError(error_text(e), 502)
        progress = runtime.InstallProgress()
        progress.begin([])  # 部品の一覧が決まるまでのあいだも「取得中」に見せる
        thread = threading.Thread(target=_install_job, args=(store, prefs["tier"], progress), daemon=True)
        _jobs[str(store.d)] = (thread, progress)
        thread.start()
        return progress.snapshot()


def install_progress(store: Store) -> dict:
    """GET /api/ocr/runtime/progress: 導入の進み具合(state・index/count・name・done/total(バイト)・elapsed・error・lines)"""
    job = _jobs.get(str(store.d))
    return (job[1] if job else runtime.InstallProgress()).snapshot()


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)
ROUTES = {
    ("GET", "/api/ocr-info"): lambda c: ocr_info(c.store),
    ("POST", "/api/ocr/prefs"): lambda c: save_prefs(c.store, c.body()),
    ("POST", "/api/ocr/runtime/install"): lambda c: c.empty_body() or install_runtime(c.store),
    ("GET", "/api/ocr/runtime/progress"): lambda c: install_progress(c.store),
}
