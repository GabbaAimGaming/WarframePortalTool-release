"""画面(HTML)の組み立て: web/ctrl.html(基礎部)に menu.html(メニュー部)と view.html(表示部)を差し込んで1枚にする

- ctrl.html の中の、行全体が `<!-- INCLUDE:ファイル名#部品名 -->` の行を、その部品の中身で置き換える
- 部品は、差し込まれる側のファイルの中で `<!-- PART:部品名 -->` の行から、次の PART の行(か最後)までの行。
  最初の PART より前はファイルの説明として使え、出力には入らない
- 差し込めるのは UI_FILES のファイルだけ(web/ の外や、ほかのファイルは読まない)。入れ子の差し込みはしない
- 目印の誤り(知らないファイル・無い部品・使われない部品)は PageError にする(画面が半端に表示されないように)
"""
from __future__ import annotations

import re
from pathlib import Path

from wfp.core import common

BASE = "ctrl.html"
UI_FILES = ("ctrl.html", "menu.html", "view.html")  # 読む順: 基礎部 → メニュー部 → 表示部
INCLUDE = re.compile(r"^[ \t]*<!-- INCLUDE:([\w.-]+)#(\w+) -->[ \t]*$")
PART = re.compile(r"^[ \t]*<!-- PART:(\w+) -->[ \t]*$")


class PageError(Exception):
    """画面の HTML を組み立てられない(目印の誤り)"""


def web_dir() -> Path:
    return common.APP_DIR / "web"


def split_parts(text: str, name: str) -> dict[str, str]:
    """ファイルを部品に分ける。{部品名: 中身(行末の改行を含む)}"""
    parts: dict[str, list[str]] = {}
    cur = None
    for line in text.splitlines(keepends=True):
        m = PART.match(line.rstrip("\n"))
        if m:
            cur = m.group(1)
            if cur in parts:
                raise PageError(f"{name}: 部品 {cur} が2つあります")
            parts[cur] = []
        elif cur is not None:
            parts[cur].append(line)
    return {k: "".join(v) for k, v in parts.items()}


def assemble(texts: dict[str, str]) -> str:
    """{ファイル名: 中身} から1枚の HTML を作る(ファイルを読まないので、テストからも使える)"""
    parts = {n: split_parts(t, n) for n, t in texts.items() if n != BASE}
    used = set()
    out = []
    for line in texts[BASE].splitlines(keepends=True):
        m = INCLUDE.match(line.rstrip("\n"))
        if not m:
            out.append(line)
            continue
        fname, part = m.groups()
        if fname not in parts:
            raise PageError(f"{BASE}: 差し込めないファイルです: {fname}")
        if part not in parts[fname]:
            raise PageError(f"{fname} に部品 {part} がありません")
        out.append(parts[fname][part])
        used.add((fname, part))
    unused = sorted(f"{n}#{p}" for n, ps in parts.items() for p in ps if (n, p) not in used)
    if unused:
        raise PageError("使われていない部品があります: " + ", ".join(unused))
    return "".join(out)


def read_ui(folder: Path | None = None) -> dict[str, str]:
    folder = folder or web_dir()
    return {n: (folder / n).read_text(encoding="utf-8") for n in UI_FILES}


def ui_html(folder: Path | None = None) -> bytes:
    """メイン画面の HTML(毎回ファイルから組み立てる。編集がすぐ反映される)"""
    return assemble(read_ui(folder)).encode("utf-8")
