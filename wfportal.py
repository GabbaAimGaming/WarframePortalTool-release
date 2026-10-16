#!/usr/bin/env python3
"""wfportal - Warframe ポータルツール (標準ライブラリのみ / Python 3.9+)

  python wfportal.py update                  公式データを取得(初回と更新時)
  python wfportal.py item ニューロード        素材 -> どこで何%で出るか(逆引き)
  python wfportal.py area 地球                エリア -> 出現ステージごとの素材一覧
  python wfportal.py cycle                    昼夜サイクルとリセットまでの時間
  python wfportal.py mods                     MOD 入手一覧 (入手先と所持チェック)
  python wfportal.py arcane                   アルケイン所持一覧 (所持チェックとランク)
  python wfportal.py riven ルビコ              Riven 相場 (公式の週次統計)
  python wfportal.py mastery                  マスター一覧 (Warframe・武器などのマスター済みチェック)
  python wfportal.py build list               ビルド管理
  python wfportal.py build analyze 画像.png     ビルド画像の自動解析 (Windows の文字認識)
  python wfportal.py logos                    公式ファンキットのロゴ素材を取得 (初回起動時に自動)

非公式のファンツールです。Digital Extremes Ltd. とは関係ありません。

データ置き場は既定で ~/.wfportal (環境変数 WFPORTAL_DIR か --data-dir で変更可)。
"""
from __future__ import annotations

import argparse
import io
import json
import lzma
import os
import re
import sys
import time
import unicodedata
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# 設定
# --------------------------------------------------------------------------

# ドロップ表: 公式ドロップ表(warframe.com/droptables)を WFCD が JSON 化したもの
#   https://github.com/WFCD/warframe-drop-data (MIT)
WFCD_BASES = [
    "https://drops.warframestat.us/data",
    "https://raw.githubusercontent.com/WFCD/warframe-drop-data/gh-pages/data",
]
DROPS_URLS = [f"{b}/missionRewards.json" for b in WFCD_BASES]
# ミッション以外の入手先(敵・バウンティ・レリック等)。取得できなくても他の機能は動く
WFCD_EXTRA = (
    "resourceByAvatar", "sigilByAvatar", "additionalItemByAvatar", "enemyModTables", "blueprintLocations",
    "miscItems", "relics", "cetusBountyRewards", "solarisBountyRewards", "deimosRewards", "zarimanRewards",
    "entratiLabRewards", "hexRewards", "sortieRewards", "transientRewards", "keyRewards",
)
# 名前辞書: 公式 Public Export (言語別。日本語名と英語名を uniqueName で突き合わせる)
#   1) calamity-inc/warframe-public-export: 公式データを展開済み JSON にして GitHub で公開しているもの
#   2) 取得できなければ公式サイトから直接 (index_*.txt.lzma を展開して各ファイルを取得)
EXPORT_GITHUB = "https://raw.githubusercontent.com/calamity-inc/warframe-public-export/senpai"
EXPORT_BASE = "http://content.warframe.com/PublicExport"
EXPORT_PREFIXES = ("ExportResources", "ExportUpgrades", "ExportGear", "ExportWarframes",
                   "ExportWeapons", "ExportSentinels", "ExportRelicArcane")
# Riven 相場: 公式が毎週公開している PC 版の取引統計。取得できなければ WFCD が同じ統計を配信しているものを使う
RIVENS_URL = "https://www-static.warframe.com/repos/weeklyRivensPC.json"
RIVENS_URLS = [RIVENS_URL, "https://api.warframestat.us/pc/rivens"]
# サイトによっては見慣れない User-Agent を拒否する(403)ため、ブラウザに近い名乗り方にする
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) wfportal/1.0"

# ロゴ素材: Digital Extremes が公開している「Warframe Fan Kit」(Dropbox) の Logos フォルダ
#   配布ページ: https://www.warframe.com/news/warframe-fansite-kit
#   権利は Digital Extremes にあるため、このツールには同梱せず、各自の PC で公式の配布元から取得する
FANKIT_PAGE = "https://www.warframe.com/news/warframe-fansite-kit"
FANKIT_LOGOS_URL = ("https://www.dropbox.com/scl/fo/el9i8ltoms44id3wt3swv/h/Logos"
                    "?rlkey=3ehhk98vupze6if64gl3lia08&dl=1")
LOGO_EXTS = (".png", ".eps", ".svg", ".jpg", ".jpeg", ".ai", ".pdf")
LOGO_MAX_BYTES = 300 * 1024 * 1024  # 想定より極端に大きいときは止める
APP_DIR = Path(__file__).resolve().parent


