"""名前辞書: 公式 Public Export から名前・MOD・マスター・アルケイン・Riven 性質の一覧を作る(純粋な処理)"""
from __future__ import annotations

import re

from wfp.core.common import (
    ARCANE_CATS,
    ARCANE_PREFIX_CAT,
    ARCANE_UNRELEASED,
    DISPO_CATS,
    ERA_JA,
    ITEM_TYPES,
    MASTERY_CATS,
    MASTERY_FOUNDER,
    MASTERY_MAX_RANK,
    MOD_TYPES,
    PART_JA,
    PART_QUALIFIERS,
    PART_SKIP_CATS,
    PART_WORDS,
    rank,
)


_MASTERY_WEAPON = {"LongGuns": "primary", "Pistols": "secondary", "Melee": "melee", "SpaceGuns": "archgun",
                   "SpaceMelee": "archmelee", "SentinelWeapons": "robotic", "OperatorAmps": "amp"}
# ExportWarframes の productCategory -> マスター一覧のカテゴリー
_MASTERY_SUIT = {"Suits": "warframe", "SpaceSuits": "archwing", "MechSuits": "necramech"}
# 200/ランクのカテゴリー(robotic はセンチネル本体だけなので mastery_xp で別に判定)
_MASTERY_XP_200 = ("warframe", "companion", "archwing", "necramech", "kdrive")


# パーツ検索の部品名・区分(Names.part_of は小文字で比べる)
_PART_WORDS = frozenset(w.lower() for w in PART_WORDS)
_PART_QUALIFIERS = frozenset(w.lower() for w in PART_QUALIFIERS)


# 組み立て式の部品。マスタリー経験値が入る部品(下の mastery_slots)以外は一覧に載せない
_MODULAR_PARTS = re.compile(r"/(OperatorAmplifiers|ModularMelee[^/]*|SUModular[^/]*|InfKitGun|Hoverboard|ZanukaPetParts|MoaPetParts)/")
# MOA・ハウンドの頭(Model)。マスタリー経験値が入る部品なので、組み立て部品の除外より前にロボティックとして拾う
# (Core・Bracket・Gyro・Stabilizer は入れない)。Nychus は内部名が MoaPetHeadMelee、ハウンドは HeadA〜C
_COMPANION_HEAD = re.compile(r"/(MoaPets/MoaPetParts/MoaPetHead[^/]+|ZanukaPets/ZanukaPetParts/ZanukaPetPartHead[A-Z])$")
# 図鑑に載らない印(excludeFromCodex)が付いているが、マスタリー経験値が入るもの。
# ハウンドの武器 Akaten / Batoten / Lacerten(SentinelWeapons。内部名は ZanukaPetMeleeWeapon PS / IP / IS)
_MASTERY_CODEX_EXEMPT = re.compile(r"/ZanukaPets/ZanukaPetMeleeWeapon[^/]+$")


def mastery_slots(export: str, it: dict) -> list[tuple[str, str]]:
    """Public Export の1項目が、マスター一覧のどのカテゴリーに入るか -> [(カテゴリー, 区分)]

    - 組み立て式は、マスタリー経験値が入る部品だけ: Kitgun はチェンバー(プライマリ版とセカンダリ版を別に数える)、
      Zaw はストライク、アンプはプリズム(と Sirocco)、Kドライブはボード(Deck)
    - アビリティ専用武器やコンクラーヴ用など、図鑑に載らないもの(excludeFromCodex)は除く。
      ただしハウンドの武器(_MASTERY_CODEX_EXEMPT)は印が付いていても載せる
    """
    uid, pc = it.get("uniqueName", ""), it.get("productCategory")
    if not it.get("name") or (it.get("excludeFromCodex") and not _MASTERY_CODEX_EXEMPT.search(uid)):
        return []
    if export == "ExportWarframes":
        return [(_MASTERY_SUIT[pc], "")] if pc in _MASTERY_SUIT else []
    if export == "ExportSentinels":
        return [("robotic", "")] if pc == "Sentinels" else [("companion", "")] if pc == "KubrowPets" else []
    if export != "ExportWeapons":
        return []
    if re.search(r"/OperatorAmplifiers/.*Barrel", uid):
        return [("amp", "")]
    if re.search(r"/ModularMelee[^/]*/Tips?/", uid):
        return [("zaw", "")]
    if re.search(r"/(SUModularSecondary[^/]*/Barrel|InfKitGun/Barrels)/", uid):
        return [("kitgun", "primary"), ("kitgun", "secondary")]
    # Kドライブ: ExportWeapons に productCategory "Pistols" で入っている。ボード以外(ノーズ・リアクター・ジェット)は対象外
    if re.search(r"/Hoverboard/.*Deck$", uid):
        return [("kdrive", "")]
    if _COMPANION_HEAD.search(uid):
        return [("robotic", "")]
    if _MODULAR_PARTS.search(uid):
        return []
    return [(_MASTERY_WEAPON[pc], "")] if pc in _MASTERY_WEAPON else []


