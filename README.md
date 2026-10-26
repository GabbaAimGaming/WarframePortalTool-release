# Warframe Portal Tool(配布用)

非公式のファンツールです / Unofficial fan tool. Digital Extremes Ltd. とは関係ありません。

このリポジトリは **配布専用** です。中身は GitHub Actions が自動で更新します(直接の変更・Pull Request は受け付けていません)。

## ダウンロード

右側の **Releases** から最新の版を開き、どちらかの zip をダウンロードしてください。

| ファイル | 向いている人 |
|---|---|
| `WarframePortalTool_with_python.zip` | Python を入れていない人(Windows 10/11 64bit・インストール不要) |
| `WarframePortalTool_lite.zip` | Python 3.9 以上を入れている人 |

zip を展開して、`start_wfportal.bat` をダブルクリックすると起動します。使い方は zip の中の `README.md` を見てください。

## 自動更新

起動するたびに、このリポジトリの `release/manifest_*.json` と手元の `version.json` を比べます。
新しい版があれば、変わったファイルだけを取得して置き換えてから起動します。

## フォルダの中身

- `release/`: 配布用の zip と、自動更新が見るファイル一覧(マニフェスト)
- それ以外: 自動更新が取得するファイル(zip の中身と同じもの)

ライセンス・免責事項は `LICENSE` を見てください。

## Python 同梱版をお使いの方へ
同梱の Python を 3.15.2 に更新しました。
自動更新では python フォルダは置き換わらないため、最新の Python にするには WarframePortalTool_with_python.zip を取り直して展開してください。
データ（~/.wfportal）はそのまま引き継がれます。Tips を編集している方は、古いフォルダの tips フォルダを新しいフォルダへコピーしてください。
なお、Brotli の脆弱性（CVE-2026-111497）について確認をしましたが、本ツールは Brotli を使っておらず、以前の版も影響を受けません。
不安な方のみ取りなおしを推奨いたします。
