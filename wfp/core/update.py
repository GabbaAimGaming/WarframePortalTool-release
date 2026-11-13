"""データ更新: ドロップ表・入手先・Riven 相場・名前辞書と、同じ Export から作るシミュレータ用データ・バロ用の辞書・MOD 効果検索のデータ・要求素材集のデータ、侵略用のノード名
(シミュレータ用データは core/simdata、内部パスの辞書は core/names の item_paths_from_exports。2026-11-10 に wfp の外から移した)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from wfp.core import arbitration, invasion, modstats, recipes, riven, simdata
from wfp.core.common import export_lang
from wfp.core.errors import TextFailure, error_text
from wfp.core.i18n import name_txt, txt
from wfp.core.log import say
from wfp.core.names import item_paths_from_exports
from wfp.core.const import DROPS_URLS, WFCD_BASES, WFCD_EXTRA
from wfp.fetch import exports, logos, net
from wfp.store import gamedata


class UpdateFailed(TextFailure):
    """データ更新を続けられない(ドロップ表か名前辞書が取れなかった)。文はテキスト指定"""


@dataclass
class _StageCtx:
    """名前辞書のあとの段階に渡すもの: データ置き場・取った Export(docs の en / ja / source)・更新日時"""
    d: Path
    docs: dict
    updated: str


def _stage_sim(c: _StageCtx) -> dict:
    """シミュレータ用のデータ(フレーム・武器の性能)。同じ Export から作る(追加のダウンロードはしない)"""
    sim = simdata.save_builder_data(c.d, simdata.extract_builder_data(c.docs["en"], c.docs["ja"]), c.docs["source"])
    return txt("log.sim.done", f=str(len(sim["frames"])), w=str(len(sim["weapons"])))


def _stage_paths(c: _StageCtx) -> dict:
    """バロの在庫(内部パス)を名前にする辞書。同じ Export から作る"""
    paths = item_paths_from_exports(c.docs["en"])
    gamedata.save_item_paths(c.d, paths)
    return txt("log.paths.done", n=str(len(paths)))


def _stage_modstats(c: _StageCtx) -> dict:
    """MOD 効果検索のデータ(ランクごとの効果テキスト)。同じ Export から作る"""
    mod_data = modstats.make_mod_stats(c.docs["en"], c.docs["ja"], c.docs["source"], c.updated)
    if not mod_data["mods"]:
        raise TextFailure(txt("err.modstats.none"))
    gamedata.save_mod_stats(c.d, mod_data)
    return txt("log.modstats.done", n=str(len(mod_data["mods"])))


def _stage_recipes(c: _StageCtx) -> dict:
    """要求素材集のデータ(設計図と素材)。同じ Export(ExportRecipes)から作る"""
    data = recipes.make_recipes(c.docs["en"], c.docs["source"], c.updated)
    if not data["recipes"]:
        raise TextFailure(txt("err.recipes.none"))
    gamedata.save_recipes(c.d, data)
    return txt("log.recipes.done", n=str(len(data["recipes"])))


def _stage_regions(c: _StageCtx) -> dict:
    """侵略サイクル・仲裁のノード名(SolNode… → ノード名・惑星名)。名前辞書とは別に取る(names.json に混ぜないため)"""
    en_doc, ja_doc, src = exports.fetch_regions()
    regions = invasion.regions_from_exports(en_doc, ja_doc)
    if not regions:
        raise TextFailure(txt("err.regions.none"))
    gamedata.save_regions(c.d, regions)
    return txt("log.regions.done", n=str(len(regions)), src=name_txt("export.src.", src))


def _stage_arbys(c: _StageCtx) -> dict:
    """仲裁のスケジュール(browse.wf の arbys.txt)"""
    sched = arbitration.update_arbys(c.d)
    last = datetime.fromtimestamp(sched.last, timezone.utc).strftime("%Y-%m-%d")
    return txt("log.arbys.done", n=str(len(sched)), last=last)


# 名前辞書のあとの段階: (取りに行く前のログ。None なら出さない, 処理 → 済みのログ, 失敗のログ)。上から順に行う
_FOLLOW_STAGES: tuple[tuple[str | None, Callable[[_StageCtx], dict], str], ...] = (
    (None, _stage_sim, "log.sim.failed"),
    (None, _stage_paths, "log.paths.failed"),
    (None, _stage_modstats, "log.modstats.failed"),
    (None, _stage_recipes, "log.recipes.failed"),
    ("log.fetching.regions", _stage_regions, "log.regions.failed"),
    ("log.fetching.arbys", _stage_arbys, "log.arbys.failed"),
)


def lang_targets(d: Path, langs: tuple[str, ...] = ()) -> list[str]:
    """日英のほかに名前辞書を取る言語: langs(画面で選んでいる言語)と、手元に名前辞書がある言語。

    ja・en と Export に無い言語は入れない(ja・en は毎回取るので)。並びは EXPORT_EXTRA_LANGS の順(held_lang_names に合わせる)
    """
    picked = {code for code in (export_lang(x) for x in langs) if code}
    held = gamedata.held_lang_names(d)
    return held + sorted(picked - set(held))


def update_lang_names(d: Path, targets: list[str], en_docs: list[dict], first_src: str | None, updated: str) -> None:
    """targets の言語の名前辞書を取って names_<言語>.json に書く。1言語ずつ、失敗してもログを出して前回分を残し、次へ進む"""
    if not targets:
        return
    say(txt("log.fetching.langs", langs=", ".join(targets)))
    for lang in targets:
        try:
            names, src = exports.fetch_lang_names(lang, en_docs, first_src)
            gamedata.save_lang_names(d, lang, names, src, updated)
            say(txt("log.lang.done", lang=lang, n=str(len(names)), src=name_txt("export.src.", src)), 1)
        except Exception as e:  # noqa: BLE001
            say(txt("log.lang.failed", lang=lang, e=error_text(e)), 1)


def update_all(d: Path, langs: tuple[str, ...] = ()) -> None:
    """公式データをまとめて取得・更新する(CLI の update / 画面の「データ更新」)。

    langs は名前辞書を日英のほかに取りたい言語(画面で選んでいる言語のコード。lang_targets で絞る)。
    進み具合は say で出す(CLI は日本語で標準出力に、画面は collect_log で集めて表示中の言語にする)。各段階は失敗しても前回分で続行し、
    ドロップ表か名前辞書が取れなかったときだけ UpdateFailed で止める。
    """
    say(txt("log.fetching.drops"))
    raw = None
    for url in DROPS_URLS:
        try:
            raw = net.http_get(url)
            json.loads(raw)
            say(txt("log.source", src=url), 1)
            break
        except Exception as e:  # noqa: BLE001
            say(txt("log.failed.what", what=url, e=error_text(e)), 1)
            raw = None
    if raw is None:
        raise UpdateFailed(txt("err.update.drops"))
    gamedata.save_drops(d, raw)

    say(txt("log.fetching.extra"))
    ok_extra = 0
    for name in WFCD_EXTRA:
        try:
            gamedata.save_wfcd(d, name, net.fetch_json([f"{b}/{name}.json" for b in WFCD_BASES]))
            ok_extra += 1
        except Exception as e:  # noqa: BLE001
            say(txt("log.failed.keep", what=name, e=error_text(e)), 1)
    say(txt("log.extra.count", ok=str(ok_extra), total=str(len(WFCD_EXTRA))), 1)

    riven.update_rivens(d)

    say(txt("log.fetching.names"))
    docs: dict = {}
    try:
        names = exports.fetch_names(docs)
    except Exception as e:  # noqa: BLE001
        raise UpdateFailed(txt("err.update.names", e=error_text(e))) from e
    names["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    gamedata.save_names(d, names)
    say(txt("log.names.done", names=str(len(names["en2ja"])), res=str(len(names["resources"])), mods=str(len(names["mods"])), dir=str(d)))

    # 日英のほかの言語の名前辞書(選んでいる言語・手元にある言語)。同じ英語版の Export と突き合わせる
    update_lang_names(d, lang_targets(d, langs), docs.get("en") or [], docs.get("source"), names["updated"])

    # 同じ Export から作るデータ・別に取るデータ(_FOLLOW_STAGES の順。どれも失敗したら前回分のまま続ける)
    ctx = _StageCtx(d, docs, names["updated"])
    for fetching, build, failed in _FOLLOW_STAGES:
        if fetching:
            say(txt(fetching))
        try:
            say(build(ctx))
        except Exception as e:  # noqa: BLE001
            say(txt(failed, e=error_text(e)), 1)

    if not logos.find_logos_dir(d):  # 初回(ロゴ素材が未取得)のときだけ取得する
        logos.fetch_logos(d)

