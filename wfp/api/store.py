"""画面向け API の共通部分: データのキャッシュ(Store)・エラー(ApiError)・更新日時の表示"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wfp.core.arbitration import Schedule, load_schedule
from wfp.core.i18n import render_ja, txt
from wfp.core.const import (
    ARBYS_FILE, BUILDER_FILE, CLAN_FILE, DROPS_FILE, MOD_STATS_FILE, MOD_TARGETS_FILE, NAMES_FILE, OTHER_FILE, RIVENS_FILE,
    WFCD_DIR,
)
from wfp.core.loader import load_drops, load_names, load_rivens, load_sources
from wfp.core.modstats import ModStats, load_mod_stats
from wfp.core.names import Names
from wfp.drops.search import all_item_names
from wfp.drops.tables import Drops, Sources
from wfp.store import appdata, gamedata


JST = timezone(timedelta(hours=9))


def file_stamp(*files: Path) -> tuple:
    """ファイルの更新日時の組(無いファイルは -1)。Store.derived の stamp に使う"""
    return tuple(f.stat().st_mtime_ns if f.exists() else -1 for f in files)


_PLAIN = (str, int, float, bool, bytes, type(None))


def _same_stamp(a: object, b: object) -> bool:
    """stamp の比べ方: tuple は要素ごと、文字列・数などは値、ほかは同じオブジェクトか"""
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_same_stamp(x, y) for x, y in zip(a, b))
    if isinstance(a, _PLAIN) and isinstance(b, _PLAIN):
        return type(a) is type(b) and a == b
    return a is b


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

    def derived(self, key: str, stamp: tuple, build):
        """作るのに時間がかかる値のキャッシュ(索引・照合の表など)。key ごとに1つ覚える。

        stamp(元になったものの組)が前と同じなら前の値、違えば build() で作り直す。stamp の要素は、文字列・数などは値で、
        それ以外(読み込んだデータのオブジェクト)は同じオブジェクトかで比べる(stamp ごと覚えるので、id の使い回しで取り違えない)。
        build は鍵の外で呼ぶ(ほかのリクエストを待たせない。同時に作り直したときは後の方が残る)。build が例外なら覚えない
        """
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None and _same_stamp(hit[0], stamp):
            return hit[1]
        obj = build()
        with self._lock:
            self._cache[key] = (stamp, obj)
        return obj

    def builder(self) -> dict | None:
        """シミュレータ用データ(builder.json。変われば読み直す)"""
        return self._cached(BUILDER_FILE, lambda: gamedata.read_builder(self.d))

    def drops(self) -> Drops | None:
        return self._cached(DROPS_FILE, lambda: load_drops(self.d))

    def arbys(self) -> Schedule | None:
        """仲裁のスケジュール(arbys.txt が変われば読み直す)"""
        return self._cached(ARBYS_FILE, lambda: load_schedule(self.d))

    def names(self) -> Names:
        return self._cached(NAMES_FILE, lambda: load_names(self.d)) or Names()

    def names_info(self) -> dict:
        f = self.d / NAMES_FILE
        if not f.exists():
            return {}
        j = json.loads(f.read_text(encoding="utf-8"))
        return {"updated": j.get("updated"), "source": j.get("source"), "mods": len(j.get("mods") or [])}

    def sources(self) -> Sources | None:
        """敵・バウンティ等 (wfcd/ 以下の複数ファイル) と同梱のクラン研究・Simaris 交換など。どれかが更新されたら読み直す。
        wfcd/ がまだ無くても同梱分の行は返す(どれも無ければ None)"""
        folder = self.d / WFCD_DIR
        files = sorted(folder.glob("*.json")) if folder.exists() else []
        bundled = [appdata.parts_dir() / n for n in (CLAN_FILE, OTHER_FILE)]
        files_all = files + [f for f in bundled if f.exists()]
        stamp = tuple((str(f), f.stat().st_mtime_ns) for f in files_all)
        return self.derived("@sources", stamp, lambda: load_sources(self.d) if files_all else None)

    def mod_stats(self) -> ModStats | None:
        """MOD 効果検索のデータ。mod_stats.json か影響先の辞書(同梱の targets.json)が変われば読み直す"""
        files = (self.d / MOD_STATS_FILE, appdata.mod_stats_dir() / MOD_TARGETS_FILE)
        return self.derived("@mod_stats", file_stamp(*files), lambda: load_mod_stats(self.d))

    def rivens(self) -> list | None:
        return self._cached(RIVENS_FILE, lambda: load_rivens(self.d))

    def all_items(self) -> list[str]:
        drops, src = self.drops(), self.sources()
        return self.derived("@items", (drops, src), lambda: all_item_names(drops, src) if drops else [])


class ApiError(Exception):
    """API のエラー。msg は日本語の文か、テキスト指定(txt("err.…", 値=…)。リストも可)。

    テキスト指定なら画面は表示中の言語で出す(応答の text)。日本語の文(error)は web/i18n/ja.json から作る(core/i18n の ja_text)。
    日本語の文を直接渡す書き方は多言語対応の済んでいないページ用(画面はその文をそのまま出す)
    """

    def __init__(self, msg, status: int = 400):
        self.text = None if isinstance(msg, str) else msg
        super().__init__(render_ja(msg) if self.text else msg)
        self.status = status

    def payload(self) -> dict:
        """応答の本文: {"error": 日本語の文, "text": テキスト指定(あれば)}"""
        return {"error": str(self), **({"text": self.text} if self.text else {})}


class Raw:
    """JSON 以外の応答(画像など)"""

    def __init__(self, body: bytes, ctype: str, cache: str = "no-store"):
        self.body, self.ctype, self.cache = body, ctype, cache


def need_drops(store: Store) -> Drops:
    drops = store.drops()
    if drops is None:
        raise ApiError(txt("err.nodata"), 409)
    return drops


def mtime_jst(f: Path) -> str | None:
    return datetime.fromtimestamp(f.stat().st_mtime, JST).strftime("%Y-%m-%d %H:%M") if f.exists() else None
