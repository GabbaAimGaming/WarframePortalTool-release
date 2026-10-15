@echo off
setlocal
rem Warframe Portal Tool - サーバー起動用
rem このファイルをダブルクリックすると wfportal_ui.py を起動し、ブラウザで画面を開きます。
rem 終了するには、この黒い画面で Ctrl+C を押すか、画面を閉じてください。

rem このバッチファイルがあるフォルダに移動(どこから実行しても動くように)
cd /d "%~dp0"

title Warframe Portal Tool

rem 使える Python を探す(py ランチャー → python の順)
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [エラー] Python が見つかりません。
    echo Python 3.9 以上をインストールしてください。
    echo 手順は同じフォルダの INSTALL_PYTHON.md を参照してください。
    echo 入手先: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

if not exist "wfportal_ui.py" (
    echo [エラー] wfportal_ui.py が見つかりません。
    echo このバッチファイルは WarframePortalTool フォルダの中に置いてください。
    echo.
    pause
    exit /b 1
)

rem 更新の確認: GitHub に新しい版があれば、変わったファイルだけ取得して置き換える
rem つながらないときや、自動更新をオフにしているとき NO_AUTO_UPDATE ファイルがあるときは、そのまま起動する
rem 起動用の bat 自身が更新されたときは、入れ替えてから起動し直す。括弧ブロックは使わない
if not defined WFPORTAL_UPDATED if exist "wfportal_update.py" %PY% wfportal_update.py
if not defined WFPORTAL_UPDATED if errorlevel 10 if exist "start_wfportal.bat.new" set "WFPORTAL_UPDATED=1" & copy /y "start_wfportal.bat.new" "%~f0" >nul & del "start_wfportal.bat.new" & "%~f0" %*
echo.

rem 初回だけ: 公式ファンキット Warframe Fan Kit のロゴ素材を、配布元の Dropbox から取得する
rem 権利は Digital Extremes にあるためツールには同梱していない。取得に失敗してもツールは起動する
if not exist "assets\Logos\LotusFlower.png" (
    echo 初回起動: 公式ファンキットのロゴ素材を取得します...
    %PY% wfportal.py logos --if-missing
    echo.
)

echo 非公式のファンツールです。Digital Extremes とは関係ありません。
echo Unofficial fan tool. Not affiliated with Digital Extremes.
echo.
echo Warframe Portal Tool を起動します...
echo この画面を閉じるとサーバーも止まります。使っている間は開いたままにしてください。
echo.
%PY% wfportal_ui.py %*

rem 異常終了したときはメッセージを読めるように止める
if errorlevel 1 (
    echo.
    echo [エラー] サーバーが異常終了しました。上のメッセージを確認してください。
    pause
)
endlocal
