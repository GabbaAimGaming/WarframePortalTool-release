"""Prime 入手可能品の時系列(ページ primes)

同梱データ(data/primes/)の release.json(Prime Access の回)と frame_order.json(元のフレームの実装順)から、
- ゲージ: いま入手できる Prime Access の回(古い順。出てからの月数と、並び順で決める色の段階)
- Prime Resurgence: いま交換できるレリックの中身から逆算した回
- 実装順の小窓: フレームごとに Prime 化したか
を作る。表示名は付けない(状態・記号はキー。名前は ja / en の両方)。日付は年月だけ(日は持たない)。

Vault 入りの判定は drops/tables の Vault を使う。ゲージは Prime Resurgence に左右されないように、Resurgence を渡さない
Vault で判定する(交換できる間も、レリックがドロップしないものは Vault 入り)。
"""
from __future__ import annotations

import re
from datetime import date

from wfp.core.const import (PRIME_ACTIVE_MAX, PRIME_MARKS, PRIME_MONTH_RE, PRIME_MONTHS, PRIME_RELEASE_LISTS,
                            PRIME_STATES, PRIME_WORD)
from wfp.core.names import Names, item_key
from wfp.drops.tables import Resurgence, Sources, Vault

_AVAILABLE, _PENDING, _UNCHECKED = PRIME_STATES
_DONE, _NONE, _LOCKED = PRIME_MARKS


def _text(x: object) -> str:
    return x.strip() if isinstance(x, str) else ""


def _str_list(x: object) -> list[str]:
    return [s for s in map(_text, x) if s] if isinstance(x, list) else []


# ---- 読み込み(形の崩れた行は飛ばす。検査は check_primes) ----

def load_releases(raw: object) -> list[dict]:
    """release.json の中身から回の一覧(出た順のまま)。行: {month, frames, weapons, others, no_relic}"""
    rows = raw.get("releases") if isinstance(raw, dict) else None
    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not re.match(PRIME_MONTH_RE, _text(row.get("month"))):
            continue
        out.append({"month": _text(row["month"]), **{k: _str_list(row.get(k)) for k in PRIME_RELEASE_LISTS},
                    "no_relic": row.get("no_relic") is True})
    return out


def load_order(raw: object) -> list[dict]:
    """frame_order.json の中身から実装順の一覧(並びのまま)。行: {no, frame}"""
    rows = raw.get("frames") if isinstance(raw, dict) else None
    return [{"no": row["no"], "frame": _text(row["frame"])} for row in rows if isinstance(row, dict)
            and isinstance(row.get("no"), int) and not isinstance(row.get("no"), bool) and _text(row.get("frame"))] \
        if isinstance(rows, list) else []


# ---- 月 ----

def month_index(month: str) -> int:
    """"YYYY-MM" を月の通し番号にする(差で月数が出る)"""
    year, mon = month.split("-")
    return int(year) * 12 + int(mon) - 1


def months_since(month: str, today: date) -> int:
    """出てから今月までの月数(今月に出たものは 0。先の月はマイナス)"""
    return today.year * 12 + today.month - 1 - month_index(month)


# ---- レリックの中身 ----

def prime_base(item: str) -> str | None:
    """部品の名前から Prime の本体の名前を取り出す(例: Frost Prime Neuroptics Blueprint → Frost Prime)。Prime が無ければ None"""
    words = item.split(" ")
    if PRIME_WORD not in words[1:]:
        return None
    return " ".join(words[:words.index(PRIME_WORD, 1) + 1])


def relic_index(sources: Sources | None) -> dict:
    """レリックの行から {"parts": 本体のキー → 部品のキーの集合, "relics": レリックのキー → 本体のキーの集合}"""
    parts: dict[str, set[str]] = {}
    relics: dict[str, set[str]] = {}
    for row in sources.rows if sources else []:
        if row.cat != "relic" or not row.relic or not (base := prime_base(row.item)):
            continue
        parts.setdefault(item_key(base), set()).add(item_key(row.item))
        relics.setdefault(item_key(row.relic), set()).add(item_key(base))
    return {"parts": parts, "relics": relics}


def release_target(rel: dict) -> str | None:
    """未反映・Vault 入りの判定に使う名前(フレーム。無い回は先頭の武器)"""
    names = rel["frames"] or rel["weapons"]
    return names[0] if names else None


