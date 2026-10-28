"""データ更新: ドロップ表・入手先・Riven 相場・名前辞書と、同じ Export から作るシミュレータ用データ・バロ用の辞書、侵略用のノード名

層のルールの例外: このモジュールだけは wfportal_builder / wfportal_baro を import してよい
(2つを wfp へ移すまでの一時的な扱い。tests/test_layers.py に同じ例外を書いてある)。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import wfportal_baro as wbaro
import wfportal_builder as wb
from wfp.core import invasion, riven
from wfp.core.common import (DROPS_URLS, WFCD_BASES, WFCD_EXTRA, TextError, TextFailure, error_text, export_lang, name_txt, say,
                             txt)
from wfp.fetch import exports, logos, net
from wfp.store import gamedata


class UpdateFailed(TextFailure):
    """データ更新を続けられない(ドロップ表か名前辞書が取れなかった)。文はテキスト指定"""


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
    (d / "missionRewards.json").write_bytes(raw)

    say(txt("log.fetching.extra"))
    (d / "wfcd").mkdir(exist_ok=True)
    ok_extra = 0
    for name in WFCD_EXTRA:
        try:
            (d / "wfcd" / f"{name}.json").write_bytes(net.fetch_json([f"{b}/{name}.json" for b in WFCD_BASES]))
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
    (d / "names.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    say(txt("log.names.done", names=str(len(names["en2ja"])), res=str(len(names["resources"])), mods=str(len(names["mods"])), dir=str(d)))

    # 日英のほかの言語の名前辞書(選んでいる言語・手元にある言語)。同じ英語版の Export と突き合わせる
    update_lang_names(d, lang_targets(d, langs), docs.get("en") or [], docs.get("source"), names["updated"])

    # シミュレータ用のデータ(フレーム・武器の性能)も、同じ Export から作る(追加のダウンロードはしない)
    try:
        sim = wb.save_builder_data(d, wb.extract_builder_data(docs["en"], docs["ja"]), docs["source"])
        say(txt("log.sim.done", f=str(len(sim["frames"])), w=str(len(sim["weapons"]))))
    except Exception as e:  # noqa: BLE001
        say(txt("log.sim.failed", e=error_text(e)), 1)

    # バロの在庫(内部パス)を名前にする辞書も、同じ Export から作る
    try:
        paths = wbaro.item_paths_from_exports(docs["en"])
        wbaro.save_item_paths(d, paths)
        say(txt("log.paths.done", n=str(len(paths))))
    except Exception as e:  # noqa: BLE001
        say(txt("log.paths.failed", e=error_text(e)), 1)

    # 侵略サイクルのノード名(SolNode… → ノード名・惑星名)。名前辞書とは別に取る(names.json に混ぜないため)
    say(txt("log.fetching.regions"))
    try:
        en_doc, ja_doc, src = exports.fetch_regions()
        regions = invasion.regions_from_exports(en_doc, ja_doc)
        if not regions:
            raise TextFailure(txt("err.regions.none"))
        gamedata.save_regions(d, regions)
        say(txt("log.regions.done", n=str(len(regions)), src=name_txt("export.src.", src)))
    except Exception as e:  # noqa: BLE001
        say(txt("log.regions.failed", e=error_text(e)), 1)

    if not logos.find_logos_dir(d):  # 初回(ロゴ素材が未取得)のときだけ取得する
        logos.fetch_logos(d)

