"""ドロップ表(ミッション)とミッション以外の入手先を表に展開する"""
from __future__ import annotations

import re

from wfp.core.common import BOUNTY_JA, ERA_JA, RELIC_STATES, RELIC_STATE_JA, to_float


class Drops:
    """missionRewards.json を [(惑星, ノード, ミッション, イベント, ローテーション, 英名, 確率, レア度)] に展開"""

    def __init__(self, raw: dict):
        self.rows = []
        self.node_order = []
        for planet, nodes in raw["missionRewards"].items():
            for node, v in nodes.items():
                self.node_order.append((planet, node))
                rewards = v["rewards"]
                groups = rewards.items() if isinstance(rewards, dict) else [("-", rewards)]
                for rot, lst in groups:
                    for e in lst:
                        self.rows.append((planet, node, v["gameMode"], bool(v.get("isEvent")),
                                          rot, e["itemName"], float(e["chance"]), e.get("rarity", "")))
        self.item_names = sorted({r[5] for r in self.rows})
        self.planets = list(dict.fromkeys(p for p, _ in self.node_order))


def _stage_ja(s: str) -> str:
    """"Stage 2, Stage 3 of 4, and Stage 3 of 5" -> "ステージ2、ステージ3(全4)、ステージ3(全5)" """
    s = re.sub(r"final stage", "最終ステージ", s or "", flags=re.I)
    s = re.sub(r"Stage\s*(\d+)\s+of\s+(\d+)", r"ステージ\1(全\2)", s)
    s = re.sub(r"Stage\s*", "ステージ", s)
    return re.sub(r",?\s*and\s+|,\s*", "、", s)


def _bounty_label(group: str, level: str) -> str:
    m = re.search(r"Level\s+(\d+)\s*-\s*(\d+)", level or "")
    lv = f" Lv{m.group(1)}-{m.group(2)}" if m else f" {level}"
    return BOUNTY_JA.get(group, group) + lv + (" (鋼の道)" if "Steel" in (level or "") else "")


class Sources:
    """ミッション以外の入手先 (WFCD の各ファイル) を1つの表に展開する。

    rows = [(種類, 入手先, 詳細, ステージ, 英名, 確率%, レア度)]
    確率は「その敵を1体倒す / その報酬を1回引く」ときにその項目が出る割合にそろえる。
    """

    def __init__(self, files: dict[str, dict]):
        self.rows: list[tuple] = []
        add = self.rows.append
        get = lambda name: (files.get(name) or {}).get(name) or []

        # 敵: 素材・シジル等 (chance は1体あたりの確率)
        for name, label in (("resourceByAvatar", "素材"), ("sigilByAvatar", "シジル等"), ("additionalItemByAvatar", "その他")):
            for e in get(name):
                for it in e.get("items", []):
                    add(("enemy", e.get("source", ""), label, "-", it.get("item", ""), to_float(it.get("chance")), it.get("rarity", "")))
        # 敵: MOD (MODを落とす確率 × その中で選ばれる確率)
        for e in get("enemyModTables"):
            drop = to_float(e.get("enemyModDropChance") or e.get("ememyModDropChance"))
            for it in e.get("mods", []):
                add(("enemy", e.get("enemyName", ""), f"MODドロップ {drop:g}%", "-", it.get("modName", ""),
                     drop * to_float(it.get("chance")) / 100, it.get("rarity", "")))
        # 敵: 設計図・パーツ
        for b in get("blueprintLocations"):
            for e in b.get("enemies", []):
                drop = to_float(e.get("enemyBlueprintDropChance"))
                add(("enemy", e.get("enemyName", ""), f"設計図ドロップ {drop:g}%", "-",
                     b.get("blueprintName") or b.get("itemName", ""), drop * to_float(e.get("chance")) / 100, e.get("rarity", "")))
        # 敵: その他アイテム
        for e in get("miscItems"):
            drop = to_float(e.get("enemyItemDropChance"))
            for it in e.get("items", []):
                add(("enemy", e.get("enemyName", ""), f"アイテムドロップ {drop:g}%", "-", it.get("itemName", ""),
                     drop * to_float(it.get("chance")) / 100, it.get("rarity", "")))
        # バウンティ (ローテーション A/B/C × ステージ)
        for name in BOUNTY_JA:
            for e in get(name):
                label = _bounty_label(name, e.get("bountyLevel", ""))
                rewards = e.get("rewards") or {}
                for rot, lst in (rewards.items() if isinstance(rewards, dict) else [("-", rewards)]):
                    for it in lst or []:
                        add(("bounty", label, _stage_ja(it.get("stage", "")), rot, it.get("itemName", ""),
                             to_float(it.get("chance")), it.get("rarity", "")))
        # レリック
        for r in get("relics"):
            if r.get("state") not in RELIC_STATES:
                continue
            label = f"{ERA_JA.get(r.get('tier'), r.get('tier'))} {r.get('relicName')} レリック"
            for it in r.get("rewards", []):
                add(("relic", label, RELIC_STATE_JA.get(r["state"], r["state"]), "-", it.get("itemName", ""),
                     to_float(it.get("chance")), it.get("rarity", "")))
        # ソーティー
        for it in get("sortieRewards"):
            add(("sortie", "ソーティー", "最終報酬", "-", it.get("itemName", ""), to_float(it.get("chance")), it.get("rarity", "")))
        # 特殊ミッション (仲裁・遺棄船・ナイトメア等) とキー・ボス
        for name, cat, field in (("transientRewards", "special", "objectiveName"), ("keyRewards", "key", "keyName")):
            for e in get(name):
                rewards = e.get("rewards") or []
                groups = rewards.items() if isinstance(rewards, dict) else [(None, rewards)]
                for rot, lst in groups:
                    for it in lst or []:
                        add((cat, e.get(field, ""), _stage_ja(it.get("stage", "")), rot or it.get("rotation") or "-",
                             it.get("itemName", ""), to_float(it.get("chance")), it.get("rarity", "")))
        self.rows = [r for r in self.rows if r[4]]
        self.item_names = sorted({r[4] for r in self.rows})


def stage_label(rot: str) -> str:
    return "—" if rot in ("-", "", None) else f"ローテ{rot}"
