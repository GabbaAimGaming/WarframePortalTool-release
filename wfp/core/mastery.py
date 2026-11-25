"""マスター一覧

- 元は名前辞書(names.json の mastery。Public Export から作る)
- Export に無い項目(プレクサス・アンプ本体。カテゴリーは extra「その他」)は同梱の data/mastery/extra.json から毎回足す。names.json には入れないので、
  データ更新や Export との照合で見つからなくても消えない
- ファウンダー限定品(MASTERY_FOUNDER)はカテゴリーを「ファウンダー」に付け替える。id は元のままなので、
  マスター済みの記録(mastered.json)は付け替えの前後で変わらない
"""
from __future__ import annotations

from pathlib import Path

from wfp.core.i18n import render_ja, txt
from wfp.core.const import MASTERY_CATS, MASTERY_EXTRA_FILE, MASTERY_FOUNDER, SOURCE_CATS
from wfp.core.names import Names, item_key
from wfp.core.text import norm
from wfp.drops.tables import Vault
from wfp.store import appdata


def mastery_label(m: dict) -> str:
    """日本語の表示名(CLI 用)。Kitgun はプライマリ版とセカンダリ版を区別する(画面は I18N の mastery.variant で同じ形にする)"""
    v = m.get("variant", "")
    return render_ja(txt("mastery.variant", name=m["ja"], variant=txt("mastery.variant." + v))) if v else m["ja"]


def check_extra(raw: object) -> list[dict]:
    """extra.json の中身を検査して項目の一覧にする。形の合わない項目は黙って飛ばす(ファイルが無い・壊れていれば空)"""
    items = raw.get("items") if isinstance(raw, dict) else None
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        en, cat, rk, xp = it.get("en"), it.get("cat"), it.get("rank"), it.get("xp")
        if (not isinstance(en, str) or not en.strip() or cat not in MASTERY_CATS or cat == "founder"
                or isinstance(rk, bool) or not isinstance(rk, int) or rk <= 0
                or isinstance(xp, bool) or not isinstance(xp, int) or xp < 0):
            continue
        ja = it.get("ja") if isinstance(it.get("ja"), str) and it["ja"].strip() else en
        out.append({"id": f"{cat}:{en.strip().lower()}", "en": en.strip(), "ja": ja.strip(), "cat": cat,
                    "variant": "", "rank": rk, "xp": xp})
    return out


def mastery_items(names: Names, src: Path | None = None) -> list[dict]:
    """マスター一覧の全項目: 名前辞書の分 + 手で足す分(同じ id は名前辞書を優先)。ファウンダー限定品は付け替える"""
    items = list(names.mastery)
    ids = {m["id"] for m in items}
    items += [m for m in check_extra(appdata.read_mastery(MASTERY_EXTRA_FILE, src)) if m["id"] not in ids]
    items = [{**m, "cat": "founder"} if m["id"] in MASTERY_FOUNDER else m for m in items]
    order = {c: i for i, c in enumerate(MASTERY_CATS)}
    return sorted(items, key=lambda m: (order.get(m["cat"], len(order)), m["en"].lower(), m.get("variant", "")))


def mastery_table(names: Names, done: set[str], src: Path | None = None) -> list[dict]:
    """マスター済みの印つきの一覧。カテゴリー・Kitgun の区別(variant)はキーのまま(表示名は画面 / CLI で付ける)"""
    return [{**m, "done": m["id"] in done} for m in mastery_items(names, src)]


def add_source_cats(rows: list[dict], index: dict[str, list[tuple]], parts: dict[str, list[str]]) -> None:
    """一覧の行に src_cats(入手先の種類のキー。SOURCE_CATS の順)を付ける。本体そのものと、そのパーツ全部の入手先から集める
    (行の詳細 /api/mastery/sources と同じ範囲。イベントは入れない)。index は drops/search の source_index、
    parts は parts_by_owner の表(本体の英名を norm したもの → パーツの英名)"""
    for r in rows:
        found = {s[0] for name in (r["en"], *parts.get(norm(r["en"]), [])) for s in index.get(item_key(name), [])}
        r["src_cats"] = [c for c in SOURCE_CATS if c in found]


def vaulted_owners(names: Names, vault: Vault, owners: dict[str, str] | None = None) -> set[str]:
    """いま作れない本体(マスター一覧の英名を小文字にしたもの)。入手不可のパーツ(Vault.items。入手先が Vault 入りのレリックだけ)を
    1つでも持つ本体は、そのパーツが手に入らないので作れない。パーツ → 本体は Names.part_of(owners は Sources.part_owner)。
    ファウンダー限定品は part_of が拾わないので入らない。ドロップ表が無ければ Vault が空なので何も入らない"""
    out = set()
    for item in vault.items:
        if hit := names.part_of(item, owners):
            out.add(hit[0].lower())
    return out


def mastery_summary(rows: list[dict]) -> dict:
    out = {}
    for c in MASTERY_CATS:
        rs = [r for r in rows if r["cat"] == c]
        out[c] = {"total": len(rs), "done": sum(r["done"] for r in rs),
                  "xp": sum(r["xp"] for r in rs), "xp_done": sum(r["xp"] for r in rs if r["done"])}
    out["all"] = {k: sum(v[k] for v in out.values()) for k in ("total", "done", "xp", "xp_done")}
    return out
