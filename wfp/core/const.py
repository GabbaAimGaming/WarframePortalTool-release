"""定数: 取得元の URL・ファイル名・機能ごとの設定と表示名の表(wfp の他のモジュールを import しない。標準ライブラリだけ)

core.i18n(テキスト指定・表示名の表 JA_TABLES。日本語の文は web/i18n/ja.json)・core.common(一致度・書式)などがこのモジュールを使う。
使う側は `from wfp.core.const import 名前`。APP_DIR だけは `from wfp.core import const` → `const.APP_DIR`(テストで差し替えるため)
"""
from __future__ import annotations

from pathlib import Path


# ドロップ表: 公式ドロップ表(warframe.com/droptables)を WFCD が JSON 化したもの
#   https://github.com/WFCD/warframe-drop-data (MIT)
WFCD_BASES = [
    "https://drops.warframestat.us/data",
    "https://raw.githubusercontent.com/WFCD/warframe-drop-data/gh-pages/data",
]


# データ置き場(~/.wfportal)に置く公式由来のファイル: ドロップ表・名前辞書・ドロップ表のほかの入手先(フォルダ)・Riven 相場
DROPS_FILE = "missionRewards.json"
NAMES_FILE = "names.json"
WFCD_DIR = "wfcd"
RIVENS_FILE = "rivens.json"


DROPS_URLS = [f"{b}/{DROPS_FILE}" for b in WFCD_BASES]


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


# 言語で中身が変わらない Export(名前を持たないもの)。GitHub(calamity-inc)には言語の付かないファイル名(ExportRecipes.json)で置かれている。
# 公式 Public Export はほかと同じく言語の付いた名前(ExportRecipes_en.json)。2026-11-13 に GitHub の一覧で確認
EXPORT_UNLOCALIZED = ("ExportRecipes",)


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
# 画面の文字の表: <APP_DIR>/<WEB_DIR>/<I18N_DIR>/<言語>.json。I18N_BASE(日本語)は必須で、Python も CLI・API の
# 日本語の文にこれを使う(core/i18n の ja_text。2026-11-10 の B14 で TEXT_JA をやめた)
WEB_DIR = "web"
I18N_DIR = "i18n"
I18N_BASE = "ja"  # 最後の拠り所の言語(ほかの言語に無いキーはこれで出す)


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
    "Disruption": "分裂", "Mobile Defense": "機動防衛", "Mirror Defense": "ミラー防衛", "Sabotage": "妨害",
    "Defection": "脱出", "Skirmish": "小競り合い", "Caches": "キャッシュ", "Conclave": "コンクラーヴ",
    "Arena": "アリーナ", "Hard": "ハード", "Normal": "ノーマル", "Rush": "ラッシュ",
    "Pursuit": "追跡", "Ascension": "アセンション", "Alchemy": "錬金",
    "Infested Salvage": "感染回収", "Void Flood": "ヴォイドフラッド",
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
    ("Mars", "Tyana Pass"): ("Defense", "Mirror Defense"),  # ExportRegions の番号は防衛と同じ(仲裁でも使う)
}


RARITY_JA = {"Common": "コモン", "Uncommon": "アンコモン", "Rare": "レア", "Legendary": "レジェンダリー"}


# レリックの時代名。公式の日本語データ(Public Export)と同じ書き方: 英語のまま、Vanguard だけ「バンガード」。後ろは「レリック」
ERA_JA = {"Lith": "Lith", "Meso": "Meso", "Neo": "Neo", "Axi": "Axi", "Requiem": "Requiem", "Vanguard": "バンガード"}


PART_JA = {"Blueprint": "設計図", "Neuroptics": "ニューロオプティクス", "Chassis": "シャーシ",
           "Systems": "システム", "Barrel": "バレル", "Receiver": "レシーバー", "Stock": "ストック",
           "Blade": "ブレード", "Handle": "ハンドル"}


