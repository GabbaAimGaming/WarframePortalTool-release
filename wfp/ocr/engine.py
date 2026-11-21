"""文字認識のエンジンの共通の形・選び方・画像のバイト列の文字認識(キャッシュつき)。

エンジンは OcrEngine を継いで probe(使えるか)・recognize(読む)・cache_key(キャッシュを分ける印)を持つ。
一覧は engine_table()。選び方は select_engine(設計 §2.4):
  auto = OCR_ENGINE_ORDER の順に使えるもの / 指定 = それ、使えなければ止めずにほかへ落とす(fallback) / どれもだめ = OcrUnavailable
probe は重い(PowerShell を呼ぶ・モデルを読む)ので、エンジンごとに1回だけ調べて覚える(forget で忘れる)。
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

from wfp.core.const import OCR_DEFAULT_LANGS, OCR_ENGINE_AUTO, OCR_ENGINE_ORDER, OCR_SPEEDS, OCR_TIMEOUT
from wfp.core.errors import TextError
from wfp.core.i18n import txt
from wfp.ocr.result import check_result


class OcrUnavailable(TextError):
    """文字認識が使えない・失敗した。文はテキスト指定(画面は表示中の言語、CLI は日本語)"""


@dataclass(frozen=True)
class OcrRequest:
    """1回の文字認識の求め。langs は winrt だけが使う(ppocr は日英を1回で読む)。scale は拡大率"""
    langs: str = OCR_DEFAULT_LANGS
    scale: float = 2.0
    speed: str = OCR_SPEEDS[0]
    timeout: int = OCR_TIMEOUT


class OcrEngine:
    """エンジンの共通の形。probe の戻り値は {"available", "reason"(テキスト指定か ""), "langs", "detail"}"""
    engine_id = ""

    def probe(self) -> dict:
        raise NotImplementedError

    def recognize(self, image_bytes: bytes, req: OcrRequest) -> dict:
        raise NotImplementedError

    def cache_key(self) -> str:
        return self.engine_id


def unavailable(reason) -> dict:
    """probe の「使えない」の形"""
    return {"available": False, "reason": reason, "langs": [], "detail": {}}


_probed: dict[str, dict] = {}
_probe_lock = threading.Lock()


def engine_table() -> dict[str, OcrEngine]:
    """エンジンの一覧(id -> エンジン)。エンジンのファイルはこのファイルを使うので、ここで読み込む"""
    from wfp.ocr import ppocr, winrt
    return {e.engine_id: e for e in (winrt.ENGINE, ppocr.ENGINE)}


def configure(data_dir: Path, tier: str) -> None:
    """データ置き場と高精度エンジンの段を各エンジンに渡す(変わったエンジンは probe を忘れる)。API・CLI が読む前に呼ぶ"""
    for engine in engine_table().values():
        if hasattr(engine, "configure") and engine.configure(data_dir, tier):
            with _probe_lock:
                _probed.pop(engine.engine_id, None)


def probe(engine: OcrEngine) -> dict:
    """エンジンが使えるか(1回だけ調べて覚える)。probe の中の OcrUnavailable は「使えない」にする"""
    with _probe_lock:
        if engine.engine_id not in _probed:
            try:
                _probed[engine.engine_id] = engine.probe()
            except OcrUnavailable as err:
                _probed[engine.engine_id] = unavailable(err.text)
        return _probed[engine.engine_id]


def forget() -> None:
    """覚えている probe の結果を捨てる(テスト・部品を入れたあと)"""
    with _probe_lock:
        _probed.clear()


def _try_order(pref: str, table: dict) -> list[str]:
    """試す順。auto は OCR_ENGINE_ORDER、指定ならそれを先に"""
    order = [eid for eid in OCR_ENGINE_ORDER if eid in table] + [eid for eid in table if eid not in OCR_ENGINE_ORDER]
    if pref != OCR_ENGINE_AUTO and pref in table:
        order = [pref] + [eid for eid in order if eid != pref]
    return order


def select_engine(pref: str = OCR_ENGINE_AUTO) -> tuple[OcrEngine, dict]:
    """使うエンジンと {"engine", "fallback", "reason"}。どれも使えなければ OcrUnavailable。理由は、指定があれば
    そのエンジンの、auto なら最後に試したエンジン(いつもの Windows OCR)の理由(入れていない高精度の理由は出さない)"""
    table = engine_table()
    reasons = []
    for eid in _try_order(pref, table):
        info = probe(table[eid])
        if info["available"]:
            fallback = pref != OCR_ENGINE_AUTO and eid != pref
            return table[eid], {"engine": eid, "fallback": fallback, "reason": reasons[0] if fallback else ""}
        reasons.append(info["reason"])
    reason = (reasons[-1] if pref == OCR_ENGINE_AUTO else reasons[0]) if reasons else None
    raise OcrUnavailable(reason or txt("err.ocr.none"))


def engine_status() -> list[dict]:
    """全エンジンの状態(画面の表示用): [{id, available, reason}]"""
    table = engine_table()
    return [{"id": eid, "available": probe(table[eid])["available"], "reason": probe(table[eid])["reason"]}
            for eid in _try_order(OCR_ENGINE_AUTO, table)]


def _cache_paths(cache_dir: Path, digest: str, engine: OcrEngine) -> list[Path]:
    """読むキャッシュの候補(新しい名前が先)。前の名前 <sha1>.json は winrt の結果として読む"""
    paths = [cache_dir / f"{digest}.{engine.cache_key()}.json"]
    if engine.cache_key() == "winrt":
        paths.append(cache_dir / f"{digest}.json")
    return paths


def _read_cache(paths: list[Path]) -> dict | None:
    for path in paths:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def run_ocr_bytes(data: bytes, cache_dir: Path | None = None, req: OcrRequest | None = None,
                  pref: str = OCR_ENGINE_AUTO) -> dict:
    """画像のバイト列を文字認識する。cache_dir を渡すと同じ画像・同じエンジンの結果を使い回す。
    結果に engine(使ったエンジン)と、指定のエンジンから落としたときは fallback を付ける"""
    engine, chosen = select_engine(pref)
    paths = _cache_paths(cache_dir, hashlib.sha1(data).hexdigest(), engine) if cache_dir else []
    cached = _read_cache(paths)
    if cached is not None:
        return cached
    result = engine.recognize(data, req or OcrRequest())
    problem = check_result(result)
    if problem:
        raise OcrUnavailable(txt("err.ocr.badresult", msg=problem))
    result.setdefault("engine", engine.engine_id)
    if chosen["fallback"]:
        result["fallback"] = True
    if paths:
        paths[0].parent.mkdir(parents=True, exist_ok=True)
        paths[0].write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
