"""共通: 設定・表示名の表・検索用の正規化など(wfp の他のモジュールを import しない)"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


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
                   "ExportWeapons", "ExportSentinels", "ExportRelicArcane",
                   # バロの在庫(内部パス)を名前にするため: 外装・グリフ・クエスト・ブースター類(ExportOther)・設計図
                   "ExportCustoms", "ExportFlavour", "ExportKeys", "ExportSortieRewards", "ExportRecipes")


# Riven 相場: 公式が毎週公開している PC 版の取引統計。取得できなければ WFCD が同じ統計を配信しているものを使う
RIVENS_URL = "https://www-static.warframe.com/repos/weeklyRivensPC.json"


RIVENS_URLS = [RIVENS_URL, "https://api.warframestat.us/pc/rivens"]


# ロゴ素材: Digital Extremes が公開している「Warframe Fan Kit」(Dropbox) の Logos フォルダ
#   配布ページ: https://www.warframe.com/news/warframe-fansite-kit
#   権利は Digital Extremes にあるため、このツールには同梱せず、各自の PC で公式の配布元から取得する
FANKIT_PAGE = "https://www.warframe.com/news/warframe-fansite-kit"


FANKIT_LOGOS_URL = ("https://www.dropbox.com/scl/fo/el9i8ltoms44id3wt3swv/h/Logos"
                    "?rlkey=3ehhk98vupze6if64gl3lia08&dl=1")


# ツールのフォルダ(wfp/ の1つ上)
APP_DIR = Path(__file__).resolve().parents[2]


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


# レリックの時代名。公式の日本語データ(Public Export)と同じ書き方: 英語のまま、Vanguard だけ「バンガード」。後ろは「レリック」
ERA_JA = {"Lith": "Lith", "Meso": "Meso", "Neo": "Neo", "Axi": "Axi", "Requiem": "Requiem", "Vanguard": "バンガード"}


PART_JA = {"Blueprint": "設計図", "Neuroptics": "ニューロオプティクス", "Chassis": "シャーシ",
           "Systems": "システム", "Barrel": "バレル", "Receiver": "レシーバー", "Stock": "ストック",
           "Blade": "ブレード", "Handle": "ハンドル"}


# ビルドの種別(表示名はマスター一覧・アルケイン所持一覧のカテゴリーと同じ書き方。保存はキーなので表示名は変えてよい)
BUILD_TYPES = {"frame": "Warframe", "primary": "プライマリ", "secondary": "セカンダリ",
               "melee": "近接", "companion": "コンパニオン", "archwing": "アークウイング", "other": "その他"}


# 入手先の種類
SOURCE_CATS = {"mission": "ミッション", "enemy": "敵", "bounty": "バウンティ", "relic": "レリック",
               "special": "特殊ミッション", "key": "キー・ボス", "sortie": "ソーティー"}


BOUNTY_JA = {"cetusBountyRewards": "平原バウンティ", "solarisBountyRewards": "オーブ峡谷バウンティ",
             "deimosRewards": "カンビオンの荒地バウンティ", "zarimanRewards": "ザリマン バウンティ",
             "entratiLabRewards": "アルブレヒト研究所バウンティ", "hexRewards": "Hex(1999)バウンティ"}


RELIC_STATE_JA = {"Intact": "無傷", "Exceptional": "上質", "Flawless": "完璧", "Radiant": "光輝"}


RELIC_STATES = ("Intact", "Radiant")  # 一覧が長くなりすぎないよう、両端の2状態だけ載せる


# MOD
MOD_TYPES = {"WARFRAME": "Warframe", "AURA": "オーラ", "PRIMARY": "プライマリ", "SECONDARY": "セカンダリ",
             "MELEE": "近接", "STANCE": "スタンス", "SENTINEL": "センチネル", "KUBROW": "クブロウ", "KAVAT": "キャバット",
             "HELMINTH CHARGER": "ヘルミンスチャージャー", "ARCHWING": "アークウイング", "ARCH-GUN": "アークウイングガン",
             "ARCH-MELEE": "アークウイング近接", "PARAZON": "パラゾン", "NECRAMECH": "ネクラメカ", "OTHER": "その他"}


COMPAT_JA = {"Rifle": "ライフル", "Shotgun": "ショットガン", "Pistol": "ピストル", "Melee": "近接", "Sniper": "スナイパー",
             "Bow": "弓", "Assault Rifle": "アサルトライフル", "Throwing": "投擲", "Kitgun": "Kitgun", "Zaw": "Zaw"}


# マスター一覧のカテゴリー
MASTERY_CATS = {"warframe": "Warframe", "primary": "プライマリ", "secondary": "セカンダリ", "melee": "近接",
                "kitgun": "Kitgun", "zaw": "Zaw", "robotic": "ロボティック", "companion": "コンパニオン",
                "archgun": "アークウイングガン", "archmelee": "アークウイング近接", "amp": "アンプ"}


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
                  "Archgun Riven Mod": "アークウイングガン", "Companion Weapon Riven Mod": "コンパニオン武器"}


# Riven 性質 (ExportWeapons の omegaAttenuation。0.5〜1.55)
DISPO_CATS = {"primary": "プライマリ", "secondary": "セカンダリ", "melee": "近接", "kitgun": "Kitgun",
              "zaw": "Zaw", "archgun": "アークウイングガン", "robotic": "コンパニオン武器"}


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


def to_float(v) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def pct(x: float) -> str:
    return f"{x:.2f}%"


# 周期から計算します。通信は不要で、時刻合わせをしなくても下の基準時刻(ref)から計算できます。
# 公式の World State で同期する(cycle sync)と、基準を取り直し、PC の時計のずれも補正します。
# 平原だけはゲーム内で見た残り時間で手動でも合わせられます(set)。
#   Cetus  : 8998.874 秒周期 (昼 = 残り + 夜 3000 秒)。公式 World State の CetusSyndicate の
#            開始〜期限がちょうどこの長さで、期限が夜明け(夜の終わり)。Cambion Drift は Cetus に連動 (昼=Fass / 夜=Vome)
#   Vallis : 1600 秒周期 (温暖 400 秒 + 寒冷 1200 秒)。World State に手がかりが無いため基準時刻から計算する
#   Zariman: Cetus と同じ長さで、コーパスとグリニアが交互に入れ替わる(切り替わりは CetusSyndicate の期限と同時)
#   Duviri : 2 時間ごとに Sorrow → Fear → Joy → Anger → Envy の順(UTC の 0 時から 10 時間で一巡)
# 基準時刻(ref)は「最初の段階が始まった時刻」。2026-10-17 に公式 World State と WFCD (api.warframestat.us) で確認した値。
#   Cetus/Zariman: CetusSyndicate の期限 2026-10-16T22:43:29.966Z(夜の終わり = 昼の始まり、グリニアの終わり = コーパスの始まり)
#   Vallis: 寒冷の終わり 2026-10-16T22:26:48Z(WFCD の vallisCycle の期限)
CETUS_PERIOD = 8998.874


CYCLES = {
    "cetus": {"name": "平原 (Cetus)", "phases": [("day", "昼", CETUS_PERIOD - 3000), ("night", "夜", 3000)],
              "ref": 1792190609.966, "manual": True, "sync": "cetus"},
    "vallis": {"name": "オーブ峡谷 (Orb Vallis)", "phases": [("warm", "温暖", 400), ("cold", "寒冷", 1200)],
               "ref": 1792189608.0, "manual": True},
    "zariman": {"name": "ザリマン (Zariman)", "phases": [("corpus", "コーパス", CETUS_PERIOD), ("grineer", "グリニア", CETUS_PERIOD)],
                "ref": 1792190609.966, "manual": False, "sync": "cetus"},
    "duviri": {"name": "デュヴィリ (Duviri)",
               "phases": [("sorrow", "Sorrow", 7200), ("fear", "Fear", 7200), ("joy", "Joy", 7200),
                          ("anger", "Anger", 7200), ("envy", "Envy", 7200)],
               "ref": 0.0, "manual": False},
}


CAMBION = {"day": "Fass(昼)", "night": "Vome(夜)"}  # カンビオンの荒地は Cetus に連動


PHASE_ALIASES = {"day": "day", "昼": "day", "night": "night", "夜": "night",
                 "warm": "warm", "温暖": "warm", "cold": "cold", "寒冷": "cold"}


CYCLE_SOURCES = {"default": "基準時刻から計算", "worldstate": "公式データで同期", "manual": "手動で時刻合わせ"}

# デュヴィリサーキットのローテーション(data/duviri/ に同梱)。キー -> ローテーションのファイル名
# 基準の週と ID は data/duviri/ の DUVIRI_BASE_FILE にモードごとに持つ
DUVIRI_MODES = {"normal": "normal.json", "steelpath": "steelpath.json"}
DUVIRI_BASE_FILE = "rotate.json"

# 鋼の道のり交換(スティール・エッセンス交換)のローテーション(data/spexchange/ に同梱。サイクルページに表示)
# 基準の週と ID は SPEX_BASE_FILE の SPEX_MODE に持つ(デュヴィリの rotate.json と同じ形。壊れても影響を分けるため別ファイル)
SPEX_MODE = "sp_exchange"
SPEX_ROTATION_FILE = "steelpath_exchange.json"
SPEX_BASE_FILE = "spex_rotate.json"


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