def app_version() -> str:
    """ツールのバージョン (version.json の "version"。例: 1.00)。読めなければ "?" """
    try:
        return str(json.loads((APP_DIR / "version.json").read_text(encoding="utf-8-sig"))["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return "?"

PLANETS_JA = {
    "Mercury": "水星", "Venus": "金星", "Earth": "地球", "Mars": "火星", "Jupiter": "木星",
    "Saturn": "土星", "Uranus": "天王星", "Neptune": "海王星", "Pluto": "冥王星",
    "Ceres": "ケレス", "Eris": "エリス", "Sedna": "セドナ", "Europa": "エウロパ",
    "Void": "ヴォイド", "Phobos": "フォボス", "Deimos": "ダイモス", "Lua": "ルア",
    "Kuva Fortress": "クバ要塞", "Sanctuary": "サンクチュアリ", "Veil Proxima": "ヴェール・プロキシマ",
    "Zariman": "ザリマン", "Duviri": "デュヴィリ", "Höllvania": "ホルバニア",
    "Dark Refractory, Deimos": "ダーク・リフラクトリー(ダイモス)",
}
MODES_JA = {
    "Survival": "生存", "Defense": "防衛", "Capture": "捕獲", "Rescue": "救出", "Spy": "スパイ",
    "Assassination": "暗殺", "Interception": "傍受", "Exterminate": "殲滅", "Excavation": "発掘",
    "Disruption": "妨害", "Mobile Defense": "モバイルディフェンス", "Sabotage": "妨害工作",
    "Defection": "亡命", "Skirmish": "小競り合い", "Caches": "キャッシュ", "Conclave": "コンクラーヴ",
    "Arena": "アリーナ", "Hard": "ハード", "Normal": "ノーマル", "Rush": "ラッシュ",
    "Pursuit": "追跡", "Ascension": "アセンション", "Alchemy": "錬金",
    "Infested Salvage": "感染サルベージ", "Void Flood": "ヴォイドフラッド",
    "Void Cascade": "ヴォイドカスケード", "Void Armageddon": "ヴォイドアルマゲドン",
    "The Circuit": "サーキット", "Legacyte Harvest": "レガシート収穫",
    "Sanctuary Onslaught": "サンクチュアリ・オンスロート", "Shrine Defense": "神殿防衛",
    "The Perita Rebellion": "ペリタの反乱", "Follie's Hunt": "フォリーの狩り",
}
RARITY_JA = {"Common": "コモン", "Uncommon": "アンコモン", "Rare": "レア", "Legendary": "レジェンダリー"}
ERA_JA = {"Lith": "リス", "Meso": "メソ", "Neo": "ネオ", "Axi": "アクシ", "Requiem": "レクイエム"}
PART_JA = {"Blueprint": "設計図", "Neuroptics": "ニューロオプティクス", "Chassis": "シャーシ",
           "Systems": "システム", "Barrel": "バレル", "Receiver": "レシーバー", "Stock": "ストック",
           "Blade": "ブレード", "Handle": "ハンドル"}
BUILD_TYPES = {"frame": "ウォーフレーム", "primary": "プライマリ", "secondary": "セカンダリ",
               "melee": "近接", "companion": "コンパニオン", "archwing": "アークウィング", "other": "その他"}

# 入手先の種類
SOURCE_CATS = {"mission": "ミッション", "enemy": "敵", "bounty": "バウンティ", "relic": "レリック",
               "special": "特殊ミッション", "key": "キー・ボス", "sortie": "ソーティー"}
BOUNTY_JA = {"cetusBountyRewards": "平原バウンティ", "solarisBountyRewards": "オーブ峡谷バウンティ",
             "deimosRewards": "カンビオンの荒地バウンティ", "zarimanRewards": "ザリマン バウンティ",
             "entratiLabRewards": "アルブレヒト研究所バウンティ", "hexRewards": "Hex(1999)バウンティ"}
RELIC_STATE_JA = {"Intact": "無傷", "Exceptional": "上質", "Flawless": "完璧", "Radiant": "光輝"}
RELIC_STATES = ("Intact", "Radiant")  # 一覧が長くなりすぎないよう、両端の2状態だけ載せる

# MOD
MOD_TYPES = {"WARFRAME": "ウォーフレーム", "AURA": "オーラ", "PRIMARY": "プライマリ", "SECONDARY": "セカンダリ",
             "MELEE": "近接", "STANCE": "スタンス", "SENTINEL": "センチネル", "KUBROW": "クブロウ", "KAVAT": "キャバット",
             "HELMINTH CHARGER": "ヘルミンスチャージャー", "ARCHWING": "アークウィング", "ARCH-GUN": "アークガン",
             "ARCH-MELEE": "アーク近接", "PARAZON": "パラゾン", "NECRAMECH": "ネクラメカ", "OTHER": "その他"}
COMPAT_JA = {"Rifle": "ライフル", "Shotgun": "ショットガン", "Pistol": "ピストル", "Melee": "近接", "Sniper": "スナイパー",
             "Bow": "弓", "Assault Rifle": "アサルトライフル", "Throwing": "投擲", "Kitgun": "キットガン", "Zaw": "ザウ"}
# マスター一覧のカテゴリー
MASTERY_CATS = {"warframe": "Warframe", "primary": "プライマリ", "secondary": "セカンダリ", "melee": "近接",
                "kitgun": "Kitgun", "zaw": "Zaw", "robotic": "ロボティック", "companion": "コンパニオン",
                "archgun": "アークウイングガン", "archmelee": "アークウイング近接", "amp": "アンプ"}
_MASTERY_WEAPON = {"LongGuns": "primary", "Pistols": "secondary", "Melee": "melee", "SpaceGuns": "archgun",
                   "SpaceMelee": "archmelee", "SentinelWeapons": "robotic", "OperatorAmps": "amp"}
# 組み立て式の部品。マスタリー経験値が入る部品(下の mastery_slots)以外は一覧に載せない
_MODULAR_PARTS = re.compile(r"/(OperatorAmplifiers|ModularMelee[^/]*|SUModular[^/]*|InfKitGun|Hoverboard|ZanukaPetParts|MoaPetParts)/")


def mastery_slots(export: str, it: dict) -> list[tuple[str, str]]:
    """Public Export の1項目が、マスター一覧のどのカテゴリーに入るか -> [(カテゴリー, 区分)]

    - 組み立て式は、マスタリー経験値が入る部品だけ: Kitgun はチェンバー(プライマリ版とセカンダリ版を別に数える)、
      Zaw はストライク、アンプはプリズム(と Sirocco)
    - アビリティ専用武器やコンクラーヴ用など、図鑑に載らないもの(excludeFromCodex)は除く
    """
    uid, pc = it.get("uniqueName", ""), it.get("productCategory")
    if it.get("excludeFromCodex") or not it.get("name"):
        return []
    if export == "ExportWarframes":
        return [("warframe", "")] if pc == "Suits" else []
    if export == "ExportSentinels":
        return [("robotic", "")] if pc == "Sentinels" else [("companion", "")] if pc == "KubrowPets" else []
    if export != "ExportWeapons":
        return []
    if re.search(r"/OperatorAmplifiers/.*Barrel", uid):
        return [("amp", "")]
    if re.search(r"/ModularMelee[^/]*/Tips?/", uid):
        return [("zaw", "")]
    if re.search(r"/(SUModularSecondary[^/]*/Barrel|InfKitGun/Barrels)/", uid):
        return [("kitgun", "primary"), ("kitgun", "secondary")]
    if _MODULAR_PARTS.search(uid):
        return []
    return [(_MASTERY_WEAPON[pc], "")] if pc in _MASTERY_WEAPON else []


def mastery_xp(cat: str, export: str, rank: int) -> int:
    """ランク最大までのマスタリー経験値: フレーム・コンパニオン・センチネル本体は 200/ランク、武器は 100/ランク"""
    per = 200 if cat in ("warframe", "companion") or (cat == "robotic" and export == "ExportSentinels") else 100
    return per * rank


# 極性(ゲーム内の英語名)
POLARITY_EN = {"AP_ATTACK": "Madurai", "AP_DEFENSE": "Vazarin", "AP_TACTIC": "Naramon", "AP_POWER": "Zenurik",
               "AP_WARD": "Unairu", "AP_PRECEPT": "Penjaga", "AP_UMBRA": "Umbra", "AP_UNIVERSAL": "Universal", "AP_ANY": "Any"}
# 装備の種類 (Public Export の productCategory -> ビルドの種別)
ITEM_TYPES = {"Suits": "frame", "SpaceSuits": "archwing", "MechSuits": "other", "LongGuns": "primary", "Pistols": "secondary",
              "Melee": "melee", "SentinelWeapons": "companion", "SpaceGuns": "archwing", "SpaceMelee": "archwing",
              "Sentinels": "companion", "KubrowPets": "companion"}

# Riven
RIVEN_TYPES_JA = {"Rifle Riven Mod": "ライフル", "Shotgun Riven Mod": "ショットガン", "Pistol Riven Mod": "ピストル",
                  "Melee Riven Mod": "近接", "Zaw Riven Mod": "Zaw", "Kitgun Riven Mod": "Kitgun",  # Kitgun・Zaw は英語のまま
                  "Archgun Riven Mod": "アークガン", "Companion Weapon Riven Mod": "コンパニオン武器"}

# Riven 性質 (ExportWeapons の omegaAttenuation。0.5〜1.55)
DISPO_CATS = {"primary": "プライマリ", "secondary": "セカンダリ", "melee": "近接", "kitgun": "Kitgun",
              "zaw": "Zaw", "archgun": "アークガン", "robotic": "コンパニオン武器"}
_DISPO_TYPE = {"secondary": "Pistol Riven Mod", "melee": "Melee Riven Mod", "kitgun": "Kitgun Riven Mod",
               "zaw": "Zaw Riven Mod", "archgun": "Archgun Riven Mod", "robotic": "Companion Weapon Riven Mod"}
# アルケイン所持一覧のカテゴリー (並び順もこの順)
ARCANE_CATS = {"warframe": "Warframe", "primary": "プライマリ", "secondary": "セカンダリ", "melee": "近接",
               "kitgun": "Kitgun", "zaw": "Zaw", "operator": "オペレーター", "amp": "アンプ", "tektolyst": "テクトリスト",
               "other": "その他"}
# 公式データ(ExportRelicArcane)には装備先が無く、内部名のフォルダ(Offensive / Utility など)も装備先と一致しないため、
# 名前の最初の語で判定する(2026-10 時点の 172 件すべてが WFCD warframe-items の装備先と一致することを確認済み)。
# 一覧に無い語で始まる新しいアルケインは "other" (その他) に入る
ARCANE_PREFIX_CAT = {
    "arcane": "warframe", "molt": "warframe", "theorem": "warframe",
    "primary": "primary", "fractalized": "primary", "longbow": "primary", "shotgun": "primary",
    "secondary": "secondary", "cascadia": "secondary", "conjunction": "secondary", "akimbo": "secondary",
    "melee": "melee", "pax": "kitgun", "residual": "kitgun", "exodia": "zaw",
    "magus": "operator", "emergence": "operator", "virtuos": "amp", "eternal": "amp",
    "zid-an": "tektolyst",  # テクトリストアーティファクト用 (Update 41.0)
}
# 公式データにはあるが、ゲームに実装されていないアルケイン (内部名)。所持一覧に載せない
#   Arcane Defense / Detoxifier / Liquid / Protection / Shield / Survival / Temperance の 7 件。
#   入手先が無く(WFCD のドロップ情報なし)、公式フォーラムでも未実装として扱われている
ARCANE_UNRELEASED = frozenset("/Lotus/Upgrades/CosmeticEnhancers/" + p for p in (
    "Defensive/PunctureProcResist", "Defensive/PoisonProcResist", "Defensive/GasProcResist",
    "Defensive/CorrosiveProcResist", "Defensive/ImpactProcResist",
    "Utility/SlowerBleedOutOnPredeath", "Utility/DamageReductionDuringRevive"))
# 公式データ(ExportRelicArcane)にまだ無く、ドロップ表にだけ載っているアルケインを補うカテゴリー
#   (2026-10 時点: テクトリスト用の Zid-An 5 件)。公式データに同じ名前が入れば、そちらを使う
ARCANE_DROP_ONLY_CATS = ("tektolyst",)
# ドロップ表には最大ランクが無いため、通常のアルケインと同じ 5 とする (Zid-An は 6 段階であることを WARFRAME Wiki で確認)
# 表記の方針(2026-10-17 決定): テクトリスト(Zid-An)の名前は英語表記のままでよい。
#   カタカナの対応表は作らない(公式データに日本語名が入った場合は、ほかのアルケインと同じく自動でそれを使う)
ARCANE_DROP_ONLY_MAX_RANK = 5


def arcane_cat(name: str) -> str:
    """アルケインの装備先カテゴリー (ARCANE_CATS のキー)"""
    first = name.strip().split(" ", 1)[0].lower()
    return ARCANE_PREFIX_CAT.get(first, "other")


# プライマリのうちショットガン用 Riven を使う武器。公式データに武器の種類が無いため、内部名に Shotgun を含むものと
# 下の名前(Prime・Kuva などを外した元の名前)で判定する。Riven 相場のデータがあれば、そちらの武器種を優先する
SHOTGUN_BASES = {"strun", "hek", "boar", "sobek", "felarx", "steflos", "corinth", "astilla", "cedo", "phantasma",
                 "rauta", "tigris", "phage", "bassocyst", "arca plasmor", "exergis", "kohm", "drakgoon", "bubonico"}
_VARIANT_WORDS = {"prime", "wraith", "vandal", "kuva", "tenet", "coda", "prisma", "sancti", "vaykor", "mara", "dex",
                  "rakta", "telos", "synoid", "secura", "mutalist", "carmine", "proboscis", "ceti"}


def weapon_base_name(name: str) -> str:
    """Prime・Kuva・MK1- などを外した元の武器名 (例: "Kuva Hek" -> "hek")"""
    words = re.sub(r"^mk1-", "", name.strip().lower()).split()
    return " ".join(x for x in words if x not in _VARIANT_WORDS)


def dispo_type(cat: str, uid: str, name: str) -> str:
    """Riven の種類 (RIVEN_TYPES_JA のキー)"""
    if cat == "primary":
        shotgun = "shotgun" in uid.lower() or weapon_base_name(name) in SHOTGUN_BASES
        return "Shotgun Riven Mod" if shotgun else "Rifle Riven Mod"
    return _DISPO_TYPE[cat]


def dispo_dots(value: float) -> int:
    """性質値 -> ●の数: 0.5〜0.7 / 0.71〜0.9 / 0.91〜1.10 / 1.11〜1.30 / 1.31〜1.55"""
    v = round(value, 2)
    return 1 if v <= 0.70 else 2 if v <= 0.90 else 3 if v <= 1.10 else 4 if v <= 1.30 else 5


def dispo_mark(dots: int) -> str:
    """性質の表示: ●と◯を合わせて5個 (例: 3 -> ●●●◯◯)"""
    return "●" * dots + "◯" * (5 - dots)


def data_dir(arg: str | None = None) -> Path:
    p = Path(arg or os.environ.get("WFPORTAL_DIR") or Path.home() / ".wfportal")
    p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------
# 表示ユーティリティ (全角を2桁として桁揃え)
# --------------------------------------------------------------------------

def disp_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, n: int, right: bool = False) -> str:
    gap = " " * max(0, n - disp_width(s))
    return gap + s if right else s + gap


def print_table(header: list[str], rows: list[list[str]], right_cols: tuple[int, ...] = ()) -> None:
    widths = [max(disp_width(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    line = lambda r: "  ".join(pad(str(c), widths[i], i in right_cols) for i, c in enumerate(r)).rstrip()
    print(line(header))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


# --------------------------------------------------------------------------
# 名前の正規化・照合 (ひらがな/カタカナ、全角半角、大文字小文字、空白や中点を無視)
# --------------------------------------------------------------------------

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)  # ひらがな -> カタカナ
    return re.sub(r"[\s・･\-_'’,()（）]", "", s)


def rank(query: str, names: list[str]) -> int | None:
    """0=完全一致 1=前方一致 2=部分一致 None=不一致"""
    q = norm(query)
    if not q:
        return None
    best = None
    for n in names:
        t = norm(n)
        r = 0 if t == q else 1 if t.startswith(q) else 2 if q in t else None
        if r is not None and (best is None or r < best):
            best = r
    return best


# --------------------------------------------------------------------------
# 名前辞書 (英語名 -> 日本語名)
# --------------------------------------------------------------------------

def parse_export_json(text: str) -> dict:
    """Public Export は文字列内に生の改行/制御文字を含むため、緩く読む。"""
    return json.loads(text.replace("\r", "").replace("\n", ""), strict=False)


def mod_type_key(it: dict) -> str:
    t = it.get("type") or ""
    if "/Necromech/" in it.get("uniqueName", ""):
        return "NECRAMECH"
    return t if t in MOD_TYPES else "OTHER"


def is_listed_mod(it: dict) -> bool:
    """MOD一覧に載せる MOD か(Riven・コンクラーヴ用・初心者用(欠陥)・変換コアは除く)"""
    uid, name = it.get("uniqueName", ""), it.get("name", "")
    return bool(name) and not (
        "Riven Mod" in name or "/PvPMods/" in uid or "/Beginner/" in uid or "/TransmuteCores/" in uid
        or "/Randomized/" in uid)


def names_from_exports(en_docs: list[dict], ja_docs: list[dict]) -> dict:
    """Export の英語版・日本語版を uniqueName で突き合わせて辞書化する。"""
    def collect(docs):
        out = {}
        for doc in docs:
            for key, val in doc.items():
                if not isinstance(val, list):
                    continue
                for it in val:
                    if isinstance(it, dict) and it.get("uniqueName") and it.get("name"):
                        out[it["uniqueName"]] = (it["name"], key)
        return out

    en, ja = collect(en_docs), collect(ja_docs)
    en2ja, resources = {}, []
    for uid, (en_name, kind) in en.items():
        if uid in ja:
            en2ja.setdefault(en_name, ja[uid][0])
        if kind == "ExportResources":
            resources.append(en_name)

    # MOD 一覧用の情報(種別・極性・レア度など)
    mods: dict[str, dict] = {}
    for doc in en_docs:
        for it in doc.get("ExportUpgrades", []):
            if not isinstance(it, dict) or not is_listed_mod(it):
                continue
            name = it["name"]
            if name.lower() in mods:
                continue
            compat = it.get("compatName") or ""
            mods[name.lower()] = {
                "en": name, "ja": ja.get(it["uniqueName"], (name,))[0],
                "type": mod_type_key(it), "polarity": it.get("polarity") or "",
                "rarity": (it.get("rarity") or "").capitalize(),
                "compat": compat if compat.upper() != compat else "",  # "WARFRAME" 等の汎用名は省く
                "drain": it.get("baseDrain"), "max_rank": it.get("fusionLimit"),
            }
    # 画像解析で照合する装備名(フレーム・武器・コンパニオン)とアルケイン名
    items: dict[str, dict] = {}
    arcanes: dict[str, str] = {}
    arcane_list: dict[str, dict] = {}  # アルケイン所持一覧
    for doc in en_docs:
        for key in ("ExportWarframes", "ExportWeapons", "ExportSentinels"):
            for it in doc.get(key, []):
                if not isinstance(it, dict) or it.get("productCategory") not in ITEM_TYPES:
                    continue
                name = re.sub(r"^<[^>]+>\s*", "", it.get("name", "")).strip()
                if name and name.lower() not in items:
                    ja_name = re.sub(r"^<[^>]+>\s*", "", ja.get(it["uniqueName"], (name,))[0]).strip()
                    items[name.lower()] = {"en": name, "ja": ja_name, "type": ITEM_TYPES[it["productCategory"]]}
        for it in doc.get("ExportRelicArcane", []):
            name = it.get("name", "") if isinstance(it, dict) else ""
            if name and not name.endswith(" Relic") and "/CosmeticEnhancers/" in it.get("uniqueName", ""):
                arcanes.setdefault(name.lower(), name)
                # 所持一覧は図鑑に載るものだけ (Arcane Steadfast の内部用の項目などを除く)。最大ランク = 段階の数 - 1
                # レア度: ExportRelicArcane はコモンのアルケインの一部で rarity を省いているため、無ければコモン
                #   (2026-10 時点で省かれている 21 件のうち、WFCD warframe-items に値がある 17 件はすべて Common。
                #    なお ExportUpgrades (MOD) はコモンも省かずに書いてある)
                levels = len(it.get("levelStats") or [])
                if (not it.get("excludeFromCodex") and levels >= 2 and name.lower() not in arcane_list
                        and it.get("uniqueName") not in ARCANE_UNRELEASED):
                    arcane_list[name.lower()] = {
                        "en": name, "ja": ja.get(it["uniqueName"], (name,))[0], "cat": arcane_cat(name),
                        "rarity": (it.get("rarity") or "COMMON").capitalize(), "max_rank": levels - 1}
    # マスター一覧
    mastery: dict[str, dict] = {}
    for doc in en_docs:
        for key in ("ExportWarframes", "ExportWeapons", "ExportSentinels"):
            for it in doc.get(key, []):
                if not isinstance(it, dict):
                    continue
                name = re.sub(r"^<[^>]+>\s*", "", it.get("name", "")).strip()
                for cat, variant in mastery_slots(key, it):
                    mid = f"{cat}:{variant}:{name.lower()}" if variant else f"{cat}:{name.lower()}"
                    if mid in mastery:
                        continue
                    rank = int(it.get("maxLevelCap") or 30)
                    mastery[mid] = {"id": mid, "en": name, "cat": cat, "variant": variant, "rank": rank,
                                    "ja": re.sub(r"^<[^>]+>\s*", "", ja.get(it["uniqueName"], (name,))[0]).strip(),
                                    "xp": mastery_xp(cat, key, rank)}
    # Riven 性質 (マスター一覧と同じ数え方の武器から、Riven を付けられないアーク近接・アンプを除く)
    dispo: dict[str, dict] = {}
    for doc in en_docs:
        for it in doc.get("ExportWeapons", []):
            if not isinstance(it, dict) or not isinstance(it.get("omegaAttenuation"), (int, float)):
                continue
            name = re.sub(r"^<[^>]+>\s*", "", it.get("name", "")).strip()
            for cat, variant in mastery_slots("ExportWeapons", it):
                if cat not in DISPO_CATS:
                    continue
                did = f"{cat}:{variant}:{name.lower()}" if variant else f"{cat}:{name.lower()}"
                if did in dispo:
                    continue
                # Kitgun のプライマリ版は primeOmegaAttenuation (無ければセカンダリ版と同じ値)
                raw = it.get("primeOmegaAttenuation") if variant == "primary" else None
                value = round(float(raw if isinstance(raw, (int, float)) else it["omegaAttenuation"]), 2)
                dispo[did] = {"id": did, "en": name, "cat": cat, "variant": variant, "value": value,
                              "type": dispo_type(cat, it.get("uniqueName", ""), name),
                              "ja": re.sub(r"^<[^>]+>\s*", "", ja.get(it["uniqueName"], (name,))[0]).strip()}
    order = {c: i for i, c in enumerate(MASTERY_CATS)}
    return {"en2ja": en2ja, "resources": sorted(set(resources)),
            "mods": sorted(mods.values(), key=lambda m: m["en"].lower()),
            "items": sorted(items.values(), key=lambda m: m["en"].lower()),
            "arcanes": sorted(arcanes.values(), key=str.lower),
            "arcane_list": sorted(arcane_list.values(), key=lambda m: (list(ARCANE_CATS).index(m["cat"]), m["en"].lower())),
            "mastery": sorted(mastery.values(), key=lambda m: (order[m["cat"]], m["en"].lower(), m["variant"])),
            "dispo": sorted(dispo.values(), key=lambda m: (list(DISPO_CATS).index(m["cat"]), -m["value"], m["en"].lower(), m["variant"]))}


class Names:
    def __init__(self, en2ja: dict | None = None, resources: list | None = None, mods: list | None = None,
                 items: list | None = None, arcanes: list | None = None, mastery: list | None = None,
                 dispo: list | None = None, arcane_list: list | None = None):
        self.en2ja = en2ja or {}
        self.resources = set(resources or [])
        self.mods = mods or []
        self.items = items or []      # 装備名 [{en, ja, type}] (画像解析用)
        self.arcanes = arcanes or []  # アルケイン名 (画像解析用)
        self.mastery = mastery or []  # マスター一覧 [{id, en, ja, cat, variant, rank, xp}]
        self.dispo = dispo or []      # Riven 性質 [{id, en, ja, cat, variant, value, type}]
        self.arcane_list = arcane_list or []  # アルケイン所持一覧 [{en, ja, cat, rarity, max_rank}]
        # ドロップ表と公式データで大文字小文字が違うことがある(例: "Bane Of Grineer" / "Bane of Grineer")
        self._lower = {k.lower(): v for k, v in self.en2ja.items()}
        self._res_lower = {r.lower() for r in self.resources}

    @classmethod
    def load(cls, d: Path) -> "Names":
        f = d / "names.json"
        if f.exists():
            j = json.loads(f.read_text(encoding="utf-8"))
            return cls(j.get("en2ja"), j.get("resources"), j.get("mods"), j.get("items"), j.get("arcanes"), j.get("mastery"),
                       j.get("dispo"), j.get("arcane_list"))
        return cls()

    @staticmethod
    def split_qty(name: str) -> tuple[str, str]:
        m = re.match(r"^([\d,]+)X\s+(.*)$", name)
        return (m.group(1), m.group(2)) if m else ("", name)

    def _get(self, en: str) -> str | None:
        return self.en2ja.get(en) or self._lower.get(en.lower())

    def ja(self, name: str) -> str:
        qty, base = self.split_qty(name)
        pre = f"{qty}個 " if qty else ""
        if hit := self._get(base):
            return pre + hit
        if m := re.match(r"^([\d,]+) Credits Cache$", base):
            return f"{m.group(1)} クレジットキャッシュ"
        if m := re.match(r"^([\d,]+) Credits$", base):
            return f"{m.group(1)} クレジット"
        if m := re.match(r"^([\d,]+) Endo$", base):
            return f"{m.group(1)} エンド"
        if m := re.match(r"^(Lith|Meso|Neo|Axi|Requiem) (\S+) Relic$", base):
            return f"{ERA_JA[m.group(1)]} {m.group(2)} 遺物"
        if base.endswith(" Blueprint"):
            b = base[:-10]
            if hit := self._get(b):
                return hit + " 設計図"
            words = b.split(" ")
            if len(words) > 1 and words[-1] in PART_JA and (first := self._get(words[0])):
                return f"{first} {PART_JA[words[-1]]} 設計図"
        return pre + base

    def is_resource(self, name: str) -> bool:
        return self.split_qty(name)[1].lower() in self._res_lower


def item_key(name: str) -> str:
    """数量違い(例: 2X Neurodes / Neurodes)や大文字小文字の違いを同じ項目として扱うためのキー"""
    return Names.split_qty(name)[1].lower()


# --------------------------------------------------------------------------
# ドロップ表
# --------------------------------------------------------------------------

class Drops:
    """missionRewards.json を [(惑星, ノード, ミッション, イベント, ローテーション, 英名, 確率, レア度)] に展開"""

    def __init__(self, raw: dict):
        self.rows = []
        self.node_order = []
        for planet, nodes in raw["missionRewards"].items():
            for node, v in nodes.items():
                self.node_order.append((planet, node))
                rewards = v["rewards"]
                groups = rewards.items() if isinstance(rewards, dict) else [("-", rewards)]
                for rot, lst in groups:
                    for e in lst:
                        self.rows.append((planet, node, v["gameMode"], bool(v.get("isEvent")),
                                          rot, e["itemName"], float(e["chance"]), e.get("rarity", "")))
        self.item_names = sorted({r[5] for r in self.rows})
        self.planets = list(dict.fromkeys(p for p, _ in self.node_order))

    @classmethod
    def load(cls, d: Path) -> "Drops":
        f = d / "missionRewards.json"
        if not f.exists():
            sys.exit("ドロップ表がありません。先に `python wfportal.py update` を実行してください。")
        return cls(json.loads(f.read_text(encoding="utf-8")))


def _num(v) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _stage_ja(s: str) -> str:
    """"Stage 2, Stage 3 of 4, and Stage 3 of 5" -> "ステージ2、ステージ3(全4)、ステージ3(全5)" """
    s = re.sub(r"final stage", "最終ステージ", s or "", flags=re.I)
    s = re.sub(r"Stage\s*(\d+)\s+of\s+(\d+)", r"ステージ\1(全\2)", s)
    s = re.sub(r"Stage\s*", "ステージ", s)
    return re.sub(r",?\s*and\s+|,\s*", "、", s)


def _bounty_label(group: str, level: str) -> str:
    m = re.search(r"Level\s+(\d+)\s*-\s*(\d+)", level or "")
    lv = f" Lv{m.group(1)}-{m.group(2)}" if m else f" {level}"
    return BOUNTY_JA.get(group, group) + lv + (" (鋼の道)" if "Steel" in (level or "") else "")


class Sources:
    """ミッション以外の入手先 (WFCD の各ファイル) を1つの表に展開する。

    rows = [(種類, 入手先, 詳細, ステージ, 英名, 確率%, レア度)]
    確率は「その敵を1体倒す / その報酬を1回引く」ときにその項目が出る割合にそろえる。
    """

    def __init__(self, files: dict[str, dict]):
        self.rows: list[tuple] = []
        add = self.rows.append
        get = lambda name: (files.get(name) or {}).get(name) or []

        # 敵: 素材・シジル等 (chance は1体あたりの確率)
        for name, label in (("resourceByAvatar", "素材"), ("sigilByAvatar", "シジル等"), ("additionalItemByAvatar", "その他")):
            for e in get(name):
                for it in e.get("items", []):
                    add(("enemy", e.get("source", ""), label, "-", it.get("item", ""), _num(it.get("chance")), it.get("rarity", "")))
        # 敵: MOD (MODを落とす確率 × その中で選ばれる確率)
        for e in get("enemyModTables"):
            drop = _num(e.get("enemyModDropChance") or e.get("ememyModDropChance"))
            for it in e.get("mods", []):
                add(("enemy", e.get("enemyName", ""), f"MODドロップ {drop:g}%", "-", it.get("modName", ""),
                     drop * _num(it.get("chance")) / 100, it.get("rarity", "")))
        # 敵: 設計図・パーツ
        for b in get("blueprintLocations"):
            for e in b.get("enemies", []):
                drop = _num(e.get("enemyBlueprintDropChance"))
                add(("enemy", e.get("enemyName", ""), f"設計図ドロップ {drop:g}%", "-",
                     b.get("blueprintName") or b.get("itemName", ""), drop * _num(e.get("chance")) / 100, e.get("rarity", "")))
        # 敵: その他アイテム
        for e in get("miscItems"):
            drop = _num(e.get("enemyItemDropChance"))
            for it in e.get("items", []):
                add(("enemy", e.get("enemyName", ""), f"アイテムドロップ {drop:g}%", "-", it.get("itemName", ""),
                     drop * _num(it.get("chance")) / 100, it.get("rarity", "")))
        # バウンティ (ローテーション A/B/C × ステージ)
        for name in BOUNTY_JA:
            for e in get(name):
                label = _bounty_label(name, e.get("bountyLevel", ""))
                rewards = e.get("rewards") or {}
                for rot, lst in (rewards.items() if isinstance(rewards, dict) else [("-", rewards)]):
                    for it in lst or []:
                        add(("bounty", label, _stage_ja(it.get("stage", "")), rot, it.get("itemName", ""),
                             _num(it.get("chance")), it.get("rarity", "")))
        # レリック
        for r in get("relics"):
            if r.get("state") not in RELIC_STATES:
                continue
            label = f"{ERA_JA.get(r.get('tier'), r.get('tier'))} {r.get('relicName')} 遺物"
            for it in r.get("rewards", []):
                add(("relic", label, RELIC_STATE_JA.get(r["state"], r["state"]), "-", it.get("itemName", ""),
                     _num(it.get("chance")), it.get("rarity", "")))
        # ソーティー
        for it in get("sortieRewards"):
            add(("sortie", "ソーティー", "最終報酬", "-", it.get("itemName", ""), _num(it.get("chance")), it.get("rarity", "")))
        # 特殊ミッション (仲裁・遺棄船・ナイトメア等) とキー・ボス
        for name, cat, field in (("transientRewards", "special", "objectiveName"), ("keyRewards", "key", "keyName")):
            for e in get(name):
                rewards = e.get("rewards") or []
                groups = rewards.items() if isinstance(rewards, dict) else [(None, rewards)]
                for rot, lst in groups:
                    for it in lst or []:
                        add((cat, e.get(field, ""), _stage_ja(it.get("stage", "")), rot or it.get("rotation") or "-",
                             it.get("itemName", ""), _num(it.get("chance")), it.get("rarity", "")))
        self.rows = [r for r in self.rows if r[4]]
        self.item_names = sorted({r[4] for r in self.rows})

    @classmethod
    def load(cls, d: Path) -> "Sources":
        files = {}
        for name in WFCD_EXTRA:
            f = d / "wfcd" / f"{name}.json"
            if f.exists():
                try:
                    files[name] = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
        return cls(files)


def stage_label(rot: str) -> str:
    return "—" if rot in ("-", "", None) else f"ローテ{rot}"


def find_sources(key: str, drops: "Drops", sources: Sources | None, names: Names, events: bool = False) -> list[dict]:
    """項目(英名)の入手先を、ミッション・敵・バウンティ・レリック等すべてから集めて確率の高い順に返す。"""
    k = item_key(key)
    out = []
    for planet, node, mode, event, rot, item, chance, rarity in drops.rows:
        if item_key(item) == k and (events or not event):
            out.append({"cat": "mission", "place": f"{PLANETS_JA.get(planet, planet)} / {node}", "planet": PLANETS_JA.get(planet, planet),
                        "node": node, "detail": MODES_JA.get(mode, mode), "event": event, "stage": stage_label(rot),
                        "qty": names.split_qty(item)[0], "chance": chance, "rarity": rarity})
    for cat, place, detail, rot, item, chance, rarity in (sources.rows if sources else []):
        if item_key(item) == k:
            out.append({"cat": cat, "place": place, "planet": "", "node": place, "detail": detail, "event": False,
                        "stage": stage_label(rot), "qty": names.split_qty(item)[0], "chance": chance, "rarity": rarity})
    order = {c: i for i, c in enumerate(SOURCE_CATS)}
    out.sort(key=lambda r: (-r["chance"], order.get(r["cat"], 99), r["place"]))
    for r in out:
        r["cat_ja"] = SOURCE_CATS.get(r["cat"], r["cat"])
        r["rarity_ja"] = RARITY_JA.get(r["rarity"], r["rarity"])
    return out


def pct(x: float) -> str:
    return f"{x:.2f}%"


# --------------------------------------------------------------------------
# コマンド: update
# --------------------------------------------------------------------------

def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding", "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
            import gzip
            data = gzip.decompress(data)
    return data


def parse_json_bytes(raw: bytes):
    """先頭の BOM や文字コードの違いを吸収して JSON を読む。

    公式の weeklyRivensPC.json は名前に反して JSON ではなく、JavaScript の書き方
    (キーに引用符なし・文字列が '...')なので、JSON として読めなければ parse_js_literal で読む。
    """
    text = raw.decode("utf-8-sig", "replace")
    try:
        return json.loads(text)
    except ValueError as e:
        try:
            return parse_js_literal(text)
        except ValueError:
            raise e from None


def parse_js_literal(text: str):
    """JavaScript のデータの書き方(オブジェクト・配列・文字列・数値・true/false/null)を読む。

    eval は使わず、データとして許す書き方だけを1文字ずつ解釈する。対応するもの:
    引用符なしのキー / '...' と "..." の文字列 / 末尾の余分なカンマ / // と /* */ のコメント /
    undefined・NaN・Infinity (null として扱う)
    """
    n, i = len(text), 0
    esc = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0", "/": "/", "\\": "\\", "'": "'", '"': '"'}

    def err(msg):
        line = text.count("\n", 0, i) + 1
        return ValueError(f"{msg} (行 {line}, {i} 文字目)")

    def skip():
        nonlocal i
        while i < n:
            c = text[i]
            if c in " \t\r\n﻿":
                i += 1
            elif text.startswith("//", i):
                j = text.find("\n", i)
                i = n if j < 0 else j + 1
            elif text.startswith("/*", i):
                j = text.find("*/", i + 2)
                if j < 0:
                    raise err("コメントが閉じていません")
                i = j + 2
            else:
                break

    def string():
        nonlocal i
        q = text[i]
        i += 1
        out = []
        while i < n:
            c = text[i]
            if c == q:
                i += 1
                return "".join(out)
            if c == "\\":
                i += 1
                if i >= n:
                    break
                c = text[i]
                if c == "u":
                    out.append(chr(int(text[i + 1:i + 5], 16)))
                    i += 5
                    continue
                if c == "x":
                    out.append(chr(int(text[i + 1:i + 3], 16)))
                    i += 3
                    continue
                if c == "\n":  # 行の継続
                    i += 1
                    continue
                out.append(esc.get(c, c))
                i += 1
                continue
            out.append(c)
            i += 1
        raise err("文字列が閉じていません")

    def word():
        nonlocal i
        m = re.compile(r"[A-Za-z_$][\w$]*|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|[+-]?Infinity").match(text, i)
        if not m:
            raise err("読めない文字があります")
        i = m.end()
        return m.group(0)

    def value():
        nonlocal i
        skip()
        if i >= n:
            raise err("データが途中で終わっています")
        c = text[i]
        if c == "{":
            i += 1
            obj = {}
            while True:
                skip()
                if i < n and text[i] == "}":
                    i += 1
                    return obj
                key = string() if text[i] in "'\"" else word()
                skip()
                if i >= n or text[i] != ":":
                    raise err("':' がありません")
                i += 1
                obj[key] = value()
                skip()
                if i < n and text[i] == ",":
                    i += 1
                elif i < n and text[i] == "}":
                    continue
                else:
                    raise err("',' か '}' がありません")
        if c == "[":
            i += 1
            arr = []
            while True:
                skip()
                if i < n and text[i] == "]":
                    i += 1
                    return arr
                arr.append(value())
                skip()
                if i < n and text[i] == ",":
                    i += 1
                elif i < n and text[i] == "]":
                    continue
                else:
                    raise err("',' か ']' がありません")
        if c in "'\"":
            return string()
        w = word()
        if w in ("true", "false"):
            return w == "true"
        if w in ("null", "undefined", "NaN") or w.lstrip("+-") == "Infinity":
            return None
        try:
            return float(w) if any(ch in w for ch in ".eE") else int(w)
        except ValueError:
            raise err(f"読めない値です: {w}")

    result = value()
    skip()
    if i < n:
        raise err("データの後ろに余分な文字があります")
    return result


def decompress_lzma_alone(raw: bytes) -> bytes:
    """旧形式 .lzma (LZMA_Alone) を展開する。

    公式の index_*.txt.lzma は「ヘッダーに展開後サイズあり」かつ「終端マーカーあり」の形式で、
    Windows 版 Python に同梱される古い liblzma (5.4 未満) では lzma.decompress が
    "Corrupt input data" で失敗する。そのため 13 バイトのヘッダーを自前で読み、
    本体を RAW 形式の LZMA1 として展開する(RAW は終端マーカーの有無を問わない)。
    """
    if len(raw) < 13:
        raise lzma.LZMAError("LZMA データが短すぎます")
    props, dict_size = raw[0], int.from_bytes(raw[1:5], "little")
    size = int.from_bytes(raw[5:13], "little")
    if props >= 9 * 5 * 5:
        raise lzma.LZMAError("LZMA ヘッダーが不正です")
    pb, rest = divmod(props, 45)
    lp, lc = divmod(rest, 9)
    filt = {"id": lzma.FILTER_LZMA1, "dict_size": max(dict_size, 4096), "lc": lc, "lp": lp, "pb": pb}
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[filt])
    out = dec.decompress(raw[13:])
    if size != 0xFFFF_FFFF_FFFF_FFFF:  # サイズが書かれていれば、それ以降(余分なデータ)は捨てる
        if len(out) < size:
            raise lzma.LZMAError(f"展開結果が不足しています ({len(out)} / {size} バイト)")
        out = out[:size]
    return out


def decompress_lzma(raw: bytes) -> bytes:
    try:
        return lzma.decompress(raw)
    except lzma.LZMAError:
        return decompress_lzma_alone(raw)


def fetch_export(lang: str) -> list[dict]:
    """公式サイトから直接取得する(予備)。"""
    raw = http_get(f"{EXPORT_BASE}/index_{lang}.txt.lzma")
    text = decompress_lzma(raw).decode("utf-8", "replace")
    docs = []
    for line in text.splitlines():
        if line.startswith(EXPORT_PREFIXES):
            print(f"  取得: {line.split('!')[0]}")
            docs.append(parse_export_json(http_get(f"{EXPORT_BASE}/Manifest/{line}").decode("utf-8", "replace")))
    return docs


def fetch_export_github(lang: str) -> list[dict]:
    """calamity-inc/warframe-public-export (展開済み JSON) から取得する。"""
    docs = []
    for prefix in EXPORT_PREFIXES:
        print(f"  取得: {prefix}_{lang}.json")
        docs.append(parse_export_json(http_get(f"{EXPORT_GITHUB}/{prefix}_{lang}.json", timeout=120).decode("utf-8", "replace")))
    return docs


def fetch_names(docs_out: dict | None = None) -> dict:
    """名前辞書を作る。docs_out を渡すと、取得した Export (en / ja) と取得元をそこに入れる(シミュレータ用データに使う)"""
    errors = []
    for label, fetch in (("GitHub (calamity-inc/warframe-public-export)", fetch_export_github),
                         ("公式 Public Export", fetch_export)):
        print(f"  取得元: {label}")
        try:
            en_docs, ja_docs = fetch("en"), fetch("ja")
            names = names_from_exports(en_docs, ja_docs)
            names["source"] = label
            if docs_out is not None:
                docs_out.update(en=en_docs, ja=ja_docs, source=label)
            return names
        except Exception as e:  # noqa: BLE001
            print(f"  失敗: {e}")
            errors.append(f"{label}: {e}")
    raise RuntimeError(" / ".join(errors))


def fetch_json(urls: list[str], verbose: bool = False) -> bytes:
    """候補 URL を順に試し、JSON として読めた最初の内容を返す。"""
    errors = []
    for url in urls:
        try:
            raw = http_get(url)
            parse_json_bytes(raw)
            if verbose:
                print(f"  取得元: {url}")
            return raw
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url} ({e})")
            if verbose:
                print(f"  失敗: {url} ({e})")
    raise RuntimeError(" / ".join(errors))


def normalize_rivens(raw) -> list[dict]:
    """Riven 相場を [{itemType, compatibility, rerolled, avg, ...}] の形にそろえる。

    公式 weeklyRivensPC.json はこの形の配列。WFCD (api.warframestat.us/pc/rivens) は
    {武器種: {武器名: {"unrolled": {...}, "rerolled": {...}}}} の入れ子で、未開封は "Veiled ○○ Riven Mod"。
    """
    if isinstance(raw, dict):
        for key in ("rivens", "data", "items"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if isinstance(raw, list):
        rows = [e for e in raw if isinstance(e, dict) and e.get("itemType")]
    elif isinstance(raw, dict):
        rows = []
        for item_type, weapons in raw.items():
            if not isinstance(weapons, dict):
                continue
            for weapon, kinds in weapons.items():
                if not isinstance(kinds, dict):
                    continue
                for kind, st in kinds.items():
                    if isinstance(st, dict) and kind in ("unrolled", "rerolled"):
                        rows.append({**st, "itemType": st.get("itemType") or item_type,
                                     "compatibility": st.get("compatibility", weapon), "rerolled": kind == "rerolled"})
    else:
        rows = []
    for e in rows:
        c = e.get("compatibility")
        if not c or str(c).lower().startswith("veiled ") or str(c).strip().lower() == "null":
            e["compatibility"] = None
    return rows


def update_rivens(d: Path) -> bool:
    """Riven 相場だけを取得し直す(データ更新の一部 / 「Riven相場だけ更新」ボタン / riven --update)"""
    print("Riven 相場(公式・週次)を取得中...")
    try:
        rows = normalize_rivens(parse_json_bytes(fetch_json(RIVENS_URLS, verbose=True)))
        if not rows:
            raise RuntimeError("Riven 相場のデータが空でした")
        (d / "rivens.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"  {len(rows)} 件取得しました")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  失敗しました: {e}  ※前回取得分があればそれを使います")
        return False


def cmd_update(args):
    d = data_dir(args.data_dir)
    print("ドロップ表を取得中...")
    raw = None
    for url in DROPS_URLS:
        try:
            raw = http_get(url)
            json.loads(raw)
            print(f"  取得元: {url}")
            break
        except Exception as e:  # noqa: BLE001
            print(f"  失敗: {url} ({e})")
            raw = None
    if raw is None:
        sys.exit("ドロップ表を取得できませんでした。ネットワーク設定を確認してください。")
    (d / "missionRewards.json").write_bytes(raw)

    print("追加の入手先(敵・バウンティ・レリック等)を取得中...")
    (d / "wfcd").mkdir(exist_ok=True)
    ok_extra = 0
    for name in WFCD_EXTRA:
        try:
            (d / "wfcd" / f"{name}.json").write_bytes(fetch_json([f"{b}/{name}.json" for b in WFCD_BASES]))
            ok_extra += 1
        except Exception as e:  # noqa: BLE001
            print(f"  失敗: {name} ({e})  ※前回取得分があればそれを使います")
    print(f"  {ok_extra} / {len(WFCD_EXTRA)} ファイル取得")

    update_rivens(d)

    print("名前辞書(Public Export)を取得中...")
    docs: dict = {}
    try:
        names = fetch_names(docs)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"名前辞書を取得できませんでした: {e}")
    names["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (d / "names.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    print(f"完了: 名前 {len(names['en2ja'])} 件 / 素材 {len(names['resources'])} 件 / MOD {len(names['mods'])} 件 -> {d}")

    # シミュレータ用のデータ(フレーム・武器の性能)も、同じ Export から作る(追加のダウンロードはしない)
    try:
        import wfportal_builder as wb
        sim = wb.save_builder_data(d, wb.extract_builder_data(docs["en"], docs["ja"]), docs["source"])
        print(f"シミュレータ用データ: フレーム {len(sim['frames'])} 件 / 武器 {len(sim['weapons'])} 件")
    except Exception as e:  # noqa: BLE001
        print(f"  シミュレータ用データを作れませんでした: {e}  ※前回取得分があればそれを使います")

    if not find_logos_dir(d):  # 初回(ロゴ素材が未取得)のときだけ取得する
        fetch_logos(d)


# --------------------------------------------------------------------------
# コマンド: logos (公式ファンキットのロゴ素材を取得)
# --------------------------------------------------------------------------

def logos_dirs(d: Path | None = None) -> list[Path]:
    """ロゴ素材の置き場の候補(優先順)。ツールのフォルダに書けなければデータ置き場を使う"""
    dirs = [APP_DIR / "assets" / "Logos"]
    if d is not None:
        dirs.append(d / "Logos")
    return dirs


def find_logos_dir(d: Path | None = None) -> Path | None:
    """取得済みのロゴ素材の置き場(LotusFlower.png がある所)。無ければ None"""
    for p in logos_dirs(d):
        if (p / "LotusFlower.png").is_file():
            return p
    return None


def extract_logos(raw: bytes, dest: Path) -> int:
    """Dropbox のフォルダ zip からロゴ画像だけを dest に展開する。展開したファイル数を返す。

    zip の中の先頭の "Logos/" は取り除き、Focus/ や Syndicates/ などのサブフォルダはそのまま残す。
    画像以外のファイルや、dest の外に出る名前(../ など)は無視する。
    """
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise RuntimeError("ダウンロードした内容が zip ではありませんでした(配布元の仕様が変わった可能性があります)")
    count = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > LOGO_MAX_BYTES:
            raise RuntimeError("展開後のサイズが大きすぎるため中止しました")
        dest_root = dest.resolve()
        for info in infos:
            parts = [x for x in info.filename.replace("\\", "/").split("/") if x not in ("", ".")]
            if parts and parts[0].lower() == "logos":
                parts = parts[1:]
            if not parts or ".." in parts or not parts[-1].lower().endswith(LOGO_EXTS):
                continue
            out = dest.joinpath(*parts)
            if dest_root not in out.resolve().parents:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(info))
            count += 1
    if count == 0:
        raise RuntimeError("zip の中にロゴ画像が見つかりませんでした")
    return count


def fetch_logos(d: Path | None = None, force: bool = False) -> Path | None:
    """公式ファンキットの Logos を取得して保存する。失敗しても例外にせず None を返す(ツールはロゴ無しで動く)"""
    have = find_logos_dir(d)
    if have and not force:
        print(f"ロゴ素材は取得済みです: {have}")
        return have
    print("公式ファンキット(Warframe Fan Kit)のロゴ素材を取得中...")
    print(f"  配布元: Digital Extremes 公式 ({FANKIT_PAGE})")
    try:
        raw = http_get(FANKIT_LOGOS_URL, timeout=180)
    except Exception as e:  # noqa: BLE001
        print(f"  失敗しました: {e}")
        print("  ※ロゴ無しでもツールは使えます。あとで「python wfportal.py logos」で取り直せます。")
        return None
    last_err = None
    for dest in logos_dirs(d):
        try:
            n = extract_logos(raw, dest)
            print(f"  {n} ファイルを保存しました -> {dest}")
            print("  ※ロゴ素材の権利は Digital Extremes にあります。個人の利用にとどめ、再配布しないでください。")
            return dest
        except PermissionError as e:
            last_err = e  # ツールのフォルダに書けないときは次の候補へ
        except Exception as e:  # noqa: BLE001
            last_err = e
            break
    print(f"  保存に失敗しました: {last_err}")
    print("  ※ロゴ無しでもツールは使えます。あとで「python wfportal.py logos」で取り直せます。")
    return None


def cmd_logos(args):
    d = data_dir(args.data_dir)
    if args.if_missing and find_logos_dir(d):
        return
    fetch_logos(d, force=args.force)


# --------------------------------------------------------------------------
# コマンド: item (逆引き)
# --------------------------------------------------------------------------

def all_item_names(drops: Drops, sources: Sources | None) -> list[str]:
    return sorted(set(drops.item_names) | set(sources.item_names if sources else []))


def pick_candidates(query: str, item_names, names: Names, materials_only: bool) -> list[str]:
    if isinstance(item_names, Drops):  # 以前の呼び方 (ドロップ表を直接渡す) にも対応
        item_names = item_names.item_names
    scored = []
    for n in item_names:
        if materials_only and not names.is_resource(n):
            continue
        r = rank(query, [n, names.ja(n), names.split_qty(n)[1]])
        if r is not None:
            scored.append((r, norm(names.ja(n)), n))
    scored.sort()
    return [n for _, _, n in scored]


def group_candidates(cands: list[str], names: Names) -> dict[str, str]:
    """候補を数量違い・大文字小文字違いで束ねる -> {キー: 表示に使う英名}"""
    groups: dict[str, str] = {}
    for n in cands:
        groups.setdefault(item_key(n), names.split_qty(n)[1])
    return groups


def cmd_item(args):
    d = data_dir(args.data_dir)
    drops, names, sources = Drops.load(d), Names.load(d), Sources.load(d)
    query = " ".join(args.query)
    cands = pick_candidates(query, all_item_names(drops, sources), names, materials_only=not args.all)
    if not cands:
        hint = "" if args.all else " (素材以外も探すには --all)"
        sys.exit(f"「{query}」に一致する項目がありません。{hint}")
    groups = group_candidates(cands, names)
    keys = list(groups.values())
    exact = [k for k in keys if norm(query) in (norm(k), norm(names.ja(k)))]
    if exact:
        keys = exact[:1]
    elif len(keys) > 1 and not args.pick:
        print(f"「{query}」の候補が {len(keys)} 件あります。--pick 番号 で選ぶか、もう少し具体的に入力してください。")
        for i, k in enumerate(keys[:30], 1):
            print(f"  {i:>2}. {names.ja(k)}  ({k})")
        return
    if args.pick:
        if not 1 <= args.pick <= len(keys):
            sys.exit("--pick の番号が範囲外です。")
        keys = [keys[args.pick - 1]]

    base = keys[0]
    rows = find_sources(base, drops, sources, names, events=args.events)
    if args.cat:
        rows = [r for r in rows if r["cat"] in args.cat]
    print(f"■ {names.ja(base)}  ({base})  — {len(rows)} か所\n")
    out = [[r["cat_ja"], r["place"] + (" [イベント]" if r["event"] else ""), r["detail"], r["stage"],
            (f"{r['qty']}個 " if r["qty"] else "") + pct(r["chance"]), r["rarity_ja"]] for r in rows[: args.limit]]
    print_table(["種類", "入手先", "詳細", "ステージ", "確率", "レア度"], out, right_cols=(4,))
    if len(rows) > args.limit:
        print(f"\n(上位 {args.limit} 件を表示。--limit で変更できます)")
    print("\n確率: ミッション/バウンティは報酬1回の抽選で選ばれる割合、敵は1体倒したときに落とす割合、"
          "レリックは開けたときに出る割合です。")


# --------------------------------------------------------------------------
# コマンド: area
# --------------------------------------------------------------------------

def cmd_area(args):
    d = data_dir(args.data_dir)
    drops, names = Drops.load(d), Names.load(d)
    query = " ".join(args.query)
    planet_hits = [p for p in drops.planets if rank(query, [p, PLANETS_JA.get(p, p)]) is not None]
    exact_planet = [p for p in planet_hits if norm(query) in (norm(p), norm(PLANETS_JA.get(p, p)))]
    if exact_planet:
        planet_hits = exact_planet
    node_hits = [] if planet_hits else [(p, n) for p, n in drops.node_order if rank(query, [n]) is not None]
    if not planet_hits and not node_hits:
        sys.exit(f"「{query}」に一致するエリア/ノードがありません。")
    targets = [(p, n) for p, n in drops.node_order if p in planet_hits] if planet_hits else node_hits
    if len(targets) > 1 and not planet_hits and not args.all_nodes:
        exact = [t for t in targets if norm(t[1]) == norm(query)]
        targets = exact or targets

    materials_only = not args.all
    for planet, node in targets:
        rows = [r for r in drops.rows if r[0] == planet and r[1] == node]
        if not rows:
            continue
        mode, event = rows[0][2], rows[0][3]
        if event and not args.events:
            continue
        out = []
        by_rot: dict[str, list] = {}
        for r in rows:
            if materials_only and not names.is_resource(r[5]):
                continue
            by_rot.setdefault(r[4], []).append(r)
        for rot in sorted(by_rot):
            first = True
            for r in sorted(by_rot[rot], key=lambda x: -x[6]):
                out.append([stage_label(rot) if first else "", names.ja(r[5]), pct(r[6]), RARITY_JA.get(r[7], r[7])])
                first = False
        if not out and len(targets) > 1:
            continue  # 素材が出ないノードは一覧から省く
        print(f"\n■ {PLANETS_JA.get(planet, planet)} / {node} — {MODES_JA.get(mode, mode)}" + (" [イベント]" if event else ""))
        if out:
            print_table(["ステージ", "素材", "確率", "レア度"], out, right_cols=(2,))
        else:
            print("  (素材のドロップはありません。--all でMODや設計図も表示)")


# --------------------------------------------------------------------------
# コマンド: cycle (昼夜サイクルとリセット)
# --------------------------------------------------------------------------
# 公式APIに接続できない環境でも動くよう、周期から計算します。
# 初回だけ、ゲーム内で見た残り時間で時刻合わせ(set)をしてください。
#   Cetus  : 150分周期 (昼100分 + 夜50分)   Cambion Drift は Cetus に連動 (昼=Fass / 夜=Vome)
#   Vallis : 1600秒周期 (温暖400秒 + 寒冷1200秒)

CYCLES = {
    "cetus": {"name": "平原 (Cetus)", "total": 9000, "first": ("day", "昼", 6000), "second": ("night", "夜", 3000)},
    "vallis": {"name": "オーブ峡谷 (Orb Vallis)", "total": 1600, "first": ("warm", "温暖", 400), "second": ("cold", "寒冷", 1200)},
}
PHASE_ALIASES = {"day": "day", "昼": "day", "night": "night", "夜": "night",
                 "warm": "warm", "温暖": "warm", "cold": "cold", "寒冷": "cold"}


def parse_remaining(s: str) -> int:
    parts = [int(x) for x in s.split(":")]
    if len(parts) == 1:
        return parts[0] * 60  # 数字だけなら分
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt_dur(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}時間{m:02d}分{s:02d}秒" if h else f"{m}分{s:02d}秒"


def cycle_state(key: str, anchor: float, now: float) -> tuple[str, str, float]:
    c = CYCLES[key]
    pos = (now - anchor) % c["total"]
    (k1, j1, l1), (k2, j2, l2) = c["first"], c["second"]
    if pos < l1:
        return k1, j1, l1 - pos
    return k2, j2, c["total"] - pos


def cycle_anchor(key: str, phase: str | None, remaining: float, now: float) -> float:
    """「いま phase で残り remaining 秒」から、周期の先頭時刻を逆算する。"""
    c = CYCLES[key]
    valid = {c["first"][0]: c["first"], c["second"][0]: c["second"]}
    if phase not in valid:
        raise ValueError(f"フェーズは {' / '.join(v[1] for v in valid.values())} のいずれかを指定してください。")
    length = valid[phase][2]
    if not 0 < remaining <= length:
        raise ValueError(f"残り時間が範囲外です(このフェーズは最長 {fmt_dur(length)})。")
    phase_start = now + remaining - length
    return phase_start if phase == c["first"][0] else phase_start - c["first"][2]


def next_daily_reset(now: datetime) -> datetime:
    base = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(days=1)


def next_weekly_reset(now: datetime) -> datetime:
    base = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(days=7 - base.weekday())  # 次の月曜 0:00 UTC


def cmd_cycle(args):
    d = data_dir(args.data_dir)
    f = d / "cycles.json"
    store = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    now = time.time()
    if args.action == "set":
        key = args.target.lower()
        if key not in CYCLES:
            sys.exit("set の対象は cetus か vallis です。")
        phase = PHASE_ALIASES.get(args.phase.lower() if args.phase else "", None)
        try:
            store[key] = cycle_anchor(key, phase, parse_remaining(args.remaining), now)
        except ValueError as e:
            sys.exit(str(e))
        f.write_text(json.dumps(store), encoding="utf-8")
        print("時刻合わせを保存しました。")
    jst = timezone(timedelta(hours=9))
    nowdt = datetime.now(jst)
    print(f"現在 {nowdt:%Y-%m-%d %H:%M:%S} JST\n")
    for key, c in CYCLES.items():
        if key not in store:
            ex = "45:30" if key == "cetus" else "3:20"
            print(f"{c['name']}: 未設定  (例: cycle set {key} {c['first'][1]} {ex})")
            continue
        k, jp, left = cycle_state(key, store[key], now)
        end = datetime.fromtimestamp(now + left, jst)
        print(f"{c['name']}: {jp}  残り {fmt_dur(left)}  (切替 {end:%H:%M:%S})")
        if key == "cetus":
            print(f"カンビオンの荒地: {'Fass(昼)' if k == 'day' else 'Vome(夜)'}  (Cetus と連動)")
    dr, wr = next_daily_reset(nowdt), next_weekly_reset(nowdt)
    print(f"\nデイリーリセットまで  {fmt_dur((dr - nowdt).total_seconds())}  ({dr.astimezone(jst):%m/%d %H:%M} JST)")
    print(f"ウィークリーリセットまで {fmt_dur((wr - nowdt).total_seconds())}  ({wr.astimezone(jst):%m/%d %H:%M} JST)")


# --------------------------------------------------------------------------
# MOD 入手一覧
# --------------------------------------------------------------------------

def load_owned(d: Path) -> set[str]:
    f = d / "mods_owned.json"
    return {x.lower() for x in json.loads(f.read_text(encoding="utf-8"))} if f.exists() else set()


def save_owned(d: Path, owned: set[str]) -> None:
    (d / "mods_owned.json").write_text(json.dumps(sorted(owned), ensure_ascii=False), encoding="utf-8")


def mod_table(names: Names, drops: Drops | None, sources: Sources | None, owned: set[str] | None = None) -> list[dict]:
    """MOD ごとに入手先の件数と、もっとも確率の高い入手先をまとめる。"""
    idx: dict[str, list[tuple]] = {}
    for planet, node, mode, event, rot, item, chance, rarity in (drops.rows if drops else []):
        if not event:
            idx.setdefault(item_key(item), []).append(
                ("mission", f"{PLANETS_JA.get(planet, planet)} / {node}", MODES_JA.get(mode, mode), stage_label(rot), chance))
    for cat, place, detail, rot, item, chance, rarity in (sources.rows if sources else []):
        idx.setdefault(item_key(item), []).append((cat, place, detail, stage_label(rot), chance))
    owned = owned or set()
    out = []
    for m in names.mods:
        src = idx.get(m["en"].lower(), [])
        counts: dict[str, int] = {}
        for s in src:
            counts[s[0]] = counts.get(s[0], 0) + 1
        best = max(src, key=lambda s: s[4]) if src else None
        out.append({
            **m, "type_ja": MOD_TYPES.get(m["type"], m["type"]), "compat_ja": COMPAT_JA.get(m.get("compat", ""), m.get("compat", "")), "polarity_name": POLARITY_EN.get(m["polarity"], m["polarity"]),
            "rarity_ja": RARITY_JA.get(m["rarity"], m["rarity"]), "owned": m["en"].lower() in owned,
            "counts": {c: counts[c] for c in SOURCE_CATS if c in counts}, "total": len(src),
            "best": {"cat": best[0], "cat_ja": SOURCE_CATS[best[0]], "place": best[1], "detail": best[2],
                     "stage": best[3], "chance": best[4]} if best else None,
        })
    return out


def cmd_mods(args):
    d = data_dir(args.data_dir)
    names = Names.load(d)
    if not names.mods:
        sys.exit("MOD の情報がありません。`python wfportal.py update` を実行してください。")
    owned = load_owned(d)
    args.action = "list"
    if args.query and args.query[0] in ("list", "own", "unown"):
        args.action, args.query = args.query[0], args.query[1:]
    if args.action in ("own", "unown"):
        q = " ".join(args.query)
        hits = [m for m in names.mods if norm(q) in (norm(m["en"]), norm(m["ja"]))] or \
               [m for m in names.mods if rank(q, [m["en"], m["ja"]]) is not None]
        if len(hits) != 1:
            sys.exit(f"「{q}」に一致する MOD が {len(hits)} 件あります。名前を正確に入力してください。"
                     + ("".join(f"\n  {m['ja']} ({m['en']})" for m in hits[:15]) if hits else ""))
        m = hits[0]
        (owned.add if args.action == "own" else owned.discard)(m["en"].lower())
        save_owned(d, owned)
        print(f"{m['ja']} を{'所持済み' if args.action == 'own' else '未所持'}にしました。")
        return
    drops = Drops.load(d) if (d / "missionRewards.json").exists() else None
    rows = mod_table(names, drops, Sources.load(d), owned)
    if args.query:
        q = " ".join(args.query)
        scored = [(rank(q, [m["en"], m["ja"], m.get("compat", "")]), m) for m in rows]
        rows = [m for r, m in sorted((x for x in scored if x[0] is not None), key=lambda x: (x[0], x[1]["en"].lower()))]
    if args.type:
        rows = [m for m in rows if m["type"] == args.type.upper()]
    if args.unowned:
        rows = [m for m in rows if not m["owned"]]
    if not rows:
        sys.exit("条件に合う MOD がありません。")
    out = []
    for m in rows[: args.limit]:
        b = m["best"]
        out.append(["✓" if m["owned"] else "", m["ja"], m["type_ja"], m["polarity_name"], m["rarity_ja"],
                    " ".join(f"{SOURCE_CATS[c]}{n}" for c, n in m["counts"].items()) or "記載なし",
                    f"{b['cat_ja']}: {b['place']} {pct(b['chance'])}" if b else ""])
    print_table(["所持", "MOD", "種別", "極性", "レア度", "入手先(件数)", "最も確率が高い入手先"], out)
    print(f"\n{len(rows)} 件中 {min(len(rows), args.limit)} 件を表示 / 所持 {sum(m['owned'] for m in rows)} 件")
    print("「記載なし」はドロップ表に無いもの(シンジケート・バロ・ナイトウェーブ・クエスト報酬など)です。")


# --------------------------------------------------------------------------
# マスター一覧
# --------------------------------------------------------------------------

def load_mastered(d: Path) -> set[str]:
    f = d / "mastered.json"
    try:
        return set(json.loads(f.read_text(encoding="utf-8-sig"))) if f.exists() else set()
    except ValueError:
        return set()


def save_mastered(d: Path, done: set[str]) -> None:
    (d / "mastered.json").write_text(json.dumps(sorted(done), ensure_ascii=False, indent=0), encoding="utf-8")


def mastery_label(m: dict) -> str:
    """表示名。Kitgun はプライマリ版とセカンダリ版を区別する"""
    v = {"primary": "プライマリ", "secondary": "セカンダリ"}.get(m.get("variant", ""), "")
    return f"{m['ja']} ({v})" if v else m["ja"]


def mastery_table(names: Names, done: set[str]) -> list[dict]:
    return [{**m, "cat_ja": MASTERY_CATS.get(m["cat"], m["cat"]), "label": mastery_label(m), "done": m["id"] in done}
            for m in names.mastery]


def mastery_summary(rows: list[dict]) -> dict:
    out = {}
    for c in MASTERY_CATS:
        rs = [r for r in rows if r["cat"] == c]
        out[c] = {"total": len(rs), "done": sum(r["done"] for r in rs),
                  "xp": sum(r["xp"] for r in rs), "xp_done": sum(r["xp"] for r in rs if r["done"])}
    out["all"] = {k: sum(v[k] for v in out.values()) for k in ("total", "done", "xp", "xp_done")}
    return out


def cmd_mastery(args):
    d = data_dir(args.data_dir)
    names = Names.load(d)
    if not names.mastery:
        sys.exit("マスター一覧のデータがありません。`python wfportal.py update` を実行してください。")
    done = load_mastered(d)
    rows = mastery_table(names, done)
    action, query = "list", list(args.query)
    if query and query[0] in ("list", "done", "undo"):
        action, query = query[0], query[1:]
    q = " ".join(query)
    if args.cat:
        rows = [r for r in rows if r["cat"] == args.cat]
    if action in ("done", "undo"):
        hits = [r for r in rows if norm(q) in (norm(r["en"]), norm(r["ja"]), norm(r["label"]))] or \
               [r for r in rows if rank(q, [r["en"], r["ja"], r["label"]]) is not None]
        if not hits:
            sys.exit(f"「{q}」に一致するものがありません。")
        if len(hits) > 1 and len({norm(r["en"]) for r in hits}) > 1:
            sys.exit(f"「{q}」に一致するものが {len(hits)} 件あります。名前を正確に入力するか --cat で絞り込んでください。"
                     + "".join(f"\n  {r['label']} [{r['cat_ja']}]" for r in hits[:15]))
        for r in hits:  # Kitgun はプライマリ版・セカンダリ版の両方 (片方だけなら --cat と名前で指定)
            (done.add if action == "done" else done.discard)(r["id"])
        save_mastered(d, done)
        print("、".join(r["label"] for r in hits) + f" を{'マスター済み' if action == 'done' else '未マスター'}にしました。")
        return
    if q:
        rows = [r for r in rows if rank(q, [r["en"], r["ja"], r["label"]]) is not None]
    if args.todo:
        rows = [r for r in rows if not r["done"]]
    if not rows:
        sys.exit("条件に合うものがありません。")
    print_table(["済", "名前", "カテゴリー", "最大ランク", "マスタリー経験値"],
                [["✓" if r["done"] else "", r["label"], r["cat_ja"], str(r["rank"]), f"{r['xp']:,}"] for r in rows[: args.limit]],
                right_cols=(3, 4))
    summ = mastery_summary(mastery_table(names, done))
    print(f"\n{len(rows)} 件中 {min(len(rows), args.limit)} 件を表示")
    for c, label in MASTERY_CATS.items():
        v = summ[c]
        print(f"  {pad(label, 18)} {v['done']:>4} / {v['total']:<4}")
    a = summ["all"]
    print(f"  {pad('全体', 18)} {a['done']:>4} / {a['total']:<4}  マスタリー経験値 {a['xp_done']:,} / {a['xp']:,}")


# --------------------------------------------------------------------------
# アルケイン所持一覧
# --------------------------------------------------------------------------
# arcanes_owned.json: {"英語名(小文字)": ランク}。キーがあれば所持、値が今のランク(0〜最大ランク)

def load_arcanes_owned(d: Path) -> dict[str, int]:
    f = d / "arcanes_owned.json"
    try:
        raw = json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else {}
    except ValueError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k).lower(): v for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool) and v >= 0}