def release_state(rel: dict, parts: dict[str, set[str]], vault: Vault) -> str | None:
    """ゲージの行の状態(PRIME_STATES)。Vault 入り・判定に使う名前が無い回は None(出さない)"""
    target = release_target(rel)
    if target is None:
        return None
    if not vault.ready:
        return _UNCHECKED
    keys = parts.get(item_key(target))
    if not keys:
        return _PENDING
    return None if keys <= vault.items else _AVAILABLE


# ---- 表示用の行 ----

def _named(names: Names, en: str) -> dict:
    return {"en": en, "ja": names.ja(en)}


def _release_names(rel: dict, names: Names) -> dict:
    return {"month": rel["month"], "frames": [_named(names, n) for n in rel["frames"]],
            "weapons": [_named(names, n) for n in rel["weapons"]]}


def gauge_blocks(months: int) -> int:
    """ゲージのマスの数(今月から出た月まで。今月に出たものは 1。PRIME_MONTHS で止める)"""
    return min(months + 1, PRIME_MONTHS)


def gauge_level(index: int, count: int) -> float:
    """色の段階(1 = 赤 = 一番上・次に Vault 入り、0 = 緑 = 一番下・最新)。並び順で決める"""
    return 1.0 if count <= 1 else round(1 - index / (count - 1), 4)


def gauge_rows(releases: list[dict], today: date, parts: dict[str, set[str]], vault: Vault, names: Names) -> list[dict]:
    """ゲージの行(古い順)。今月以前に出て、レリックから出て、Vault 入りしていない回の新しい方から PRIME_ACTIVE_MAX 件。

    行: {month, frames, weapons, months(出てからの月数), blocks(塗るマスの数), state(PRIME_STATES), level(色の段階)}
    """
    picked = []
    for rel in releases:
        if rel["no_relic"] or months_since(rel["month"], today) < 0:
            continue
        if (state := release_state(rel, parts, vault)) is not None:
            months = months_since(rel["month"], today)
            picked.append({**_release_names(rel, names), "months": months, "blocks": gauge_blocks(months), "state": state})
    picked = picked[-PRIME_ACTIVE_MAX:]
    return [{**row, "level": gauge_level(i, len(picked))} for i, row in enumerate(picked)]


def resurgence_rows(releases: list[dict], resurgence: Resurgence, relics: dict[str, set[str]], names: Names,
                    now: float) -> dict:
    """Prime Resurgence で交換できるレリックの中身から逆算した回(出た順)。

    {active(期間の内か), activation, expiry(UNIX 時刻か None), rows: [{month, frames, weapons}]}
    """
    bases = set().union(*(relics.get(k, set()) for k in resurgence.keys)) if resurgence.keys else set()
    rows = [_release_names(rel, names) for rel in releases
            if any(item_key(n) in bases for k in PRIME_RELEASE_LISTS for n in rel[k])]
    return {"active": resurgence.active(now), "activation": resurgence.activation, "expiry": resurgence.expiry,
            "rows": rows}


def order_mark(frame: str, releases: list[dict], today: date) -> str:
    """フレームが Prime 化したか(PRIME_MARKS)。Prime の回が no_relic なら locked"""
    prime = item_key(f"{frame} {PRIME_WORD}")
    for rel in releases:
        if prime in {item_key(n) for n in rel["frames"]} and months_since(rel["month"], today) >= 0:
            return _LOCKED if rel["no_relic"] else _DONE
    return _NONE


def order_rows(order: list[dict], releases: list[dict], today: date, names: Names) -> list[dict]:
    """実装順の小窓の行(並びのまま)。行: {no, frame: {en, ja}, mark(PRIME_MARKS)}"""
    return [{"no": row["no"], "frame": _named(names, row["frame"]), "mark": order_mark(row["frame"], releases, today)}
            for row in order]


def unknown_names(releases: list[dict], order: list[dict], names: Names) -> list[str]:
    """名前辞書(names.json)に無い名前(知らせるだけ。消さない)。出てくる順・重複なし"""
    found = [n for rel in releases for k in PRIME_RELEASE_LISTS for n in rel[k]] + [r["frame"] for r in order]
    return [n for n in dict.fromkeys(found) if not names.has(n)]


