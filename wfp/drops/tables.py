"""ドロップ表(ミッション)とミッション以外の入手先を表に展開する"""
from __future__ import annotations

import re
import time
from typing import NamedTuple

from wfp.core.common import to_float
from wfp.core.i18n import ja_text, name_txt, txt
from wfp.core.const import (BOUNTY_JA, CLAN_LABS, NODE_MODES, OTHER_SOURCES, RELIC_STATES, RESURGENCE_RELIC_MARK,
                            RESURGENCE_STORE_PREFIX, VAULT_SKIP_ERAS, WFCD_EXTRA)
from wfp.core.names import item_key


class DropRow(NamedTuple):
    """ドロップ表(ミッション)の1行。項目は名前で読む(row.item・row.chance。番号で読まない)"""
    planet: str   # 惑星(英名)
    node: str     # ノード
    mode: str     # ミッションの種類(node_mode で付け替えたあと)
    event: bool   # イベントのノードか
    rot: str      # ローテーション(無ければ "-")
    item: str     # 項目の英名(数量つきのことがある)
    chance: float  # 確率(%)
    rarity: str   # レア度(無ければ空)


class SourceRow(NamedTuple):
    """ミッション以外の入手先の1行。項目は名前で読む。place・detail はテキスト指定のことがある"""
    cat: str      # 入手先の種類(SOURCE_CATS のキー: enemy / bounty / relic / clan など)
    place: object  # 入手先(敵の名前・バウンティ・レリックなど)
    detail: object  # 詳細(ドロップの種類・ステージ・クエスト名など)
    rot: str      # ローテーション(無ければ "-")
    item: str     # 項目の英名
    chance: float | None  # 確率(%)。確率の無い入手先(クラン研究など)は None
    rarity: str   # レア度(無ければ空)
    relic: str = ""  # レリックの行だけ: レリックの英名(例: "Lith A1 Relic")。Vault 入りの判定(Vault)に使う


class Drops:
    """missionRewards.json を DropRow の一覧(rows)に展開する。node_order はノードの並び、by_node はノードごとの行"""

    def __init__(self, raw: dict):
        self.rows: list[DropRow] = []
        self.node_order = []
        self.by_node: dict[tuple[str, str], list[DropRow]] = {}
        for planet, nodes in raw["missionRewards"].items():
            for node, v in nodes.items():
                self.node_order.append((planet, node))
                rewards = v["rewards"]
                groups = rewards.items() if isinstance(rewards, dict) else [("-", rewards)]
                node_rows = self.by_node.setdefault((planet, node), [])
                for rot, lst in groups:
                    for e in lst:
                        node_rows.append(DropRow(planet, node, node_mode(planet, node, v["gameMode"]), bool(v.get("isEvent")),
                                                 rot, e["itemName"], float(e["chance"]), e.get("rarity", "")))
                self.rows.extend(node_rows)
        self.item_names = sorted({row.item for row in self.rows})
        self.planets = list(dict.fromkeys(p for p, _ in self.node_order))

    def node_rows(self, planet: str, node: str) -> list[DropRow]:
        """1ノードの行(無ければ空)。全部の行をなめずに引く"""
        return self.by_node.get((planet, node), [])