def save_arcanes_owned(d: Path, owned: dict[str, int]) -> None:
    (d / "arcanes_owned.json").write_text(json.dumps(dict(sorted(owned.items())), ensure_ascii=False, indent=0),
                                          encoding="utf-8")


def arcane_entries(names: Names, drop_items=()) -> list[dict]:
    """所持一覧に載せるアルケイン = 公式データの一覧 + ドロップ表にだけあるもの(ARCANE_DROP_ONLY_CATS のカテゴリー)

    drop_items: ドロップ表・入手先データの英語名 (all_item_names の結果)。ドロップ表だけのものは
    日本語名・レア度が無いため、日本語名は名前辞書にあれば使い(無ければ英語名)、レア度は空にする
    """
    out = list(names.arcane_list)
    known = {m["en"].lower() for m in out}
    for name in sorted(set(drop_items), key=str.lower):
        cat = arcane_cat(name)
        if cat in ARCANE_DROP_ONLY_CATS and name.lower() not in known:
            known.add(name.lower())
            out.append({"en": name, "ja": names._get(name) or name, "cat": cat, "rarity": "",
                        "max_rank": ARCANE_DROP_ONLY_MAX_RANK, "drop_only": True})
    order = list(ARCANE_CATS)
    return sorted(out, key=lambda m: (order.index(m["cat"]) if m["cat"] in order else len(order), m["en"].lower()))


