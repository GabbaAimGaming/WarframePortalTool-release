"""ドロップ表(ミッション)とミッション以外の入手先を表に展開する"""
from __future__ import annotations

import re

from wfp.core.common import BOUNTY_JA, CLAN_LABS, OTHER_SOURCES, RELIC_STATES, TEXT_JA, name_txt, to_float, txt
from wfp.core.names import item_key


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


def stage_txt(s: str):
    """WFCD のステージの書き方をテキスト指定にする。
    "Stage 2, Stage 3 of 4, and Stage 3 of 5" -> [ステージ2, ステージ3(全4), ステージ3(全5)](日本語の画面では「、」でつなぐ)。
    読めない部分は英語のまま残す"""
    out = []
    for piece in re.split(r",?\s*\band\s+|,\s*", (s or "").strip()):
        if not piece:
            continue
        if re.fullmatch(r"final\s+stage", piece, re.I):
            out.append(txt("src.stage.final"))
        elif m := re.fullmatch(r"Stage\s*(\d+)\s+of\s+(\d+)", piece, re.I):
            out.append(txt("src.stage.of", n=m.group(1), of=m.group(2)))
        elif m := re.fullmatch(r"Stage\s*(\d+)", piece, re.I):
            out.append(txt("src.stage", n=m.group(1)))
        else:
            out.append(piece)
    return out[0] if len(out) == 1 else out


def _bounty_label(group: str, level: str) -> dict:
    name = name_txt("bounty.", group)
    m = re.search(r"Level\s+(\d+)\s*-\s*(\d+)", level or "")
    place = txt("src.bounty.lv", name=name, a=m.group(1), b=m.group(2)) if m else txt("src.bounty.level", name=name, level=level or "")
    return txt("src.bounty.steel", place=place) if "Steel" in (level or "") else place


def mission_place(planet: str, node: str) -> dict:
    """ミッションの入手先「惑星 / ノード」のテキスト指定"""
    return txt("src.mission", planet=name_txt("planet.", planet), node=node)


class Sources:
    """ミッション以外の入手先 (WFCD の各ファイル) を1つの表に展開する。

    rows = [(種類, 入手先, 詳細, ローテーション, 英名, 確率%, レア度)]。入手先・詳細はテキスト指定(wfp/core/common.py の txt)
    確率は「その敵を1体倒す / その報酬を1回引く」ときにその項目が出る割合にそろえる。
    clan / other(同梱の data/parts/clan.json / other.json の中身)を渡すと、クラン研究・Simaris 交換などの行も足す(確率は None)。
    part_owner は extras(設計図ではない作成素材)の {名前(小文字): 本体の英名}。パーツ検索のカテゴリー分けに使う
    relic_items はレリックから出る項目のキー(item_key。数量違い・大文字小文字をそろえる)。パーツ検索の「Prime を除外する」に使う
    """

    def __init__(self, files: dict[str, dict], clan: object = None, other: object = None):
        self.rows: list[tuple] = []
        self.part_owner: dict[str, str] = {}
        add = self.rows.append
        get = lambda name: (files.get(name) or {}).get(name) or []

        # 敵: 素材・シジル等 (chance は1体あたりの確率)
        for name, label in (("resourceByAvatar", txt("src.enemy.resource")), ("sigilByAvatar", txt("src.enemy.sigil")),
                            ("additionalItemByAvatar", txt("src.enemy.other"))):
            for e in get(name):
                for it in e.get("items", []):
                    add(("enemy", e.get("source", ""), label, "-", it.get("item", ""), to_float(it.get("chance")), it.get("rarity", "")))
        # 敵: MOD (MODを落とす確率 × その中で選ばれる確率)
        for e in get("enemyModTables"):
            drop = to_float(e.get("enemyModDropChance") or e.get("ememyModDropChance"))
            for it in e.get("mods", []):
                add(("enemy", e.get("enemyName", ""), txt("src.enemy.mod", p=f"{drop:g}"), "-", it.get("modName", ""),
                     drop * to_float(it.get("chance")) / 100, it.get("rarity", "")))
        # 敵: 設計図・パーツ
        for b in get("blueprintLocations"):
            for e in b.get("enemies", []):
                drop = to_float(e.get("enemyBlueprintDropChance"))
                add(("enemy", e.get("enemyName", ""), txt("src.enemy.bp", p=f"{drop:g}"), "-",
                     b.get("blueprintName") or b.get("itemName", ""), drop * to_float(e.get("chance")) / 100, e.get("rarity", "")))
        # 敵: その他アイテム
        for e in get("miscItems"):
            drop = to_float(e.get("enemyItemDropChance"))
            for it in e.get("items", []):
                add(("enemy", e.get("enemyName", ""), txt("src.enemy.item", p=f"{drop:g}"), "-", it.get("itemName", ""),
                     drop * to_float(it.get("chance")) / 100, it.get("rarity", "")))
        # バウンティ (ローテーション A/B/C × ステージ)
        for name in BOUNTY_JA:
            for e in get(name):
                label = _bounty_label(name, e.get("bountyLevel", ""))
                rewards = e.get("rewards") or {}
                for rot, lst in (rewards.items() if isinstance(rewards, dict) else [("-", rewards)]):
                    for it in lst or []:
                        add(("bounty", label, stage_txt(it.get("stage", "")), rot, it.get("itemName", ""),
                             to_float(it.get("chance")), it.get("rarity", "")))
        # レリック
        for r in get("relics"):
            if r.get("state") not in RELIC_STATES:
                continue
            label = txt("src.relic", era=name_txt("relic.era.", r.get("tier") or ""), name=r.get("relicName") or "")
            for it in r.get("rewards", []):
                add(("relic", label, name_txt("relic.state.", r["state"]), "-", it.get("itemName", ""),
                     to_float(it.get("chance")), it.get("rarity", "")))
        # ソーティー
        for it in get("sortieRewards"):
            add(("sortie", txt("src.sortie"), txt("src.sortie.final"), "-", it.get("itemName", ""), to_float(it.get("chance")), it.get("rarity", "")))
        # 特殊ミッション (仲裁・遺棄船・ナイトメア等) とキー・ボス
        for name, cat, field in (("transientRewards", "special", "objectiveName"), ("keyRewards", "key", "keyName")):
            for e in get(name):
                rewards = e.get("rewards") or []
                groups = rewards.items() if isinstance(rewards, dict) else [(None, rewards)]
                for rot, lst in groups:
                    for it in lst or []:
                        add((cat, e.get(field, ""), stage_txt(it.get("stage", "")), rot or it.get("rotation") or "-",
                             it.get("itemName", ""), to_float(it.get("chance")), it.get("rarity", "")))
        self.rows.extend(clan_rows(clan, self.part_owner))
        self.rows.extend(other_rows(other, self.part_owner))
        self.rows = [r for r in self.rows if r[4]]
        self.item_names = sorted({r[4] for r in self.rows})
        self.relic_items = {item_key(r[4]) for r in self.rows if r[0] == "relic"}