def mastery_xp(cat: str, export: str, rank: int, uid: str = "") -> int:
    """ランク最大までのマスタリー経験値: フレーム・コンパニオン・センチネル本体・MOA/ハウンド(頭)・アークウイング・
    ネクロメカ・Kドライブは 200/ランク、武器は 100/ランク"""
    per = 200 if (cat in _MASTERY_XP_200 or (cat == "robotic" and export == "ExportSentinels")
                  or _COMPANION_HEAD.search(uid)) else 100
    return per * rank


_DISPO_TYPE = {"secondary": "Pistol Riven Mod", "melee": "Melee Riven Mod", "kitgun": "Kitgun Riven Mod",
               "zaw": "Zaw Riven Mod", "archgun": "Archgun Riven Mod", "robotic": "Companion Weapon Riven Mod"}


def arcane_cat(name: str) -> str:
    """アルケインの装備先カテゴリー (ARCANE_CATS のキー)"""
    first = name.strip().split(" ", 1)[0].lower()
    return ARCANE_PREFIX_CAT.get(first, "other")


# プライマリのうちショットガン用 Riven を使う武器。公式データに武器の種類が無いため、内部名に Shotgun を含むものと
# 下の名前(Prime・Kuva などを外した元の名前)で判定する。Riven 相場のデータがあれば、そちらの武器種を優先する
SHOTGUN_BASES = {"strun", "hek", "boar", "sobek", "felarx", "steflos", "corinth", "astilla", "cedo", "phantasma",
                 "rauta", "tigris", "phage", "bassocyst", "arca plasmor", "exergis", "kohm", "drakgoon", "bubonico"}


_VARIANT_WORDS = {"prime", "wraith", "vandal", "kuva", "tenet", "coda", "prisma", "sancti", "vaykor", "mara", "dex",
                  "rakta", "telos", "synoid", "secura", "mutalist", "carmine", "proboscis", "ceti"}


def weapon_base_name(name: str) -> str:
    """Prime・Kuva・MK1- などを外した元の武器名 (例: "Kuva Hek" -> "hek")"""
    words = re.sub(r"^mk1-", "", name.strip().lower()).split()
    return " ".join(x for x in words if x not in _VARIANT_WORDS)


def dispo_type(cat: str, uid: str, name: str) -> str:
    """Riven の種類 (RIVEN_TYPES_JA のキー)"""
    if cat == "primary":
        shotgun = "shotgun" in uid.lower() or weapon_base_name(name) in SHOTGUN_BASES
        return "Shotgun Riven Mod" if shotgun else "Rifle Riven Mod"
    return _DISPO_TYPE[cat]


def dispo_dots(value: float) -> int:
    """性質値 -> ●の数: 0.5〜0.7 / 0.71〜0.9 / 0.91〜1.10 / 1.11〜1.30 / 1.31〜1.55"""
    v = round(value, 2)
    return 1 if v <= 0.70 else 2 if v <= 0.90 else 3 if v <= 1.10 else 4 if v <= 1.30 else 5


def mod_type_key(it: dict) -> str:
    t = it.get("type") or ""
    if "/Necromech/" in it.get("uniqueName", ""):
        return "NECRAMECH"
    return t if t in MOD_TYPES else "OTHER"