def arcane_table(names: Names, owned: dict[str, int], drop_items=()) -> list[dict]:
    """所持状況つきの一覧。ランクは最大ランクを超えないように丸める(ゲーム側で最大ランクが下がった場合に備えて)"""
    out = []
    for m in arcane_entries(names, drop_items):
        k = m["en"].lower()
        out.append({**m, "cat_ja": ARCANE_CATS.get(m["cat"], m["cat"]),
                    "rarity_ja": RARITY_JA.get(m["rarity"], m["rarity"]), "owned": k in owned,
                    "rank": min(owned[k], m["max_rank"]) if k in owned else None})
    return out


def arcane_summary(rows: list[dict]) -> dict:
    """カテゴリーごと(と全体 "all")の 件数 / 所持数 / ランク最大の数"""
    out = {c: {"total": 0, "owned": 0, "maxed": 0} for c in ARCANE_CATS}
    for r in rows:
        o = out.setdefault(r["cat"], {"total": 0, "owned": 0, "maxed": 0})
        o["total"] += 1
        o["owned"] += r["owned"]
        o["maxed"] += r["owned"] and r["rank"] == r["max_rank"]
    out["all"] = {k: sum(v[k] for v in out.values()) for k in ("total", "owned", "maxed")}
    return out


class ArcaneNotFound(ValueError):
    """一覧に無いアルケイン名"""


