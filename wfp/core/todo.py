"""ToDo: デイリー・ウィークリーの完了をチェックする、利用者が自由に作る一覧(利用者データの todo)

- 項目は {"id", "name", "kind"(TODO_KINDS), "done_at"(チェックした時刻。ISO 8601 の UTC か None)}。並びは保存の順
- 完了かどうかは保存しない。「最後のリセットより後にチェックしたか」で決める(リセットを過ぎれば何もしなくても未完了に戻る)
  - daily: 毎日 0:00 UTC / weekly: 月曜 0:00 UTC(サイクルの next_daily_reset / next_weekly_reset と同じ)
  - long(ロングタスク): 戻らない(チェックしてあれば完了。リセットの時刻は None)
- 変える関数(add_item など)は一覧をその場で変える(呼ぶ側は userdata.editing の中で使う)。入力の誤りは TodoError、
  無い id は TodoNotFound(どちらもテキスト指定)
- 最初から入れておく項目は無い(利用者が作る)
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from wfp.core.const import TODO_FLOAT_KINDS, TODO_ID_BYTES, TODO_KINDS, TODO_MAX, TODO_NAME_MAX
from wfp.core.cycle import next_daily_reset, next_weekly_reset
from wfp.core.errors import TextError
from wfp.core.i18n import txt

# リセットのある種類 -> (次のリセットの時刻を求める関数, 1回の長さ)。ここに無い種類(long)は未完了に戻らない
_RESETS = {"daily": (next_daily_reset, timedelta(days=1)), "weekly": (next_weekly_reset, timedelta(days=7))}


class TodoError(TextError):
    """ToDo の入力の誤り(名前が空・長すぎる・種類が違う・数が多すぎる)"""


class TodoNotFound(TodoError):
    """指定の id の項目が無い"""


def next_reset(kind: str, now: datetime) -> datetime | None:
    """次に未完了に戻る時刻(UTC)。戻らない種類(long)は None"""
    if kind not in _RESETS:
        return None
    return _RESETS[kind][0](now)


def last_reset(kind: str, now: datetime) -> datetime | None:
    """最後に未完了に戻った時刻(UTC)。この時刻より後のチェックが「完了」。戻らない種類(long)は None"""
    nxt = next_reset(kind, now)
    return None if nxt is None else nxt - _RESETS[kind][1]


def _parse_time(text) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        t = datetime.fromisoformat(text)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def clean_items(raw) -> list[dict]:
    """保存の中身を確かめる(読むときに使う)。形の悪い項目・同じ id の2件目は黙って外す。読めない done_at は None"""
    out, seen = [], set()
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict):
            continue
        item_id, name, kind = it.get("id"), it.get("name"), it.get("kind")
        if not isinstance(item_id, str) or not item_id or item_id in seen or not isinstance(name, str) or kind not in TODO_KINDS:
            continue
        seen.add(item_id)
        done_at = it.get("done_at") if _parse_time(it.get("done_at")) else None
        out.append({"id": item_id, "name": name, "kind": kind, "done_at": done_at})
    return out


def is_done(item: dict, now: datetime) -> bool:
    t = _parse_time(item.get("done_at"))
    if t is None:
        return False
    since = last_reset(item["kind"], now)
    return since is None or t >= since


def todo_view(items: list[dict], now: datetime) -> dict:
    """画面に渡す形: 項目(完了かどうか付き。done_at は渡さない)・種類・小窓に出す種類・
    リセットのある種類ごとの次のリセット(UNIX 秒。long は入れない)・今(UNIX 秒)"""
    rows = [{"id": it["id"], "name": it["name"], "kind": it["kind"], "done": is_done(it, now)} for it in items]
    resets = {k: next_reset(k, now) for k in TODO_KINDS}
    return {"items": rows, "kinds": list(TODO_KINDS), "float_kinds": list(TODO_FLOAT_KINDS), "now": now.timestamp(),
            "resets": {k: t.timestamp() for k, t in resets.items() if t is not None},
            "name_max": TODO_NAME_MAX, "max": TODO_MAX}


def _clean_name(name) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise TodoError(txt("err.todo.name"))
    if len(text) > TODO_NAME_MAX:
        raise TodoError(txt("err.todo.long", n=str(TODO_NAME_MAX)))
    return text


def _clean_kind(kind) -> str:
    if kind not in TODO_KINDS:
        raise TodoError(txt("err.todo.kind", name=str(kind)))
    return kind


def _find(items: list[dict], item_id) -> int:
    for i, it in enumerate(items):
        if it["id"] == item_id:
            return i
    raise TodoNotFound(txt("err.todo.unknown", id=str(item_id)))


def _new_id(items: list[dict]) -> str:
    used = {it["id"] for it in items}
    while True:
        item_id = secrets.token_hex(TODO_ID_BYTES)
        if item_id not in used:
            return item_id


def add_item(items: list[dict], name, kind) -> dict:
    """末尾に足す(未完了)。足した項目を返す"""
    if len(items) >= TODO_MAX:
        raise TodoError(txt("err.todo.full", n=str(TODO_MAX)))
    item = {"id": _new_id(items), "name": _clean_name(name), "kind": _clean_kind(kind), "done_at": None}
    items.append(item)
    return item


def edit_item(items: list[dict], item_id, name=None, kind=None) -> dict:
    """名前・種類を変える(None は変えない)。種類を変えたら未完了に戻す(前の種類のリセットで数えたチェックなので)"""
    item = items[_find(items, item_id)]
    if name is not None:
        item["name"] = _clean_name(name)
    if kind is not None and _clean_kind(kind) != item["kind"]:
        item["kind"], item["done_at"] = kind, None
    return item


def delete_item(items: list[dict], item_id) -> None:
    del items[_find(items, item_id)]


def move_item(items: list[dict], item_id, step) -> None:
    """同じ種類の中で、前(step < 0)か後ろ(step > 0)の項目と入れ替える。端なら何もしない"""
    pos = _find(items, item_id)
    kind = items[pos]["kind"]
    same = [i for i, it in enumerate(items) if it["kind"] == kind]
    at = same.index(pos) + (-1 if int(step) < 0 else 1)
    if 0 <= at < len(same):
        other = same[at]
        items[pos], items[other] = items[other], items[pos]


def check_item(items: list[dict], item_id, done: bool, now: datetime) -> None:
    """完了(今の時刻を覚える)か未完了(時刻を消す)にする"""
    item = items[_find(items, item_id)]
    item["done_at"] = now.astimezone(timezone.utc).isoformat(timespec="seconds") if done else None