def is_listed_mod(it: dict) -> bool:
    """MOD一覧に載せる MOD か(Riven・コンクラーヴ用・初心者用(欠陥)・変換コアは除く)"""
    uid, name = it.get("uniqueName", ""), it.get("name", "")
    return bool(name) and not (
        "Riven Mod" in name or "/PvPMods/" in uid or "/Beginner/" in uid or "/TransmuteCores/" in uid
        or "/Randomized/" in uid)


def names_from_exports(en_docs: list[dict], ja_docs: list[dict]) -> dict:
    """Export の英語版・日本語版を uniqueName で突き合わせて辞書化する。"""
    def collect(docs):
        out = {}
        for doc in docs:
            for key, val in doc.items():
                if not isinstance(val, list):
                    continue
                for it in val:
                    if isinstance(it, dict) and it.get("uniqueName") and it.get("name"):
                        out[it["uniqueName"]] = (it["name"], key)
        return out

    en, ja = collect(en_docs), collect(ja_docs)
    en2ja, resources = {}, []
    for uid, (en_name, kind) in en.items():
        if uid in ja:
            en2ja.setdefault(en_name, ja[uid][0])
        if kind == "ExportResources":
            resources.append(en_name)

    # MOD 一覧用の情報(種別・極性・レア度など)
    mods: dict[str, dict] = {}
    for doc in en_docs:
        for it in doc.get("ExportUpgrades", []):
            if not isinstance(it, dict) or not is_listed_mod(it):
                continue
            name = it["name"]
            if name.lower() in mods:
                continue
            compat = it.get("compatName") or ""
            mods[name.lower()] = {
                "en": name, "ja": ja.get(it["uniqueName"], (name,))[0],
                "type": mod_type_key(it), "polarity": it.get("polarity") or "",
                "rarity": (it.get("rarity") or "").capitalize(),
                "compat": compat if compat.upper() != compat else "",  # "WARFRAME" 等の汎用名は省く
                "drain": it.get("baseDrain"), "max_rank": it.get("fusionLimit"),
            }
    # 画像解析で照合する装備名(フレーム・武器・コンパニオン)とアルケイン名
    items: dict[str, dict] = {}
    arcanes: dict[str, str] = {}
    arcane_list: dict[str, dict] = {}  # アルケイン所持一覧
    for doc in en_docs:
        for key in ("ExportWarframes", "ExportWeapons", "ExportSentinels"):
            for it in doc.get(key, []):
                if not isinstance(it, dict) or it.get("productCategory") not in ITEM_TYPES:
                    continue
                name = re.sub(r"^<[^>]+>\s*", "", it.get("name", "")).strip()
                if name and name.lower() not in items:
                    ja_name = re.sub(r"^<[^>]+>\s*", "", ja.get(it["uniqueName"], (name,))[0]).strip()
                    items[name.lower()] = {"en": name, "ja": ja_name, "type": ITEM_TYPES[it["productCategory"]]}
        for it in doc.get("ExportRelicArcane", []):
            name = it.get("name", "") if isinstance(it, dict) else ""
            if name and not name.endswith(" Relic") and "/CosmeticEnhancers/" in it.get("uniqueName", ""):
                arcanes.setdefault(name.lower(), name)
                # 所持一覧は図鑑に載るものだけ (Arcane Steadfast の内部用の項目などを除く)。最大ランク = 段階の数 - 1
                # レア度: ExportRelicArcane はコモンのアルケインの一部で rarity を省いているため、無ければコモン
                #   (2026-10 時点で省かれている 21 件のうち、WFCD warframe-items に値がある 17 件はすべて Common。
                #    なお ExportUpgrades (MOD) はコモンも省かずに書いてある)
                levels = len(it.get("levelStats") or [])
                if (not it.get("excludeFromCodex") and levels >= 2 and name.lower() not in arcane_list
                        and it.get("uniqueName") not in ARCANE_UNRELEASED):
                    arcane_list[name.lower()] = {
                        "en": name, "ja": ja.get(it["uniqueName"], (name,))[0], "cat": arcane_cat(name),
                        "rarity": (it.get("rarity") or "COMMON").capitalize(), "max_rank": levels - 1}
    # マスター一覧
    mastery: dict[str, dict] = {}
    for doc in en_docs:
        for key in ("ExportWarframes", "ExportWeapons", "ExportSentinels"):
            for it in doc.get(key, []):
                if not isinstance(it, dict):
                    continue
                name = re.sub(r"^<[^>]+>\s*", "", it.get("name", "")).strip()
                for cat, variant in mastery_slots(key, it):
                    mid = f"{cat}:{variant}:{name.lower()}" if variant else f"{cat}:{name.lower()}"
                    if mid in mastery:
                        continue
                    rank = int(it.get("maxLevelCap") or MASTERY_MAX_RANK.get(cat, 30))
                    mastery[mid] = {"id": mid, "en": name, "cat": cat, "variant": variant, "rank": rank,
                                    "ja": re.sub(r"^<[^>]+>\s*", "", ja.get(it["uniqueName"], (name,))[0]).strip(),
                                    "xp": mastery_xp(cat, key, rank, it.get("uniqueName", ""))}
    # Riven 性質 (マスター一覧と同じ数え方の武器から、Riven を付けられないアークウイング近接・アンプを除く)
    dispo: dict[str, dict] = {}
    for doc in en_docs:
        for it in doc.get("ExportWeapons", []):
            if not isinstance(it, dict) or not isinstance(it.get("omegaAttenuation"), (int, float)):
                continue
            if _COMPANION_HEAD.search(it.get("uniqueName", "")) or _MASTERY_CODEX_EXEMPT.search(it.get("uniqueName", "")):
                continue  # MOA・ハウンドの頭とハウンドの武器はマスター一覧(robotic)だけ。Riven 性質には今まで通り出さない
            name = re.sub(r"^<[^>]+>\s*", "", it.get("name", "")).strip()
            for cat, variant in mastery_slots("ExportWeapons", it):
                if cat not in DISPO_CATS:
                    continue
                did = f"{cat}:{variant}:{name.lower()}" if variant else f"{cat}:{name.lower()}"
                if did in dispo:
                    continue
                # Kitgun のプライマリ版は primeOmegaAttenuation (無ければセカンダリ版と同じ値)
                raw = it.get("primeOmegaAttenuation") if variant == "primary" else None
                value = round(float(raw if isinstance(raw, (int, float)) else it["omegaAttenuation"]), 2)
                dispo[did] = {"id": did, "en": name, "cat": cat, "variant": variant, "value": value,
                              "type": dispo_type(cat, it.get("uniqueName", ""), name),
                              "ja": re.sub(r"^<[^>]+>\s*", "", ja.get(it["uniqueName"], (name,))[0]).strip()}
    order = {c: i for i, c in enumerate(MASTERY_CATS)}
    return {"en2ja": en2ja, "resources": sorted(set(resources)),
            "mods": sorted(mods.values(), key=lambda m: m["en"].lower()),
            "items": sorted(items.values(), key=lambda m: m["en"].lower()),
            "arcanes": sorted(arcanes.values(), key=str.lower),
            "arcane_list": sorted(arcane_list.values(), key=lambda m: (list(ARCANE_CATS).index(m["cat"]), m["en"].lower())),
            "mastery": sorted(mastery.values(), key=lambda m: (order[m["cat"]], m["en"].lower(), m["variant"])),
            "dispo": sorted(dispo.values(), key=lambda m: (list(DISPO_CATS).index(m["cat"]), -m["value"], m["en"].lower(), m["variant"]))}