def primes_view(release_raw: object, order_raw: object, *, relics: dict, vault: Vault, resurgence: Resurgence,
                names: Names, names_loaded: bool, today: date, now: float) -> dict:
    """ページの中身。{months(ゲージのマスの数), as_of, gauge, resurgence, order, ready(Vault の判定ができたか), unknown}"""
    releases, order = load_releases(release_raw), load_order(order_raw)
    as_of = _text(release_raw.get("as_of")) if isinstance(release_raw, dict) else ""
    return {"months": PRIME_MONTHS, "as_of": as_of, "ready": vault.ready,
            "gauge": gauge_rows(releases, today, relics["parts"], vault, names),
            "resurgence": resurgence_rows(releases, resurgence, relics["relics"], names, now),
            "order": order_rows(order, releases, today, names),
            "unknown": unknown_names(releases, order, names) if names_loaded else []}


# ---- 検査(テスト用) ----

def _check_release(row: object, where: str, seen: set[str], last: str) -> list[str]:
    """回の1行の検査。seen は出た名前のキー(足していく)、last は前の行の月"""
    if not isinstance(row, dict):
        return [f"{where}: オブジェクトではない"]
    problems = [f"{where}: 知らない項目 {k}" for k in row if k not in ("month", "no_relic", *PRIME_RELEASE_LISTS)]
    month = _text(row.get("month"))
    if not re.match(PRIME_MONTH_RE, month):
        problems.append(f"{where}: month が YYYY-MM ではない")
    elif last and month < last:
        problems.append(f"{where}: month が前の行より前")
    for key in PRIME_RELEASE_LISTS:
        value = row.get(key)
        if (key != "others" or value is not None) and (not isinstance(value, list) or len(_str_list(value)) != len(value)):
            problems.append(f"{where}: {key} は名前の配列")
    for name in (n for k in PRIME_RELEASE_LISTS for n in _str_list(row.get(k))):
        if not name.endswith(f" {PRIME_WORD}"):
            problems.append(f"{where}: {name} が Prime で終わらない")
        if item_key(name) in seen:
            problems.append(f"{where}: {name} が2回出ている")
        seen.add(item_key(name))
    if "no_relic" in row and not isinstance(row["no_relic"], bool):
        problems.append(f"{where}: no_relic は true / false")
    return problems


def _check_order(rows: object) -> list[str]:
    if not isinstance(rows, list) or not rows:
        return ["frame_order: frames が無い"]
    problems: list[str] = []
    seen: set[str] = set()
    last = 0
    for i, row in enumerate(rows, 1):
        no = row.get("no") if isinstance(row, dict) else None
        frame = _text(row.get("frame")) if isinstance(row, dict) else ""
        if not isinstance(no, int) or isinstance(no, bool) or not frame:
            problems.append(f"frame_order {i}件目: no(整数)と frame が要る")
            continue
        if no < last:
            problems.append(f"frame_order {i}件目({frame}): no が前の行より小さい")
        if frame.endswith(f" {PRIME_WORD}") or item_key(frame) in seen:
            problems.append(f"frame_order {i}件目({frame}): Prime 付き・重複の名前")
        seen.add(item_key(frame))
        last = no
    return problems


def check_primes(release_raw: object, order_raw: object) -> list[str]:
    """同梱データの検査。見つかった問題の一覧(無ければ空)。名前辞書に無い名前は見ない(unknown_names)"""
    rows = release_raw.get("releases") if isinstance(release_raw, dict) else None
    if not isinstance(rows, list) or not rows:
        return ["release: releases が無い"] + _check_order(order_raw.get("frames") if isinstance(order_raw, dict) else None)
    problems: list[str] = []
    seen: set[str] = set()
    last = ""
    for i, row in enumerate(rows, 1):
        problems += _check_release(row, f"release {i}件目", seen, last)
        last = _text(row.get("month")) if isinstance(row, dict) else last
    order = order_raw.get("frames") if isinstance(order_raw, dict) else None
    return problems + _check_order(order) + _check_frames_in_order(load_releases(release_raw), load_order(order_raw))


def _check_frames_in_order(releases: list[dict], order: list[dict]) -> list[str]:
    """回のフレーム(「〜 Prime」)の元の名前が実装順にあるか(綴りの誤りを見つける)"""
    bases = {item_key(r["frame"]) for r in order}
    return [f"release: {name} の元のフレームが frame_order に無い" for rel in releases for name in rel["frames"]
            if name.endswith(f" {PRIME_WORD}") and item_key(name[:-len(PRIME_WORD) - 1]) not in bases]