def _manual_rows(raw: object, field: str, labels: dict, cat: str | None, prefix: str,
                 owners: dict[str, str] | None) -> list[tuple]:
    """手で書いた入手先の一覧(data/parts/ の clan.json / other.json)を入手先の行にする。確率は無いので None。

    field は入手先のキーの項目名(クラン研究は "lab"、その他は "source")、labels はキー -> (英語名, 日本語名)(キーの検査に使う)。
    種類(行の先頭)は cat、None ならキーそのもの(SOURCE_CATS にあるキー)。入手先は名前のテキスト指定(prefix + キー)、詳細は note。
    note は文字列か {言語: 文}(言語ごとに書いた文)。
    本体は "<英名> Blueprint"(body が false なら無し)、部品は "<英名> <部品名> Blueprint"、
    extras(設計図ではない作成素材)は item の名前そのまま。owners を渡すと {extras の名前(小文字): 本体の英名} を書き足す。
    部品・extras のキーを省略すると本体と同じ。部品・extras の詳細は自分の note、無ければ本体と同じ入手先のときだけ本体の note。形が違う行・知らないキーの行は黙って飛ばす(ツールを止めない。同梱データの検査はテストで行う)
    quest({"en", "ja"})はクエスト名。詳細には TEXT_JA の src.quest.<入手先> の形で出し(例: Simaris 交換は「〜完了後」)、note があれば「クエスト名 / note」。
    部品・extras の quest も note と同じく、自分の quest、無ければ本体と同じ入手先のときだけ本体の quest。形が違う quest は無いものとして扱う
    """
    items = raw.get("items") if isinstance(raw, dict) else None
    out: list[tuple] = []

    def add(key: object, note, item: str) -> bool:
        ok = isinstance(key, str) and key in labels
        if ok:
            out.append((cat or key, name_txt(prefix, key), note, "-", item, None, ""))
        return ok

    def by_lang(v: object):
        """言語ごとに書いた文 {"en", "ja", ...} をテキスト指定 {"l": ...} に。文字列はそのまま。形が違えば空"""
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, dict):
            d = {k: x.strip() for k, x in v.items() if isinstance(k, str) and isinstance(x, str) and x.strip()}
            return {"l": d} if d else ""
        return ""

    def quest_of(q: object):
        """クエスト名のテキスト指定。{"en", "ja"} の形でなければ空"""
        return by_lang(q) if isinstance(q, dict) else ""

    def detail(src: object, quest, note):
        """詳細欄: クエスト名(入手先ごとの形)と note を「 / 」でつなぐ"""
        if quest and isinstance(src, str) and f"src.quest.{src}" in TEXT_JA:
            quest = txt(f"src.quest.{src}", q=quest)
        if quest and note:
            return txt("src.note", a=quest, b=note)
        return quest or note

    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not isinstance(it.get("en"), str) or not it["en"].strip():
            continue
        en, key = it["en"].strip(), it.get(field)
        note = by_lang(it.get("note"))
        quest = quest_of(it.get("quest"))
        if it.get("body", True) is not False:
            add(key, detail(key, quest, note), f"{en} Blueprint")
        def sub_note(sub: dict) -> str:
            """部品・extras の詳細: note・quest はそれぞれ自分のもの、無ければ本体と同じ入手先のときだけ本体のもの(例: クエスト名を Simaris 交換の部品に付けない)"""
            same = sub.get(field, key) == key
            n = by_lang(sub["note"]) if isinstance(sub.get("note"), (str, dict)) else (note if same else "")
            q = quest_of(sub["quest"]) if "quest" in sub else (quest if same else "")
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
    return _manual_rows(raw, "lab", CLAN_LABS, "clan", "clan.lab.", owners)


def other_rows(raw: object, owners: dict[str, str] | None = None) -> list[tuple]:
    """ドロップしない入手先の一覧(data/parts/other.json)を行にする。種類は入手先のキー(simaris / quest。OTHER_SOURCES)"""
    return _manual_rows(raw, "source", OTHER_SOURCES, None, "src.cat.", owners)


def stage_label(rot: str):
    """ローテーションのテキスト指定(無ければ「—」)"""
    return "—" if rot in ("-", "", None) else txt("src.rot", r=rot)