class Names:
    def __init__(self, en2ja: dict | None = None, resources: list | None = None, mods: list | None = None,
                 items: list | None = None, arcanes: list | None = None, mastery: list | None = None,
                 dispo: list | None = None, arcane_list: list | None = None):
        self.en2ja = en2ja or {}
        self.resources = set(resources or [])
        self.mods = mods or []
        self.items = items or []      # 装備名 [{en, ja, type}] (画像解析用)
        self.arcanes = arcanes or []  # アルケイン名 (画像解析用)
        self.mastery = mastery or []  # マスター一覧 [{id, en, ja, cat, variant, rank, xp}]
        self.dispo = dispo or []      # Riven 性質 [{id, en, ja, cat, variant, value, type}]
        self.arcane_list = arcane_list or []  # アルケイン所持一覧 [{en, ja, cat, rarity, max_rank}]
        # ドロップ表と公式データで大文字小文字が違うことがある(例: "Bane Of Grineer" / "Bane of Grineer")
        self._lower = {k.lower(): v for k, v in self.en2ja.items()}
        self._res_lower = {r.lower() for r in self.resources}
        self._parts: dict[str, tuple[str, str]] | None = None  # パーツ検索用 {本体の英名(小文字): (英名, カテゴリー)}。初回に作る

    @classmethod
    def from_json(cls, j: dict | None) -> "Names":
        """names.json の中身から作る。None なら空の辞書"""
        if j is None:
            return cls()
        return cls(j.get("en2ja"), j.get("resources"), j.get("mods"), j.get("items"), j.get("arcanes"), j.get("mastery"),
                   j.get("dispo"), j.get("arcane_list"))

    @staticmethod
    def split_qty(name: str) -> tuple[str, str]:
        m = re.match(r"^([\d,]+)X\s+(.*)$", name)
        return (m.group(1), m.group(2)) if m else ("", name)

    def _get(self, en: str) -> str | None:
        return self.en2ja.get(en) or self._lower.get(en.lower())

    def ja(self, name: str) -> str:
        qty, base = self.split_qty(name)
        pre = f"{qty}個 " if qty else ""
        if hit := self._get(base):
            return pre + hit
        if m := re.match(r"^([\d,]+) Credits Cache$", base):
            return f"{m.group(1)} クレジットキャッシュ"
        if m := re.match(r"^([\d,]+) Credits$", base):
            return f"{m.group(1)} クレジット"
        if m := re.match(r"^([\d,]+) Endo$", base):
            return f"{m.group(1)} エンド"
        if m := re.match(r"^(Lith|Meso|Neo|Axi|Requiem|Vanguard) (\S+) Relic$", base):
            return f"{ERA_JA[m.group(1)]} {m.group(2)} レリック"
        if base.endswith(" Blueprint"):
            b = base[:-10]
            if hit := self._get(b):
                return hit + " 設計図"
            words = b.split(" ")
            if len(words) > 1 and words[-1] in PART_JA and (first := self._get(words[0])):
                return f"{first} {PART_JA[words[-1]]} 設計図"
        return pre + base

    def is_resource(self, name: str) -> bool:
        return self.split_qty(name)[1].lower() in self._res_lower

    def part_of(self, name: str) -> tuple[str, str] | None:
        """パーツ検索の対象(Warframe・武器などの本体・設計図・パーツ)なら (本体の英名, マスター一覧のカテゴリー)、違えば None。

        「本体名 + 部品名(PART_WORDS。前に PART_QUALIFIERS が付くことがある)+ Blueprint」の形だけを拾う。
        本体名は一番長く一致するもの(例: "Lato Prime Barrel" は Lato ではなく Lato Prime)。
        """
        if self._parts is None:
            self._parts = {}
            for m in sorted(self.mastery, key=lambda m: list(MASTERY_CATS).index(m["cat"]) if m["cat"] in MASTERY_CATS else 99):
                if m["cat"] not in PART_SKIP_CATS and m.get("id") not in MASTERY_FOUNDER:  # ファウンダー限定品も除く
                    self._parts.setdefault(m["en"].lower(), (m["en"], m["cat"]))
        words = self.split_qty(name)[1].lower().split()  # ドロップ表と公式データで大文字小文字が違うことがあるので小文字でそろえる
        if words and words[-1] == "blueprint":
            words = words[:-1]
        for i in range(len(words), 0, -1):
            hit = self._parts.get(" ".join(words[:i]))
            if hit is None:
                continue
            rest = words[i:]
            if len(rest) > 1 and rest[0] in _PART_QUALIFIERS:
                rest = rest[1:]
            return hit if not rest or " ".join(rest) in _PART_WORDS else None
        return None


def item_key(name: str) -> str:
    """数量違い(例: 2X Neurodes / Neurodes)や大文字小文字の違いを同じ項目として扱うためのキー"""
    return Names.split_qty(name)[1].lower()
