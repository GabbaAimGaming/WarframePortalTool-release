"""シンジケート・クエスト報酬・商人の入手先(オプション。2026-11-25)。

データ更新で「Export Plus も取る」を選んだときだけ、calamity-inc/warframe-public-export-plus の
ExportSyndicates・ExportKeys・ExportVendors を取り、要る項目だけを内部パスのまま取り出して offers.json に書く(extract_offers)。
読み込むときに item_paths.json(内部パス -> 英名)で名前にして、入手先の行(SourceRow)にする(offer_rows)。
使う組織は core/const の SYNDICATE_NAMES・SYNDICATE_AS_OTHER にあるものだけ。商人は期間限定(VENDOR_SKIP_PATTERNS)を除いて全部取り出し、
どれを入手先に出すかは利用者が選ぶ(利用者データ offer_vendors。vendors_on)。名前の無い一覧は auto_vendor_label で名前を作る
"""
from __future__ import annotations

import re

from wfp.core.const import (
    EXPORT_PLUS_SRC, OFFER_SKIP_PATHS, RESURGENCE_STORE_PREFIX, SYNDICATE_AS_OTHER, SYNDICATE_NAMES, VENDOR_DEFAULT_OFF,
    VENDOR_MANIFEST_PREFIX, VENDOR_MANIFESTS, VENDOR_NAMES, VENDOR_SKIP_PATTERNS,
)
from wfp.core.common import to_float
from wfp.core.i18n import name_txt, txt
from wfp.core.names import Names, item_key
from wfp.drops.tables import SourceRow

# クエスト報酬のうち品物として拾う種類(RT_CREDITS などは拾わない)
_QUEST_REWARD_TYPES = ("RT_STORE_ITEM", "RT_RECIPE", "RT_RESOURCE")


