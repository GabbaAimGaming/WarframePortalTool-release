"""ドロップ表(ミッション)とミッション以外の入手先を表に展開する"""
from __future__ import annotations

import re

from wfp.core.common import BOUNTY_JA, CLAN_LABS, ERA_JA, OTHER_SOURCES, QUEST_NOTE, RELIC_STATES, RELIC_STATE_JA, to_float


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
    clan / other(同梱の data/parts/clan.json / other.json の中身)を渡すと、クラン研究・Simaris 交換などの行も足す(確率は None)。
    part_owner は extras(設計図ではない作成素材)の {名前(小文字): 本体の英名}。パーツ検索のカテゴリー分けに使う
    """

    def __init__(self, files: dict[str, dict], clan: object = None, other: object = None):
        self.rows: list[tuple] = []
        self.part_owner: dict[str, str] = {}
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
        self.rows.extend(clan_rows(clan, self.part_owner))
        self.rows.extend(other_rows(other, self.part_owner))
        self.rows = [r for r in self.rows if r[4]]
        self.item_names = sorted({r[4] for r in self.rows})


def _manual_rows(raw: object, field: str, labels: dict, cat: str | None,
                 owners: dict[str, str] | None) -> list[tuple]:
    """手で書いた入手先の一覧(data/parts/ の clan.json / other.json)を入手先の行にする。確率は無いので None。

    field は入手先のキーの項目名(クラン研究は "lab"、その他は "source")、labels はキー -> (英語名, 日本語名)。
    種類(行の先頭)は cat、None ならキーそのもの(SOURCE_CATS にあるキー)。入手先は日本語名、詳細は note。
    本体は "<英名> Blueprint"(body が false なら無し)、部品は "<英名> <部品名> Blueprint"、
    extras(設計図ではない作成素材)は item の名前そのまま。owners を渡すと {extras の名前(小文字): 本体の英名} を書き足す。
    部品・extras のキーを省略すると本体と同じ。部品・extras の詳細は自分の note、無ければ本体と同じ入手先のときだけ本体の note。形が違う行・知らないキーの行は黙って飛ばす(ツールを止めない。同梱データの検査はテストで行う)
    quest({"en", "ja"})はクエスト名。詳細には ja だけを QUEST_NOTE の形で出し(例: Simaris 交換は「〜完了後」)、note があれば「クエスト名 / note」。
    部品・extras の quest も note と同じく、自分の quest、無ければ本体と同じ入手先のときだけ本体の quest。形が違う quest は無いものとして扱う
    """
    items = raw.get("items") if isinstance(raw, dict) else None
    out: list[tuple] = []

    def add(key: object, note: str, item: str) -> bool:
        label = labels.get(key) if isinstance(key, str) else None
        if label:
            out.append((cat or key, label[1], note, "-", item, None, ""))
        return bool(label)

    def quest_ja(q: object) -> str:
        """クエスト名(quest の ja)。形が違えば空"""
        return q["ja"].strip() if isinstance(q, dict) and isinstance(q.get("ja"), str) else ""

    def detail(src: object, quest: str, note: str) -> str:
        """詳細欄の文: クエスト名(入手先ごとの形)と note を「 / 」でつなぐ"""
        if quest:
            quest = QUEST_NOTE.get(src, "{}").format(quest) if isinstance(src, str) else quest
        return " / ".join(s for s in (quest, note) if s)

    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not isinstance(it.get("en"), str) or not it["en"].strip():
            continue
        en, key = it["en"].strip(), it.get(field)
        note = it.get("note") if isinstance(it.get("note"), str) else ""
        quest = quest_ja(it.get("quest"))
        if it.get("body", True) is not False:
            add(key, detail(key, quest, note), f"{en} Blueprint")
        def sub_note(sub: dict) -> str:
            """部品・extras の詳細: note・quest はそれぞれ自分のもの、無ければ本体と同じ入手先のときだけ本体のもの(例: クエスト名を Simaris 交換の部品に付けない)"""
            same = sub.get(field, key) == key
            n = sub["note"] if isinstance(sub.get("note"), str) else (note if same else "")
            q = quest_ja(sub["quest"]) if "quest" in sub else (quest if same else "")
            return detail(sub.get(field, key), q, n)

        for p in it.get("parts") if isinstance(it.get("parts"), list) else []:
            if isinstance(p, dict) and isinstance(p.get("part"), str) and p["part"].strip():
                add(p.get(field, key), sub_note(p), f"{en} {p['part'].strip()} Blueprint")
        for x in it.get("extras") if isinstance(it.get("extras"), list) else []:
            if isinstance(x, dict) and isinstance(x.get("item"), str) and x["item"].strip():
                if add(x.get(field, key), sub_note(x), x["item"].strip()) and owners is not None:
                    owners.setdefault(x["item"].strip().lower(), en)
    return out


def clan_rows(raw: object, owners: dict[str, str] | None = None) -> list[tuple]:
    """クラン研究の一覧(data/parts/clan.json)を入手先「クラン研究」の行にする(入手先は研究所。CLAN_LABS)"""
    return _manual_rows(raw, "lab", CLAN_LABS, "clan", owners)


def other_rows(raw: object, owners: dict[str, str] | None = None) -> list[tuple]:
    """ドロップしない入手先の一覧(data/parts/other.json)を行にする。種類は入手先のキー(simaris / quest。OTHER_SOURCES)"""
    return _manual_rows(raw, "source", OTHER_SOURCES, None, owners)


def stage_label(rot: str) -> str:
    return "—" if rot in ("-", "", None) else f"ローテ{rot}"
