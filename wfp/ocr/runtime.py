"""高精度の文字認識の部品(ホイール・モデル)の場所・導入・検査。設計 §5 の案 A(画面のボタンで、データ置き場に入れる)。

置き場所: <データ置き場>/ocr_runtime/
  site-packages/      ホイールを展開したもの(Python のタグごと。タグが変われば入れ直す)
  models/<段>/det|rec/inference.onnx・inference.yml
  installed.json      {"tag": "cp314", "wheels": [名前], "models": {段: [パス]}}
入れる部品の表は data/ocr/runtime.json(packages・files は Python のタグごと)。**表に今の Python のタグが無ければ
ホイールは入れない**(onnxruntime の cp315 待ちのあいだ、3.15 の同梱版は winrt のまま動く)。lite 版で pip で入れた人は
モジュールがあればそれを使い、モデルだけ取る。SHA-256 が空の部品は入れない(表は tools/ocr_runtime_lock.py が作る)。
"""
from __future__ import annotations

import hashlib
import importlib
import io
import json
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

from wfp.core.const import (
    OCR_DOWNLOAD_TIMEOUT, OCR_RUNTIME_DIR, OCR_RUNTIME_INSTALLED, OCR_RUNTIME_MODELS, OCR_RUNTIME_MODULES, OCR_RUNTIME_SITE,
    PPOCR_MODEL_FILES, PPOCR_MODEL_PARTS,
)
from wfp.core.i18n import txt
from wfp.core.log import say
from wfp.fetch import net
from wfp.ocr.engine import OcrUnavailable
from wfp.store import appdata, datadir


def python_tag(version=None) -> str:
    """ホイールのタグ(例: cp314)"""
    v = version or sys.version_info
    return f"cp{v[0]}{v[1]}"


def runtime_root(d: Path) -> Path:
    return d / OCR_RUNTIME_DIR


def site_dir(d: Path) -> Path:
    return runtime_root(d) / OCR_RUNTIME_SITE


def model_dir(d: Path, tier: str) -> Path:
    return runtime_root(d) / OCR_RUNTIME_MODELS / tier


def model_paths(d: Path, tier: str) -> dict[str, dict[str, Path]]:
    """{"det": {"inference.onnx": パス, ...}, "rec": {...}}"""
    return {part: {f: model_dir(d, tier) / part / f for f in PPOCR_MODEL_FILES} for part in PPOCR_MODEL_PARTS}


def read_table() -> dict:
    """部品の表(data/ocr/runtime.json)。無い・壊れていれば空の表"""
    raw = appdata.read_ocr_runtime()
    raw = raw if isinstance(raw, dict) else {}
    return {key: raw.get(key) if isinstance(raw.get(key), dict) else {} for key in ("packages", "files", "models")}