# ビルドの種別(表示名はマスター一覧・アルケイン所持一覧のカテゴリーと同じ書き方。保存はキーなので表示名は変えてよい)
BUILD_TYPES = {"frame": "Warframe", "primary": "プライマリ", "secondary": "セカンダリ",
               "melee": "近接", "companion": "コンパニオン", "archwing": "アークウイング", "summon": "呼び出し", "other": "その他"}


# 入手先の種類
SOURCE_CATS = {"mission": "ミッション", "enemy": "敵", "bounty": "バウンティ", "relic": "レリック",
               "special": "特殊ミッション", "key": "キー・ボス", "sortie": "ソーティー", "clan": "クラン研究",
               "simaris": "Simaris 交換", "quest": "クエスト報酬"}


# アイテムの種類(Names.item_kind)。エリア検索・アイテムから探すで共用。並びは画面のチェックと、種類で分けたときの表の並び
AREA_KINDS = {"resource": "素材", "part": "パーツ・設計図", "mod": "MOD", "relic": "レリック", "other": "その他"}


AREA_KIND_DEFAULT = ("resource",)  # エリア検索で種類の指定が無いときに出す種類(これまでの「素材だけ」と同じ)


ITEM_KIND_DEFAULT = ("resource", "part", "mod")  # アイテムから探すで種類の指定が無いときに探す種類(画面の初期のチェック・CLI の既定)


ENEMY_KIND_DEFAULT = tuple(AREA_KINDS)  # 敵から探すで種類の指定が無いときに出す種類(1体の敵の表は短いので全部)


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
    "fire_rate": "連射速度(攻撃速度)", "status": "状態異常確率", "status_duration": "状態異常の持続時間",
    "heat": "火炎", "cold": "冷気", "electricity": "電気", "toxin": "毒", "impact": "衝撃", "puncture": "貫通", "slash": "切断",
    "faction": "勢力ダメージ(Grineer など)", "magazine": "マガジンサイズ", "reload": "リロード速度", "ammo": "最大弾薬数",
    "projectile_speed": "弾速", "recoil": "反動(マイナスが有利)", "zoom": "ズーム", "punch_through": "貫通力",
    "range": "射程(近接)", "combo_duration": "コンボ持続時間", "initial_combo": "初期コンボ",
    "slide_cc": "スライド攻撃のクリティカル率", "finisher": "フィニッシャーダメージ", "heavy_efficiency": "ヘビーアタック効率",
    # コンボカウント追加確率と、スプライス効果(Riven Splicer)
    "combo_chance": "コンボカウント追加確率",
    "ammo_efficiency": "弾薬効率",
    "blast": "爆発",
    "corrosive": "腐食",
    "gas": "ガス",
    "magnetic": "磁気",
    "radiation": "放射線",
    "viral": "感染",
    "faction_spliced": "勢力ダメージ(Orokin・Scaldra・Techrot)",
    "status_damage": "状態異常ダメージ",
    "reload_holstered": "非装備中のリロード",
    "weakpoint_damage": "弱点ダメージ",
    "weakpoint_cc": "弱点へのクリティカル率",
    "heavy_windup": "ヘビーアタックの溜め速度",
    "heavy_damage": "ヘビーアタックの近接ダメージ",
    "slam_damage": "スラム攻撃ダメージ",
    "parry_angle": "パリィ角度",
}


# MOD
MOD_TYPES = {"WARFRAME": "Warframe", "AURA": "オーラ", "PRIMARY": "プライマリ", "SECONDARY": "セカンダリ",
             "MELEE": "近接", "STANCE": "スタンス", "SENTINEL": "センチネル", "KUBROW": "クブロウ", "KAVAT": "キャバット",
             "HELMINTH CHARGER": "ヘルミンスチャージャー", "ARCHWING": "アークウイング", "ARCH-GUN": "アークウイングガン",
             "ARCH-MELEE": "アークウイング近接", "PARAZON": "パラゾン", "NECRAMECH": "ネクラメカ", "OTHER": "その他"}


