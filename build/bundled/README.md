# wfportal

Warframe 用のポータルツール(Python 同梱版。インストール不要・Windows 10 / 11 専用)。

> **非公式のファンツールです / Unofficial fan tool**
> このツールは有志が個人で作成した非公式のファンツールで、Digital Extremes Ltd. とは一切関係がなく、同社の承認・支援・監修を受けたものではありません。
> This is an unofficial, fan-made tool. It is not affiliated with, endorsed, sponsored, or approved by Digital Extremes Ltd.
> Warframe および関連する名称・ロゴ・画像は Digital Extremes Ltd. の商標または著作物です。
>
> 無料で配布しています(営利目的ではありません)。使用条件と免責事項は [LICENSE](LICENSE) を参照してください。ご利用の前に、下の「[ご利用にあたっての注意](#ご利用にあたっての注意)」も必ずお読みください。

## 動作環境(Python 同梱版)

- **Python のインストールは不要です。** この版には、Python 公式(python.org)が配布している Windows 用の「埋め込み版 Python」(Python 3.15.2 / 64 ビット)を `python/` フォルダに同梱しています。
  - インストール作業はなく、PC の設定(PATH など)も変更しません。不要になったらフォルダごと削除するだけです。
  - すでに Python をお使いの方は、Python を同梱していない通常版(lite 版)もお使いいただけます。
- **OS**: Windows 10 / 11(64 ビット)専用です。
- **ブラウザ**: 画面はブラウザで表示します。「ゲーム画面の読み取り」は Chrome または Edge が必要です。
- **インターネット接続**: データ更新と、初回のロゴ素材の取得のときに必要です。

### はじめ方

1. ダウンロードした zip を右クリックして **「すべて展開」** します(zip を開いたままでは動きません)。
2. 展開したフォルダの中の **`start_wfportal.bat` をダブルクリック** します。
3. ブラウザで画面が開いたら、左のメニューの「データ更新」から「公式データを取得」を押します。

- 黒い画面(コマンドプロンプト)は、使っている間は閉じないでください。閉じるとツールが止まります。
- bat を開くときにセキュリティの警告が出ることがあります。インターネットから入手したファイルを開くときに Windows が表示する確認です。配布元を確認したうえで実行してください。

## フォルダ構成

```
WarframePortalTool/
├── wfportal.py          # コマンドラインの入口(中身は wfp/)
├── wfportal_ui.py       # ブラウザ UI のローカルサーバーの入口(中身は wfp/api/)
├── wfp/                 # 本体(データ取得・検索・各機能の処理、コマンドラインと画面の API)
├── wfportal_ocr.py      # ビルド画像の自動解析(文字認識の結果を名前一覧と照合)
├── wfportal_builder.py  # シミュレータの計算(フレーム・武器・Riven)
├── wfportal_worldstate.py # 公式 World State の取得(サイクルの時刻合わせ・バロの今回の品物・侵略)
├── wfportal_baro.py     # バロ吉入手一覧(Void 商人の品物と所持の照合)
├── data/
│   ├── baro_rules.json  # バロ吉入手一覧の初期リストの調整(除外する Primed MOD・追加する品物。編集できます)
│   ├── duviri/          # デュヴィリサーキットのローテーション(rotate.json 基準の週・normal.json / steelpath.json 報酬)
│   ├── spexchange/      # 鋼の道のり交換のローテーション(spex_rotate.json 基準の週・steelpath_exchange.json 報酬)
│   └── invasion/        # 侵略サイクルの獲得パーツ一覧(parts.json 武器ごとのパーツと内部パス)
├── wfportal_update.py   # 起動時の自動更新(GitHub の新しい版と比べて、変わったファイルだけ置き換える)
├── version.json         # この版のバージョン(例: 1.00)
├── ocr/
│   └── winocr.ps1       # Windows 標準の文字認識(Windows.Media.Ocr)を呼ぶスクリプト
├── start_wfportal.bat   # Windows 用: ダブルクリックで UI を起動(初回はロゴ素材も取得)
├── LICENSE              # 使用条件・免責事項
├── python/              # 同梱の Python (python.org 公式の埋め込み版 Python 3.15.2。中身は変更しない)
├── web/
│   ├── ctrl.html        # UI 画面の基礎部(骨組み・画面の動き。タブのアイコンもここに埋め込み)
│   ├── menu.html        # UI 画面のメニュー部(メニューの並びと表示する文字)
│   ├── view.html        # UI 画面の表示部(配色・ロゴと各ページの見た目)
│   └── wfportal_builder.html # シミュレータの画面(UI 画面の中に表示)
├── tips/                # Tips ページに表示するメモ(.md / .txt / .csv。自由に編集・追加できます)
└── assets/
    └── Logos/           # 公式ファンキットのロゴ素材 (同梱していません。初回起動時に各自の PC へ自動で取得・作成)
```

コマンドはすべてこのフォルダ(`WarframePortalTool/`)で実行します。

## バージョンと自動更新

- いまの版は `version.json` に書いてあります(例: `1.00`)。画面の左上のタイトルの横にも表示されます。`python wfportal.py --version` でも確認できます。
- バージョンは 0.10 ずつ上がります(1.00 → 1.10 → 1.20 …)。小さな修正は 0.01(1.10 → 1.11)のこともあります。
- `start_wfportal.bat` で起動すると、最初に GitHub の最新の版と比べます。新しい版があれば、**変わったファイルだけ** を取得して置き換えてから起動します(`wfportal_update.py`)。
  - 取得したファイルは、一覧(マニフェスト)の SHA-256 と一致するか確かめてから、まとめて置き換えます。途中で失敗したときは何も変えずに、いまの版のまま起動します。
  - インターネットにつながらないとき・GitHub を見られないときも、そのまま起動します。
  - `tips/` のメモは、自分で書き換えたもの・自分で消したものはそのままにします(配布したままのメモだけを更新し、新しいメモは追加します)。
  - 同梱の Python(`python/`)・ロゴ素材(`assets/`)・データ置き場(`~/.wfportal`)には触りません。
  - 起動用の bat 自身が新しくなったときは、入れ替えてから自動で起動し直します。
  - 自動更新を止めたいときは、このフォルダに `NO_AUTO_UPDATE` という名前の空のファイルを置いてください。手動で確かめるだけなら `python wfportal_update.py --check` です。
  - 更新は配布用の公開リポジトリ(GabbaAimGaming/WarframePortalTool-release)から取得します。

## はじめに

> **Python 同梱版でコマンドを使うとき**: 以下の例の `python` は、同梱の Python を指す `python\python.exe` に読み替えてください(例: `python\python.exe wfportal.py update`)。コマンドプロンプトでこのフォルダに移動してから実行します。通常は `start_wfportal.bat` と画面だけで使えるので、コマンドを使う必要はありません。

```
python wfportal.py update
```

次のデータを取得して `~/.wfportal` に保存します(`WFPORTAL_DIR` または `--data-dir` で変更可)。

| 用途 | 取得元 |
|---|---|
| ドロップ表(ミッション報酬) | [WFCD/warframe-drop-data](https://github.com/WFCD/warframe-drop-data)(公式ドロップ表を JSON 化したもの。drops.warframestat.us → 失敗時は GitHub) |
| 敵・バウンティ・レリック等の入手先 | 同上の `resourceByAvatar` `enemyModTables` `relics` `cetusBountyRewards` など 16 ファイル(`wfcd/` に保存) |
| Riven 相場 | 公式の [weeklyRivensPC.json](https://www-static.warframe.com/repos/weeklyRivensPC.json)(PC 版・毎週更新)。取得できなければ WFCD の [api.warframestat.us/pc/rivens](https://api.warframestat.us/pc/rivens)(同じ統計) |
| 日本語名・MOD 情報 | [calamity-inc/warframe-public-export](https://github.com/calamity-inc/warframe-public-export)(公式 Public Export を展開済み JSON にしたもの)。取得できなければ公式 Public Export(`content.warframe.com`)から直接。バロの品物の名前用に、外装・グリフ・クエスト・ブースター・設計図の Export も取得します。侵略サイクルのノード名用に、ノードの Export(ExportRegions)も別に取得します |
| サイクルの時刻合わせ・バロの今回の品物・侵略の一覧(ボタンを押したときだけ) | 公式の World State(`api.warframe.com`。取得できなければ `content.warframe.com`) |

| ロゴ素材(初回のみ) | Digital Extremes 公式の [Warframe Fan Kit](https://www.warframe.com/news/warframe-fansite-kit)(Dropbox)の Logos フォルダ。下の「公式配布素材(ロゴ)について」を参照 |

ゲームのアップデート後に `update` を再実行すると最新になります。ドロップ表と名前辞書以外は、取得に失敗しても前回の分を使って続けます。

## ブラウザで使う(UI)

Windows では `start_wfportal.bat` をダブルクリックするだけで起動できます(黒い画面は使っている間は開いたままにしてください)。
初回の起動時は、公式ファンキットのロゴ素材を取得してから画面を開きます(数十秒かかることがあります)。

```
python wfportal_ui.py
python wfportal.py          # 同じ画面が開きます(python wfportal.py serve でも可)
```

ブラウザが開き、左のメニューは「各種検索」「個人チェック表」「情報」「シミュレーション」のカテゴリーに分かれていて、カテゴリーを押すと中のページが開きます(同時に開くカテゴリーは1つ)。各種検索: 素材から探す・パーツ検索・エリアから探す / 個人チェック表: マスター一覧・MOD入手一覧・アルケイン所持一覧・バロ吉入手一覧 / 情報: Riven相場・侵略サイクル・サイクル・デュヴィリサーキット / シミュレーション: ビルド・シミュレータ。メニューの一番上の「トップ」は、各ページへのジャンプボタンをカテゴリごとに並べたページです(初めて開いたときに表示されます)。「トップ」「Tips」「ページ説明」「データ更新」は単独のボタンで、「ページ説明」は各ページでできることの説明です。自分のPCの中だけ(127.0.0.1)で動き、データは下記のコマンドラインと共通です。
初回は「データ更新」でデータを取得してください。`--port 9000` `--no-open` `--data-dir` も指定できます。配色は `web/view.html` 先頭の `:root` にまとめています。

**表示する言語(日本語 / English)**: 画面右上の「JA」「EN」で、画面の表示を日本語と英語で切り替えられます(シミュレータも一緒に切り替わります)。選んだ言語はこのブラウザに覚えます。アイテム・武器などの名前は、日本語の画面では日本語名(下に英名)、英語の画面では英名で表示します。Tips は説明文・ボタン・編集画面・確認の小窓・ゴミ箱が切り替わり、目次の名前とメモの中身(同梱の例文も)、コマンドライン(下記)は日本語のままです。

- **素材から探す**: ミッション・敵・バウンティ・レリック・特殊ミッション(仲裁・遺棄船など)・キー/ボス・ソーティーの入手先をまとめて表示し、種類ごとに絞り込めます。「素材のみ」を外すと MOD や設計図も探せます。
- **パーツ検索**: Warframe・武器などの本体・設計図・パーツだけを候補に出し、入手先と確率を表示します。候補はマスター一覧と同じカテゴリー(ファウンダー・その他を除く)で絞り込めます。「Prime を除外する」にチェックすると、入手先がレリックのもの(Prime の設計図・パーツ)を候補から外します。入手状況は記録しません。クラン研究(研究所を表示)・Simaris 交換・クエスト報酬で手に入る設計図も入手先に出ます(確率は「—」)。Octavia の Mandachord のような設計図ではない作成素材も出ます。どれにも無いもの(マーケット・侵略の報酬など)は出てきません。
- **MOD入手一覧**: 全 MOD(約1200件)の種別・極性・レア度・入手先の件数・最も確率が高い入手先を一覧にします。行をクリックすると入手先の詳細、左端のチェックで所持状況を記録(`mods_owned.json`)、見出しクリックで並べ替え、「CSVで保存」で Excel 用の CSV を保存できます。
  - **ゲーム画面の読み取り**(Windows 10/11): 「ゲーム画面の読み取り: OFF」を押して ON にし、共有するウィンドウ(Warframe)を選ぶと、ON の間は数秒ごとに画面を取り込みます。ゲームの MOD 画面を開いてスクロールしていくと、映った MOD 名を Windows の文字認識で読み取り、所持にチェックしていきます。画面が変わったときだけ読み取ります。
    - 一致度が高いもの(90%以上)は自動でチェックします。低いものは「要確認」に出るので、正しければクリックしてください。
    - 自動でチェックした分は「新しく所持にした」から × で取り消せます。「自動でチェックせず、確認してから付ける」にすると、すべて要確認に出ます。
    - 排他的フルスクリーンでは映らないことがあります。その場合はゲームをボーダーレス(ウィンドウ)表示にするか、「スクリーンショットから読み取る」で画像ファイルを読み込んでください(複数枚まとめて選べます)。
    - 画面の取り込みはブラウザの画面共有機能を使います(Chrome / Edge)。取り込んだ画像は文字認識に使うだけで、保存しません。
- **アルケイン所持一覧**: 公式データ(ExportRelicArcane.json)のアルケイン(約170件)を、Warframe / プライマリ / セカンダリ / 近接 / Kitgun / Zaw / オペレーター / アンプ / テクトリスト のカテゴリーごとのタブで、名前・レア度をカタカナにして一覧にします(英語名でも絞り込めます)。左端のチェックで所持を記録し、所持しているものはランク(0〜最大ランク。Pax・Exodia・Virtuos などは 3、ほかは 5)を選べます(`arcanes_owned.json`)。チェックを外すとランクも消えます。名前と状態(所持のみ・未所持のみ・ランク最大のみなど)で絞り込み、見出しクリックで並べ替え、表示中のタブを CSV で保存できます。種類は名前の最初の語で判定します(Arcane・Molt・Theorem は Warframe、Magus・Emergence はオペレーター、Virtuos・Eternal はアンプなど。判定できない新しいアルケインは「その他」)。テクトリストアーティファクト用の Zid-An は、公式データにまだ無いためドロップ表から補います(英語名・レア度なし・最大ランク 5。公式データに入ればそちらを使います)。公式データにあってもゲームに実装されていない 7 件(Arcane Survival・Shield・Defense・Detoxifier・Liquid・Protection・Temperance)は載せません。この機能を追加する前に取得したデータには含まれていないため、一度「データ更新」が必要です。
- **バロ吉入手一覧**: Void 商人(Baro Ki'Teer)が今回持ってきた品物と、履歴リスト(これまでに持ってきた品物)を、自分の所持と照合します。今回の品物は「バロ情報を更新」を押したときだけ公式の World State から取得します(`worldstate.json`)。バロが来ていないときは、次に来る日時と場所を表示します。履歴リストは、公式データから作る初期リスト(名前が Prisma で始まるマスター対象・名前が Primed で始まるレジェンダリーの MOD・Primed Chamber)に、この PC で記録した来訪を足したものです。バロが来ているときに更新すると、その来訪を記録し(`baro_seen.json`)、リストに無い品物は追加、ある品物は「最後に来た日」「回数」を更新します。過去の日付は分からないため、「最後に来た日」「回数」はこの PC で記録した来訪だけで数えます(TennoCon の来訪は記録しません)。初期リストから外す Primed MOD(ログインボーナスでも手に入るものなど)と追加する品物は `data/baro_rules.json` で変えられます。MOD は「MOD入手一覧」の所持、武器は「マスター一覧」のマスター済み(= 入手したことがある)で判定し、装飾・外装・グリフなどはこのページのチェックで記録します(`baro_owned.json`)。名前が Skin で終わるものは装飾・外装として扱います。消耗品・ブースター・レリックなど何度でも買えるものは照合しません。品物の名前と初期リストには、この機能を追加したあとに一度「データ更新」が必要です。
- **Riven相場**: 武器ごとに(武器種の Kitgun・Zaw は英語表記)未リロール/リロール済みの中央値・平均・範囲・件数を表示します(単位はプラチナ)。「Riven相場だけ更新」ボタンで、ほかのデータを取り直さずに Riven 相場だけを更新できます(「データ更新」画面の「Riven相場だけ取得」も同じ)。
- **マスター一覧**: Warframe / プライマリ / セカンダリ / 近接 / Kitgun / Zaw / ロボティック / コンパニオン / アークウイング / アークウイングガン / アークウイング近接 / ネクロメカ / Kドライブ / アンプ / その他 のカテゴリーごと、または全体で、マスター済みかどうかをチェックして記録します(`mastered.json`)。カテゴリーのボタンでマスター済み数/総数を、上部に全体の進み具合とマスタリー経験値の合計を表示します。名前での絞り込み、未マスターのみの表示、表示中の一括チェック、CSV 保存ができます。ファウンダー限定の Excalibur Prime・Skana Prime・Lato Prime は、「ファウンダー」にチェックを入れたときだけ「ファウンダー」の項目に表示し、件数と経験値の合計に入れます(チェックの状態はこのブラウザに保存)。プレクサスとアンプ本体は公式データに無いため、ツールに同梱の `data/mastery/extra.json` から足しています。
- **侵略サイクル**: いま進行中の侵略を、場所(惑星・ノード)・攻め側と守り側の報酬・進み具合のカードで表示し、右側に侵略で手に入る武器パーツ(Wraith・Vandal・Sheev の7武器)の一覧を出します。手に入れたパーツにチェックを付けて管理でき(`invasion_parts.json`。ツールの更新では消えません)、いま侵略の報酬に来ているパーツには「侵略中」の印が付きます。侵略の一覧は「公式データで更新」を押したときだけ公式の World State から取得します(`worldstate.json`。60 秒以内に押し直したときは前回の結果を使います)。完了した侵略は表示しません。ノード名は「データ更新」で取得する辞書(`regions.json`)を使い、まだ無いときは内部名(例: SolNode131)で表示します。武器名は英語、パーツ名は日本語で表示します。パーツの一覧は `data/invasion/` にツールと一緒に配布しています(一覧に無い武器パーツが侵略に来たときは、ページに知らせが出ます)。
- **サイクル**: 平原(Cetus)・カンビオンの荒地・オーブ峡谷・ZARIMAN・デュヴィリの切り替えと、デイリー・ウィークリーのリセットまでの時間を表示します。周期から計算するので通信しなくても表示できます。「公式データで時刻合わせ」を押したときだけ公式の World State に問い合わせて、平原・ZARIMANの切り替わりと PC の時計のずれを合わせます(60 秒以内に押し直したときは前回の結果を使います)。公式データが取れないときは、平原とオーブ峡谷をゲーム内の残り時間で手動で合わせることもできます。鋼の道のりの「スティール・エッセンス交換」の今週の報酬と今後の並びも表示します(毎週月曜 9:00 JST に切り替わり。中身は `data/spexchange/` にツールと一緒に配布しています。報酬の名前は一部だけ日本語にして、ほかは英語のまま表示します)。
- **デュヴィリサーキット**: サーキットで選べる報酬(ノーマル / 鋼の道のり)の今週分と、来週以降のローテーションを表示します。毎週月曜 9:00(JST)のウィークリーリセットで切り替わり、通信しなくても表示できます(「サイクル」で公式データと時刻合わせしていれば、その時計のずれも反映します)。タブは最後に選んだ方を覚えています。ゲーム内の報酬とズレているときは、ページ下の「手動で調整」で今週の ID を選び直すと、以降はそこから毎週進めて表示します(`duviri_adjust.json`。モードごと・ツールの更新では消えません。「同梱の設定に戻す」で消せます)。ローテーションの中身は `data/duviri/` にツールと一緒に配布しています(ツールの更新で置き換わるので、直したいときは手動調整を使ってください)。報酬の名前は英語のまま表示します(Normal は Warframe、Steel Path は武器)。
- **ビルド**: 画像(MOD 構成のスクリーンショットなど)を添付できます。「クリックして選ぶ」「ドラッグ&ドロップ」「Ctrl+V で貼り付け」のどれでも追加でき、一覧のサムネイルをクリックすると拡大表示します。4MB を超える画像は保存前に自動で縮小します。画像はデータ置き場の `build_images/` に保存され、ビルドを削除すると一緒に消えます。
- **アルケイン**: ビルドにアルケインを登録できます。「候補から追加」に名前の一部を入れると公式のアルケイン名(約170件)が候補に出ます。装備できる数(Warframe 2つ、プライマリ・セカンダリ・近接 1つ)を超えたときや、一覧に無い名前のときは注意を表示します。画像の自動解析で読み取ったアルケインはアルケイン欄に入ります。
- **ビルド画像の自動解析(Windows 10/11)**: 画像を追加すると、Windows 標準の文字認識で読み取り、フレーム/武器名・MOD・フォーマ数・極性を空欄の項目に自動入力します(「フォームにすべて反映」で上書きも可)。詳しくは下の「ビルド画像の自動解析」を参照してください。
- **シミュレータ**: フレーム・武器・Riven の性能を計算する参考ツールです(画面上部のタブで切り替え)。値はすべて参考値で、入力欄で直しながら使えます。
  - フレーム: ランク 30 のヘルス・シールド・アーマー・エネルギー、MOD(%・固定値)を足した値、実効ヘルス(被ダメージ軽減を含む)、アビリティの威力・持続時間・範囲・効率(効率は上限 175%)。アビリティの基準値を入れると MOD 適用後の参考値も出します
  - 武器: MOD を足したダメージの内訳(属性 MOD は上から2つずつ複合)、クリティカル込みの1発の平均、瞬間 DPS・リロード込み DPS、状態異常 / 秒
  - Riven 振れ幅: 武器(または Riven の種類)・効果の組み合わせ・ランクから、各効果の最小〜最大を計算します(性質値は 1.20 固定)
  - フレームと武器の基礎値は公式 Public Export(ExportWarframes / ExportWeapons)から「データ更新」のときに作ります(`builder.json`)。MOD の効果量・Riven の基準値は WARFRAME Wiki などの公開情報をもとにした参考値です
- **Tips**: すぐ見たいメモをまとめるページです。左の目次でメモを選ぶと、右に内容を表示します。中身はツールのフォルダにある `tips/` フォルダのファイルで、このページの「新規」「編集」「削除」「グループ追加」で追加・編集できるほか、メモ帳や Excel で直接編集・追加・削除してもそのまま反映されます(「再読み込み」ボタン、または Tips を開き直す)。「tips フォルダを開く」ボタンでフォルダを開けます。
  - ページで作る・編集できるのは `.md` だけです(900KB まで。`.txt` / `.csv` は削除だけ)。新規はタイトルからファイル名を作り、本文の先頭に `# タイトル` を入れます。編集で見出しを変えてもファイル名は変わりません(ほかのメモからのリンクが切れないように)。ほかのアプリで同じメモを書き換えていたときは、上書きせずに知らせます。保存しないでページを離れようとすると確認します
  - 削除は「ゴミ箱に入れる」(`tips/_trash/` に移します。「ゴミ箱」ボタンの一覧から元に戻せます)か「完全削除する」(2回確認します。メモに貼った画像は残り、ほかのメモからのリンクは切れます)を選べます。グループはページからは追加だけできます(名前の変更・削除・メモの移動は tips フォルダで行ってください)
  - 目次の ▲▼ で並べ替えると `tips/_order.json` に保存され、ファイル名の数字より優先されます。並べ替えていないメモや新しいメモは、末尾に数字の順で並びます
  - 使えるファイル: `.md`(見出し・表・箇条書き・チェックボックス・リンク・画像などの簡単な書き方)/ `.txt`(そのまま表示)/ `.csv`(表として表示。Excel で保存した Shift_JIS の CSV も可)
  - ファイル名の先頭の数字(例: `10_日課.md`)は並び順に使われ、目次には出ません。`.md` の最初の `# 見出し` が目次の名前になります。`tips/` の中にフォルダを作ると目次の見出しになります(1段まで)
  - 書き方の例は同梱の `tips/00_Tipsの使い方.md` にあります。ツールを新しい版に入れ替えるときは、自分の `tips/` フォルダを残して(またはコピーして)ください

### ロゴの表示

ロゴ素材を取得済みなら、ヘッダーに公式ロゴ(LotusFlower.png)が表示されます。未取得のときと、ブラウザのタブのアイコンはオリジナルの図形です。配色は `web/view.html` 先頭の `:root` で変更できます。

## コマンドラインで使う

> **Python 同梱版でコマンドを使うとき**: 以下の例の `python` は、同梱の Python を指す `python\python.exe` に読み替えてください(例: `python\python.exe wfportal.py update`)。コマンドプロンプトでこのフォルダに移動してから実行します。通常は `start_wfportal.bat` と画面だけで使えるので、コマンドを使う必要はありません。

### 素材 → どこで出るか(逆引き)

```
python wfportal.py item ニューロード
python wfportal.py item にゅーろーど        # ひらがな・全角半角・大小文字は区別しない
python wfportal.py item neurodes --limit 20
python wfportal.py item ガ                   # 候補が複数なら一覧を表示 -> --pick 番号
python wfportal.py item 設計図 --all         # MOD・設計図など素材以外も対象
```

種類(ミッション/敵/バウンティ/レリックなど)、入手先、詳細、ステージ(ローテーション)、確率、レア度を確率の高い順に表示します。`--cat enemy` のように種類で絞り込めます(mission / enemy / bounty / relic / special / key / sortie。複数指定可)。

### MOD 入手一覧

```
python wfportal.py mods                       # 全 MOD (先頭 60 件)
python wfportal.py mods vitality              # 名前で絞り込み
python wfportal.py mods --type stance --unowned --limit 100
python wfportal.py mods own Vitality          # 所持済みにする (unown で外す)
```

### アルケイン所持

```
python wfportal.py arcane                                 # 全体 (先頭 60 件) とカテゴリーごとの所持数
python wfportal.py arcane --cat warframe --unowned        # Warframe 用の未所持だけ
python wfportal.py arcane own "Arcane Energize" --rank 5  # 所持にしてランクを設定 (--rank を省くと、所持済みならそのまま・未所持なら 0)
python wfportal.py arcane unown グレイス                   # 未所持にする (ランクも消える)
```

カテゴリー(`--cat`)は warframe / primary / secondary / melee / kitgun / zaw / operator / amp / tektolyst / other。

### バロ吉入手一覧

```
python wfportal.py baro update                       # 今回の品物を公式 World State から取得(来ていれば来訪を記録)
python wfportal.py baro                              # 今回の品物と、履歴リスト(最後に来た日の新しい順、先頭 60 件)
python wfportal.py baro --kind manual --unowned      # 装飾・外装などの未所持だけ
python wfportal.py baro own "Eskhatos Ki'Teer Floof" # 所持にする (unown で外す。装飾・外装などだけ)
```

種類(`--kind`)は mod / weapon / manual(装飾・外装など)/ repeat(消耗品など。照合しない)。MOD は `mods own`、武器は `mastery done` の記録で判定します。

### Riven 相場

```
python wfportal.py riven                      # 中央値の高い順
python wfportal.py riven rubico
python wfportal.py riven --type 近接
python wfportal.py riven --update             # Riven 相場だけ取得し直してから表示
```

### マスター一覧

```
python wfportal.py mastery                       # 全体 (先頭 60 件) とカテゴリーごとの進み具合
python wfportal.py mastery --cat primary --todo  # プライマリの未マスターだけ
python wfportal.py mastery done "Rhino Prime"    # マスター済みにする (undo で外す)
python wfportal.py mastery done catchmoon        # Kitgun はプライマリ版・セカンダリ版の両方
```

カテゴリー(`--cat`)は warframe / primary / secondary / melee / kitgun / zaw / robotic / companion / archgun / archmelee / amp。
数え方:
- Kitgun はチェンバー(プライマリ版とセカンダリ版を別々に)、Zaw はストライク、アンプはプリズムと Sirocco の単位
- グリップやリンクなど、マスタリー経験値が入らない部品は載せない
- アビリティ専用武器(Exalted Blade など)やコンクラーヴ用の部品は載せない
- MOA・ハウンドは頭(Model。Para / Lambeo / Oloro / Nychus、Dorma / Bhaira / Hec)だけをロボティックに載せる(Core・Bracket・Gyro・Stabilizer は載せない)
- ハウンドの武器(Akaten / Batoten / Lacerten)もロボティックに載せる(表示には一度「データ更新」が必要)
- プレクサスとアンプ本体はカテゴリー「その他」(`--cat extra`)。`data/mastery/extra.json` から足す。CLI ではファウンダー限定品 3 件は常に `--cat founder` のカテゴリーに出る
- マスタリー経験値はランク最大までの値: Warframe・コンパニオン・センチネル・MOA/ハウンド・プレクサスは 1 ランク 200、武器は 100(Kuva・Tenet・Coda などランク 40 の武器は 4,000)

### エリア → 何が出るか

```
python wfportal.py area 地球          # 惑星内の全ノード
python wfportal.py area Cervantes     # ノード名でも検索可
python wfportal.py area 地球 --kind part --kind mod   # 種類を選んで表示(複数可)
python wfportal.py area 地球 --all    # すべての種類を表示
```

出現ステージ(ローテーション A/B/C)ごとに、ドロップと確率を表示します。種類は `resource`(素材・既定)/ `part`(パーツ・設計図)/ `mod`(MOD)/ `relic`(レリック)/ `other`(その他)。画面の「エリアから探す」でもチェックで種類を選べます。

### 昼夜サイクルとリセット

```
python wfportal.py cycle
python wfportal.py cycle sync                    # 公式データ(World State)で時刻合わせ
python wfportal.py cycle set cetus 昼 45:30     # ゲーム内で見た「昼の残り 45:30」で時刻合わせ
python wfportal.py cycle set vallis 寒冷 5      # 数字だけなら分
```

平原(Cetus)・カンビオンの荒地(Cetus 連動)・オーブ峡谷・ZARIMAN・デュヴィリを周期から計算します。時刻合わせをしなくても、基準時刻から計算して表示します。`cycle sync` は公式の World State に問い合わせて、平原・ZARIMANの切り替わりと PC の時計のずれを合わせます(60 秒以内に実行し直したときは前回の結果を使います)。`cycle set` は公式データが取れないときの手動の時刻合わせです(平原・オーブ峡谷)。デイリー(毎日 9:00 JST)とウィークリー(月曜 9:00 JST)のリセットまでの時間も表示します。

### ビルド管理

```
python wfportal.py build add "Rhino 耐久" --type frame --target Rhino --forma 3 \
    --mods "Vitality,Steel Fiber,Redirection" --tags 耐久,SP --note "鉄の道向け"
python wfportal.py build list [--type frame] [検索語]
python wfportal.py build show rhino
python wfportal.py build add "Rhino 耐久" --update --forma 4   # 上書き(画像は残る)
python wfportal.py build add "Rhino 耐久" --update --image shot1.png --image shot2.png   # 画像を追加
python wfportal.py build add "Saryn" --type frame --arcanes "Arcane Energize,Arcane Grace"   # アルケインを登録
python wfportal.py build rm rhino
python wfportal.py build export > builds_backup.json
```

`--type` は frame / primary / secondary / melee / companion / archwing / other。

## ビルド画像の自動解析

Windows 10/11 に標準で入っている文字認識(Windows.Media.Ocr)を使います。追加のインストールやインターネット接続は不要です。

- **読み取るもの**
  - 対象: 名前一覧(フレーム・武器・コンパニオン)に一致する中で、いちばん大きく表示されている名前
  - MOD・アルケイン: 画面の上の段から、左から順に。読み間違い(例: `Stee1 Fiber`)は公式の名前一覧と照合して補正し、補正したものは「要確認」と表示します
  - フォーマ数: アップグレード画面の上部「アップグレード/NOVA PRIME [30] (アイコン) (アイコン) 6」の最後の数字(ランクの後ろの数字)を読み、そのまま登録します(入力済みでも上書き)。読めなかったときは、各 MOD カードのドレイン(右上の数字)から推定します
  - 画面下半分の所持 MOD 一覧(「検索...」欄より下)は、装備中の MOD ではないので読み取りません
  - アルケインは日本語版では日本語(例: アルケイン エナージャイズ)で表示されるため、日本語の文字認識の結果から照合して英語名で登録します
  - 極性: MOD ごとの極性(Madurai / Vazarin / Naramon / Zenurik / Unairu / Penjaga / Umbra)と、極性が一致しているスロットの集計(メモ欄に「極性(推定): Vazarin×2, Madurai×1」の形で入ります)
- **フォーマ数の推定方法**: 極性が一致したスロットでは MOD の消費キャパシティが半分になるため、「最大ランクでの消費」と画面のドレインを比べて一致しているスロットを数えます。MOD が最大ランクでない場合は判定できず、元から付いている極性(生まれつきの極性)も1つと数えるので、実際より多くなることがあります。
- **精度を上げるコツ**: ゲームの MOD 画面を、できるだけ大きな解像度でそのまま撮ったスクリーンショットを使ってください。Windows に英語(English)の言語を追加しておくと、英語の MOD 名の読み取り精度が上がります(設定 → 時刻と言語 → 言語と地域)。
- **コマンドラインで確認する**:

```
python wfportal.py build analyze shot.png             # 解析結果を表示
python wfportal.py build analyze shot.png --raw       # 読み取った文字もそのまま表示
python wfportal.py build analyze shot.png --save-ocr ocr.json   # 文字認識の結果を保存(うまく読めないときの報告用)
python wfportal.py build analyze --ocr-json ocr.json  # 保存した結果から解析し直す(Windows 以外でも可)
```

## 公式配布素材(ロゴ)について

ロゴ・Lotus のマーク・フォーカス流派・シンジケートのエンブレムなどは、Digital Extremes が公開している「[Warframe Fan Kit](https://www.warframe.com/news/warframe-fansite-kit)」の Logos フォルダの素材です。権利は Digital Extremes にあるため、**このツールには同梱していません**。各自の PC で、公式の配布元(Dropbox)から直接取得します。

- **自動取得**: `start_wfportal.bat` の初回起動時、またはロゴ素材が未取得の状態で「データ更新」(`python wfportal.py update`)をしたときに取得します。
- **手動取得**: `python wfportal.py logos`(取り直すときは `--force`)
- **保存先**: `assets/Logos/`(書き込めない場合はデータ置き場の `Logos/`)
- 取得に失敗してもツールはロゴ無しで使えます。配布元のリンクが変わった場合は、上の公式ページからファンキットを入手し、Logos フォルダの中身を `assets/Logos/` に置いてください。
- 取得した素材は個人の利用にとどめ、ツールと一緒に再配布しないでください。素材の利用は Digital Extremes の [Content Policy](https://www.warframe.com/contentpolicy) などの定めに従ってください。

## ご利用にあたっての注意

- **非公式ツールです**: Digital Extremes Ltd. とは関係ありません。このツールについて Digital Extremes(ゲームのサポート窓口を含む)に問い合わせないでください。
- **ゲームの規約について**: Digital Extremes は、外部ツールを Warframe と一緒に使う場合は自己責任だとしています。このツールはゲームのファイルやメモリを書き換えたり読み取ったりはせず、ゲームを自動で操作することもありません。ただし「ゲーム画面の読み取り」などの機能を含め、利用はご自身の判断と責任で行ってください。アカウントへの措置などについて、作者は責任を負いません。
- **データの正確さ**: 表示する確率・入手先・相場などは、公式や有志が公開しているデータを取得して加工したものです。誤りや古い情報が含まれることがあります。
- **通信について**: データ取得の際に、上の表にある公開サイトにだけ接続します(公式 World State は、サイクル・バロ吉入手一覧・侵略サイクルのボタンを押したときだけ)。画面(UI)は自分の PC の中(127.0.0.1)だけで動き、ビルドや所持状況などのデータを外部に送ることはありません。画面の取り込み画像は文字認識に使うだけで保存しません。
- **データの再配布**: 取得したデータ(`~/.wfportal`)やロゴ素材には、それぞれの提供元の権利・条件があります。ツールと一緒に再配布しないでください。

## 注意

- 確率の意味は入手先の種類で異なります。
  - ミッション・バウンティ・特殊ミッション: その報酬1回の抽選で、そのアイテムが選ばれる割合
  - 敵: 1体倒したときに落とす割合(「MODドロップ 3%」などは、その敵が MOD を落とす確率を掛けた後の値)
  - レリック: 開けたときに出る割合(無傷と光輝のみ掲載)
- 公式ドロップ表に無い入手方法(シンジケート・バロ・ナイトウェーブ・クエスト報酬など)は「記載なし」になります。
- 極性の名前は、ゲーム内と同じ英字表記(Madurai / Vazarin / Naramon / Zenurik / Unairu / Penjaga / Umbra)で表示します。
- ノード名・敵の名前・MOD 名・武器名は、日本語版のゲーム内でも英字表記のものが多いため英語のまま表示します。日本語名は Public Export にある場合のみ訳されます。
- ドロップ表と公式データで大文字小文字が違う名前(例: Bane Of Grineer / Bane of Grineer)は同じものとして扱います。
- Riven 相場は PC 版のみです。極端な出品価格が混ざるため、平均より中央値が目安になります。

## Python 同梱版をお使いの方へ

同梱の Python を 3.15.2 に更新しました。
自動更新では `python` フォルダは置き換わらないため、最新の Python にするには `WarframePortalTool_with_python.zip` を取り直して展開してください。
データ(`~/.wfportal`)はそのまま引き継がれます。Tips を編集している方は、古いフォルダの `tips` フォルダを新しいフォルダへコピーしてください。
なお、Brotli の脆弱性(CVE-2026-111497)について確認をしましたが、本ツールは Brotli を使っておらず、以前の版も影響を受けません。
不安な方のみ取りなおしを推奨いたします。
