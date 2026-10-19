"""画面向け API: Tips(tips フォルダのメモを表示する。ファイルを直接編集すると内容が変わる)"""
from __future__ import annotations

import csv
import io
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

from wfp.api.store import ApiError, Raw, mtime_jst
from wfp.core import common


TIPS_KINDS = {".md": "md", ".markdown": "md", ".txt": "txt", ".csv": "csv"}


TIPS_MAX_BYTES = 2 * 1024 * 1024


_TIPS_PREFIX = re.compile(r"^\d+[\s._\-]*")


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


def tips_list(root: Path) -> dict:
    """目次: tips 直下のファイルと、1段下のフォルダ(目次の見出しになる)のファイル"""
    items = []
    if root.is_dir():
        files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in TIPS_KINDS
                 and not p.name.startswith((".", "~$")) and len(p.relative_to(root).parts) <= 2]
        files.sort(key=lambda p: [_natural(x) for x in p.relative_to(root).parts])
        for p in files:
            parts = p.relative_to(root).parts
            items.append({"path": "/".join(parts), "title": _tip_title(p),
                          "group": _tips_label(parts[0]) if len(parts) == 2 else "",
                          "kind": TIPS_KINDS[p.suffix.lower()]})
    return {"dir": str(root), "exists": root.is_dir(), "items": items}


def tip_path(root: Path, rel: str) -> Path | None:
    """tips フォルダの中にあるファイルだけを返す(../ などで外に出られないようにする)"""
    if not rel or "\x00" in rel:
        return None
    try:
        base = root.resolve()
        p = (base / rel).resolve()
    except (OSError, ValueError):
        return None
    return p if base in p.parents and p.is_file() else None


def tip_file(root: Path, rel: str) -> dict:
    p = tip_path(root, rel)
    if p is None or p.suffix.lower() not in TIPS_KINDS:
        raise ApiError("メモが見つかりません。目次を読み込み直してください。", 404)
    text = _read_tip_text(p)
    kind = TIPS_KINDS[p.suffix.lower()]
    out = {"path": rel, "title": _tip_title(p, text), "kind": kind, "updated": mtime_jst(p)}
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
    ("GET", "/tips/"): lambda c: tip_image(c.tips, unquote(c.path[len("/tips/"):])),
}
