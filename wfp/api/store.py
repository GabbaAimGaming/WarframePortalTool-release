"""画面向け API の共通部分: データのキャッシュ(Store)・エラー(ApiError)・更新日時の表示"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wfp.core.common import CLAN_FILE, OTHER_FILE
from wfp.core.loader import load_drops, load_names, load_rivens, load_sources
from wfp.core.names import Names
from wfp.drops.search import all_item_names
from wfp.drops.tables import Drops, Sources
from wfp.store import appdata


JST = timezone(timedelta(hours=9))


class Store:
    def __init__(self, d: Path):
        self.d = d
        self._cache: dict[str, tuple[int, object]] = {}
        self._lock = threading.Lock()

    def _cached(self, name: str, loader):
        f = self.d / name
        mtime = f.stat().st_mtime_ns if f.exists() else -1
        with self._lock:
            hit = self._cache.get(name)
            if hit and hit[0] == mtime:
                return hit[1]
            obj = loader() if mtime != -1 else None
            self._cache[name] = (mtime, obj)
            return obj

    def drops(self) -> Drops | None:
        return self._cached("missionRewards.json", lambda: load_drops(self.d))

    def names(self) -> Names:
        return self._cached("names.json", lambda: load_names(self.d)) or Names()

    def names_info(self) -> dict:
        f = self.d / "names.json"
        if not f.exists():
            return {}
        j = json.loads(f.read_text(encoding="utf-8"))
        return {"updated": j.get("updated"), "source": j.get("source"), "mods": len(j.get("mods") or [])}

    def sources(self) -> Sources | None:
        """敵・バウンティ等 (wfcd/ 以下の複数ファイル) と同梱のクラン研究・Simaris 交換など。どれかが更新されたら読み直す。
        wfcd/ がまだ無くても同梱分の行は返す(どれも無ければ None)"""
        folder = self.d / "wfcd"
        files = sorted(folder.glob("*.json")) if folder.exists() else []
        bundled = [appdata.parts_dir() / n for n in (CLAN_FILE, OTHER_FILE)]
        files_all = files + [f for f in bundled if f.exists()]
        stamp = tuple((str(f), f.stat().st_mtime_ns) for f in files_all)
        with self._lock:
            hit = self._cache.get("@sources")
            if hit and hit[0] == stamp:
                return hit[1]
        obj = load_sources(self.d) if files_all else None
        with self._lock:
            self._cache["@sources"] = (stamp, obj)
        return obj

    def rivens(self) -> list | None:
        return self._cached("rivens.json", lambda: load_rivens(self.d))

    def all_items(self) -> list[str]:
        drops, src = self.drops(), self.sources()
        key = (id(drops), id(src))
        with self._lock:
            hit = self._cache.get("@items")
            if hit and hit[0] == key:
                return hit[1]
        names = all_item_names(drops, src) if drops else []
        with self._lock:
            self._cache["@items"] = (key, names)
        return names


class ApiError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


class Raw:
    """JSON 以外の応答(画像など)"""

    def __init__(self, body: bytes, ctype: str, cache: str = "no-store"):
        self.body, self.ctype, self.cache = body, ctype, cache


def need_drops(store: Store) -> Drops:
    drops = store.drops()
    if drops is None:
        raise ApiError("データがありません。メニューの「データ更新」から取得してください。", 409)
    return drops


def mtime_jst(f: Path) -> str | None:
    return datetime.fromtimestamp(f.stat().st_mtime, JST).strftime("%Y-%m-%d %H:%M") if f.exists() else None
