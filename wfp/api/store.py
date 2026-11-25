"""画面向け API の共通部分: データのキャッシュ(Store)・エラー(ApiError)・更新日時の表示"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from wfp.core.arbitration import Schedule, load_schedule
from wfp.core.i18n import render_ja, txt
from wfp.core.const import (
    ARBYS_FILE, BUILDER_FILE, CLAN_FILE, DROPS_FILE, MOD_STATS_FILE, MOD_TARGETS_FILE, NAMES_FILE, OTHER_FILE, RECIPES_FILE, RIVENS_FILE,
    WFCD_DIR, JST, ITEM_PATHS_FILE, WORLDSTATE_FILE,
)
from wfp.core.loader import load_drops, load_recipes, load_resurgence, load_rivens, load_sources, vendor_choices
from wfp.core.modstats import ModStats, load_mod_stats
from wfp.core.names import Names
from wfp.core.offers import vendors_on
from wfp.core.recipes import Recipes
from wfp.drops.search import all_item_names, source_index
from wfp.drops.tables import Drops, Resurgence, Sources, Vault
from wfp.store import appdata, gamedata


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
        self._offer_choices: dict[str, bool] | None = None  # 入手先に出す商人の選択(利用者データ。offer_choices で読んで覚える)

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

    def _names(self) -> tuple[Names, dict] | None:
        """名前辞書と、その取得の情報(更新日時・取得元・MOD の数)。names.json を読むのは1回(変われば読み直す)。
        無ければ None、壊れていれば gamedata.DataBroken(覚えない)"""
        def load() -> tuple[Names, dict] | None:
            raw = gamedata.read_names(self.d)
            if raw is None:
                return None
            info = {"updated": raw.get("updated"), "source": raw.get("source"), "mods": len(raw.get("mods") or [])}
            return Names.from_json(raw), info
        return self._cached(NAMES_FILE, load)

    def names(self) -> Names:
        pair = self._names()
        return pair[0] if pair else Names()

    def names_info(self) -> dict:
        """names.json の取得の情報(無ければ空)"""
        pair = self._names()
        return pair[1] if pair else {}

    def sources(self) -> Sources | None:
        """敵・バウンティ等 (wfcd/ 以下の複数ファイル) と同梱のクラン研究・Simaris 交換など。どれかが更新されたら読み直す。
        wfcd/ がまだ無くても同梱分の行は返す(どれも無ければ None)"""
        folder = self.d / WFCD_DIR
        files = sorted(folder.glob("*.json")) if folder.exists() else []
        bundled = [appdata.parts_dir() / n for n in (CLAN_FILE, OTHER_FILE)]
        files_all = files + [f for f in bundled if f.exists()]
        # オプションの offers.json は、名前を引く item_paths.json・names.json と、選んだ商人(利用者データ)と一緒に目印にする
        # (どれかが変われば作り直す)
        offers = gamedata.offers_path(self.d)
        named = [offers, self.d / ITEM_PATHS_FILE, self.d / NAMES_FILE] if offers.exists() else []
        choices = self.offer_choices() if named else {}
        chosen = tuple(sorted(vendors_on(choices)))
        stamp = tuple((str(f), f.stat().st_mtime_ns) for f in files_all + [f for f in named if f.exists()]) + (chosen,)
        return self.derived("@sources", stamp, lambda: load_sources(self.d, choices) if files_all or named else None)

    def offer_choices(self) -> dict[str, bool]:
        """入手先に出す商人の選択。1回読んだら覚える(sources のたびに userdata.db を開かない)。
        選択を変えるのは画面のサーバー(POST /api/offers/vendors)だけなので、変えたら forget_offer_choices で読み直させる"""
        choices = self._offer_choices
        if choices is None:
            choices = self._offer_choices = vendor_choices(self.d)
        return choices

    def forget_offer_choices(self) -> None:
        """商人の選択を読み直させる(選択を保存したあとに呼ぶ)"""
        self._offer_choices = None

    def mod_stats(self) -> ModStats | None:
        """MOD 効果検索のデータ。mod_stats.json か影響先の辞書(同梱の targets.json)が変われば読み直す"""
        files = (self.d / MOD_STATS_FILE, appdata.mod_stats_dir() / MOD_TARGETS_FILE)
        return self.derived("@mod_stats", file_stamp(*files), lambda: load_mod_stats(self.d))

    def recipes(self) -> Recipes:
        """要求素材集の設計図(recipes.json が変われば読み直す。無ければ空)"""
        return self._cached(RECIPES_FILE, lambda: load_recipes(self.d)) or Recipes()

    def rivens(self) -> list | None:
        return self._cached(RIVENS_FILE, lambda: load_rivens(self.d))

    def resurgence(self) -> Resurgence:
        """Prime Resurgence の期間と交換できるレリック(worldstate.json・item_paths.json が変われば読み直す)"""
        files = (self.d / WORLDSTATE_FILE, self.d / ITEM_PATHS_FILE)
        return self.derived("@resurgence", file_stamp(*files), lambda: load_resurgence(self.d))

    def vault(self) -> Vault:
        """Vault 入りのレリックと入手不可の項目(ドロップ表・入手先・Prime Resurgence が変わるか、その期間に入る・終わると作り直す)"""
        drops, src, res = self.drops(), self.sources(), self.resurgence()
        active = res.active(time.time())
        return self.derived("@vault", (drops, src, res, active), lambda: Vault(drops, src, res))

    def vault_plain(self) -> Vault:
        """Prime Resurgence を見ない Vault 入りの判定(レリックがドロップしないものは、交換できる間も Vault 入り)。
        Prime の時系列のゲージ用。ドロップ表・入手先が変われば作り直す"""
        drops, src = self.drops(), self.sources()
        return self.derived("@vault_plain", (drops, src), lambda: Vault(drops, src))

    def source_index(self) -> dict[str, list[tuple]]:
        """項目ごとの入手先の索引(drops/search の source_index。MOD 入手一覧・アルケイン所持一覧の集計用)。
        ドロップ表・入手先が変われば作り直す"""
        drops, src = self.drops(), self.sources()
        return self.derived("@srcidx", (drops, src), lambda: source_index(drops, src))

    def all_items(self) -> list[str]:
        """候補になる項目の英名(いま Prime Resurgence で交換できるレリックも入る)"""
        drops, src, vault = self.drops(), self.sources(), self.vault()
        return self.derived("@items", (drops, src, vault),
                            lambda: all_item_names(drops, src, vault.offered_names) if drops else [])


class ApiError(Exception):
    """API のエラー。msg は日本語の文か、テキスト指定(txt("err.…", 値=…)。リストも可)。

    テキスト指定なら画面は表示中の言語で出す(応答の text)。日本語の文(error)は web/i18n/ja/ から作る(core/i18n の ja_text)。
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


def str_list(body: dict, field: str) -> list[str]:
    """本文の項目(名前・id を1つか複数)を文字列の一覧にそろえる: 文字列 → 1件、文字列の配列 → そのまま、無い・null → 空。
    それ以外(数・オブジェクト・文字列でない要素)は 400"""
    value = body.get(field)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ApiError(txt("err.req.str_list", name=field))


def need_drops(store: Store) -> Drops:
    drops = store.drops()
    if drops is None:
        raise ApiError(txt("err.nodata"), 409)
    return drops


def mtime_jst(f: Path) -> str | None:
    return datetime.fromtimestamp(f.stat().st_mtime, JST).strftime("%Y-%m-%d %H:%M") if f.exists() else None