COMPAT_JA = {"Rifle": "ライフル", "Shotgun": "ショットガン", "Pistol": "ピストル", "Melee": "近接", "Sniper": "スナイパー",
             "Bow": "弓", "Assault Rifle": "アサルトライフル", "Throwing": "投擲", "Kitgun": "Kitgun", "Zaw": "Zaw"}


# MOD 効果検索の区分(MOD 入手一覧の MOD_TYPES とは別。1つの MOD が複数の区分を持てる。判定は core/modstats の MOD_GROUP_RULES)
MOD_GROUPS = {"warframe": "Warframe", "primary": "プライマリ", "secondary": "セカンダリ", "melee": "近接",
              "necramech": "ネクロメカ", "archwing": "アークウイング", "archgun": "アークウイングガン", "archmelee": "アークウイング近接",
              "kdrive": "K-ドライブ", "robotic": "ロボティック", "beast": "ビースト", "comp_weapon": "コンパニオン武器",
              "parazon": "パラゾン", "amp": "オペレーター/アンプ", "railjack": "レールジャック", "other": "その他"}


# MOD 効果検索のデータ: データ更新で Export から作るファイル(~/.wfportal)と、影響先の辞書(data/mod_stats/ の中。開発側が手で編集)
MOD_STATS_FILE = "mod_stats.json"


MOD_TARGETS_FILE = "targets.json"


RIVEN_WORDS_FILE = "stat_words.json"  # data/riven/ の Riven の効果名の辞書(画像の読み取り用)


# 検索結果の件数の上限(全文検索で広い語を打ったときに画面が重くならないように)
MOD_STATS_LIMIT = 200


# 要求素材集: データ更新で Export(ExportRecipes)から作るファイル(~/.wfportal)
RECIPES_FILE = "recipes.json"
RECIPE_EXPORT = "ExportRecipes"
# 部品として下に開く素材の内部パスの頭(ニューロティック・シャーシ・銃身など = /Lotus/Types/Recipes/…Component・WeaponParts、
# ネクロメカ・Thanotech のアークガンの部品 = …/InfestedMicroplanet/Resources/Mechs/)。
# ここに無い素材(Forma・オロキンセル・精錬した鉱石や宝石・素材に使う武器など)は、設計図があっても開かずに末端の素材として出す
# (2026-11-13 利用者の判断。2026-11-13 の ExportRecipes で確認)
RECIPE_PART_PREFIXES = ("/Lotus/Types/Recipes/", "/Lotus/Types/Gameplay/InfestedMicroplanet/Resources/Mechs/")
RECIPE_MAX_DEPTH = 4         # 部品を開く深さの上限(輪になったデータで止まらないように)
RECIPE_SOURCE_LIMIT = 2      # 末端の素材ごとに出す入手先の数(確率の高い順)
# 入手先を後ろに回すミッションの種類(MODES_JA のキー)。ほかの入手先があればそちらを先に出し、これしか無ければこれを出す
# (2026-11-14 利用者の指定: コンクラーヴ)
RECIPE_SOURCE_LAST_MODES = ("Conclave",)
RECIPE_SUGGEST_LIMIT = 10    # 候補の最大件数


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


# クエスト一覧: 種類(キー -> 日本語)。並びは画面・CLI の表示順。ジャンクションもチェックの対象として同じ一覧に入る
QUEST_CATS = {"main": "メインクエスト", "side": "サイドクエスト", "warframe": "Warframe クエスト",
              "junction": "ジャンクション", "other": "その他"}


# 状態: 完了 / 今すぐ受けられる(前提が全部完了) / 前提が足りない
QUEST_STATES = {"done": "完了", "ready": "受けられる", "locked": "前提が未完了"}


# 前提条件を手で書くファイル(data/quests/ の中)。Export に無いクエスト(Prelude to War など)もここに書く。データ更新で無くても消さない
QUEST_FLOW_FILE = "flow.json"


