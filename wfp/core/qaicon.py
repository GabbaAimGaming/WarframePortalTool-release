"""Q&A のアイコン(セファロン クロの姿)。一覧は data/qa/icons.json、画像は data/qa/icons/<姿の id>/。

- 姿(sets)は利用者が画面で選ぶ(例: セファロン体・人間体)。default = 選んでいないときの姿
- images は「場面 -> ファイルの一覧」。default は必須、ほかの場面(QA_ICON_SCENES の値)は任意。
  画面は答えの場面の一覧(無ければ default)からランダムに1枚選ぶ
- title = Q&A のタイトルの横に出す1枚(無ければ images.default の先頭)
- menu = メニューの Q&A のボタンに出す1枚(姿に関係なく固定。{set, file})。無くてもよい
- 画像の API は、この一覧に載っているファイルだけを返す(listed)
- ファイルを読むのは store.appdata。ここはデータの形・検査・場面の決め方だけ
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from wfp.core.const import QA_ICON_DEFAULT_SCENE, QA_ICON_MIME, QA_ICON_SCENES

_SET_ID = re.compile(r"^[a-z0-9_]+$")
_FILE_NAME = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9]+$")  # 区切り文字・「..」を含まない
_SCENE_KEYS = (QA_ICON_DEFAULT_SCENE, *dict.fromkeys(QA_ICON_SCENES.values()))  # images に書ける場面


def safe_name(name: object) -> bool:
    """画像のファイル名として使えるか(フォルダの区切り・「..」なし・拡張子が QA_ICON_MIME にある)"""
    return isinstance(name, str) and bool(_FILE_NAME.match(name)) and icon_ext(name) in QA_ICON_MIME


def icon_ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


@dataclass
class IconData:
    default: str | None = None                       # 選んでいないときの姿の id
    sets: list[dict] = field(default_factory=list)   # [{id, label: {ja, en}, title, images: {場面: [ファイル]}}]
    menu: dict | None = None                         # {set, file} か None

    def __post_init__(self):
        self._by_id = {s["id"]: s for s in self.sets}

    def get(self, set_id: str) -> dict | None:
        return self._by_id.get(set_id)

    def listed(self, set_id: str, name: str) -> bool:
        """一覧に載っているファイルか(画像の API が返してよいもの)"""
        s = self.get(set_id)
        if s is None:
            return bool(self.menu and self.menu == {"set": set_id, "file": name})
        return (name == s["title"] or any(name in files for files in s["images"].values())
                or self.menu == {"set": set_id, "file": name})


def _files(raw: object) -> list[str]:
    return [f for f in raw if safe_name(f)] if isinstance(raw, list) else []


def _set(row: object) -> dict | None:
    """姿1つの形を整える(id・images.default が必要)。崩れていれば None"""
    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not _SET_ID.match(row["id"]):
        return None
    images_raw = row.get("images") if isinstance(row.get("images"), dict) else {}
    images = {k: _files(v) for k, v in images_raw.items() if k in _SCENE_KEYS}
    images = {k: v for k, v in images.items() if v}
    if QA_ICON_DEFAULT_SCENE not in images:
        return None
    label = row.get("label") if isinstance(row.get("label"), dict) else {}
    label = {k: label[k].strip() for k in ("ja", "en") if isinstance(label.get(k), str) and label[k].strip()}
    title = row.get("title") if safe_name(row.get("title")) else images[QA_ICON_DEFAULT_SCENE][0]
    return {"id": row["id"], "label": label or {"ja": row["id"], "en": row["id"]}, "title": title, "images": images}


def load_icons(raw: object) -> IconData:
    """data/qa/icons.json から IconData を作る。形の崩れた姿は飛ばす(読めなければ空 = アイコンを出さない)"""
    if not isinstance(raw, dict):
        return IconData()
    seen: set[str] = set()
    sets = []
    for s in (_set(r) for r in raw.get("sets") or []):
        if s and s["id"] not in seen:
            seen.add(s["id"])
            sets.append(s)
    ids = [s["id"] for s in sets]
    default = raw.get("default") if raw.get("default") in ids else (ids[0] if ids else None)
    m = raw.get("menu")
    menu = ({"set": m["set"], "file": m["file"]}
            if isinstance(m, dict) and isinstance(m.get("set"), str) and _SET_ID.match(m["set"]) and safe_name(m.get("file"))
            else None)
    return IconData(default, sets, menu)


def check_icons(raw: object, exists: Callable[[str, str], bool]) -> list[str]:
    """同梱データの検査(テスト用)。exists(姿の id, ファイル名) = 画像があるか。見つかった問題の一覧(無ければ空)"""
    if not isinstance(raw, dict):
        return ["icons.json が読めない"]
    problems: list[str] = []
    rows = raw.get("sets") or []
    data = load_icons(raw)
    ids = [r.get("id") for r in rows if isinstance(r, dict)]
    problems += [f"sets: id {i} が重複" for i in sorted({i for i in ids if isinstance(i, str) and ids.count(i) > 1})]
    if len({s["id"] for s in data.sets}) != len(rows):
        problems.append("sets に形の崩れた姿がある(id は英小文字・数字・_、images.default にファイルが必要)")
    if raw.get("default") not in {s["id"] for s in data.sets}:
        problems.append(f"default {raw.get('default')} が sets に無い")
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("id")
        images = row.get("images") if isinstance(row.get("images"), dict) else {}
        problems += [f"{sid}: 場面 {k} は使えない(使えるのは {' / '.join(_SCENE_KEYS)})" for k in images if k not in _SCENE_KEYS]
        names = [row.get("title")] if row.get("title") is not None else []
        names += [f for v in images.values() for f in (v if isinstance(v, list) else [v])]
        for f in names:
            if not safe_name(f):
                problems.append(f"{sid}: ファイル名 {f} が使えない(拡張子は {' / '.join(QA_ICON_MIME)}、区切り文字なし)")
            elif isinstance(sid, str) and not exists(sid, f):
                problems.append(f"{sid}: ファイル {f} が無い")
    if "menu" in raw:
        m = raw["menu"]
        if data.menu is None:
            problems.append("menu の形が崩れている({set, file}。file は使えるファイル名)")
        elif data.get(m["set"]) is None:
            problems.append(f"menu: 姿 {m['set']} が sets に無い")
        elif not exists(m["set"], m["file"]):
            problems.append(f"menu: ファイル {m['file']} が無い")
    return problems


def scene_of(res: dict) -> str:
    """答え(/api/qa の応答)の場面。表 QA_ICON_SCENES に無い type は QA_ICON_DEFAULT_SCENE"""
    return QA_ICON_SCENES.get(res.get("type"), QA_ICON_DEFAULT_SCENE)


def icon_view(data: IconData) -> dict:
    """画面向けの一覧(GET /api/qa/icons)。ファイル名だけ返し、URL は画面が組み立てる(/qa-icon/<姿>/<ファイル>)"""
    return {"default": data.default, "menu": dict(data.menu) if data.menu else None,
            "sets": [{"id": s["id"], "label": dict(s["label"]), "title": s["title"],
                      "images": {k: list(v) for k, v in s["images"].items()}} for s in data.sets]}