def node_mode(planet: str, node: str, mode: str) -> str:
    """ノードのミッションの種類。NODE_MODES にあるノード(例: ルアの結合耐久)は付け替える。ノード名の後ろの「 (Extra)」などは外して照合"""
    base = re.sub(r"\s*\([^)]*\)$", "", node or "")
    hit = NODE_MODES.get((planet, base))
    return hit[1] if hit and hit[0] == mode else mode


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

    rows は SourceRow の一覧(種類・入手先・詳細・ローテーション・英名・確率%・レア度)。入手先・詳細はテキスト指定(wfp/core/i18n.py の txt)
    確率は「その敵を1体倒す / その報酬を1回引く」ときにその項目が出る割合にそろえる。
    clan / other(同梱の data/parts/clan.json / other.json の中身)を渡すと、クラン研究・Simaris 交換などの行も足す(確率は None)。
    part_owner は extras(設計図ではない作成素材)の {名前(小文字): 本体の英名}。パーツ検索のカテゴリー分けに使う
    relic_items はレリックから出る項目のキー(item_key。数量違い・大文字小文字をそろえる)。パーツ検索の「Prime を除外する」に使う
    enemies は敵の名前(入手先の種類が enemy の行の入手先。英名のみ。和名の出どころが無いため)。敵から探すの候補に使う
    """

    def __init__(self, files: dict[str, dict], clan: object = None, other: object = None):
        self.part_owner: dict[str, str] = {}
        self.files: set[str] = set(files)  # 読めた WFCD のファイル(WFCD_EXTRA の名前)。Vault がそろっているかを見る
        # 並びは検索結果の並びに出るので変えない(敵 → バウンティ → レリック → ソーティー → 特殊ミッション・キー → 同梱)
        rows = (_enemy_rows(files) + _bounty_rows(files) + _relic_rows(files) + _sortie_rows(files) + _special_rows(files)
                + clan_rows(clan, self.part_owner) + other_rows(other, self.part_owner))
        self.rows: list[SourceRow] = [row for row in rows if row.item]
        self.item_names = sorted({row.item for row in self.rows})
        self.relic_items = {item_key(row.item) for row in self.rows if row.cat == "relic"}
        self.enemies = sorted({row.place for row in self.rows if row.cat == "enemy" and row.place})  # 敵から探すの候補(WFCD の英名そのまま)


def _wfcd_list(files: dict[str, dict], name: str) -> list:
    """WFCD のファイル <name>.json の中身の一覧(中身は {name: [...]} の形。無い・形が違えば空)"""
    return (files.get(name) or {}).get(name) or []


def _enemy_rows(files: dict[str, dict]) -> list[SourceRow]:
    """敵の行(素材・シジル・その他・MOD・設計図・アイテム)。確率は1体あたり(落とす確率 × その中で選ばれる確率)"""
    rows: list[SourceRow] = []
    for name, label in (("resourceByAvatar", txt("src.enemy.resource")), ("sigilByAvatar", txt("src.enemy.sigil")),
                        ("additionalItemByAvatar", txt("src.enemy.other"))):
        for e in _wfcd_list(files, name):
            for it in e.get("items", []):
                rows.append(SourceRow("enemy", e.get("source", ""), label, "-", it.get("item", ""), to_float(it.get("chance")), it.get("rarity", "")))
    for e in _wfcd_list(files, "enemyModTables"):
        drop = to_float(e.get("enemyModDropChance") or e.get("ememyModDropChance"))
        for it in e.get("mods", []):
            rows.append(SourceRow("enemy", e.get("enemyName", ""), txt("src.enemy.mod", p=f"{drop:g}"), "-", it.get("modName", ""),
                                  drop * to_float(it.get("chance")) / 100, it.get("rarity", "")))
    for b in _wfcd_list(files, "blueprintLocations"):
        for e in b.get("enemies", []):
            drop = to_float(e.get("enemyBlueprintDropChance"))
            rows.append(SourceRow("enemy", e.get("enemyName", ""), txt("src.enemy.bp", p=f"{drop:g}"), "-",
                                  b.get("blueprintName") or b.get("itemName", ""), drop * to_float(e.get("chance")) / 100, e.get("rarity", "")))
    for e in _wfcd_list(files, "miscItems"):
        drop = to_float(e.get("enemyItemDropChance"))
        for it in e.get("items", []):
            rows.append(SourceRow("enemy", e.get("enemyName", ""), txt("src.enemy.item", p=f"{drop:g}"), "-", it.get("itemName", ""),
                                  drop * to_float(it.get("chance")) / 100, it.get("rarity", "")))
    return rows


def _bounty_rows(files: dict[str, dict]) -> list[SourceRow]:
    """バウンティの行(組織ごと。ローテーション A/B/C × ステージ)"""
    rows: list[SourceRow] = []
    for name in BOUNTY_JA:
        for e in _wfcd_list(files, name):
            label = _bounty_label(name, e.get("bountyLevel", ""))
            rewards = e.get("rewards") or {}
            for rot, lst in (rewards.items() if isinstance(rewards, dict) else [("-", rewards)]):
                for it in lst or []:
                    rows.append(SourceRow("bounty", label, stage_txt(it.get("stage", "")), rot, it.get("itemName", ""),
                                          to_float(it.get("chance")), it.get("rarity", "")))
    return rows


def _relic_rows(files: dict[str, dict]) -> list[SourceRow]:
    """レリックの行(精錬の段階 RELIC_STATES のものだけ)"""
    rows: list[SourceRow] = []
    for r in _wfcd_list(files, "relics"):
        if r.get("state") not in RELIC_STATES:
            continue
        label = txt("src.relic", era=name_txt("relic.era.", r.get("tier") or ""), name=r.get("relicName") or "")
        relic = f"{r.get('tier') or ''} {r.get('relicName') or ''} Relic"
        for it in r.get("rewards", []):
            rows.append(SourceRow("relic", label, name_txt("relic.state.", r["state"]), "-", it.get("itemName", ""),
                                  to_float(it.get("chance")), it.get("rarity", ""), relic))
    return rows


class Resurgence:
    """Prime Resurgence(Varzia)の期間と、その期間にアヤで交換できるレリック(英名。例: "Lith S17 Relic")。

    作るのは resurgence_from(World State から取り出した在庫と item_paths.json から)。期間の内かは active で見る
    """

    def __init__(self, relics=(), activation: float | None = None, expiry: float | None = None):
        self.names: list[str] = sorted(set(relics))
        self.keys: frozenset[str] = frozenset(item_key(r) for r in self.names)
        self.activation, self.expiry = activation, expiry

    def active(self, now: float) -> bool:
        """now(UNIX 時刻)が期間の内で、交換できるレリックがあるか"""
        started = self.activation is None or self.activation <= now
        return bool(self.keys) and self.expiry is not None and started and now < self.expiry


def resurgence_from(snap: dict | None, paths: dict) -> Resurgence:
    """World State の取り出し結果(fetch/worldstate の extract_resurgence)の在庫から、レリックだけを英名にして Resurgence にする。

    paths は item_paths.json(内部パス -> 英名)。在庫のパスは /StoreItems の付いた形なので、Export の形に読み替えて引く。
    名前の引けないもの(item_paths.json が古い・無い)は飛ばす。snap が無ければ空(期間の外と同じ)
    """
    if not isinstance(snap, dict):
        return Resurgence()
    relics = [name for path in snap.get("items") or [] if isinstance(path, str) and RESURGENCE_RELIC_MARK in path
              if (name := paths.get(_export_path(path)))]
    return Resurgence(relics, to_float(snap.get("activation")), to_float(snap.get("expiry")))


def _export_path(path: str) -> str:
    """在庫の内部パス(/Lotus/StoreItems/…)を Export の内部パス(/Lotus/…)にする。違う形ならそのまま"""
    store, export = RESURGENCE_STORE_PREFIX
    return export + path[len(store):] if path.startswith(store) else path


class Vault:
    """Vault 入り(いまは出ない)レリックと、それでしか手に入らない項目(入手不可の Prime パーツなど)。

    WFCD の relics.json には Vault 入りを含む全レリックの中身が載るが、レリック自体の入手先(ミッション・敵・バウンティなど)には
    いま出るレリックだけが載る。そこで、どの入手先にも項目として出てこないレリックを Vault 入りとみなす。
    relics は Vault 入りのレリックの item_key、items は入手先がレリックだけで、そのレリックが全部 Vault 入りの項目の item_key。
    ミッションはイベントのノードも数える(ドロップ表には開催中のイベントしか載らないため)。
    ready は判定できたか。ミッションのドロップ表と WFCD の全ファイル(WFCD_EXTRA)がそろっていないと、いま出るレリックを
    見落として Vault 入りに見えるので、そのときは何も判定しない(relics・items は空、ready は False)。
    resurgence を渡すと、期間の内(now。省略時はいま)なら Prime Resurgence で交換できるレリックを Vault 入りから外す
    (offered に入る。そのレリックでしか出ない項目も入手不可にしない)。期間の外なら渡さないのと同じ
    """

    def __init__(self, drops: Drops | None, sources: Sources | None, resurgence: Resurgence | None = None,
                 now: float | None = None):
        now = time.time() if now is None else now
        self.resurgence: Resurgence | None = resurgence if resurgence and resurgence.active(now) else None
        offered = self.resurgence.keys if self.resurgence else frozenset()
        self.ready: bool = drops is not None and sources is not None and set(WFCD_EXTRA) <= sources.files
        srows = sources.rows if self.ready else []
        # レリック以外の入手先に出る項目(レリック自体もここに出る)
        other = {item_key(r.item) for r in (drops.rows if self.ready else [])} | {item_key(r.item) for r in srows if r.cat != "relic"}
        relic_of: dict[str, set[str]] = {}
        for r in srows:
            # Vault に入らない時代(VAULT_SKIP_ERAS。Requiem)のレリックは見ない(入手先が表に載らないことがあるため)
            if r.cat == "relic" and r.relic and r.relic.split(" ", 1)[0] not in VAULT_SKIP_ERAS:
                relic_of.setdefault(item_key(r.item), set()).add(item_key(r.relic))
        all_relics = set().union(*relic_of.values()) if relic_of else set()
        self.relics: set[str] = {k for k in all_relics if k not in other and k not in offered}
        self.items: set[str] = {k for k, rel in relic_of.items() if k not in other and rel <= self.relics}

    def relic_vaulted(self, relic: str) -> bool:
        """レリック(英名。数量つき可)が Vault 入りか"""
        return item_key(relic) in self.relics

    def relic_offered(self, relic: str) -> bool:
        """レリック(英名。数量つき可)をいま Prime Resurgence で交換できるか"""
        return self.resurgence is not None and item_key(relic) in self.resurgence.keys

    @property
    def offered_names(self) -> list[str]:
        """いま Prime Resurgence で交換できるレリックの英名(期間の外なら空)"""
        return self.resurgence.names if self.resurgence else []

    @property
    def until(self) -> float | None:
        """Prime Resurgence の期限(UNIX 時刻。期間の外なら None)"""
        return self.resurgence.expiry if self.resurgence else None

    def unavailable(self, item: str) -> bool:
        """項目(英名。数量つき可)がいま入手できないか(入手先が Vault 入りのレリックだけ)"""
        return item_key(item) in self.items


def _sortie_rows(files: dict[str, dict]) -> list[SourceRow]:
    """ソーティーの行(最後のミッションの報酬)"""
    return [SourceRow("sortie", txt("src.sortie"), txt("src.sortie.final"), "-", it.get("itemName", ""), to_float(it.get("chance")), it.get("rarity", ""))
            for it in _wfcd_list(files, "sortieRewards")]


def _special_rows(files: dict[str, dict]) -> list[SourceRow]:
    """特殊ミッション(仲裁・遺棄船・ナイトメア等)とキー・ボスの行"""
    rows: list[SourceRow] = []
    for name, cat, field in (("transientRewards", "special", "objectiveName"), ("keyRewards", "key", "keyName")):
        for e in _wfcd_list(files, name):
            rewards = e.get("rewards") or []
            groups = rewards.items() if isinstance(rewards, dict) else [(None, rewards)]
            for rot, lst in groups:
                for it in lst or []:
                    rows.append(SourceRow(cat, e.get(field, ""), stage_txt(it.get("stage", "")), rot or it.get("rotation") or "-",
                                          it.get("itemName", ""), to_float(it.get("chance")), it.get("rarity", "")))
    return rows


def _manual_rows(raw: object, field: str, labels: dict, cat: str | None, prefix: str,
                 owners: dict[str, str] | None) -> list[SourceRow]:
    """手で書いた入手先の一覧(data/parts/ の clan.json / other.json)を入手先の行にする。確率は無いので None。

    field は入手先のキーの項目名(クラン研究は "lab"、その他は "source")、labels はキー -> (英語名, 日本語名)(キーの検査に使う)。
    種類(行の先頭)は cat、None ならキーそのもの(SOURCE_CATS にあるキー)。入手先は名前のテキスト指定(prefix + キー)、詳細は note。
    note は文字列か {言語: 文}(言語ごとに書いた文)。
    本体は "<英名> Blueprint"(body が false なら無し)、部品は "<英名> <部品名> Blueprint"、
    extras(設計図ではない作成素材)は item の名前そのまま。owners を渡すと {extras の名前(小文字): 本体の英名} を書き足す。
    部品・extras のキーを省略すると本体と同じ。部品・extras の詳細は自分の note、無ければ本体と同じ入手先のときだけ本体の note。形が違う行・知らないキーの行は黙って飛ばす(ツールを止めない。同梱データの検査はテストで行う)
    quest({"en", "ja"})はクエスト名。詳細には web/i18n の src.quest.<入手先> の形で出し(例: Simaris 交換は「〜完了後」)、note があれば「クエスト名 / note」。
    部品・extras の quest も note と同じく、自分の quest、無ければ本体と同じ入手先のときだけ本体の quest。形が違う quest は無いものとして扱う
    """
    items = raw.get("items") if isinstance(raw, dict) else None
    out: list[SourceRow] = []

    def add(key: object, note, item: str) -> bool:
        ok = isinstance(key, str) and key in labels
        if ok:
            out.append(SourceRow(cat or key, name_txt(prefix, key), note, "-", item, None, ""))
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
        if quest and isinstance(src, str) and ja_text(f"src.quest.{src}") is not None:
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


def clan_rows(raw: object, owners: dict[str, str] | None = None) -> list[SourceRow]:
    """クラン研究の一覧(data/parts/clan.json)を入手先「クラン研究」の行にする(入手先は研究所。CLAN_LABS)"""
    return _manual_rows(raw, "lab", CLAN_LABS, "clan", "clan.lab.", owners)


def other_rows(raw: object, owners: dict[str, str] | None = None) -> list[SourceRow]:
    """ドロップしない入手先の一覧(data/parts/other.json)を行にする。種類は入手先のキー(simaris / quest。OTHER_SOURCES)"""
    return _manual_rows(raw, "source", OTHER_SOURCES, None, "src.cat.", owners)


def stage_label(rot: str):
    """ローテーションのテキスト指定(無ければ「—」)"""
    return "—" if rot in ("-", "", None) else txt("src.rot", r=rot)