# ジャンクションの id(完了の記録・前提の参照)は「junction:<flow.json のキー>」。クエストは内部パス(Export に無いものは extra:<名前>)
QUEST_JUNCTION_PREFIX = "junction:"


# Helminth: 吸収できるアビリティの一覧(data/helminth/ の中。どのフレームから何を吸収できるかは Export に無いので手で書く)。
# Helminth 自身のアビリティ(Export の ExportAbilities)は frame を HELMINTH_FRAME にして同じ一覧に書く。Export に無くても消さない
HELMINTH_SUBSUME_FILE = "subsume.json"


HELMINTH_FRAME = "Helminth"


# ビルド管理で置き換えられるアビリティの番号(1〜4)
HELMINTH_SLOTS = (1, 2, 3, 4)


# アルコンの欠片: 色ごとの効果の一覧(data/archon/ の中)。効果の種類と値は Export に無いので、ゲーム画面を見て手で書く。
# 文の {v} {max} {per} に値を埋める。Tauforged は値に tauforged_rate を掛ける(効果ごとの "tauforged" で上書きできる)
ARCHON_SHARDS_FILE = "shards.json"


# ビルドに付けられる欠片の数(Warframe の枠の数)
ARCHON_SLOTS = 5


# 効果の値の項目(文の {v} = value)
ARCHON_VALUE_KEYS = ("value", "max", "per")


# 開発者のビルド(data/builds/ の中)。ビルド管理の builds.json と同じ形のビルドを並べ、外側に as_of(いつ時点か)を付ける。
# 作るのは tools/dev_builds.py(タグ DEV_BUILDS_TAG のビルドを選ぶ)。ツールから書き込まない。Q&A が読む
DEV_BUILDS_FILE = "dev_builds.json"


DEV_BUILDS_TAG = "Developer"


# ビルドに書ける項目(この順で書き出す)。images は配らない。as_of はビルドごとに外側の値を上書きしたいときだけ
DEV_BUILD_KEYS = ("name", "type", "target", "forma", "mods", "arcanes", "tags", "note", "helminth", "shards", "as_of")


# 言語ごとに書ける項目(文字列か {"ja", "en"})
DEV_BUILD_LANGS = ("ja", "en")


# 呼び出し(Warframe の中から呼び出す、Warframe のような存在。例: Sevagoth's Shadow)。data/summons/ の中。
# 公式データに本体の数値・アビリティが無いので手で書く(ゲーム画面の値)。Export に無くても消さない。ビルド管理の種別は BUILD_TYPES の summon
SUMMONS_FILE = "summons.json"


# 数値の項目(frame の builder.json と同じ名前)とアビリティの番号
SUMMON_STATS = ("health", "shield", "armor", "energy", "sprint")


SUMMON_SLOTS = (1, 2, 3, 4)


# Q&A からビルド管理に追加するときの名前の初期値の末尾(例: Jade_dev)
DEV_BUILD_SUFFIX = "_dev"


# 開発者のビルドを基本の名前でも拾う派生の語(対象の末尾。例: Ash → Ash Prime、Excalibur → Excalibur Umbra)
DEV_BUILD_VARIANTS = ("Prime", "Umbra")


# Q&A からビルド管理に追加したビルドのメモの末尾(利用者のデータに入る文。日本語のみ)
DEV_BUILD_NOTE = "(開発者のビルド・{as_of}時点)"


# Q&A(LLM なし版): 質問から名前と聞きたいことを拾い、データから決まった文の型で答える。**日本語のみ**(答えの文は I18N に入れない)。
# 同梱データは data/qa/ の中: キーワードの表・答えの文の型・ヒットしなかったときの文
QA_INTENTS_FILE = "intents.json"


QA_ANSWERS_FILE = "answers.json"


QA_MISS_FILE = "miss.json"


# 解説(設定・ストーリー)と、解説のセリフ(枕詞・ネタバレの確認など)。解説の種類: 設定(クエストと無縁)/ クエストの中身(requires で確認)
QA_LORE_FILE = "lore.json"


