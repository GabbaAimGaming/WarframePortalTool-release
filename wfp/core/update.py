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
from wfp.core.common import DROPS_URLS, WFCD_BASES, WFCD_EXTRA
from wfp.fetch import exports, logos, net
from wfp.store import gamedata


class UpdateFailed(Exception):
    """データ更新を続けられない(ドロップ表か名前辞書が取れなかった)"""


def update_all(d: Path) -> None:
    """公式データをまとめて取得・更新する(CLI の update / 画面の「データ更新」)。

    進み具合は print で出す(画面は標準出力を横取りしてログにする)。各段階は失敗しても前回分で続行し、
    ドロップ表か名前辞書が取れなかったときだけ UpdateFailed で止める。
    """
    print("ドロップ表を取得中...")
    raw = None
    for url in DROPS_URLS:
        try:
            raw = net.http_get(url)
            json.loads(raw)
            print(f"  取得元: {url}")
            break
        except Exception as e:  # noqa: BLE001
            print(f"  失敗: {url} ({e})")
            raw = None
    if raw is None:
        raise UpdateFailed("ドロップ表を取得できませんでした。ネットワーク設定を確認してください。")
    (d / "missionRewards.json").write_bytes(raw)

    print("追加の入手先(敵・バウンティ・レリック等)を取得中...")
    (d / "wfcd").mkdir(exist_ok=True)
    ok_extra = 0
    for name in WFCD_EXTRA:
        try:
            (d / "wfcd" / f"{name}.json").write_bytes(net.fetch_json([f"{b}/{name}.json" for b in WFCD_BASES]))
            ok_extra += 1
        except Exception as e:  # noqa: BLE001
            print(f"  失敗: {name} ({e})  ※前回取得分があればそれを使います")
    print(f"  {ok_extra} / {len(WFCD_EXTRA)} ファイル取得")

    riven.update_rivens(d)

    print("名前辞書(Public Export)を取得中...")
    docs: dict = {}
    try:
        names = exports.fetch_names(docs)
    except Exception as e:  # noqa: BLE001
        raise UpdateFailed(f"名前辞書を取得できませんでした: {e}") from e
    names["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (d / "names.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    print(f"完了: 名前 {len(names['en2ja'])} 件 / 素材 {len(names['resources'])} 件 / MOD {len(names['mods'])} 件 -> {d}")

    # シミュレータ用のデータ(フレーム・武器の性能)も、同じ Export から作る(追加のダウンロードはしない)
    try:
        sim = wb.save_builder_data(d, wb.extract_builder_data(docs["en"], docs["ja"]), docs["source"])
        print(f"シミュレータ用データ: フレーム {len(sim['frames'])} 件 / 武器 {len(sim['weapons'])} 件")
    except Exception as e:  # noqa: BLE001
        print(f"  シミュレータ用データを作れませんでした: {e}  ※前回取得分があればそれを使います")

    # バロの在庫(内部パス)を名前にする辞書も、同じ Export から作る
    try:
        paths = wbaro.item_paths_from_exports(docs["en"])
        wbaro.save_item_paths(d, paths)
        print(f"内部パスの辞書: {len(paths)} 件")
    except Exception as e:  # noqa: BLE001
        print(f"  内部パスの辞書を作れませんでした: {e}  ※前回取得分があればそれを使います")

    # 侵略サイクルのノード名(SolNode… → ノード名・惑星名)。名前辞書とは別に取る(names.json に混ぜないため)
    print("ノード名(ExportRegions)を取得中...")
    try:
        en_doc, ja_doc, src = exports.fetch_regions()
        regions = invasion.regions_from_exports(en_doc, ja_doc)
        if not regions:
            raise RuntimeError("ノードが見つかりません")
        gamedata.save_regions(d, regions)
        print(f"ノード名: {len(regions)} 件(取得元: {src})")
    except Exception as e:  # noqa: BLE001
        print(f"  ノード名を取得できませんでした: {e}  ※前回取得分があればそれを使います(無ければ内部名で表示)")

    if not logos.find_logos_dir(d):  # 初回(ロゴ素材が未取得)のときだけ取得する
        logos.fetch_logos(d)

