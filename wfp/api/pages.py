"""画面(HTML)の組み立て: web/ctrl.html(基礎部)に menu.html(メニュー部)・view.html(表示部)・i18n.html(文字を引く部品)を
差し込んで1枚にする。シミュレータ(web/wfportal_builder.html)にも i18n.html を差し込む

- ctrl.html の中の、行全体が `<!-- INCLUDE:ファイル名#部品名 -->` の行を、その部品の中身で置き換える
- 部品は、差し込まれる側のファイルの中で `<!-- PART:部品名 -->` の行から、次の PART の行(か最後)までの行。
  最初の PART より前はファイルの説明として使え、出力には入らない
- 差し込めるのは UI_FILES / BUILDER_FILES のファイルだけ(web/ の外や、ほかのファイルは読まない)。入れ子の差し込みはしない
- 目印の誤り(知らないファイル・無い部品・使われない部品)は PageError にする(画面が半端に表示されないように)
- 表示する文字は web/i18n/<言語>.json(キー → 文字)。組み立てた後、`I18N_SLOT` の箇所を
  {言語: 表} の JSON に置き換える。日本語(ja.json)は必須で先頭、ほかはファイル名の順
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from wfp.core import common

BASE = "ctrl.html"
UI_FILES = ("ctrl.html", "menu.html", "view.html", "i18n.html")  # 読む順: 基礎部 → メニュー部 → 表示部 → 文字を引く部品
BUILDER = "wfportal_builder.html"
BUILDER_FILES = (BUILDER, "i18n.html")  # シミュレータ: 本体 → 文字を引く部品
INCLUDE = re.compile(r"^[ \t]*<!-- INCLUDE:([\w.-]+)#(\w+) -->[ \t]*$")
PART = re.compile(r"^[ \t]*<!-- PART:(\w+) -->[ \t]*$")
I18N_DIR = "i18n"
I18N_BASE = "ja"  # 最後の拠り所の言語(ほかの言語に無いキーはこれで出す)
I18N_SLOT = "/* I18N:DATA */ {}"
LANG_CODE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


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


def assemble(texts: dict[str, str], base: str = BASE) -> str:
    """{ファイル名: 中身} から1枚の HTML を作る(base が土台。ファイルを読まないので、テストからも使える)"""
    parts = {n: split_parts(t, n) for n, t in texts.items() if n != base}
    used = set()
    out = []
    for line in texts[base].splitlines(keepends=True):
        m = INCLUDE.match(line.rstrip("\n"))
        if not m:
            out.append(line)
            continue
        fname, part = m.groups()
        if fname not in parts:
            raise PageError(f"{base}: 差し込めないファイルです: {fname}")
        if part not in parts[fname]:
            raise PageError(f"{fname} に部品 {part} がありません")
        out.append(parts[fname][part])
        used.add((fname, part))
    unused = sorted(f"{n}#{p}" for n, ps in parts.items() for p in ps if (n, p) not in used)
    if unused:
        raise PageError("使われていない部品があります: " + ", ".join(unused))
    return "".join(out)


def check_i18n(tables: dict) -> None:
    """言語の表の形を検査する(言語コード・日本語の有無・キーと値が空でない文字列)"""
    if I18N_BASE not in tables:
        raise PageError(f"{I18N_DIR}/{I18N_BASE}.json がありません")
    for code, table in tables.items():
        if not LANG_CODE.match(code):
            raise PageError(f"{I18N_DIR}: 言語コードの形が違います: {code}")
        if not isinstance(table, dict):
            raise PageError(f"{I18N_DIR}/{code}.json: 中身がオブジェクトではありません")
        bad = [k for k, v in table.items() if not isinstance(v, str) or not v.strip() or not k.strip()]
        if bad:
            raise PageError(f"{I18N_DIR}/{code}.json: 空か文字でない値があります: " + ", ".join(bad[:5]))


def read_i18n(folder: Path | None = None) -> dict[str, dict[str, str]]:
    """web/i18n/*.json を {言語: {キー: 文字}} で読む(日本語が先頭)。壊れていれば PageError"""
    base = (folder or web_dir()) / I18N_DIR
    files = sorted(base.glob("*.json"), key=lambda f: (f.stem != I18N_BASE, f.stem))
    tables = {}
    for f in files:
        try:
            tables[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise PageError(f"{I18N_DIR}/{f.name} が読めません: {e}") from e
    check_i18n(tables)
    return tables


def inject_i18n(html: str, tables: dict) -> str:
    """HTML の I18N_SLOT(1か所だけ)を言語の表の JSON に置き換える。
    スクリプトの中に入るので、`</` は `<\\/` にして </script> と読まれないようにする"""
    n = html.count(I18N_SLOT)
    if n != 1:
        raise PageError(f"{I18N_SLOT} の目印が {n} か所あります(1か所だけにする)")
    data = json.dumps(tables, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return html.replace(I18N_SLOT, data)


def read_ui(folder: Path | None = None, files: tuple[str, ...] = UI_FILES) -> dict[str, str]:
    folder = folder or web_dir()
    return {n: (folder / n).read_text(encoding="utf-8") for n in files}


def ui_html(folder: Path | None = None) -> bytes:
    """メイン画面の HTML(毎回ファイルから組み立て、言語の表を差し込む。編集がすぐ反映される)"""
    return inject_i18n(assemble(read_ui(folder)), read_i18n(folder)).encode("utf-8")


def builder_html(folder: Path | None = None) -> bytes:
    """シミュレータの HTML(文字を引く部品と言語の表を差し込む。毎回ファイルから組み立てる)"""
    return inject_i18n(assemble(read_ui(folder, BUILDER_FILES), BUILDER), read_i18n(folder)).encode("utf-8")