def set_arcanes_owned(names: Names, owned: dict[str, int], targets: list[str], is_owned: bool,
                      rank_: int | None = None, drop_items=()) -> list[dict]:
    """所持状況を変更する(owned を書き換える。保存は呼び出し側)。変更したアルケインを返す

    - is_owned=False: 未所持にする(ランクも消える)
    - is_owned=True: 所持にする。rank_ を省くと、所持済みならランクはそのまま、未所持ならランク 0
    - 一覧に無い名前は ArcaneNotFound、0〜最大ランクの範囲外のランクは ValueError (どちらも何も変更しない)
    """
    by = {m["en"].lower(): m for m in arcane_entries(names, drop_items)}
    hits = []
    for en in targets:
        m = by.get(str(en).lower())
        if m is None:
            raise ArcaneNotFound(f"アルケインが見つかりません: {en}")
        if rank_ is not None and not (0 <= rank_ <= m["max_rank"]):
            raise ValueError(f"{m['en']} のランクは 0〜{m['max_rank']} です: {rank_}")
        hits.append(m)
    for m in hits:
        k = m["en"].lower()
        if not is_owned:
            owned.pop(k, None)
        else:
            owned[k] = rank_ if rank_ is not None else min(owned.get(k, 0), m["max_rank"])
    return hits


