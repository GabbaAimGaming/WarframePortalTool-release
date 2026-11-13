"""画面(HTML)の組み立て: web/ctrl.html(基礎部)に menu.html(メニュー部)・view.html(全体の CSS)・i18n.html(文字を引く部品)・
parts.html(画面の共通部品)・pages/<id>.html(ページごとの表示部と処理)を差し込んで1枚にする。
シミュレータ(web/wfportal_builder.html)にも i18n.html を差し込む

- ctrl.html の中の、行全体が `<!-- INCLUDE:ファイル名#部品名 -->` の行を、その部品の中身で置き換える
- 部品は、差し込まれる側のファイルの中で `<!-- PART:部品名 -->` の行から、次の PART の行(か最後)までの行。
  最初の PART より前はファイルの説明として使え、出力には入らない
- `<!-- INCLUDE:pages#部品名 -->` は web/pages/ のページのファイル全部の、その部品を PAGE_FILES の順に並べたもの。
  ページのファイルは view(<section id="view-<id>">)と script が必須、style は任意。PAGE_FILES と web/pages/ の
  ファイルが食い違えば PageError(ページを足すときは PAGE_FILES に id を1つ)
- 差し込めるのは UI_FILES / BUILDER_FILES / PAGE_FILES のファイルだけ(web/ の外や、ほかのファイルは読まない)。入れ子の差し込みはしない
- 目印の誤り(知らないファイル・無い部品・使われない部品)は PageError にする(画面が半端に表示されないように)
- 表示する文字は web/i18n/<言語>.json(キー → 文字)。組み立てた後、`I18N_SLOT` の箇所を
  {言語: 表} の JSON に置き換える。日本語(ja.json)は必須で先頭、ほかはファイル名の順
- 画面でも使う Python の定数(PAGE_CONSTS。core/const の名前)は、メイン画面の `CONST_SLOT` の箇所に {名前: 値} の JSON で差し込む
  (画面で手で写さない。足すときは PAGE_CONSTS に名前を1つ)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from wfp.core import const
from wfp.core.const import I18N_BASE, I18N_DIR, WEB_DIR

BASE = "ctrl.html"
UI_FILES = ("ctrl.html", "menu.html", "view.html", "i18n.html", "parts.html")  # 基礎部・メニュー部・全体の CSS・文字を引く部品・共通部品
PAGES_DIR = "pages"  # ページごとのファイル(web/pages/<id>.html)。INCLUDE の「ファイル名」に書くとページ全部になる
# ページの並び(マークアップと処理を差し込む順。メニューの並びは web/menu.html の MENU で、これとは別)
PAGE_FILES = ("home", "item", "area", "enemy", "recipe", "mods", "arcane", "baro", "riven", "mastery", "quests", "invasion",
              "arbitration", "cycle", "duviri", "modstats", "qa", "build", "sim", "tips", "guide", "update")
PAGE_PARTS = ("view", "script")  # ページのファイルに必須の部品(style は任意)
PAGE_PART_KINDS = PAGE_PARTS + ("style",)
BUILDER = "wfportal_builder.html"
BUILDER_FILES = (BUILDER, "i18n.html")  # シミュレータ: 本体 → 文字を引く部品
INCLUDE = re.compile(r"^[ \t]*<!-- INCLUDE:([\w.-]+)#(\w+) -->[ \t]*$")
PART = re.compile(r"^[ \t]*<!-- PART:(\w+) -->[ \t]*$")
I18N_SLOT = "/* I18N:DATA */ {}"
CONST_SLOT = "/* CONST:DATA */ {}"
# 画面(メイン画面の CONST)に差し込む core/const の定数。dict は並びのあるキーの一覧に、tuple は配列にする
PAGE_CONSTS = ("AREA_KINDS", "AREA_KIND_DEFAULT", "ITEM_KIND_DEFAULT", "ENEMY_KIND_DEFAULT")
LANG_CODE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


class PageError(Exception):
    """画面の HTML を組み立てられない(目印の誤り)"""


def web_dir() -> Path:
    return const.APP_DIR / WEB_DIR


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


def page_name(page: str) -> str:
    """ページの id → {ファイル名: 中身} のキー(pages/<id>.html)"""
    return f"{PAGES_DIR}/{page}.html"


def check_pages(parts: dict[str, dict[str, str]], pages: tuple[str, ...]) -> None:
    """ページのファイルの部品を検査する(必須の部品・知らない部品・section の id)"""
    for page in pages:
        name = page_name(page)
        if name not in parts:
            raise PageError(f"ページのファイルがありません: web/{name}")
        got = parts[name]
        for need in PAGE_PARTS:
            if need not in got:
                raise PageError(f"web/{name} に部品 {need} がありません")
        bad = sorted(set(got) - set(PAGE_PART_KINDS))
        if bad:
            raise PageError(f"web/{name} に知らない部品があります: " + ", ".join(bad))
        if f'<section id="view-{page}"' not in got["view"]:
            raise PageError(f'web/{name} の view に <section id="view-{page}"> がありません')


def assemble(texts: dict[str, str], base: str = BASE, pages: tuple[str, ...] = PAGE_FILES) -> str:
    """{ファイル名: 中身} から1枚の HTML を作る(base が土台。ページは pages/<id>.html のキーで渡す。
    ファイルを読まないので、テストからも使える)"""
    parts = {n: split_parts(t, n) for n, t in texts.items() if n != base}
    page_keys = {page_name(p) for p in pages}
    extra = sorted(n for n in parts if n.startswith(PAGES_DIR + "/") and n not in page_keys)
    if extra:
        raise PageError("PAGE_FILES に無いページのファイルです: " + ", ".join(extra))
    has_pages = any(INCLUDE.match(x) and INCLUDE.match(x).group(1) == PAGES_DIR for x in texts[base].splitlines())
    if has_pages:
        check_pages(parts, pages)
    used = set()
    out = []
    for line in texts[base].splitlines(keepends=True):
        m = INCLUDE.match(line.rstrip("\n"))
        if not m:
            out.append(line)
            continue
        fname, part = m.groups()
        if fname == PAGES_DIR:  # ページ全部の、その部品(style のように無いページは飛ばす)
            if part not in PAGE_PART_KINDS:
                raise PageError(f"{base}: ページの部品ではありません: {part}")
            for page in pages:
                name = page_name(page)
                if part in parts[name]:
                    out.append(parts[name][part])
                    used.add((name, part))
            continue
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


def inject_data(html: str, slot: str, data: object) -> str:
    """HTML の slot(1か所だけ)を data の JSON に置き換える。
    スクリプトの中に入るので、`</` は `<\\/` にして </script> と読まれないようにする"""
    n = html.count(slot)
    if n != 1:
        raise PageError(f"{slot} の目印が {n} か所あります(1か所だけにする)")
    return html.replace(slot, json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))


def inject_i18n(html: str, tables: dict) -> str:
    """HTML の I18N_SLOT を言語の表の JSON に置き換える"""
    return inject_data(html, I18N_SLOT, tables)


def page_consts() -> dict[str, list]:
    """画面に差し込む定数 {名前: 値}(PAGE_CONSTS。dict はキーの一覧)"""
    return {name: list(getattr(const, name)) for name in PAGE_CONSTS}


def read_ui(folder: Path | None = None, files: tuple[str, ...] = UI_FILES, pages: tuple[str, ...] = PAGE_FILES) -> dict[str, str]:
    """画面のファイルを {ファイル名: 中身} で読む(ページは pages/<id>.html。web/pages/ にあって pages に無いファイルも
    読み、assemble の検査で落とす)"""
    folder = folder or web_dir()
    texts = {n: (folder / n).read_text(encoding="utf-8") for n in files}
    if pages:
        names = {page_name(p) for p in pages} | {f"{PAGES_DIR}/{f.name}" for f in (folder / PAGES_DIR).glob("*.html")}
        for name in sorted(names):
            path = folder / name
            if not path.is_file():
                raise PageError(f"ページのファイルがありません: web/{name}")
            texts[name] = path.read_text(encoding="utf-8")
    return texts


def ui_html(folder: Path | None = None) -> bytes:
    """メイン画面の HTML(毎回ファイルから組み立て、言語の表を差し込む。編集がすぐ反映される)"""
    html = inject_i18n(assemble(read_ui(folder)), read_i18n(folder))
    return inject_data(html, CONST_SLOT, page_consts()).encode("utf-8")


def builder_html(folder: Path | None = None) -> bytes:
    """シミュレータの HTML(文字を引く部品と言語の表を差し込む。毎回ファイルから組み立てる)"""
    return inject_i18n(assemble(read_ui(folder, BUILDER_FILES, ()), BUILDER), read_i18n(folder)).encode("utf-8")