QA_LORE_TALK_FILE = "lore_talk.json"


QA_LORE_TYPES = ("setting", "quest", "system")


# lore_talk.json の一言の場面(すべて {id, ja} の一覧からランダムに1つ)
QA_LORE_LINES = ("spoiler_ask", "spoiler_ok", "spoiler_ng", "declined", "ask_what", "next_stage", "pick_topic")


# 「教えてクロちゃん」(話題のメニュー。core.qamenu)。QA_MENU_TOP = 分類の一覧(1段目)の id(分類の id には使えない)
QA_MENU_FILE = "menu.json"


QA_MENU_TOP = "top"


# Warframe と関係ない話(core.qatalk): ツールの使い方 tool / 雑談 chat
QA_TALK_FILE = "talk.json"


QA_TALK_TYPES = ("tool", "chat")


# Q&A のアイコン(セファロン クロの姿。core.qaicon)。一覧は data/qa/icons.json、画像は data/qa/icons/<姿の id>/
QA_ICONS_FILE = "icons.json"


QA_ICON_DIR = "icons"


# 画像の拡張子 -> Content-Type(この表に無い拡張子は使えない)
QA_ICON_MIME = {"svg": "image/svg+xml", "png": "image/png", "webp": "image/webp", "ico": "image/x-icon"}


# 答えの場面: /api/qa の応答の type -> 場面(icons.json の images のキー)。無い type・姿に無い場面は QA_ICON_DEFAULT_SCENE
QA_ICON_SCENES = {"menu": "greet", "lore": "lore", "spoiler_ask": "lore", "talk": "talk",
                  "answer": "answer", "options": "answer", "miss": "miss"}


QA_ICON_DEFAULT_SCENE = "default"


# アイコンの画像の応答のキャッシュ(更新で差し替わるので immutable にしない)と、メニューのアイコンの URL の名前(/qa-icon/menu)
QA_ICON_CACHE = "private, max-age=86400"


QA_ICON_MENU = "menu"


# 名前の種類: フレーム・武器(builder.json)/ アイテム(ドロップ表)/ アビリティ(builder.json と吸収一覧)/
# 吸収一覧のフレーム(Helminth 自身・Orion & Sirius など builder.json に無いもの)/ 開発者のビルドの名前・対象 /
# 呼び出し(data/summons/。Sevagoth's Shadow など)
QA_KINDS = ("frame", "weapon", "item", "ability", "hframe", "devbuild", "summon")


# 解説の needs に書く種類の印(「@frame」= 拾った名前がフレームなら当たり)。印の後ろは QA_KINDS のどれか
QA_NEEDS_MARK = "@"


# ヒットしなかったときの場面: 名前が拾えない / 聞きたいことが分からない / 開発者のビルドが無い / データが無い(データ更新の前)/ データに答えが無い
QA_MISS_KINDS = ("no_name", "no_intent", "no_build", "no_data", "no_hit")


# 文の形式: 数値 / 割合(0.25 → 25%)/ 倍率(x2)/ 秒
QA_FORMATS = ("num", "pct", "mult", "sec")


# 入手先の答えに出す件数(本体 / パーツごと)と、拾えなかったときの候補の数
QA_SOURCE_LIMIT = 8


QA_PART_SOURCE_LIMIT = 2


QA_CANDIDATE_LIMIT = 6


# レリックは時代(Lith など。ERA_JA のキー)ごとにまとめて答える: 入手先の場所の件数と、時代が無いときに候補(時代の一覧)を出す語
QA_RELIC_SOURCE_LIMIT = 8


QA_RELIC_WORDS = ("レリック", "relic", "relics")


# 英字の名前はこれより短いと拾わない(「Ash」などが単語の中で当たらないよう、英字は単語の区切りも見る)
QA_MIN_ASCII = 3