def cmd_arcane(args):
    d = data_dir(args.data_dir)
    names = Names.load(d)
    if not names.arcane_list:
        sys.exit("アルケインのデータがありません。`python wfportal.py update` を実行してください"
                 "(この機能を追加する前に取得したデータには含まれていません)。")
    owned = load_arcanes_owned(d)
    drop_items = all_item_names(Drops.load(d), Sources.load(d)) if (d / "missionRewards.json").exists() else []
    rows = arcane_table(names, owned, drop_items)
    action, query = "list", list(args.query)
    if query and query[0] in ("list", "own", "unown"):
        action, query = query[0], query[1:]
    q = " ".join(query)
    if args.cat:
        rows = [r for r in rows if r["cat"] == args.cat]
    if action in ("own", "unown"):
        hits = [r for r in rows if norm(q) in (norm(r["en"]), norm(r["ja"]))] or \
               [r for r in rows if rank(q, [r["en"], r["ja"]]) is not None]
        if not hits:
            sys.exit(f"「{q}」に一致するアルケインがありません。")
        if len(hits) > 1:
            sys.exit(f"「{q}」に一致するアルケインが {len(hits)} 件あります。名前を正確に入力してください。"
                     + "".join(f"\n  {r['ja']} [{r['cat_ja']}]" for r in hits[:15]))
        try:
            m, = set_arcanes_owned(names, owned, [hits[0]["en"]], action == "own", args.rank if action == "own" else None,
                                   drop_items)
        except ValueError as e:
            sys.exit(str(e))
        save_arcanes_owned(d, owned)
        print(f"{m['ja']} を" + (f"所持(ランク {owned[m['en'].lower()]})にしました。" if action == "own" else "未所持にしました。"))
        return
    if args.rank is not None:
        sys.exit("--rank は own と一緒に使います(例: python wfportal.py arcane own \"Arcane Energize\" --rank 5)。")
    if q:
        rows = [r for r in rows if rank(q, [r["en"], r["ja"]]) is not None]
    if args.unowned:
        rows = [r for r in rows if not r["owned"]]
    if not rows:
        sys.exit("条件に合うアルケインがありません。")
    print_table(["所持", "名前", "種類", "レア度", "ランク"],
                [["✓" if r["owned"] else "", r["ja"], r["cat_ja"], r["rarity_ja"] or "-", f"{r['rank'] if r['owned'] else '-'} / {r['max_rank']}"] for r in rows[: args.limit]],
                right_cols=(4,))
    summ = arcane_summary(arcane_table(names, owned, drop_items))
    print(f"\n{len(rows)} 件中 {min(len(rows), args.limit)} 件を表示")
    for c, label in list(ARCANE_CATS.items()) + [("all", "全体")]:
        v = summ[c]
        if v["total"]:
            print(f"  {pad(label, 18)} {v['owned']:>4} / {v['total']:<4} (ランク最大 {v['maxed']})")


