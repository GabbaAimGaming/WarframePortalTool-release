"""画面向け API: Tips(tips フォルダのメモを表示・編集する。ファイルを直接編集しても内容が変わる)

画面からの書き込み: 新規・編集(.md のみ)・グループ追加・ゴミ箱(tips/_trash/)・完全削除・並び順(tips/_order.json)。
目次から外すのは名前が一致する _trash と _order.json だけ(利用者の「_メモ.md」などは出す)。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from wfp.api.store import JST, ApiError, Raw, mtime_jst
from wfp.core import common


TIPS_KINDS = {".md": "md", ".markdown": "md", ".txt": "txt", ".csv": "csv"}


TIPS_MAX_BYTES = 2 * 1024 * 1024


_TIPS_PREFIX = re.compile(r"^\d+[\s._\-]*")


TIPS_TRASH = "_trash"            # ゴミ箱(tips/_trash/)。目次には出さない
TIPS_ORDER = "_order.json"       # 並び順(tips/_order.json)
TIPS_TRASH_INDEX = "_index.json"  # ゴミ箱の元の場所・日時・タイトル(tips/_trash/_index.json)
TIPS_EDIT_MAX_BYTES = 900 * 1024  # 画面で編集できる大きさ(読み込みは TIPS_MAX_BYTES で切る・本文は 1MB 上限のため)
TIPS_NAME_MAX = 80               # ファイル名・グループ名の長さ(拡張子・重複番号を除く)
TIPS_EDIT_KINDS = ("md",)        # 画面で新規・編集できる形式
_TIPS_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_TIPS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_TIPS_LOCK = threading.Lock()    # 画面サーバーは複数スレッドで動くので、書き込みは1つずつ


def tips_root() -> Path:
    return common.APP_DIR / "tips"


def _natural(s: str) -> list:
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", s)]


def _tips_label(stem: str) -> str:
    """ファイル名・フォルダ名から表示名を作る(先頭の並び順用の数字は外す)"""
    return (_TIPS_PREFIX.sub("", stem) or stem).replace("_", " ").strip()


def _read_tip_text(p: Path) -> str:
    data = p.read_bytes()[:TIPS_MAX_BYTES]
    for enc in ("utf-8-sig", "cp932"):  # メモ帳は UTF-8、Excel の CSV は Shift_JIS(cp932)で保存されることが多い
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _tip_title(p: Path, text: str | None = None) -> str:
    if TIPS_KINDS.get(p.suffix.lower()) == "md":
        try:
            for line in (text if text is not None else _read_tip_text(p)).splitlines()[:30]:
                if m := re.match(r"^#\s+(.+?)\s*#*\s*$", line):
                    return m.group(1)
        except OSError:
            pass
    return _tips_label(p.stem)


def _is_tip_file(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in TIPS_KINDS and not p.name.startswith((".", "~$"))


def _is_group_dir(p: Path) -> bool:
    """目次のグループになるフォルダ(tips 直下の1段目。ゴミ箱と隠しフォルダは除く)"""
    return p.is_dir() and p.name.lower() != TIPS_TRASH and not p.name.startswith((".", "~$"))


def _read_order(root: Path) -> dict:
    """並び順(_order.json)。無い・壊れているときは空(ファイル名の番号順になる)"""
    try:
        data = json.loads((root / TIPS_ORDER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"top": [], "groups": {}}
    if not isinstance(data, dict):
        return {"top": [], "groups": {}}
    top = data.get("top")
    groups = data.get("groups")
    return {"top": [x for x in top if isinstance(x, str)] if isinstance(top, list) else [],
            "groups": {k: [x for x in v if isinstance(x, str)] for k, v in groups.items()
                       if isinstance(k, str) and isinstance(v, list)} if isinstance(groups, dict) else {}}


def _ordered(names: list[str], listed: list[str]) -> list[str]:
    """_order.json に載っている順 → 載っていないものは末尾に自然順"""
    have = set(names)
    head = list(dict.fromkeys(x for x in listed if x in have))
    done = set(head)
    return head + sorted((x for x in names if x not in done), key=_natural)


def tips_list(root: Path) -> dict:
    """目次: tips 直下のファイルと、1段下のフォルダ(目次の見出しになる)のファイル

    toc: 直下のメモとグループの並び(グループは中身つき・空のグループも出す)。
    items: toc を平らにした一覧(最終の並び順。画面のリンク判定などが使う)。
    order: 保存してある並び順(_order.json)。画面は動かした一覧だけを差し替えて送る(ほかのグループの番号順を固定しないため)。
    """
    toc, items, order = [], [], {"top": [], "groups": {}}
    if root.is_dir():
        order = _read_order(root)
        entries = {}  # 並び順のキー(ファイル名 / "グループ名/")→ 実体
        for p in root.iterdir():
            if _is_tip_file(p):
                entries[p.name] = p
            elif _is_group_dir(p):
                entries[p.name + "/"] = p
        for key in _ordered(list(entries), order["top"]):
            p = entries[key]
            if key.endswith("/"):
                files = {f.name: f for f in p.iterdir() if _is_tip_file(f)}
                label = _tips_label(p.name)
                sub = [_toc_item(files[n], f"{p.name}/{n}", label) for n in _ordered(list(files), order["groups"].get(p.name, []))]
                toc.append({"type": "group", "name": p.name, "label": label, "items": sub})
                items.extend(sub)
            else:
                it = _toc_item(p, p.name, "")
                toc.append({"type": "tip", **it})
                items.append(it)
    return {"dir": str(root), "exists": root.is_dir(), "items": items, "toc": toc, "order": order}


def _toc_item(p: Path, rel: str, group: str) -> dict:
    return {"path": rel, "title": _tip_title(p), "group": group, "kind": TIPS_KINDS[p.suffix.lower()]}


def _in_trash(base: Path, p: Path) -> bool:
    rel = p.relative_to(base).parts
    return bool(rel) and rel[0].lower() == TIPS_TRASH


def tip_path(root: Path, rel: str) -> Path | None:
    """tips フォルダの中にあるファイルだけを返す(../ などで外に出られないようにする。ゴミ箱の中は除く)"""
    if not rel or "\x00" in rel:
        return None
    try:
        base = root.resolve()
        p = (base / rel).resolve()
    except (OSError, ValueError):
        return None
    return p if base in p.parents and p.is_file() and not _in_trash(base, p) else None


def _rev(p: Path) -> str:
    """外部での変更を見分ける版(更新時刻のナノ秒。JS の数値では桁が足りないので文字列)"""
    return str(p.stat().st_mtime_ns)


def tip_file(root: Path, rel: str) -> dict:
    p = tip_path(root, rel)
    if p is None or p.suffix.lower() not in TIPS_KINDS:
        raise ApiError(common.txt("err.tips.missing"), 404)
    text = _read_tip_text(p)
    kind = TIPS_KINDS[p.suffix.lower()]
    out = {"path": rel, "title": _tip_title(p, text), "kind": kind, "updated": mtime_jst(p),
           "rev": _rev(p), "editable": kind in TIPS_EDIT_KINDS and p.stat().st_size <= TIPS_EDIT_MAX_BYTES}
    if kind == "csv":
        sample = text[:4096]
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim)]
        while rows and not any(c.strip() for c in rows[-1]):
            rows.pop()
        out["rows"] = rows
    else:
        out["text"] = text
    return out


# ---- 画面からの書き込み(新規・編集・グループ追加・ゴミ箱・完全削除・並び順) ----

def tip_name(raw: str, default: str) -> str:
    """タイトルからファイル名・グループ名(拡張子なし)を作る

    Windows で使えない文字・制御文字は _ に置き換え、前後の空白と末尾の . を除く。
    先頭の _ . ~$ は除く(付くと目次から消える・ゴミ箱と紛れるため)。予約名(CON など)は _ を足して避ける。
    """
    s, prev = _TIPS_BAD_CHARS.sub("_", raw or ""), None
    while s != prev:
        prev = s
        s = s[:TIPS_NAME_MAX].strip().rstrip(".")
        s = s[2:] if s.startswith("~$") else s[1:] if s.startswith(("_", ".")) else s
    if not s:
        return default
    head, dot, tail = s.partition(".")
    if head.strip().upper() in _TIPS_RESERVED:
        s = head.rstrip() + "_" + dot + tail
    return s


def _unique(d: Path, base: str, ext: str) -> str:
    """d の中で重ならない名前(「名前 (2)」「名前 (3)」…。大文字小文字の違いも重なりとみなす)"""
    have = {n.lower() for n in os.listdir(d)} if d.is_dir() else set()
    name, n = base + ext, 1
    while name.lower() in have:
        n += 1
        name = f"{base} ({n}){ext}"
    return name


def _write_text(p: Path, text: str) -> None:
    """一時ファイルに書いてから置き換える(途中で止まっても元のファイルが壊れない)。UTF-8 で保存"""
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".wfp-", suffix=".tmp")  # 先頭の . で目次には出ない
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _Writing:
    """書き込みの失敗を画面向けの文言にする(PermissionError はほかのアプリで開いているときに多い)"""

    def __init__(self, failed):
        self.failed = failed  # 文字列(日本語)か、テキスト指定(画面が表示中の言語で出す。メモの保存だけ)

    def __enter__(self):
        return self

    def __exit__(self, et, e, tb):
        text = not isinstance(self.failed, str)
        if et is not None and issubclass(et, PermissionError):
            raise ApiError(common.txt("err.tips.locked", what=self.failed) if text else
                           f"{self.failed}。ファイルがほかのアプリで開かれていないか、書き込みが許可されているか確認してください。", 423) from e
        if et is not None and issubclass(et, OSError):
            raise ApiError(common.txt("err.tips.write", what=self.failed, e=str(e)) if text else f"{self.failed}: {e}", 500) from e
        return False


def _obj(body) -> dict:
    if not isinstance(body, dict):
        raise ApiError("リクエストの形式が正しくありません。")
    return body


def _str(body: dict, key: str) -> str:
    v = body.get(key) or ""
    if not isinstance(v, str):
        raise ApiError(f"{key} は文字列で指定してください。")
    return v


def _check_size(text: str) -> None:
    if len(text.encode("utf-8")) > TIPS_EDIT_MAX_BYTES:
        raise ApiError(common.txt("err.tips.large", kb=str(TIPS_EDIT_MAX_BYTES // 1024)), 413)


def _group_dir(root: Path, group: str) -> Path | None:
    """tips 直下のグループのフォルダ(名前だけを受け付ける。../ やゴミ箱は不可)"""
    if not group or "/" in group or "\\" in group or group in (".", "..") or "\x00" in group:
        return None
    p = root / group
    return p if _is_group_dir(p) else None


def save_tip(root: Path, body) -> dict:
    """メモを保存する。path があれば上書き(rev で外部の変更を検知)、無ければ新規(title と group から作る)

    新規: ファイル名はタイトルから作り、本文の先頭に「# タイトル」を入れる。
    編集: 見出しを変えてもファイル名は変えない(ほかのメモからのリンクを切らないため)。
    """
    body = _obj(body)
    text, rel = body.get("text"), _str(body, "path")
    if not isinstance(text, str):
        raise ApiError("text は文字列で指定してください。")
    with _TIPS_LOCK, _Writing(common.txt("err.tips.save")):
        if rel:
            p = tip_path(root, rel)
            if p is None:
                raise ApiError(common.txt("err.tips.missing"), 404)
            if TIPS_KINDS.get(p.suffix.lower()) not in TIPS_EDIT_KINDS or p.stat().st_size > TIPS_EDIT_MAX_BYTES:
                raise ApiError(common.txt("err.tips.editable", kb=str(TIPS_EDIT_MAX_BYTES // 1024)))
            if _str(body, "rev") != _rev(p):
                raise ApiError(common.txt("err.tips.changed"), 409)
            _check_size(text)
            _write_text(p, text)
        else:
            title = " ".join(_str(body, "title").split())
            if not title:
                raise ApiError(common.txt("err.tips.title"))
            group = _str(body, "group")
            d = _group_dir(root, group) if group else root
            if d is None:
                raise ApiError(common.txt("err.tips.group"), 404)
            text = f"# {title}\n\n{text.lstrip(chr(10))}"
            _check_size(text)
            root.mkdir(parents=True, exist_ok=True)
            name = _unique(d, tip_name(title, "メモ"), ".md")
            _write_text(d / name, text)
            rel = f"{group}/{name}" if group else name
    return tip_file(root, rel)


def add_group(root: Path, body) -> dict:
    """グループ(tips 直下のフォルダ)を足す。名前の変更・削除は画面からはしない(リンクが切れるため)"""
    name = tip_name(_str(_obj(body), "name"), "グループ")
    with _TIPS_LOCK, _Writing("グループを追加できませんでした"):
        root.mkdir(parents=True, exist_ok=True)
        name = _unique(root, name, "")
        (root / name).mkdir()
    return {"group": name}


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root.resolve()).as_posix()


def _drop_order(root: Path, rel: str) -> None:
    """並び順から消す(ゴミ箱・完全削除のとき。元に戻したメモは末尾に並ぶ)"""
    if not (root / TIPS_ORDER).exists():
        return
    order, parts = _read_order(root), rel.split("/")
    lst = order["top"] if len(parts) == 1 else order["groups"].get(parts[0], [])
    if parts[-1] in lst:
        lst.remove(parts[-1])
        _write_text(root / TIPS_ORDER, json.dumps(order, ensure_ascii=False, indent=1))


def _trash_index(td: Path) -> list[dict]:
    try:
        data = json.loads((td / TIPS_TRASH_INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    keys = ("id", "path", "title", "trashed")
    return [e for e in data if isinstance(e, dict) and all(isinstance(e.get(k), str) for k in keys)] \
        if isinstance(data, list) else []


def _save_trash_index(td: Path, entries: list[dict]) -> None:
    _write_text(td / TIPS_TRASH_INDEX, json.dumps(entries, ensure_ascii=False, indent=1))


def _trash_item(root: Path, tid) -> Path:
    """ゴミ箱の中のメモ(名前だけを受け付ける)"""
    td = root / TIPS_TRASH
    ok = isinstance(tid, str) and tid and "/" not in tid and "\\" not in tid and "\x00" not in tid \
        and not tid.startswith(".") and tid != TIPS_TRASH_INDEX
    p = td / tid if ok else None
    if p is None or not p.is_file() or p.suffix.lower() not in TIPS_KINDS:
        raise ApiError(common.txt("err.tips.trashmissing"), 404)
    return p


def trash_tip(root: Path, body) -> dict:
    """メモをゴミ箱(tips/_trash/)へ移す。元の場所・日時・タイトルは _index.json に残す"""
    rel = _str(_obj(body), "path")
    with _TIPS_LOCK, _Writing(common.txt("err.tips.trashmove")):
        p = tip_path(root, rel)
        if p is None or p.suffix.lower() not in TIPS_KINDS:
            raise ApiError(common.txt("err.tips.missing"), 404)
        rel, title = _rel(root, p), _tip_title(p)
        td = root / TIPS_TRASH
        td.mkdir(exist_ok=True)
        tid = _unique(td, p.stem, p.suffix)
        os.replace(p, td / tid)
        entries = _trash_index(td)
        entries.append({"id": tid, "path": rel, "title": title,
                        "trashed": datetime.now(JST).strftime("%Y-%m-%d %H:%M")})
        _save_trash_index(td, entries)
        _drop_order(root, rel)
    return {"id": tid}


def trash_list(root: Path) -> dict:
    """ゴミ箱の一覧(新しい順)。_index.json に無いファイルも出す(元の場所は tips 直下とみなす)"""
    td = root / TIPS_TRASH
    if not td.is_dir():
        return {"items": []}
    files = {p.name: p for p in td.iterdir() if _is_tip_file(p)}
    known = {e["id"]: e for e in _trash_index(td) if e["id"] in files}
    items = [known.get(n) or {"id": n, "path": n, "title": _tip_title(p), "trashed": mtime_jst(p) or ""}
             for n, p in files.items()]
    items.sort(key=lambda e: (e["trashed"], e["id"]), reverse=True)
    return {"items": items}


def restore_tip(root: Path, body) -> dict:
    """ゴミ箱から元の場所へ戻す。元のグループが無ければ作り直す。同じ名前があれば「名前 (2)」"""
    tid = _obj(body).get("id")
    with _TIPS_LOCK, _Writing(common.txt("err.tips.restore")):
        src = _trash_item(root, tid)
        td = src.parent
        entries = _trash_index(td)
        orig = next((e["path"] for e in entries if e["id"] == tid), tid).split("/")
        name = orig[-1] if orig[-1] and orig[-1] not in (".", "..") and "\\" not in orig[-1] else tid
        d = root
        if len(orig) == 2 and _group_name_ok(orig[0]) and not (root / orig[0]).is_file():
            d = root / orig[0]
            d.mkdir(exist_ok=True)
        new = _unique(d, Path(name).stem, Path(name).suffix)
        os.replace(src, d / new)
        _save_trash_index(td, [e for e in entries if e["id"] != tid])
    return {"path": new if d == root else f"{d.name}/{new}"}


def _group_name_ok(name: str) -> bool:
    return bool(name) and name not in (".", "..") and "\\" not in name and "\x00" not in name \
        and name.lower() != TIPS_TRASH and not name.startswith((".", "~$"))


def purge_tip(root: Path, body) -> dict:
    """完全に消す。id ならゴミ箱の中、path なら目次のメモ。メモに貼った画像は残す"""
    body = _obj(body)
    with _TIPS_LOCK, _Writing(common.txt("err.tips.purge")):
        if "id" in body:
            p = _trash_item(root, body.get("id"))
            p.unlink()
            _save_trash_index(p.parent, [e for e in _trash_index(p.parent) if e["id"] != p.name])
            return {"ok": True}
        rel = _str(body, "path")
        p = tip_path(root, rel)
        if p is None or p.suffix.lower() not in TIPS_KINDS:
            raise ApiError(common.txt("err.tips.missing"), 404)
        rel = _rel(root, p)
        p.unlink()
        _drop_order(root, rel)
    return {"ok": True}


def set_order(root: Path, body) -> dict:
    """並び順を保存する(tips/_order.json)。形: {"top": ["a.md", "20_ビルド/", ...], "groups": {"20_ビルド": ["x.md", ...]}}

    グループは塊で動き、グループの中のメモはそのグループの中だけで動く。無くなったものは保存しない。返り値は新しい目次。
    """
    body = _obj(body)
    top, groups = body.get("top", []), body.get("groups", {})
    if not (isinstance(top, list) and all(isinstance(x, str) for x in top) and isinstance(groups, dict)
            and all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in groups.values())):
        raise ApiError("並び順の形式が正しくありません。")
    with _TIPS_LOCK, _Writing("並び順を保存できませんでした"):
        if not root.is_dir():
            raise ApiError("tips フォルダがありません。", 404)
        have = {p.name: p for p in root.iterdir()}
        out_top = [x for x in dict.fromkeys(top)
                   if (x.endswith("/") and _group_dir(root, x[:-1]) is not None) or (x in have and _is_tip_file(have[x]))]
        out_groups = {}
        for g, names in groups.items():
            gd = _group_dir(root, g)
            if gd is not None:
                out_groups[g] = [x for x in dict.fromkeys(names) if "/" not in x and "\\" not in x and _is_tip_file(gd / x)]
        _write_text(root / TIPS_ORDER, json.dumps({"top": out_top, "groups": out_groups}, ensure_ascii=False, indent=1))
    return tips_list(root)


def open_tips_folder(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(root))  # noqa: S606 (エクスプローラーで開く)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(root)])
        else:
            subprocess.Popen(["xdg-open", str(root)])
    except OSError as e:
        raise ApiError(f"フォルダを開けませんでした: {e}", 500)
    return {"dir": str(root)}


TIPS_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


def tip_image(root: Path, rel: str) -> Raw:
    """Tips のメモに貼った画像 (tips フォルダの中の画像だけ)"""
    p = tip_path(root, rel)
    if p is None or p.suffix.lower() not in TIPS_IMAGE_MIME:
        raise ApiError("画像が見つかりません。", 404)
    return Raw(p.read_bytes(), TIPS_IMAGE_MIME[p.suffix.lower()])


# (メソッド, パス) -> 処理。c はリクエスト(wfp/api/server.py の Request)。パスが / で終わるものは前方一致
ROUTES = {
    ("GET", "/api/tips"): lambda c: tips_list(c.tips),
    ("GET", "/api/tips/file"): lambda c: tip_file(c.tips, c.q.get("path", "")),
    ("POST", "/api/tips/open"): lambda c: c.empty_body() or open_tips_folder(c.tips),
    ("POST", "/api/tips/save"): lambda c: save_tip(c.tips, c.body()),
    ("POST", "/api/tips/group"): lambda c: add_group(c.tips, c.body()),
    ("GET", "/api/tips/trash"): lambda c: trash_list(c.tips),
    ("POST", "/api/tips/trash"): lambda c: trash_tip(c.tips, c.body()),
    ("POST", "/api/tips/restore"): lambda c: restore_tip(c.tips, c.body()),
    ("POST", "/api/tips/purge"): lambda c: purge_tip(c.tips, c.body()),
    ("POST", "/api/tips/order"): lambda c: set_order(c.tips, c.body()),
    ("GET", "/tips/"): lambda c: tip_image(c.tips, unquote(c.path[len("/tips/"):])),
}
