"""ビルド管理"""
from __future__ import annotations

import re

from wfp.core.archon import clean_shards
from wfp.core.const import BUILD_TYPES
from wfp.core.errors import TextError
from wfp.core.helminth import clean_helminth
from wfp.core.i18n import txt
from wfp.core.text import norm


def find_build(builds: list[dict], name: str) -> dict | None:
    hits = [b for b in builds if norm(b["name"]) == norm(name)] or [b for b in builds if norm(name) in norm(b["name"])]
    return hits[0] if len(hits) == 1 else None


def arcane_pairs(names) -> list[dict]:
    """ビルドのアルケイン欄の候補: [{en, ja}](names は core.names.Names)。和名が無ければ ja は英名"""
    return [{"en": en, "ja": names.ja(en)} for en in names.arcanes]


def canon_arcanes(names, given: list[str]) -> list[str]:
    """英名・和名のどちらで書いたアルケインも英名にそろえる(保存は英名)。
    照合は norm(大文字小文字・ひらがな/カタカナ・区切りを無視)。一覧に無い名前は書いたまま残し、同じものは1つにまとめる"""
    index: dict[str, str] = {}
    for pair in arcane_pairs(names):
        for label in (pair["en"], pair["ja"]):
            index.setdefault(norm(label), pair["en"])
    out: list[str] = []
    for name in given:
        en = index.get(norm(name), name)
        if norm(en) not in {norm(x) for x in out}:
            out.append(en)
    return out


def split_list(value) -> list[str]:
    """MOD・アルケイン・タグの入力を一覧にする。区切りは改行・「,」・「、」(配列なら1つにつないでから)。空の行は捨てる"""
    text = "\n".join(str(x) for x in value) if isinstance(value, list) else str(value or "")
    return [part.strip() for part in re.split(r"[\n,、]", text) if part.strip()]


def make_build(raw: dict, names, shard_data: dict, images: list[str] | None = None) -> dict:
    """入力(画面の本文・CLI の引数を同じ形の dict にしたもの)から保存するビルド1件を作る(API・CLI 共通)。

    raw: name type target forma mods arcanes tags note helminth shards(無い項目は空として扱う)。
    種別が BUILD_TYPES に無ければ other、フォーマは 0 以上の整数(負の数は 0)。アルケインは英名にそろえる(names は Names)。
    Helminth・アルコンの欠片は Warframe のビルドで入力したときだけ付ける(shard_data は core.archon の shard_list)。
    images は検査済みの画像の名前(呼ぶ側が検査する)。入力の誤りは TextError
    """
    name = str(raw.get("name") or "").strip()
    if not name:
        raise TextError(txt("err.build.name"))
    btype = raw.get("type") if raw.get("type") in BUILD_TYPES else "other"
    try:
        forma = max(0, int(raw.get("forma") or 0))
    except (TypeError, ValueError):
        raise TextError(txt("err.build.forma"))
    helminth = clean_helminth(btype, raw.get("helminth"))
    shards = clean_shards(btype, raw.get("shards"), shard_data)
    return {"name": name, "type": btype, "target": str(raw.get("target") or "").strip(), "forma": forma,
            "mods": split_list(raw.get("mods")), "arcanes": canon_arcanes(names, split_list(raw.get("arcanes"))),
            "tags": split_list(raw.get("tags")), "note": str(raw.get("note") or "").strip(),
            "images": list(images or []),
            # Helminth は Warframe のビルドで入力したときだけ付ける(無ければ項目ごと無い)
            **({"helminth": helminth} if helminth else {}),
            # アルコンの欠片も同じ(5枠の一覧。空の枠は null)
            **({"shards": shards} if shards else {})}