QA_MIN_LABEL = 2


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
# 手で書いた入手先のクエスト名を詳細欄に出すときの形は web/i18n の src.quest.<入手先のキー>(無い入手先はクエスト名そのまま)


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


# ExportRegions の missionIndex -> ミッションの種類(MODES_JA のキー。画面は I18N の mode.<キー>)。
# 対応は WARFRAME Wiki の Module:Missions/data の Index(2026-11-08 確認)。MODES_JA に無い種類は書かない(画面は「不明」と番号)。
# 8 は防衛・ミラー防衛・ステージ防衛で共通(ExportRegions では区別できない)
REGION_MISSIONS = {
    0: "Assassination", 1: "Exterminate", 2: "Survival", 3: "Rescue", 4: "Sabotage", 5: "Capture", 7: "Spy",
    8: "Defense", 9: "Mobile Defense", 10: "Conclave", 13: "Interception", 17: "Excavation", 21: "Infested Salvage",
    22: "Arena", 24: "Pursuit", 25: "Rush", 27: "Defection", 31: "The Circuit", 33: "Disruption", 34: "Void Flood",
    35: "Void Cascade", 36: "Void Armageddon", 38: "Alchemy", 39: "Ascension", 40: "Legacyte Harvest", 41: "Shrine Defense",
}


# ExportRegions の factionIndex -> 勢力のキー(FACTIONS_JA。画面は I18N の faction.<キー>)。
# 公式の対応表が無いので、ノードの勢力から確かめた(2026-11-08。3 = ヴォイド(和名はオロキン)、5 = Ropalolyst、7 = ダイモスの研究所(和名はササヤキ)、8・9 = ホルバニア)
REGION_FACTIONS = {
    0: "FC_GRINEER", 1: "FC_CORPUS", 2: "FC_INFESTATION", 3: "FC_OROKIN", 5: "FC_SENTIENT", 7: "FC_MURMUR",
    8: "FC_SCALDRA", 9: "FC_TECHROT", 10: "FC_DUVIRI", 11: "FC_TENNO",
}


FACTIONS_JA = {
    "FC_GRINEER": "グリニア", "FC_CORPUS": "コーパス", "FC_INFESTATION": "感染体", "FC_OROKIN": "オロキン",
    "FC_SENTIENT": "センティエント", "FC_MURMUR": "ササヤキ", "FC_SCALDRA": "スカルドラ", "FC_TECHROT": "テクロット",
    "FC_DUVIRI": "デュヴィリ", "FC_TENNO": "テンノ",
}


# 利用者データの置き場(SQLite。wfp/store/userdb.py)。所持・マスター済み・ビルドなどを1つのファイルに入れる。
# バックアップは同じ中身の別ファイルで、起動したときと USERDB_BACKUP_INTERVAL 秒ごとに、本体が変わっていれば写す
USERDB_FILE = "userdata.db"


USERDB_BACKUP_FILE = "userdata_backup.db"


USERDB_SCHEMA_VERSION = 1      # テーブルの形の版(形を変えたら上げて、読み替えを足す)


USERDB_BACKUP_INTERVAL = 600   # バックアップを確かめる間隔(秒)


USERDB_TIMEOUT = 5             # ほかの書き込みを待つ秒数


# 仲裁(Arbitration)のスケジュール: browse.wf が公開している CSV(1 行 =「UNIX 時刻(秒・UTC。その 1 時間の始まり),ノードの内部名」。
# 古い順・1 時間ごと・数年先まで)。データ更新とページのボタンで取り直し、取れなければ前回分を使う
ARBYS_URL = "https://browse.wf/arbys.txt"


ARBYS_FILE = "arbys.txt"


ARBY_SLOT = 3600   # 1 件の長さ(秒)


ARBY_COUNT = 13    # 出す件数(今の 1 件 + 次の 12 件)


# 目立たせる仲裁(画面で背景に色。開催中はオレンジ・まだの枠はクリーム)。種類(MODES_JA のキー)のどれか かつ 勢力のどれか。
# 2026-11-08 利用者の指定: 防衛・耐久 かつ 感染体(ミラー防衛は入れない)
ARBY_PICK = {"missions": ("Defense", "Survival"), "factions": ("FC_INFESTATION",)}