# --------------------------------------------------------------------------
# Riven 相場
# --------------------------------------------------------------------------

def load_rivens(d: Path) -> list[dict] | None:
    f = d / "rivens.json"
    if not f.exists():
        return None
    try:
        rows = normalize_rivens(json.loads(f.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError):
        return None
    return rows or None


def riven_table(raw: list[dict], names: Names) -> list[dict]:
    """武器(と武器種)ごとに、未リロール/リロール済みの統計を1行にまとめる。"""
    rows: dict[tuple, dict] = {}
    for e in raw:
        t, weapon = e.get("itemType") or "", e.get("compatibility")
        key = (t, weapon or "")
        row = rows.setdefault(key, {
            "type": t, "type_ja": RIVEN_TYPES_JA.get(t, t.replace(" Riven Mod", "")),
            "veiled": not weapon, "weapon_en": weapon or "",
            "weapon_ja": names.ja(weapon.title() if weapon and weapon.isupper() else weapon) if weapon else "未開封(ヴェール)",
            "unrolled": None, "rerolled": None})
        row["rerolled" if e.get("rerolled") else "unrolled"] = {
            k: _num(e.get(k)) for k in ("median", "avg", "min", "max", "stddev", "pop")}
    out = list(rows.values())
    best = lambda r: max((s["median"] for s in (r["unrolled"], r["rerolled"]) if s), default=0)
    out.sort(key=lambda r: (-best(r), r["weapon_en"]))
    return out


def dispo_table(names: Names, rivens: list[dict] | None = None) -> list[dict]:
    """Riven 性質の一覧。性質の高い順(●5 -> 1)。Riven 相場があれば、プライマリのライフル/ショットガンはその武器種に合わせる"""
    market = {}
    for e in rivens or []:
        t, c = e.get("itemType"), e.get("compatibility")
        if c and t in ("Rifle Riven Mod", "Shotgun Riven Mod"):
            market[str(c).lower()] = t
    out = []
    for m in names.dispo:
        t = market.get(m["en"].lower(), m["type"]) if m["cat"] == "primary" else m["type"]
        label = RIVEN_TYPES_JA.get(t, t.replace(" Riven Mod", ""))
        if m["variant"]:
            label += f"({ {'primary': 'プライマリ', 'secondary': 'セカンダリ'}.get(m['variant'], m['variant']) })"
        out.append({**m, "type": t, "type_ja": label, "cat_ja": DISPO_CATS.get(m["cat"], m["cat"]),
                    "dots": dispo_dots(m["value"])})
    order = list(DISPO_CATS)
    out.sort(key=lambda r: (order.index(r["cat"]) if r["cat"] in order else 99, -r["value"], r["en"].lower(), r["variant"]))
    return out


def cmd_dispo(args):
    d = data_dir(args.data_dir)
    names = Names.load(d)
    if not names.dispo:
        sys.exit("Riven 性質のデータがありません。`python wfportal.py update` を実行してください。")
    rows = dispo_table(names, load_rivens(d))
    rows = [r for r in rows if r["cat"] == args.cat]
    if args.query:
        q = " ".join(args.query)
        rows = [r for r in rows if rank(q, [r["en"], r["ja"]]) is not None]
    if not rows:
        sys.exit("条件に合う武器がありません。")
    print_table(["武器区分", "武器名", "性質", "性質値"],
                [[r["type_ja"], r["ja"] if r["ja"] == r["en"] else f"{r['ja']} ({r['en']})", dispo_mark(r["dots"]), f"{r['value']:.2f}"]
                 for r in rows[: args.limit]], right_cols=(3,))
    print(f"\n{DISPO_CATS[args.cat]}: {len(rows)} 件中 {min(len(rows), args.limit)} 件を表示"
          "(性質値 0.5〜0.7 ●◯◯◯◯ / 〜0.9 ●●◯◯◯ / 〜1.10 ●●●◯◯ / 〜1.30 ●●●●◯ / 〜1.55 ●●●●●)")


def cmd_riven(args):
    d = data_dir(args.data_dir)
    if args.update and not update_rivens(d):
        sys.exit(1)
    raw = load_rivens(d)
    if raw is None:
        sys.exit("Riven 相場のデータがありません。`python wfportal.py update` を実行してください。")
    rows = riven_table(raw, Names.load(d))
    if args.query:
        q = " ".join(args.query)
        rows = [r for r in rows if rank(q, [r["weapon_en"], r["weapon_ja"], r["type_ja"]]) is not None]
    if args.type:
        rows = [r for r in rows if norm(args.type) in (norm(r["type_ja"]), norm(r["type"].split(" ")[0]))]
    if not rows:
        sys.exit("条件に合う Riven がありません。")
    stat = lambda s: f"{s['median']:g} ({s['min']:g}〜{s['max']:g}, {int(s['pop'])}件)" if s else "—"
    print_table(["武器", "武器種", "未リロール 中央値(最小〜最大, 件数)", "リロール済み 中央値(最小〜最大, 件数)"],
                [[r["weapon_ja"], r["type_ja"], stat(r["unrolled"]), stat(r["rerolled"])] for r in rows[: args.limit]])
    f = d / "rivens.json"
    print(f"\n単位はプラチナ(PC 版・公式の週次統計 / {datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d} 取得)。"
          "極端な出品価格が混ざるため、平均より中央値が目安になります。")


# --------------------------------------------------------------------------
# ビルドの画像
# --------------------------------------------------------------------------

IMAGE_DIR = "build_images"
IMAGE_MAX_BYTES = 20 * 1024 * 1024
IMAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")
IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def image_ext(data: bytes) -> str | None:
    """中身(先頭のバイト列)から画像の種類を判定する。拡張子や申告は信用しない。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_build_image(d: Path, data: bytes) -> str:
    if len(data) > IMAGE_MAX_BYTES:
        raise ValueError(f"画像が大きすぎます(上限 {IMAGE_MAX_BYTES // 1024 // 1024}MB)。")
    ext = image_ext(data)
    if not ext:
        raise ValueError("PNG / JPEG / GIF / WebP の画像を選んでください。")
    import uuid
    folder = d / IMAGE_DIR
    folder.mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (folder / name).write_bytes(data)
    return name


def build_image_path(d: Path, name: str) -> Path | None:
    if not IMAGE_NAME_RE.match(name or ""):
        return None
    p = d / IMAGE_DIR / name
    return p if p.is_file() else None


def delete_build_images(d: Path, names_: list[str]) -> None:
    for n in names_:
        if p := build_image_path(d, n):
            p.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# コマンド: build (ビルド管理)
# --------------------------------------------------------------------------

def load_builds(d: Path) -> list[dict]:
    f = d / "builds.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save_builds(d: Path, builds: list[dict]) -> None:
    (d / "builds.json").write_text(json.dumps(builds, ensure_ascii=False, indent=2), encoding="utf-8")


def find_build(builds: list[dict], name: str) -> dict | None:
    hits = [b for b in builds if norm(b["name"]) == norm(name)] or [b for b in builds if norm(name) in norm(b["name"])]
    return hits[0] if len(hits) == 1 else None


def cmd_build(args):
    d = data_dir(args.data_dir)
    builds = load_builds(d)
    act = args.action
    if act == "list":
        rows = [b for b in builds if not args.type or b["type"] == args.type]
        if args.query:
            q = " ".join(args.query)
            rows = [b for b in rows if rank(q, [b["name"], b.get("target", ""), *b.get("tags", [])]) is not None]
        if not rows:
            print("ビルドがありません。`build add` で登録できます。")
            return
        print_table(["名前", "種別", "対象", "フォーマ", "MOD数", "画像", "タグ"],
                    [[b["name"], BUILD_TYPES.get(b["type"], b["type"]), b.get("target", ""), str(b.get("forma", 0)),
                      str(len(b.get("mods", []))), str(len(b.get("images", []))), ",".join(b.get("tags", []))] for b in rows],
                    right_cols=(3, 4, 5))
    elif act == "show":
        b = find_build(builds, " ".join(args.query))
        if not b:
            sys.exit("該当するビルドが見つからない、または複数あります。")
        print(f"■ {b['name']}  [{BUILD_TYPES.get(b['type'], b['type'])}]  対象: {b.get('target', '-')}  フォーマ: {b.get('forma', 0)}")
        for i, m in enumerate(b.get("mods", []), 1):
            print(f"  {i:>2}. {m}")
        if b.get("arcanes"):
            print("アルケイン: " + ", ".join(b["arcanes"]))
        if b.get("note"):
            print(f"\nメモ: {b['note']}")
        if b.get("tags"):
            print("タグ: " + ", ".join(b["tags"]))
        for n in b.get("images", []):
            print(f"画像: {d / IMAGE_DIR / n}")
    elif act == "add":
        name = " ".join(args.query)
        if not name:
            sys.exit("ビルド名を指定してください。")
        old = find_build(builds, name)
        entry = {"name": name, "type": args.type or "frame", "target": args.target or "",
                 "forma": args.forma or 0, "mods": [m.strip() for m in (args.mods or "").split(",") if m.strip()],
                 "arcanes": [a.strip() for a in (args.arcanes or "").split(",") if a.strip()],
                 "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()], "note": args.note or "",
                 "images": []}
        same = old is not None and norm(old["name"]) == norm(name)
        if same and not args.update:
            sys.exit("同名のビルドがあります。上書きするには --update を付けてください。")
        if same:
            entry["images"] = list(old.get("images", []))  # 既存の画像は残し、--image の分を追加する
        for path in args.image or []:
            try:
                entry["images"].append(save_build_image(d, Path(path).expanduser().read_bytes()))
            except (OSError, ValueError) as e:
                sys.exit(f"画像を追加できませんでした({path}): {e}")
        if same:
            builds[builds.index(old)] = entry
            print("更新しました。")
        else:
            builds.append(entry)
            print("追加しました。")
        save_builds(d, builds)
    elif act == "rm":
        b = find_build(builds, " ".join(args.query))
        if not b:
            sys.exit("該当するビルドが見つからない、または複数あります。")
        builds.remove(b)
        save_builds(d, builds)
        delete_build_images(d, b.get("images", []))
        print(f"削除しました: {b['name']}")
    elif act == "export":
        print(json.dumps(builds, ensure_ascii=False, indent=2))
    elif act == "analyze":
        import wfportal_ocr  # Windows の文字認識を使う画像解析
        wfportal_ocr.main_analyze(args.query, d, raw=args.raw, save_ocr=args.save_ocr, ocr_json=args.ocr_json)


# --------------------------------------------------------------------------
# コマンド: serve (ブラウザ画面)
# --------------------------------------------------------------------------

def cmd_serve(args):
    import wfportal_ui  # 画面を使わない場合は読み込まない
    argv = ["--port", str(args.port)]
    if args.data_dir:
        argv += ["--data-dir", args.data_dir]
    if args.no_browser:
        argv.append("--no-open")
    wfportal_ui.main(argv)


# --------------------------------------------------------------------------
# エントリポイント
# --------------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wfportal", description="Warframe ポータルツール")
    p.add_argument("--version", action="version", version=f"Warframe Portal Tool v{app_version()}")
    p.add_argument("--data-dir", help="データ置き場 (既定: ~/.wfportal)")
    sub = p.add_subparsers(dest="cmd")  # 省略時は画面(serve)を起動

    s = sub.add_parser("serve", help="ブラウザで操作する画面を起動 (引数なしでも起動)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    s.set_defaults(fn=cmd_serve)

    sub.add_parser("update", help="公式データを取得/更新").set_defaults(fn=cmd_update)

    s = sub.add_parser("logos", help="公式ファンキットのロゴ素材を取得 (各自の PC に保存)")
    s.add_argument("--force", action="store_true", help="取得済みでも取り直す")
    s.add_argument("--if-missing", action="store_true", help="未取得のときだけ取得する (起動用バッチから使用)")
    s.set_defaults(fn=cmd_logos)

    s = sub.add_parser("item", help="素材名 -> 入手場所・ステージ・確率 (ミッション・敵・バウンティ・レリック等)")
    s.add_argument("query", nargs="+")
    s.add_argument("--all", action="store_true", help="素材以外(MOD・設計図など)も対象にする")
    s.add_argument("--pick", type=int, help="候補が複数のとき番号で選ぶ")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--events", action="store_true", help="イベント限定ノードも含める")
    s.add_argument("--cat", action="append", choices=list(SOURCE_CATS), help="入手先の種類で絞り込み (複数回指定可)")
    s.set_defaults(fn=cmd_item)

    s = sub.add_parser("area", help="エリア(惑星/ノード) -> ステージごとの素材と確率")
    s.add_argument("query", nargs="+")
    s.add_argument("--all", action="store_true", help="素材以外も表示")
    s.add_argument("--all-nodes", action="store_true", help="部分一致のノードをすべて表示")
    s.add_argument("--events", action="store_true")
    s.set_defaults(fn=cmd_area)

    s = sub.add_parser("cycle", help="昼夜サイクルとリセット時刻")
    s.add_argument("action", nargs="?", default="show", choices=["show", "set"])
    s.add_argument("target", nargs="?", help="set のとき cetus / vallis")
    s.add_argument("phase", nargs="?", help="現在のフェーズ (昼/夜/温暖/寒冷)")
    s.add_argument("remaining", nargs="?", help="そのフェーズの残り時間 (分 or mm:ss)")
    s.set_defaults(fn=cmd_cycle)

    s = sub.add_parser("build", help="ビルド管理")
    s.add_argument("action", choices=["list", "show", "add", "rm", "export", "analyze"])
    s.add_argument("query", nargs="*", help="ビルド名 / 検索語 / analyze のときは画像ファイル")
    s.add_argument("--type", choices=list(BUILD_TYPES))
    s.add_argument("--target", help="フレーム名・武器名")
    s.add_argument("--forma", type=int)
    s.add_argument("--mods", help="カンマ区切り")
    s.add_argument("--arcanes", help="アルケイン (カンマ区切り)")
    s.add_argument("--tags", help="カンマ区切り")
    s.add_argument("--note")
    s.add_argument("--update", action="store_true", help="同名ビルドを上書き")
    s.add_argument("--image", action="append", metavar="画像ファイル", help="画像を添付 (複数回指定可)")
    s.add_argument("--raw", action="store_true", help="analyze: 読み取った文字をそのまま表示")
    s.add_argument("--save-ocr", metavar="JSON", help="analyze: 文字認識の結果を保存 (不具合の報告用)")
    s.add_argument("--ocr-json", metavar="JSON", help="analyze: 保存した文字認識の結果から解析し直す")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("mods", help="MOD 入手一覧 (入手先と所持チェック)")
    s.add_argument("query", nargs="*", metavar="[own|unown] 名前",
                   help="MOD 名で絞り込み。先頭に own / unown を付けると所持チェックを付ける/外す")
    s.add_argument("--type", choices=[k.lower() for k in MOD_TYPES], help="種別で絞り込み")
    s.add_argument("--unowned", action="store_true", help="未所持のみ")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_mods)

    s = sub.add_parser("riven", help="Riven 相場 (公式の週次統計)")
    s.add_argument("query", nargs="*", help="武器名で絞り込み")
    s.add_argument("--type", help="武器種 (ライフル / 近接 / rifle など)")
    s.add_argument("--limit", type=int, default=40)
    s.add_argument("--update", action="store_true", help="Riven 相場だけを取得し直してから表示")
    s.set_defaults(fn=cmd_riven)

    s = sub.add_parser("dispo", help="Riven 性質 (武器ごとの性質値。カテゴリーごとに性質の高い順)")
    s.add_argument("query", nargs="*", help="武器名で絞り込み")
    s.add_argument("--cat", choices=list(DISPO_CATS), default="primary", help="カテゴリー (既定: primary)")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_dispo)

    s = sub.add_parser("mastery", help="マスター一覧 (Warframe・武器・コンパニオンなどのマスター済みチェック)")
    s.add_argument("query", nargs="*", metavar="[done|undo] 名前",
                   help="名前で絞り込み。先頭に done / undo を付けるとマスター済みにする / 外す")
    s.add_argument("--cat", choices=list(MASTERY_CATS), help="カテゴリーで絞り込み")
    s.add_argument("--todo", action="store_true", help="未マスターのみ")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_mastery)

    s = sub.add_parser("arcane", help="アルケイン所持一覧 (所持チェックとランク)")
    s.add_argument("query", nargs="*", metavar="[own|unown] 名前",
                   help="名前で絞り込み。先頭に own / unown を付けると所持にする / 外す")
    s.add_argument("--cat", choices=list(ARCANE_CATS), help="種類で絞り込み")
    s.add_argument("--unowned", action="store_true", help="未所持のみ")
    s.add_argument("--rank", type=int, help="own で設定するランク (省略時: 所持済みならそのまま、未所持なら 0)")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_arcane)
    return p


def main(argv: list[str] | None = None) -> None:
    args = make_parser().parse_args(argv)
    if args.cmd is None:
        args.fn, args.port, args.no_browser = cmd_serve, 8765, False
    try:
        args.fn(args)
    except BrokenPipeError:  # `| head` などで出力が途中で閉じられた場合
        sys.stderr.close()


if __name__ == "__main__":
    main()
