"""MOD 効果検索: Export の levelStats(ランク0〜最大の効果テキスト)を、影響先(アビリティ威力など)と全文で探す。

- データ更新で ExportUpgrades / ExportAvionics(en・ja)から mod_stats.json を作る(make_mod_stats)。ダウンロードは増えない
- 影響先は保存しない。読み込むときに data/mod_stats/targets.json(開発側が手で編集)と突き合わせる(辞書を直せばデータ更新なしで反映)
- 判定は en の行で行い、表示は同じ位置の ja の行(ja はランク数・行数が en と違えば使わない)
- 区分(MOD_GROUPS)は MOD_GROUP_RULES を上から当てはめ、最初に当たった行の区分を全部付ける(ペット共通は robotic と beast の両方)
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from wfp.core.common import MOD_GROUPS, MOD_STATS_LIMIT, TextError, txt
from wfp.core.names import is_listed_mod
from wfp.store import appdata, gamedata

# 効果テキストを持つ Export のキー -> 区分を決める方法(ExportAvionics はすべてレールジャック)
MOD_EXPORT_KEYS = ("ExportUpgrades", "ExportAvionics")
RAILJACK_KEY = "ExportAvionics"

CLAW_COMPATS = ("Claws", "Kubrow Claws", "Helminth Claws")  # コンパニオン(ビースト)の爪。STANCE の Claws はプレイヤーの爪武器(melee)とコンパニオン(beast。uniqueName で見分ける)の両方がある
# 区分の判定(上から順に当てはめ、最初に当たった行の区分を付ける)。条件: uid = uniqueName に含む文字列 / type / compat = compatName
MOD_GROUP_RULES = (
    ({"uid": "/Necromech/"}, ("necramech",)),
    ({"uid": "/Antiques/"}, ("amp",)),
    ({"uid": "/Pets/BeastWeapons/", "type": ("STANCE",)}, ("beast",)),  # コンパニオンの爪のスタンス(〜Posture。compatName は Claws)
    ({"type": ("MELEE",), "compat": CLAW_COMPATS}, ("comp_weapon",)),
    ({"type": ("SENTINEL",), "compat": ("COMPANION",)}, ("robotic", "beast")),  # ペット共通(Pack Leader など)
    ({"type": ("SENTINEL",), "compat": ("BEAST",)}, ("beast",)),
    ({"type": ("SENTINEL",)}, ("robotic",)),  # Sentinel・Moa・Hound・ROBOTIC・各センチネル名
    ({"type": ("KUBROW", "KAVAT", "HELMINTH CHARGER")}, ("beast",)),
    ({"type": ("WARFRAME", "AURA")}, ("warframe",)),
    ({"type": ("PRIMARY",)}, ("primary",)),
    ({"type": ("---",), "compat": ("Sniper",)}, ("primary",)),  # Sniper Ammo Mutation
    ({"type": ("SECONDARY",)}, ("secondary",)),
    ({"type": ("MELEE", "STANCE")}, ("melee",)),
    ({"type": ("ARCHWING",)}, ("archwing",)),
    ({"type": ("ARCH-GUN",)}, ("archgun",)),
    ({"type": ("ARCH-MELEE",)}, ("archmelee",)),
    ({"type": ("---",), "compat": ("K-Drive",)}, ("kdrive",)),
    ({"type": ("PARAZON",)}, ("parazon",)),
)
# 条件付きの効果の見分け方(en の行。大文字小文字は区別しない)。見出し付き(On Kill:)・条件の語・時間制限・クールダウン
MOD_COND_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"^[^\n:]{1,40}:\s*\n",
    r"\b(on|when|while|whenever|after|during|upon|if|vs)\b",
    r"\bfor [\d.,]+\s*s\b",
    r"\bcooldown\b",
))
_TAG_RE = re.compile(r"<[^<>]*>")
_SPACE_RE = re.compile(r"[ \t]+")


def strip_tags(text: str) -> str:
    """表示用の文字列から色タグ(<DT_FIRE_COLOR> など)を消し、改行を \\n にそろえる"""
    text = _TAG_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_SPACE_RE.sub(" ", ln).strip() for ln in text.split("\n")).strip()


def fold(text: str) -> str:
    """検索用に表記をそろえる(全角/半角・大文字/小文字)"""
    return unicodedata.normalize("NFKC", text).lower()


def mod_groups(it: dict, export_key: str = "ExportUpgrades") -> list[str]:
    """MOD の区分キーの一覧(MOD_GROUP_RULES の最初に当たった行。どれにも当たらなければ other)"""
    if export_key == RAILJACK_KEY:
        return ["railjack"]
    uid, mod_type, compat = it.get("uniqueName") or "", it.get("type") or "", it.get("compatName") or ""
    for cond, groups in MOD_GROUP_RULES:
        if "uid" in cond and cond["uid"] not in uid:
            continue
        if "type" in cond and mod_type not in cond["type"]:
            continue
        if "compat" in cond and compat not in cond["compat"]:
            continue
        return list(groups)
    return ["other"]


def _desc(it: dict) -> str:
    """説明文(文字列か、文字列の配列)"""
    desc = it.get("description") or ""
    if isinstance(desc, list):
        desc = "\n".join(s for s in desc if isinstance(s, str))
    return strip_tags(desc) if isinstance(desc, str) else ""


def _ranks(it: dict) -> list[list[str]]:
    out = []
    for lv in it.get("levelStats") or []:
        stats = lv.get("stats") if isinstance(lv, dict) else None
        out.append([strip_tags(s) for s in stats or [] if isinstance(s, str)])
    return out


def same_shape(ranks_en: list, ranks_ja: list) -> bool:
    """ja の効果テキストが en と同じランク数・行数か(違えば表示に使わない)"""
    return isinstance(ranks_ja, list) and len(ranks_ja) == len(ranks_en) and all(
        isinstance(ja_lns, list) and len(ja_lns) == len(en_lns) for en_lns, ja_lns in zip(ranks_en, ranks_ja))


def build_mod_stats(en_docs: list[dict], ja_docs: list[dict]) -> list[dict]:
    """Export(en・ja)から MOD ごとの効果テキストを抜き出す。対象外は is_listed_mod と同じ。同じ名前は最初の1件(names の MOD 一覧と同じ)"""
    ja_by_uid: dict[str, dict] = {}
    for doc in ja_docs:
        for key in MOD_EXPORT_KEYS:
            for it in doc.get(key) or []:
                if isinstance(it, dict) and it.get("uniqueName"):
                    ja_by_uid[it["uniqueName"]] = it
    rows, seen = [], set()
    for doc in en_docs:
        for key in MOD_EXPORT_KEYS:
            for it in doc.get(key) or []:
                if not isinstance(it, dict) or not it.get("uniqueName") or not is_listed_mod(it):
                    continue
                ranks_en = _ranks(it)
                desc_en = "" if ranks_en else _desc(it)
                name_key = (key, it["name"].lower())
                if (not ranks_en and not desc_en) or name_key in seen:
                    continue
                seen.add(name_key)
                ja_it = ja_by_uid.get(it["uniqueName"]) or {}
                ranks_ja = _ranks(ja_it)
                rows.append({
                    "uid": it["uniqueName"], "en": it["name"], "ja": ja_it.get("name") or it["name"],
                    "groups": mod_groups(it, key), "compat": it.get("compatName") or "",
                    "rarity": (it.get("rarity") or "").capitalize(), "polarity": it.get("polarity") or "",
                    "max_rank": len(ranks_en) - 1 if ranks_en else (it.get("fusionLimit") or 0),
                    "stats_en": ranks_en, "stats_ja": ranks_ja if same_shape(ranks_en, ranks_ja) else [],
                    "desc_en": desc_en, "desc_ja": _desc(ja_it) if desc_en else "",
                })
    return sorted(rows, key=lambda r: r["en"].lower())


def make_mod_stats(en_docs: list[dict], ja_docs: list[dict], source: str, updated: str) -> dict:
    """mod_stats.json の中身(データ更新で保存する)"""
    return {"source": source, "updated": updated, "mods": build_mod_stats(en_docs, ja_docs)}


def check_targets(raw: object) -> dict[str, dict]:
    """影響先の辞書(targets.json)の形を確かめる。{キー: {"ja", "en", "match": [en の判定語…]}}。形の悪い項目は黙って外す"""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for key, ent in raw.items():
        if not isinstance(ent, dict) or not isinstance(ent.get("ja"), str) or not isinstance(ent.get("en"), str):
            continue
        words = [w for w in ent.get("match") or [] if isinstance(w, str) and w.strip()]
        if words:
            out[str(key)] = {"ja": ent["ja"], "en": ent["en"], "match": words}
    return out


def check_mods(raw: object) -> list[dict]:
    """mod_stats.json の mods の形を確かめる。形の悪い行は黙って外し、ja の行が en とずれていれば ja を使わない"""
    mods = raw.get("mods") if isinstance(raw, dict) else None
    out = []
    for row in mods if isinstance(mods, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("en"), str):
            continue
        ranks_en = row.get("stats_en", [])
        if not isinstance(ranks_en, list) or not all(isinstance(lns, list) and all(isinstance(s, str) for s in lns) for lns in ranks_en):
            continue
        if not ranks_en and not row.get("desc_en"):
            continue
        ranks_ja = row.get("stats_ja")
        groups = [g for g in row.get("groups") or [] if g in MOD_GROUPS] or ["other"]
        out.append({**row, "stats_en": ranks_en, "stats_ja": ranks_ja if same_shape(ranks_en, ranks_ja) else [],
                    "groups": groups, "ja": row.get("ja") if isinstance(row.get("ja"), str) else row["en"],
                    "desc_en": str(row.get("desc_en") or ""), "desc_ja": str(row.get("desc_ja") or "")})
    return out


class ModStats:
    """MOD 効果検索のデータ(読み込み時に影響先・条件付きを判定しておく)"""

    def __init__(self, mods: list[dict], targets: dict[str, dict]):
        self.targets = targets
        # 長い判定語から当てて、当たった部分は消す("Critical Damage" を "Damage" で二重に拾わないため)
        terms = sorted(((w, key) for key, ent in targets.items() for w in ent["match"]), key=lambda p: -len(p[0]))
        self._terms = [(re.compile(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", re.I), key) for w, key in terms]
        self.mods = [self._analyze(row) for row in mods]

    def line_targets(self, line_en: str) -> list[str]:
        """en の1行に当たる影響先キー(辞書の並び順)"""
        rest, hits = line_en, set()
        for term_re, key in self._terms:
            if term_re.search(rest):
                hits.add(key)
                rest = term_re.sub(" ", rest)
        return [key for key in self.targets if key in hits]

    def _analyze(self, row: dict) -> dict:
        last = row["stats_en"][-1] if row["stats_en"] else ([row["desc_en"]] if row["desc_en"] else [])
        lines = [{"targets": self.line_targets(ln), "cond": is_conditional(ln)} for ln in last]
        texts = [row["en"], row["ja"], row["desc_en"], row["desc_ja"]]
        texts += [s for lns in row["stats_en"] + row["stats_ja"] for s in lns]
        targets = list(dict.fromkeys(k for ln in lines for k in ln["targets"]))
        return {**row, "lines": lines, "targets": targets, "_hay": fold("\n".join(texts))}

    def suggest(self, query: str, limit: int = 10) -> list[dict]:
        """影響先の候補(表示名の ja・en のどちらかに部分一致。完全一致・前方一致を先に、あとは辞書の並び)"""
        q = fold(query.strip())
        if not q:
            return []
        hits = []
        for idx, (key, ent) in enumerate(self.targets.items()):
            names = (fold(ent["ja"]), fold(ent["en"]))
            if any(q in n for n in names):
                hits.append((q not in names, not any(n.startswith(q) for n in names), idx, key))
        return [{"key": key, "ja": self.targets[key]["ja"], "en": self.targets[key]["en"]} for *_, key in sorted(hits)[:limit]]

    def find(self, target: str = "", query: str = "", groups: set[str] | None = None, limit: int = MOD_STATS_LIMIT) -> dict:
        """影響先キー(target)か全文(query。部分一致)で探す。どちらも空なら区分の中の全部。groups は区分キー(None は全部)"""
        if target and target not in self.targets:
            raise TextError(txt("err.modstats.target", name=target))
        q = fold(query.strip())
        rows = [r for r in self.mods
                if (groups is None or set(r["groups"]) & groups)
                and (target in r["targets"] if target else (q in r["_hay"] if q else True))]
        tgt = {"key": target, **{k: self.targets[target][k] for k in ("ja", "en")}} if target else None
        shown = rows[:limit]
        used = dict.fromkeys(k for r in shown for k in r["targets"])  # 表示する行の影響先の表示名(画面が列の見出しに使う)
        names = {k: {"ja": self.targets[k]["ja"], "en": self.targets[k]["en"]} for k in used}
        return {"rows": [_public(r) for r in shown], "total": len(rows), "limit": limit, "target": tgt, "names": names}


def _public(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def is_conditional(line_en: str) -> bool:
    """条件付きの効果か(On Kill: など。MOD_COND_PATTERNS)"""
    return any(p.search(line_en) for p in MOD_COND_PATTERNS)


def parse_groups(text: str) -> set[str] | None:
    """"warframe,primary" -> 区分キーの集合(空なら None = 全部)。知らないキーは TextError"""
    keys = {k.strip() for k in (text or "").split(",") if k.strip()}
    bad = sorted(keys - set(MOD_GROUPS))
    if bad:
        raise TextError(txt("err.modstats.group", name=", ".join(bad)))
    return keys or None


def load_mod_stats(d: Path) -> ModStats | None:
    """mod_stats.json と影響先の辞書を読む。mod_stats.json が無い・読めなければ None(辞書が無ければ影響先なしで全文検索だけ)"""
    raw = gamedata.read_mod_stats(d)
    if raw is None:
        return None
    return ModStats(check_mods(raw), check_targets(appdata.read_mod_targets()))
