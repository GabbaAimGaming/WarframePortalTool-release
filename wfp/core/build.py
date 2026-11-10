"""ビルド管理"""
from __future__ import annotations

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