def _num(v: object) -> int:
    """数(整数にする)。数でなければ 0"""
    return int(to_float(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _syndicates(doc: dict) -> dict[str, list[dict]]:
    """ExportSyndicates の交換品(favours)。使う組織だけ。{キー: [{path, level, standing}]}"""
    out: dict[str, list[dict]] = {}
    for key, s in doc.items():
        if key not in SYNDICATE_NAMES and key not in SYNDICATE_AS_OTHER or not isinstance(s, dict):
            continue
        favours = s.get("favours") if isinstance(s.get("favours"), list) else []
        out[key] = [{"path": f["storeItem"], "level": _num(f.get("requiredLevel")), "standing": _num(f.get("standingCost"))}
                    for f in favours if isinstance(f, dict) and isinstance(f.get("storeItem"), str)]
    return out


def _quests(doc: dict) -> dict[str, list[str]]:
    """ExportKeys の報酬。段(Key)の報酬は、その段を chainStages に持つクエスト(KeyChain)に寄せる。{クエストの内部パス: [品物の内部パス]}"""
    chain_of: dict[str, str] = {}
    for path, k in doc.items():
        for st in (k.get("chainStages") if isinstance(k, dict) and isinstance(k.get("chainStages"), list) else []):
            if isinstance(st, dict) and isinstance(st.get("key"), str):
                chain_of.setdefault(st["key"], path)
    out: dict[str, list[str]] = {}
    for path, k in doc.items():
        rewards = k.get("rewards") if isinstance(k, dict) and isinstance(k.get("rewards"), list) else []
        for r in rewards:
            if isinstance(r, dict) and r.get("rewardType") in _QUEST_REWARD_TYPES and isinstance(r.get("itemType"), str):
                items = out.setdefault(chain_of.get(path, path), [])
                if r["itemType"] not in items:
                    items.append(r["itemType"])
    return out


def _vendors(doc: dict) -> dict[str, list[dict]]:
    """ExportVendors の品物。期間限定の一覧(VENDOR_SKIP_PATTERNS)を除いて全部。{一覧のキー: [{path, qty, prices, credits, platinum, focus, rotating}]}。
    qty は1回で買える個数(例: Teshin の Kuva は 10,000 と 50,000)。
    一覧のキーは VendorManifests/ より後(例: "Hubs/TeshinHardModeVendorManifest")。
    rotating は日替わり・週替わりの品(一覧が入れ替わるもので、いつも並ぶ品ではない)"""
    out: dict[str, list[dict]] = {}
    for path, v in doc.items():
        tail = path[len(VENDOR_MANIFEST_PREFIX):] if isinstance(path, str) and path.startswith(VENDOR_MANIFEST_PREFIX) else ""
        if not tail or any(x in path for x in VENDOR_SKIP_PATTERNS) or not isinstance(v, dict):
            continue
        dynamic = bool(v.get("isDynamic"))
        rows = []
        for it in v.get("items") if isinstance(v.get("items"), list) else []:
            if not isinstance(it, dict) or not isinstance(it.get("storeItem"), str):
                continue
            prices = [[p["ItemType"], _num(p.get("ItemCount"))] for p in (it.get("itemPrices") or [])
                      if isinstance(p, dict) and isinstance(p.get("ItemType"), str)]
            rows.append({"path": it["storeItem"], "qty": _num(it.get("quantity")) or 1, "prices": prices,
                         "credits": _num(it.get("credits")),
                         "platinum": _num(it.get("platinum")), "focus": _num(it.get("focusXpCost")),
                         "rotating": dynamic and not it.get("alwaysOffered")})
        out[tail] = rows
    return out


def vendor_key(tail: str) -> str:
    """一覧のキー -> 商人のキー(名前のある一覧は VENDOR_MANIFESTS の値、無い一覧は一覧のキーそのもの)"""
    return VENDOR_MANIFESTS.get(tail, tail)


def vendor_named(key: str) -> bool:
    """商人のキーに名前があるか(VENDOR_NAMES。無ければ auto_vendor_label で作る)"""
    return key in VENDOR_NAMES


def auto_vendor_label(key: str):
    """名前の無い一覧の名前のテキスト指定: 「拠点: 一覧の名前」。拠点は VENDOR_GROUPS(web/i18n の vgroup.<組>)、
    一覧の名前は末尾の VendorManifest / Manifest を外して単語に区切った英語(例: "Ostron/NewThingVendorManifest" -> シータス: New Thing)"""
    group, _, rest = key.partition("/")
    base = re.sub(r"(Vendor)?Manifest$", "", rest.rsplit("/", 1)[-1]) or rest
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", base).strip() or key
    if not rest:
        return words
    return txt("src.vendor.auto", place=name_txt("vgroup.", group), name=words)


def vendor_place(key: str):
    """商人の入手先の名前のテキスト指定(名前があれば vendor.<キー>、無ければ auto_vendor_label)"""
    return name_txt("vendor.", key) if vendor_named(key) else auto_vendor_label(key)


def vendors_on(choices: object, keys=None) -> set[str]:
    """入手先に出す商人のキー。choices は利用者の選択 {キー: true/false}(userdata の offer_vendors)。
    選んでいない商人は初期値(名前があり VENDOR_DEFAULT_OFF に無ければオン、名前の無い一覧はオフ)。
    keys は候補(省略すると名前のある商人と、choices でオンにしたキー)"""
    chosen = choices if isinstance(choices, dict) else {}
    pool = set(VENDOR_NAMES) | {k for k, v in chosen.items() if v is True} if keys is None else set(keys)
    return {k for k in pool if chosen.get(k, vendor_default(k)) is True}


def vendor_default(key: str) -> bool:
    """商人の初期値(選んでいないときにオンか)"""
    return vendor_named(key) and key not in VENDOR_DEFAULT_OFF


def extract_offers(docs: dict[str, dict], updated: str) -> dict:
    """取得した Export Plus({ファイル名: 中身})から offers.json の中身を作る"""
    return {"source": EXPORT_PLUS_SRC, "updated": updated,
            "syndicates": _syndicates(docs.get("ExportSyndicates") or {}),
            "quests": _quests(docs.get("ExportKeys") or {}),
            "vendors": _vendors(docs.get("ExportVendors") or {})}


def offer_count(data: dict) -> int:
    """取り出した品物の数(ログ用)"""
    return sum(len(v) for part in ("syndicates", "quests", "vendors") for v in (data.get(part) or {}).values())


class _Namer:
    """内部パス -> 英名(item_paths.json)。交換品の /Lotus/StoreItems/… は /Lotus/… に読み替えて引く。出さない品物(OFFER_SKIP_PATHS)は None"""

    def __init__(self, paths: dict, names: Names):
        self.paths, self.names = paths, names

    def name(self, path: object) -> str | None:
        """内部パスの英名(無ければ None)"""
        if not isinstance(path, str):
            return None
        store, export = RESURGENCE_STORE_PREFIX
        name = (self.paths.get(export + path[len(store):]) if path.startswith(store) else None) or self.paths.get(path)
        return name.strip() if isinstance(name, str) and name.strip() else None

    def item(self, path: object) -> str | None:
        """入手先に出す品物の英名。出さない品物(OFFER_SKIP_PATHS)・名前の引けない品物は None"""
        if not isinstance(path, str) or any(s in path for s in OFFER_SKIP_PATHS):
            return None
        return self.name(path)

    def both(self, en: str) -> dict:
        """英名を ja・en のテキスト指定にする(和名は名前辞書。無ければ英名)"""
        return {"l": {"en": en, "ja": self.names.ja(en)}}


def _price(namer: _Namer, it: dict):
    """商人の品物の値段のテキスト指定(通貨 ×数・クレジット・プラチナ・フォーカス。複数は「 / 」でつなぐ)。
    2個以上で売る品は頭に個数(src.vendor.qty)、入れ替わる品は印を付ける"""
    parts = []
    for p in it.get("prices") if isinstance(it.get("prices"), list) else []:
        if isinstance(p, list) and len(p) == 2 and isinstance(p[0], str):
            cur = namer.name(p[0]) or p[0].rsplit("/", 1)[-1]
            parts.append(txt("src.price.item", name=namer.both(cur), n=f"{_num(p[1]):,}"))
    for field, key in (("credits", "src.price.credits"), ("platinum", "src.price.plat"), ("focus", "src.price.focus")):
        if _num(it.get(field)):
            parts.append(txt(key, n=f"{_num(it.get(field)):,}"))
    out = parts[0] if parts else ""
    for p in parts[1:]:
        out = txt("src.note", a=out, b=p)
    if _num(it.get("qty")) > 1:  # 値段が無い品(日替わりで値段が決まるものなど)は個数だけ
        n = f"{_num(it.get('qty')):,}"
        out = txt("src.vendor.qty", n=n, p=out) if out else txt("src.qty", n=n)
    return txt("src.vendor.rotating", p=out) if it.get("rotating") else out


def offer_rows(raw: object, paths: dict, names: Names, vendors: set[str] | None = None) -> list[SourceRow]:
    """offers.json の中身を入手先の行にする。名前の引けない品物・使わない組織・形の違う行は黙って飛ばす。
    vendors は入手先に出す商人のキー(vendors_on。None なら全部)。
    同じ (種類, 入手先, 詳細, 品物) は最初の1行だけ(1つの商人が複数の一覧を持つため。値段が違えば別の行)"""
    if not isinstance(raw, dict):
        return []
    namer = _Namer(paths if isinstance(paths, dict) else {}, names)
    rows: list[SourceRow] = []
    seen: set[tuple] = set()

    def add(cat: str, place, detail, item: str | None) -> None:
        if not item:
            return
        mark = (cat, repr(place), repr(detail), item_key(item))
        if mark not in seen:
            seen.add(mark)
            rows.append(SourceRow(cat, place, detail, "-", item, None, ""))

    syn = raw.get("syndicates") if isinstance(raw.get("syndicates"), dict) else {}
    for key, lst in syn.items():
        if key in SYNDICATE_AS_OTHER:
            cat, place = SYNDICATE_AS_OTHER[key], name_txt("src.cat.", SYNDICATE_AS_OTHER[key])
        elif key in SYNDICATE_NAMES:
            cat, place = "syndicate", name_txt("syndicate.", key)
        else:
            continue
        for f in lst if isinstance(lst, list) else []:
            if not isinstance(f, dict):
                continue
            cost = f"{_num(f.get('standing')):,}"
            detail = txt("src.standing", cost=cost) if cat != "syndicate" else txt("src.syndicate.rank", r=str(_num(f.get("level"))), cost=cost)
            add(cat, place, detail, namer.item(f.get("path")))

    quest_names = {q["id"]: q for q in names.quests if isinstance(q, dict) and isinstance(q.get("id"), str)}
    quests = raw.get("quests") if isinstance(raw.get("quests"), dict) else {}
    for qpath, items in quests.items():
        q = quest_names.get(qpath)
        en = q.get("en") if q else namer.name(qpath)
        if not isinstance(en, str) or not en.strip():
            continue
        place = {"l": {"en": en.strip(), "ja": (q.get("ja") if q else None) or names.ja(en.strip())}}
        for path in items if isinstance(items, list) else []:
            add("quest", place, "", namer.item(path))

    for key, it in _vendor_items(raw):
        if vendors is None or key in vendors:
            add("vendor", vendor_place(key), _price(namer, it), namer.item(it.get("path")))
    return rows


def _vendor_items(raw: dict):
    """offers.json の商人の品物を (商人のキー, 品物) で順に返す(形の違うものは飛ばす)"""
    vendors = raw.get("vendors") if isinstance(raw.get("vendors"), dict) else {}
    for tail, lst in vendors.items():
        if isinstance(tail, str):
            for it in lst if isinstance(lst, list) else []:
                if isinstance(it, dict):
                    yield vendor_key(tail), it


def vendor_counts(raw: object, paths: dict) -> dict[str, int]:
    """商人ごとの、入手先に出る品物の数(選択に関係なく数える。0 件の商人は入れない)。並びは VENDOR_NAMES の順 → 名前の無い一覧"""
    if not isinstance(raw, dict):
        return {}
    namer = _Namer(paths if isinstance(paths, dict) else {}, Names())
    items: dict[str, set[str]] = {}
    for key, it in _vendor_items(raw):
        if (name := namer.item(it.get("path"))):
            items.setdefault(key, set()).add(item_key(name))
    order = [k for k in VENDOR_NAMES if k in items] + sorted(k for k in items if k not in VENDOR_NAMES)
    return {k: len(items[k]) for k in order}