# 文字の正規化(core.text の norm・spaced): 消す記号と、単語の区切りとして扱う文字(正規表現の文字クラスの中身)。
# norm は両方とも消し、spaced は区切りを1つの空白で残す
TEXT_PUNCT = "'’,()（）・･"
TEXT_SEP = r"\s\-_"


# --------------------------------------------------------------------------
# シミュレータ用のデータ・内部パスの辞書・World State(2026-11-10 に wfp の外のファイルから移した。D4)
# --------------------------------------------------------------------------

# シミュレータ用のデータ(フレーム・武器の性能)。データ更新・シミュレータ用データの取得で Export から作る(core/simdata)
BUILDER_FILE = "builder.json"
BUILDER_EXPORTS = ("ExportWarframes", "ExportWeapons")
# 武器のカテゴリー: ExportWeapons の productCategory -> SIM_CATS のキー
SIM_WEAPON_CATS = {"LongGuns": "primary", "Pistols": "secondary", "Melee": "melee",
                   "SpaceGuns": "archgun", "SentinelWeapons": "robotic"}

# 内部パス -> 英語名(データ更新で Export から作る。core/names の item_paths_from_exports。バロ吉・侵略サイクルの照合)
ITEM_PATHS_FILE = "item_paths.json"

# 公式 World State(core/worldstate・fetch/worldstate)。新しい URL を先に試し、だめなら以前の URL。
# URL にクエリを付けると中身が空で返る(2026-10 時点)ので付けない
WORLDSTATE_URLS = [
    "https://api.warframe.com/cdn/worldState.php",
    "https://content.warframe.com/dynamic/worldState.php",
]
WORLDSTATE_COOLDOWN = 60          # 秒。前回の取得からこの間は取り直さない(CDN のキャッシュ max-age 60 と同じ)
WORLDSTATE_CLOCK_TOLERANCE = 2.0  # 秒。Date ヘッダーは 1 秒単位なので、これ未満のずれは 0 とみなす
WORLDSTATE_FILE = "worldstate.json"  # 取り出した結果だけを保存する(取得した全文は保存しない)
# バロ(Void 商人)が来る中継地点: World State のノード -> (名前, 惑星の英名。無ければ空)
BARO_RELAYS = {
    "MercuryHUB": ("Larunda Relay", "Mercury"), "VenusHUB": ("Vesper Relay", "Venus"),
    "EarthHUB": ("Strata Relay", "Earth"), "SaturnHUB": ("Kronia Relay", "Saturn"),
    "ErisHUB": ("Kuiper Relay", "Eris"), "EuropaHUB": ("Leonov Relay", "Europa"),
    "PlutoHUB": ("Orcus Relay", "Pluto"), "TennoConHUB2": ("TennoCon Relay", ""),
}

# --- 画面のサーバー(wfp/api/server.py) ---
# どの応答にも付けるヘッダー。ほかのサイトのページに埋め込ませない(シミュレータの iframe は同じオリジンなので通る)・
# ほかのサイトから画像やスクリプトとして読み込ませない・中身から種類を推測させない
SERVER_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "frame-ancestors 'self'",
    "Cross-Origin-Resource-Policy": "same-origin",
}
# /api/ への要求で通す Sec-Fetch-Site の値(ブラウザが付ける「どこからの要求か」)。same-origin = この画面から・none = アドレス欄などから直接。
# ほか(cross-site = ほかのサイト・same-site = localhost の別のポートのページ)は断る。ヘッダーが無い要求(古いブラウザ・CLI・curl)は通す
API_FETCH_SITES = ("same-origin", "none")
REQUEST_MAX_BYTES = 1_000_000  # JSON の本文の上限(バイト)。画像の上限は store/build_images の IMAGE_MAX_BYTES
