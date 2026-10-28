"""共通: 設定・表示名の表・検索用の正規化など(wfp の他のモジュールを import しない)"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from contextlib import contextmanager
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
# 取得元の名前(names.json・builder.json の source に入る。画面は I18N の export.src.<名前>)
EXPORT_SRC_GITHUB = "GitHub (calamity-inc/warframe-public-export)"
EXPORT_SRC_OFFICIAL = "公式 Public Export"


EXPORT_PREFIXES = ("ExportResources", "ExportUpgrades", "ExportGear", "ExportWarframes",
                   "ExportWeapons", "ExportSentinels", "ExportRelicArcane",
                   # バロの在庫(内部パス)を名前にするため: 外装・グリフ・クエスト・ブースター類(ExportOther)・設計図
                   "ExportCustoms", "ExportFlavour", "ExportKeys", "ExportSortieRewards", "ExportRecipes")

# 日英のほかに名前辞書を取れる言語(公式 Public Export の言語コード。en・ja は毎回取るので入れない)。
# 取得先の URL と保存するファイル名(LANG_NAMES_FILE)には、ここにある値だけを使う
EXPORT_EXTRA_LANGS = ("de", "es", "fr", "it", "ko", "pl", "pt", "ru", "tc", "th", "tr", "uk", "zh")
# 画面の言語コード(web/i18n のファイル名)と Export の言語コードが違うもの。キーは小文字
EXPORT_LANG_ALIAS = {"zh-cn": "zh", "zh-hans": "zh", "zh-tw": "tc", "zh-hk": "tc", "zh-hant": "tc"}
# 日英のほかの言語の名前辞書(英名 -> その言語の名前)。データ置き場に言語ごとに置く
LANG_NAMES_FILE = "names_{lang}.json"


def export_lang(code: str) -> str | None:
    """画面の言語コードを、日英のほかに取る Export の言語コードにする。ja・en・Export に無い言語は None

    別名(EXPORT_LANG_ALIAS)を先に見て、無ければ地域を外したコード(ko-KR → ko)で探す。
    """
    low = code.strip().lower()
    lang = EXPORT_LANG_ALIAS.get(low) or low.split("-")[0]
    return lang if lang in EXPORT_EXTRA_LANGS else None


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
    "Zariman": "ZARIMAN", "Duviri": "デュヴィリ", "Höllvania": "ホルバニア",
    "Dark Refractory, Deimos": "ダーク・リフラクトリー(ダイモス)",
}


MODES_JA = {
    "Survival": "耐久", "Defense": "防衛", "Capture": "確保", "Rescue": "救出", "Spy": "潜入",
    "Assassination": "抹殺", "Interception": "傍受", "Exterminate": "掃滅", "Excavation": "発掘",
    "Disruption": "分裂", "Mobile Defense": "機動防衛", "Sabotage": "妨害",
    "Defection": "脱出", "Skirmish": "小競り合い", "Caches": "キャッシュ", "Conclave": "コンクラーヴ",
    "Arena": "アリーナ", "Hard": "ハード", "Normal": "ノーマル", "Rush": "ラッシュ",
    "Pursuit": "追跡", "Ascension": "アセンション", "Alchemy": "錬金",
    "Infested Salvage": "感染サルベージ", "Void Flood": "ヴォイドフラッド",
    "Void Cascade": "ヴォイドカスケード", "Void Armageddon": "ヴォイドアルマゲドン",
    "The Circuit": "サーキット", "Legacyte Harvest": "レガシート収穫",
    "Sanctuary Onslaught": "サンクチュアリ", "Elite Sanctuary Onslaught": "エリート・サンクチュアリ", "Shrine Defense": "神殿防衛",
    "Conjunction Survival": "結合耐久",
    "The Perita Rebellion": "ペリタの反乱", "Follie's Hunt": "フォリーの狩り",
}

# ドロップ表ではほかと同じ種類で入っているが、ゲーム内では別の名前のノード: (惑星, ノード) -> (元の種類, 付け替える種類)。
# ノード名の後ろの「 (Extra)」などは外して照合する。元の種類が違うとき(元データの書き方が変わったとき)は付け替えない
NODE_MODES = {
    ("Lua", "Yuvarium"): ("Survival", "Conjunction Survival"),
    ("Lua", "Circulus"): ("Survival", "Conjunction Survival"),
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
               "special": "特殊ミッション", "key": "キー・ボス", "sortie": "ソーティー", "clan": "クラン研究",
               "simaris": "Simaris 交換", "quest": "クエスト報酬"}


# エリア検索で出すアイテムの種類(Names.item_kind)。並びは画面のチェックと、種類で分けたときの表の並び
AREA_KINDS = {"resource": "素材", "part": "パーツ・設計図", "mod": "MOD", "relic": "レリック", "other": "その他"}
AREA_KIND_DEFAULT = ("resource",)  # 種類の指定が無いときに出す種類(これまでの「素材だけ」と同じ)


BOUNTY_JA = {"cetusBountyRewards": "平原バウンティ", "solarisBountyRewards": "オーブ峡谷バウンティ",
             "deimosRewards": "カンビオンの荒地バウンティ", "zarimanRewards": "ZARIMAN バウンティ",
             "entratiLabRewards": "アルブレヒト研究所バウンティ", "hexRewards": "Hex(1999)バウンティ"}


RELIC_STATE_JA = {"Intact": "無傷", "Exceptional": "上質", "Flawless": "完璧", "Radiant": "光輝"}


RELIC_STATES = ("Intact", "Radiant")  # 一覧が長くなりすぎないよう、両端の2状態だけ載せる


# バロ吉入手一覧: 照合の種類と、それぞれをどこで照合するか(wfportal_baro.py が使う)
BARO_KINDS = {"mod": "MOD", "weapon": "武器", "manual": "装飾・外装など", "repeat": "消耗品など"}
BARO_CHECK_BY = {"mod": "MOD入手一覧の所持", "weapon": "マスター一覧のマスター済み", "manual": "このページのチェック", "repeat": "照合しない"}


# シミュレータ(wfportal_builder.py が使う)の表示名。画面は I18N の sim.dmg / sim.cat / sim.group / sim.stat
# ダメージの種類は ExportWeapons の damagePerShot(20 要素の配列)の順
SIM_DAMAGE_TYPES = {
    "impact": "衝撃", "puncture": "貫通", "slash": "切断",
    "heat": "火炎", "cold": "冷気", "electricity": "電気", "toxin": "毒",
    "blast": "爆発", "radiation": "放射線", "gas": "ガス", "magnetic": "磁気",
    "viral": "感染", "corrosive": "腐食", "void": "Void", "tau": "Tau",
    "cinematic": "演出用", "shield_drain": "シールド吸収", "health_drain": "ヘルス吸収",
    "energy_drain": "エネルギー吸収", "true": "True",
}
SIM_CATS = {"primary": "プライマリ", "secondary": "セカンダリ", "melee": "近接",
            "archgun": "アークウイングガン", "robotic": "コンパニオン武器"}
SIM_RIVEN_GROUPS = {"rifle": "ライフル", "shotgun": "ショットガン", "pistol": "ピストル", "melee": "近接", "archgun": "アークウイングガン"}
SIM_STATS = {
    "cc": "クリティカル率", "cd": "クリティカルダメージ", "damage": "ダメージ(近接ダメージ)", "multishot": "マルチショット",
    "fire_rate": "連射速度(攻撃速度)", "status": "状態異常率", "status_duration": "状態異常の持続時間",
    "heat": "火炎", "cold": "冷気", "electricity": "電気", "toxin": "毒", "impact": "衝撃", "puncture": "貫通", "slash": "切断",
    "faction": "勢力ダメージ(Grineer など)", "magazine": "マガジン容量", "reload": "リロード速度", "ammo": "最大弾薬数",
    "projectile_speed": "弾速", "recoil": "反動(マイナスが有利)", "zoom": "ズーム", "punch_through": "貫通力",
    "range": "射程(近接)", "combo_duration": "コンボ持続時間", "initial_combo": "初期コンボ",
    "slide_cc": "スライド攻撃のクリティカル率", "finisher": "フィニッシャーダメージ", "heavy_efficiency": "ヘビーアタック効率",
}


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
                "archwing": "アークウイング", "archgun": "アークウイングガン", "archmelee": "アークウイング近接",
                "necramech": "ネクロメカ", "kdrive": "Kドライブ", "amp": "アンプ",
                "extra": "その他", "founder": "ファウンダー"}
# マスター一覧の最大ランクの既定値(Public Export に maxLevelCap が無いカテゴリー用。無ければ 30)
MASTERY_MAX_RANK = {"necramech": 40}
# ファウンダー限定品。元のカテゴリーから「ファウンダー」へ付け替える(id は元のまま。画面ではチェック ON のときだけ数える)
MASTERY_FOUNDER = frozenset({"warframe:excalibur prime", "melee:skana prime", "secondary:lato prime"})
# Public Export に無い項目を手で足すファイル(data/mastery/ の中)。データ更新・照合で無くても消さない
MASTERY_EXTRA_FILE = "extra.json"


# パーツ検索: ドロップ表の英名が「マスター一覧の項目名 + 部品名(+ Blueprint)」ならパーツとして扱う。
# 部品名はこの一覧にあるものだけ(スキン・ヘルメット・コンクラーヴ用などを拾わないため。新しい部品名が出たら足す)
PART_WORDS = frozenset({
    "Neuroptics", "Chassis", "Systems", "Aspect",                        # Warframe(Aspect は Equinox)
    "Barrel", "Receiver", "Stock", "Link", "String", "Grip", "Upper Limb", "Lower Limb",
    "Blade", "Blades", "Handle", "Hilt", "Guard", "Head", "Disc", "Pouch", "Stars", "Ornament",
    "Gauntlet", "Boot", "Chain", "Glove", "Rivet", "Motor", "Core", "Subcortex", "Engine",
    "Carapace", "Cerebrum",                                              # センチネル
    "Harness", "Wings",                                                  # アークウイング
})
# 部品名の前に付く区分(Equinox の Day / Night、Furax Wraith の Left / Right)
PART_QUALIFIERS = frozenset({"Day", "Night", "Left", "Right"})
# パーツ検索で扱わないマスター一覧のカテゴリー(並びと表示名は MASTERY_CATS)
PART_SKIP_CATS = frozenset({"extra", "founder"})


# クラン研究(同梱の data/parts/ の中のファイル。開発側が手で編集して配布)。研究で手に入る設計図を入手先「クラン研究」として出す
CLAN_FILE = "clan.json"
# 研究所: キー -> (英語名, 日本語名)。画面の文字は web/i18n の clan.lab.<キー>(日本語は CLI 用にここにも置き、テストで一致を確かめる)
CLAN_LABS = {"tenno": ("Tenno Lab", "テンノ ラボ"), "energy": ("Energy Lab", "エネルギー ラボ"),
             "chemical": ("Chemical Lab", "ケミカル ラボ"), "bio": ("Bio Lab", "バイオ ラボ"),
             "bash": ("Ventkids Bash Lab", "バッシュ ラボ"), "dagath": ("Dagath's Hollow", "Dagathの空洞")}
# ドロップもクラン研究もしない入手先(同梱の data/parts/ の中のファイル。開発側が手で編集して配布)
OTHER_FILE = "other.json"
# 入手先: キー -> (英語名, 日本語名)。キーは入手先の種類(SOURCE_CATS)にもそのまま使う。足すときは SOURCE_CATS にも足す
OTHER_SOURCES = {"simaris": ("Simaris Offerings", "Simaris 交換"), "quest": ("Quest Reward", "クエスト報酬")}
# 手で書いた入手先のクエスト名を詳細欄に出すときの形は TEXT_JA の src.quest.<入手先のキー>(無い入手先はクエスト名そのまま)


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


def pct(x: float | None) -> str:
    """確率の表示。確率の無い入手先(クラン研究)は「—」"""
    return "—" if x is None else f"{x:.2f}%"


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
    "zariman": {"name": "ZARIMAN", "phases": [("corpus", "コーパス", CETUS_PERIOD), ("grineer", "グリニア", CETUS_PERIOD)],
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

# 侵略サイクル: 獲得パーツの一覧(data/invasion/ に同梱。武器ごとのパーツと内部パス)
INVASION_PARTS_FILE = "parts.json"
# パーツの種類(画面の I18N の invasion.part.<キー> で名前にする)。並びは同梱ファイルの書き順を使う
INVASION_PART_KINDS = ("blueprint", "barrel", "receiver", "stock", "link", "blade", "heatsink", "hilt")
# 陣営(World State の値。画面の I18N の invasion.faction.<値> で名前にする)
INVASION_INFESTED = "FC_INFESTATION"
# 報酬のうち、このパスで始まるものを武器のパーツ・設計図とみなす(一覧に無いものを unknown_parts で知らせる)
INVASION_WEAPON_PART_PREFIX = "/Lotus/Types/Recipes/Weapons/"

# ノード名の辞書: 公式 Public Export の ExportRegions から作る(EXPORT_PREFIXES には入れない。
# 名前辞書 names.json にノード名が混ざらないよう、別に取得して regions.json にする)
REGIONS_EXPORT = "ExportRegions"
REGIONS_FILE = "regions.json"


def parse_remaining(s: str) -> int:
    parts = [int(x) for x in s.split(":")]
    if len(parts) == 1:
        return parts[0] * 60  # 数字だけなら分
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt_clock(sec: float) -> str:
    """秒数を「h:mm:ss」(1時間未満は「mm:ss」)にする(言語によらない書き方。画面の dur と同じ)"""
    sec = max(0, int(sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_dur(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}時間{m:02d}分{s:02d}秒" if h else f"{m}分{s:02d}秒"


# ---------- 画面の文字(テキスト指定) ----------
# API は日本語の文を作らず、「テキスト指定」を返して画面(web/i18n の表)で文にする。形は次のどれか:
#   文字列            そのまま出す(敵の名前・ノード名などの固有名詞)
#   リスト            各要素を文にして list.sep でつなぐ
#   {"k", "v", "d"}  表のキー k の文の {名前} を v の値(テキスト指定)で置き換える。k が表に無ければ d(無ければ k)
#   {"l": {言語: 文}} 同梱データに言語ごとに書いた文(クエスト名など)。表示中の言語、無ければ ja、en の順
# CLI・API のエラー文は日本語で出すので、同じものを render_ja で文にする。日本語の文は画面と同じものを下の TEXT_JA・JA_TABLES に置き、
# web/i18n/ja.json と一致することを tests/test_i18n_text.py が確かめる(どちらかだけ直すと落ちる)
TEXT_JA = {
    "list.sep": "、",
    "src.rot": "ローテ{r}",
    "src.stage": "ステージ{n}", "src.stage.of": "ステージ{n}(全{of})", "src.stage.final": "最終ステージ",
    "src.mission": "{planet} / {node}",
    "src.enemy.resource": "素材", "src.enemy.sigil": "シジル等", "src.enemy.other": "その他",
    "src.enemy.mod": "MODドロップ {p}%", "src.enemy.bp": "設計図ドロップ {p}%", "src.enemy.item": "アイテムドロップ {p}%",
    "src.bounty.lv": "{name} Lv{a}-{b}", "src.bounty.level": "{name} {level}", "src.bounty.steel": "{place} (鋼の道)",
    "src.relic": "{era} {name} レリック",
    "src.sortie": "ソーティー", "src.sortie.final": "最終報酬",
    "src.quest.simaris": "{q}完了後",
    "src.note": "{a} / {b}",
    # API のエラー(wfp/api/store.py の ApiError にテキスト指定で渡す)
    "err.nodata": "データがありません。メニューの「データ更新」から取得してください。",
    "err.part.cat": "不明なカテゴリーです。",
    "err.item.none": "該当する入手先がありません。",
    "err.req.json_type": "Content-Type は application/json にしてください。",
    "err.req.too_large": "リクエストが大きすぎます。",
    "err.req.bad_json": "JSON を読み取れません。",
    "err.req.image_type": "画像ファイルを送ってください。",
    "err.req.image_large": "画像が大きすぎます(上限 {mb}MB)。",
    "err.req.object": "JSON のオブジェクトで送ってください。",
    "err.logo.none": "ロゴ素材が未取得です。",
    "err.mods.nodata": "MOD の情報がありません。「データ更新」で取得してください。",
    "err.mods.unknown": "MOD が見つかりません: {name}",
    "err.image.format": "PNG / JPEG / GIF / WebP の画像を送ってください。",
    "err.ocr.none": "文字認識が使えません。",
    "err.ocr.nolang": "文字認識に使える言語がありません。Windows の設定で言語を追加してください。",
    "err.ocr.windows": "Windows の文字認識は Windows 10/11 でのみ使えます。",
    "err.ocr.script": "{path} が見つかりません。",
    "err.ocr.timeout": "文字認識が {sec} 秒以内に終わりませんでした。",
    "err.ocr.failed": "文字認識に失敗しました: {msg}",
    "err.mastery.nodata": "マスター一覧のデータがありません。「データ更新」で取得してください。",
    "err.mastery.unknown": "見つかりません: {id}",
    "err.arcane.nodata": "アルケインのデータがありません。「データ更新」で取得し直してください(このページを追加する前に取得したデータには含まれていません)。",
    "err.arcane.rank": "ランクが正しくありません: {rank}",
    "err.arcane.unknown": "アルケインが見つかりません: {name}",
    "err.arcane.range": "{name} のランクは 0〜{max} です: {rank}",
    "err.baro.noname": "名前がありません。",
    "err.baro.notmanual": "{name} は {by} で照合します(このページではチェックしません)。",
    "err.baro.fetch": "今回の品物(公式データ)を取得できませんでした: {e}",
    "err.duviri.mode": "モードを選んでください。",
    "err.duviri.broken": "ローテーションのデータが読めないため、調整できません。",
    "err.duviri.id": "ID は 1〜{max} で選んでください。",
    "err.invasion.broken": "獲得パーツの一覧(同梱データ)が読めません。",
    "err.invasion.unknown": "一覧に無いパーツです。",
    "err.invasion.fetch": "公式データを取得できませんでした。前回取得した内容で表示しています。({e})",
    "err.riven.nodata": "Riven 相場のデータがありません。「データ更新」で取得してください。",
    "err.cycle.manual": "手動で合わせられるのは平原とオーブ峡谷です。",
    "err.cycle.phase": "フェーズを選んでください。",
    "err.cycle.remaining": "残り時間は「45:30」または分の数字で入力してください。",
    "err.cycle.range": "残り時間が範囲外です(このフェーズは最長 {max})。",
    "err.cycle.nosync": "{name} は World State から同期できません。",
    "err.cycle.fetch": "公式データを取得できませんでした。基準時刻(または前回の同期)からの計算で表示しています。({e})",
    "err.build.name": "ビルド名を入力してください。",
    "err.build.forma": "フォーマの数は数字で入力してください。",
    "err.build.original": "編集元のビルドが見つかりません。",
    "err.build.dup": "同じ名前のビルドがあります。",
    "err.build.none": "ビルドが見つかりません。",
    "err.build.images": "画像は1つのビルドに{n}枚までです。",
    "err.image.none": "画像が見つかりません。",
    "err.sim.buffs.n": "プラス効果の数は 2 か 3 です。",
    "err.sim.nocurse": "マイナス効果が無い構成です。",
    "err.sim.rank": "ランクは 0〜8 です。",
    "err.sim.group": "Riven の種類が不正です。",
    "err.sim.dispo": "性質値は 0.5〜1.55 程度の数字で入力してください。",
    "err.sim.buffs": "プラス効果は 2 つか 3 つ選んでください。",
    "err.sim.dup": "同じ効果は2回選べません。",
    "err.sim.stat": "{group}の Riven には付かない効果です: {stat}",
    "err.sim.nodata": "シミュレータ用のデータがありません。メニューの「データ更新」か、画面上部の「シミュレータ用データを取得」で取得してください。",
    "err.sim.unknown": "見つかりません: {name}",
    "err.sim.rank.num": "ランクは数字で入力してください。",
    "err.update.drops": "ドロップ表を取得できませんでした。ネットワーク設定を確認してください。",
    "err.update.names": "名前辞書を取得できませんでした: {e}",
    "err.update.lang": "言語は文字列で指定してください。",
    "err.update.lang_unknown": "名前辞書を取れない言語です: {lang}",
    "err.notfound": "{name} が見つかりません",
    "err.regions.none": "ノードが見つかりません",
    "err.sim.empty": "フレームか武器のデータが空でした",
    "err.riven.empty": "Riven 相場のデータが空でした",
    "err.logo.notzip": "ダウンロードした内容が zip ではありませんでした(配布元の仕様が変わった可能性があります)",
    "err.logo.toolarge": "展開後のサイズが大きすぎるため中止しました",
    "err.logo.noimage": "zip の中にロゴ画像が見つかりませんでした",
    # データ更新などの進み具合のログ(say で出す。CLI は日本語、画面は表示中の言語)
    "log.fetching.drops": "ドロップ表を取得中...",
    "log.source": "取得元: {src}",
    "log.failed": "失敗: {e}",
    "log.failed.what": "失敗: {what} ({e})",
    "log.failed.keep": "失敗: {what} ({e})  ※前回取得分があればそれを使います",
    "log.get": "取得: {file}",
    "log.fetching.extra": "追加の入手先(敵・バウンティ・レリック等)を取得中...",
    "log.extra.count": "{ok} / {total} ファイル取得",
    "log.fetching.names": "名前辞書(Public Export)を取得中...",
    "log.names.done": "完了: 名前 {names} 件 / 素材 {res} 件 / MOD {mods} 件 -> {dir}",
    "log.fetching.langs": "ほかの言語の名前辞書を取得中: {langs}",
    "log.lang.done": "{lang}: 名前 {n} 件(取得元: {src})",
    "log.lang.failed": "{lang}: 取得できませんでした: {e}  ※前回取得分があればそれを使います",
    "log.sim.done": "シミュレータ用データ: フレーム {f} 件 / 武器 {w} 件",
    "log.sim.failed": "シミュレータ用データを作れませんでした: {e}  ※前回取得分があればそれを使います",
    "log.paths.done": "内部パスの辞書: {n} 件",
    "log.paths.failed": "内部パスの辞書を作れませんでした: {e}  ※前回取得分があればそれを使います",
    "log.fetching.regions": "ノード名(ExportRegions)を取得中...",
    "log.regions.done": "ノード名: {n} 件(取得元: {src})",
    "log.regions.failed": "ノード名を取得できませんでした: {e}  ※前回取得分があればそれを使います(無ければ内部名で表示)",
    "log.fetching.riven": "Riven 相場(公式・週次)を取得中...",
    "log.riven.count": "{n} 件取得しました",
    "log.riven.failed": "失敗しました: {e}  ※前回取得分があればそれを使います",
    "log.fetching.sim": "シミュレータ用のデータ(ExportWarframes / ExportWeapons)を取得中...",
    "log.sim.done2": "完了: フレーム {f} 件 / 武器 {w} 件",
    "log.sim.fetchfail": "取得できませんでした: {e}  ※前回取得分があればそれを使います",
    "log.logo.have": "ロゴ素材は取得済みです: {dir}",
    "log.fetching.logo": "公式ファンキット(Warframe Fan Kit)のロゴ素材を取得中...",
    "log.logo.from": "配布元: Digital Extremes 公式 ({url})",
    "log.logo.failed": "失敗しました: {e}",
    "log.logo.later": "※ロゴ無しでもツールは使えます。あとで「python wfportal.py logos」で取り直せます。",
    "log.logo.saved": "{n} ファイルを保存しました -> {dir}",
    "log.logo.rights": "※ロゴ素材の権利は Digital Extremes にあります。個人の利用にとどめ、再配布しないでください。",
    "log.logo.savefail": "保存に失敗しました: {e}",
    "err.tips.save": "保存できませんでした",
    "err.tips.locked": "{what}。ファイルがほかのアプリで開かれていないか、書き込みが許可されているか確認してください。",
    "err.tips.write": "{what}: {e}",
    "err.tips.large": "メモが大きすぎます(上限 {kb}KB)。",
    "err.tips.missing": "メモが見つかりません。目次を読み込み直してください。",
    "err.tips.editable": "画面で編集できるのは .md のメモ({kb}KB 以下)だけです。",
    "err.tips.changed": "ほかのアプリでメモが変更されています。内容を確かめてから、もう一度開き直してください。",
    "err.tips.title": "タイトルを入れてください。",
    "err.tips.group": "グループが見つかりません。目次を読み込み直してください。",
    "err.tips.trashmove": "ゴミ箱に移せませんでした",
    "err.tips.restore": "元に戻せませんでした",
    "err.tips.purge": "削除できませんでした",
    "err.tips.trashmissing": "ゴミ箱にメモが見つかりません。一覧を読み込み直してください。",
    # 画面にも CLI にも出す文(バロの来た場所・Kitgun の区別)
    "baro.relay": "{name}({planet})",
    "mastery.variant": "{name} ({variant})",
}
# キーの頭 -> {キーの残り: 日本語}。表示名の表をそのまま画面の文字として使う
JA_TABLES = {
    "planet.": PLANETS_JA, "mode.": MODES_JA, "rarity.": RARITY_JA, "src.cat.": SOURCE_CATS, "area.kind.": AREA_KINDS, "bounty.": BOUNTY_JA,
    "relic.era.": ERA_JA, "relic.state.": RELIC_STATE_JA, "clan.lab.": {k: v[1] for k, v in CLAN_LABS.items()},
    "mod.type.": MOD_TYPES, "mod.compat.": COMPAT_JA, "mastery.cat.": MASTERY_CATS, "arcane.cat.": ARCANE_CATS,
    "mastery.variant.": {"primary": "プライマリ", "secondary": "セカンダリ"},
    "baro.kind.": BARO_KINDS, "baro.check.": BARO_CHECK_BY,
    "riven.type.": RIVEN_TYPES_JA, "build.type.": BUILD_TYPES,
    "cycle.name.": {k: c["name"] for k, c in CYCLES.items()},
    "cycle.phase.": {p[0]: p[1] for c in CYCLES.values() for p in c["phases"]},
    "cycle.cambion.": CAMBION, "cycle.src.": CYCLE_SOURCES,
    "export.src.": {EXPORT_SRC_GITHUB: EXPORT_SRC_GITHUB, EXPORT_SRC_OFFICIAL: EXPORT_SRC_OFFICIAL},
    "sim.dmg.": SIM_DAMAGE_TYPES, "sim.cat.": SIM_CATS, "sim.group.": SIM_RIVEN_GROUPS, "sim.stat.": SIM_STATS,
}


def txt(key: str, default: str | None = None, **values) -> dict:
    """テキスト指定 {"k", "v", "d"} を作る(値はテキスト指定。数は書式を決めた文字列で渡す)"""
    out: dict = {"k": key}
    if values:
        out["v"] = values
    if default is not None:
        out["d"] = default
    return out


def name_txt(prefix: str, key: str) -> dict | str:
    """表示名の表にある名前(惑星・ミッションの種類など)のテキスト指定。表に無い名前はそのまま出す"""
    return txt(prefix + key, key) if key else ""


def ja_text(key: str) -> str | None:
    """キーの日本語(TEXT_JA・JA_TABLES)。無ければ None"""
    if key in TEXT_JA:
        return TEXT_JA[key]
    for head, table in JA_TABLES.items():
        if key.startswith(head) and key[len(head):] in table:
            return table[key[len(head):]]
    return None


def render_txt(x, lookup=ja_text, lang: str = "ja") -> str:
    """テキスト指定を文にする(lookup はキー -> 文。既定は日本語)。画面の renderTxt と同じ決まり"""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, (int, float)):
        return f"{x:g}"
    if isinstance(x, list):
        return (lookup("list.sep") or ", ").join(render_txt(e, lookup, lang) for e in x)
    if isinstance(x, dict) and isinstance(x.get("l"), dict):
        by = x["l"]
        return next((by[c] for c in (lang, "ja", "en") if isinstance(by.get(c), str) and by[c]), "")
    if isinstance(x, dict) and isinstance(x.get("k"), str):
        tmpl = lookup(x["k"])
        if tmpl is None:
            return x["d"] if isinstance(x.get("d"), str) else x["k"]
        vals = x.get("v") or {}
        return re.sub(r"\{(\w+)\}", lambda m: render_txt(vals[m.group(1)], lookup, lang) if m.group(1) in vals else m.group(0), tmpl)
    return str(x)


def render_ja(x) -> str:
    """テキスト指定を日本語の文にする(CLI・並べ替え用)"""
    return render_txt(x)


_LOG = threading.local()


def say(text, level: int = 0) -> None:
    """進み具合の1行(テキスト指定)。標準出力には日本語で出す(CLI)。collect_log の中なら行も集める(画面が表示中の言語で出す)。
    level は字下げの段(1 段 = 空白2つ)"""
    print("  " * level + render_ja(text))
    lines = getattr(_LOG, "lines", None)
    if lines is not None:
        lines.append({"level": level, "text": text})


@contextmanager
def collect_log():
    """この中で say した行を集める(画面向けの API が使う)。{"level", "text"} のリストを返す"""
    prev = getattr(_LOG, "lines", None)
    _LOG.lines = []
    try:
        yield _LOG.lines
    finally:
        lines, _LOG.lines = _LOG.lines, prev
        if prev is not None:
            prev.extend(lines)


class _TextMessage:
    """文がテキスト指定の例外の共通部分。str() は日本語の文(CLI 用)、text はテキスト指定(API が画面へ渡す)"""

    def __init__(self, text):
        self.text = text
        super().__init__(render_ja(text))


class TextError(_TextMessage, ValueError):
    """入力・値の誤り(ValueError の仲間)。文はテキスト指定"""


class TextFailure(_TextMessage, RuntimeError):
    """取得・処理の失敗(RuntimeError の仲間)。文はテキスト指定"""


def error_text(e: BaseException):
    """例外の文: テキスト指定があればそれ(TextError)、無ければ str(e)(API の ApiError にそのまま渡せる)"""
    return getattr(e, "text", None) or str(e)