def wheel_entries(table: dict, tag: str) -> list[dict]:
    files = table["files"].get(tag)
    return [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []


def model_entries(table: dict, tier: str) -> list[dict]:
    files = table["models"].get(tier)
    return [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []


def read_installed(d: Path) -> dict:
    raw = datadir.read_json(runtime_root(d) / OCR_RUNTIME_INSTALLED)
    raw = raw if isinstance(raw, dict) else {}
    return {"tag": raw.get("tag") or "", "wheels": list(raw.get("wheels") or []),
            "models": raw.get("models") if isinstance(raw.get("models"), dict) else {}}


def activate(d: Path) -> bool:
    """入れたホイールを読めるようにする(sys.path の先頭に足す)。入れたときのタグが今の Python と違えば足さない"""
    site = str(site_dir(d))
    if read_installed(d)["tag"] != python_tag() or not site_dir(d).is_dir():
        return False
    if site not in sys.path:
        sys.path.insert(0, site)
    return True


def missing_module() -> str:
    """要るモジュールのうち読めない最初のもの(全部読めれば "")"""
    for name in OCR_RUNTIME_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            return name
    return ""


def models_ready(d: Path, tier: str) -> bool:
    return all(p.is_file() for files in model_paths(d, tier).values() for p in files.values())


def status(d: Path, tier: str) -> dict:
    """画面の表示用: {"tag", "supported"(この Python 向けのホイールが表にある), "modules", "models", "ready"}"""
    activate(d)
    tag = python_tag()
    modules = not missing_module()
    models = models_ready(d, tier)
    return {"tag": tag, "tier": tier, "supported": bool(wheel_entries(read_table(), tag)),
            "modules": modules, "models": models, "ready": modules and models}


def plan_install(d: Path, tier: str) -> tuple[list[dict], list[dict]]:
    """入れるもの (ホイール, モデル)。この Python 向けのホイールが無く、モジュールも無ければ OcrUnavailable。
    SHA-256 が空の部品があれば OcrUnavailable(表がまだ用意されていない)"""
    activate(d)
    table, tag = read_table(), python_tag()
    wheels = []
    if missing_module():
        wheels = wheel_entries(table, tag)
        if not wheels:
            raise OcrUnavailable(txt("err.ocr.runtime.pyver", tag=tag))
    models = [] if models_ready(d, tier) else model_entries(table, tier)
    if not models_ready(d, tier) and not models:
        raise OcrUnavailable(txt("err.ocr.runtime.nohash"))
    if any(not e.get("sha256") or not e.get("url") for e in wheels + models):
        raise OcrUnavailable(txt("err.ocr.runtime.nohash"))
    return wheels, models


class InstallProgress:
    """導入の進み具合。導入する裏のスレッドが書き、画面の問い合わせ(snapshot)が読む。
    state: idle(まだ)/ running(取得・展開中)/ done(終わった)/ failed(失敗。error にテキスト指定)。
    量は部品の表の size を足したもの(大きさの分からない部品は取れた量だけ足す)"""

    def __init__(self):
        self._lock = threading.Lock()
        self.state, self.phase, self.name, self.error = "idle", "", "", None
        self.index = self.count = self.done = self.total = self._base = 0
        self.started = self.ended = 0.0
        self.lines: list = []

    def begin(self, entries: list[dict]) -> None:
        with self._lock:
            self.state, self.phase, self.error, self.lines = "running", "fetch", None, []
            self.index, self.count, self.done, self._base = 0, len(entries), 0, 0
            self.total = sum(int(e.get("size") or 0) for e in entries)
            self.started, self.ended = time.time(), 0.0

    def next_file(self, entry: dict) -> None:
        """次の部品を取り始める(前の部品の量を確定する)"""
        with self._lock:
            self._base = self.done
            self.index += 1
            self.name = entry_name(entry)

    def got(self, size_in_file: int) -> None:
        with self._lock:
            self.done = self._base + size_in_file

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self.phase = phase

    def finish(self, lines: list, error=None) -> None:
        with self._lock:
            self.state = "failed" if error else "done"
            self.error, self.lines, self.ended = error, list(lines), time.time()

    def snapshot(self) -> dict:
        with self._lock:
            end = self.ended or time.time()
            return {"state": self.state, "phase": self.phase, "index": self.index, "count": self.count, "name": self.name,
                    "done": self.done, "total": max(self.total, self.done),
                    "elapsed": round(end - self.started, 1) if self.started else 0, "error": self.error, "lines": self.lines}


def entry_name(entry: dict) -> str:
    return str(entry.get("name") or entry.get("path") or entry.get("url", "").rsplit("/", 1)[-1])


def download(entry: dict, progress: InstallProgress | None = None) -> bytes:
    """部品を少しずつ取って(進み具合を progress に)SHA-256(と大きさ)を照合する。合わなければ OcrUnavailable"""
    name = entry_name(entry)
    say(txt("log.ocr.fetch", name=name), 1)
    if progress:
        progress.next_file(entry)
    try:
        data = net.http_download(entry["url"], timeout=OCR_DOWNLOAD_TIMEOUT, on_chunk=progress.got if progress else None)
    except OSError as e:
        raise OcrUnavailable(txt("err.ocr.runtime.fetch", name=name, msg=str(e)))
    if hashlib.sha256(data).hexdigest() != str(entry["sha256"]).lower() or (entry.get("size") and len(data) != entry["size"]):
        raise OcrUnavailable(txt("err.ocr.runtime.hash", name=name))
    return data


def safe_members(archive: zipfile.ZipFile, name: str) -> list[str]:
    """展開してよい名前の一覧。絶対パス・.. を含む名前があれば OcrUnavailable"""
    members = archive.namelist()
    for member in members:
        parts = member.replace("\\", "/").split("/")
        if member.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
            raise OcrUnavailable(txt("err.ocr.runtime.zip", name=name))
    return members


def _swap_dir(new_dir: Path, target: Path) -> None:
    """new_dir を target に置き換える(前の target は消す)。途中で失敗しても前の target が残るように、先に退避する"""
    old = target.with_name(f".{target.name}.old")
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    try:
        new_dir.rename(target)
    except OSError:
        if old.exists():
            old.rename(target)
        raise
    shutil.rmtree(old, ignore_errors=True)


def install_wheels(d: Path, wheels: list[dict], progress: InstallProgress | None = None) -> None:
    """ホイールを一時フォルダに全部展開してから site-packages と置き換える(途中で失敗したら前のまま)"""
    new_dir = runtime_root(d) / f".{OCR_RUNTIME_SITE}.new"
    shutil.rmtree(new_dir, ignore_errors=True)
    new_dir.mkdir(parents=True)
    try:
        for entry in wheels:
            data = download(entry, progress)
            if progress:
                progress.set_phase("extract")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.extractall(new_dir, safe_members(archive, entry_name(entry)))
            if progress:
                progress.set_phase("fetch")
        _swap_dir(new_dir, site_dir(d))
    finally:
        shutil.rmtree(new_dir, ignore_errors=True)


def install_models(d: Path, tier: str, models: list[dict], progress: InstallProgress | None = None) -> None:
    """モデルを全部取ってから書く(1つでも取れなければ何も書かない)。パスに .. があれば取る前に止める"""
    for entry in models:
        if ".." in Path(str(entry["path"])).parts:
            raise OcrUnavailable(txt("err.ocr.runtime.zip", name=entry_name(entry)))
    fetched = [(entry, download(entry, progress)) for entry in models]
    if progress:
        progress.set_phase("write")
    for entry, data in fetched:
        path = model_dir(d, tier) / str(entry["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        datadir.write_atomic(path, data)


def install(d: Path, tier: str, progress: InstallProgress | None = None) -> dict:
    """足りない部品を入れる。戻り値は status。失敗は OcrUnavailable(入れる前の状態のまま)。
    progress を渡すと進み具合を書く(終わった・失敗したの印は呼ぶ側が finish で付ける)"""
    wheels, models = plan_install(d, tier)
    if progress:
        progress.begin(wheels + models)
    runtime_root(d).mkdir(parents=True, exist_ok=True)
    installed = read_installed(d)
    if wheels:
        install_wheels(d, wheels, progress)
        installed.update(tag=python_tag(), wheels=[entry_name(e) for e in wheels])
    if models:
        install_models(d, tier, models, progress)
        installed["models"][tier] = [str(e["path"]) for e in models]
    datadir.write_atomic(runtime_root(d) / OCR_RUNTIME_INSTALLED, json.dumps(installed, ensure_ascii=False, indent=1))
    say(txt("log.ocr.done"))
    return status(d, tier)
