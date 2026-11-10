@echo off
setlocal
rem Warframe Portal Tool - データ置き場の片付け
rem データ置き場 .wfportal を、このツールの userdata フォルダに zip にして退避してから消します。
rem ツール本体と tips フォルダは消しません。完全に消すときは、このあとツールのフォルダごと削除してください。
rem 流れ: 確認 Y/N → userdata\.wfportal にコピー → wfportal_日時 に名前を変える → zip にする → zip を確かめる → 展開したフォルダと元のフォルダを消す
rem 途中で失敗したら、そこで止めて元のフォルダには触らない。括弧ブロックは使わない

cd /d "%~dp0"
title Warframe Portal Tool - uninstall

rem ツールの場所(末尾の \ を外す)
set "TOOL=%~dp0"
if "%TOOL:~-1%"=="\" set "TOOL=%TOOL:~0,-1%"

rem 対象の場所: 環境変数 WFPORTAL_DIR があればそこ、無ければ %USERPROFILE%\.wfportal(ツールと同じ決め方)
set "SRC=%USERPROFILE%\.wfportal"
if defined WFPORTAL_DIR set "SRC=%WFPORTAL_DIR%"
for %%a in ("%SRC%") do set "SRC=%%~fa"
if "%SRC:~-1%"=="\" set "SRC=%SRC:~0,-1%"

set "UD=%TOOL%\userdata"
set "WORK=%UD%\.wfportal"

echo はいはーい、ここでもクロちゃんですよ。
echo 今からデータ置き場を片付けるね
echo.
echo データ置き場: "%SRC%"
echo 退避先　　　: "%UD%"
echo.

rem 消してはいけない場所なら止める: ドライブの直下・ユーザーのフォルダそのもの・ツールのフォルダと重なる場所
if not exist "%SRC%\" goto no_src
if "%SRC:~2%"=="" goto bad_path
if "%SRC:~3%"=="" goto bad_path
if /i "%SRC%"=="%USERPROFILE%" goto bad_path
powershell -NoProfile -Command "$t = $env:TOOL + '\'; $s = $env:SRC + '\'; if ($t.StartsWith($s, [StringComparison]::OrdinalIgnoreCase) -or $s.StartsWith($t, [StringComparison]::OrdinalIgnoreCase)) { exit 1 } else { exit 0 }"
if errorlevel 1 goto bad_path

rem ツールが動いていたら止める。サーバーは userdata.db を使うときだけ開くので、動いたままでも消せてしまい、あとでデータ置き場を作り直す
call :find_running
if errorlevel 2 goto err_proc
if errorlevel 1 goto running

echo データ置き場を zip にして退避し、元のフォルダを消すね。
choice /c YN /n /m "続ける？ [Y/N]: "
if errorlevel 2 goto cancel

rem 前回が途中で止まった跡があれば、触らずに止める
if exist "%WORK%" goto left_work

rem zip の名前に使う日時(%date% は PC の設定で形が変わるので使わない)
set "STAMP="
for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%a"
if not defined STAMP goto err_stamp
set "NAME=wfportal_%STAMP%"
set "ZIPSRC=%UD%\%NAME%"
set "ZIP=%UD%\%NAME%.zip"
if exist "%ZIPSRC%" goto err_exists
if exist "%ZIP%" goto err_exists
if not exist "%UD%\" md "%UD%" || goto err_md

echo.
echo [1/5] userdata にコピーしてるよ...
rem ドライブが違ってもフォルダを移せるように robocopy を使う。終了コードは 8 以上が失敗
robocopy "%SRC%" "%WORK%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto err_copy
if not exist "%WORK%\" md "%WORK%" || goto err_copy

echo [2/5] 名前を %NAME% に変更中...
ren "%WORK%" "%NAME%" || goto err_ren

echo [3/5] 圧縮圧縮、zipに圧縮...
rem tar は Windows 10 1803 以降に入っている。無いときや失敗したときは PowerShell の Compress-Archive で作る
set "DONE="
where tar >nul 2>&1 && tar -a -c -f "%ZIP%" -C "%UD%" "%NAME%" && set "DONE=1"
if not defined DONE if exist "%ZIP%" del /q "%ZIP%"
if not defined DONE powershell -NoProfile -Command "try { Compress-Archive -LiteralPath $env:ZIPSRC -DestinationPath $env:ZIP -ErrorAction Stop; exit 0 } catch { exit 1 }" && set "DONE=1"
if not defined DONE goto err_zip

echo [4/5] zip 確認中～...
rem zip の中のファイルの数が、コピーしたフォルダのファイルの数と同じかを見る
powershell -NoProfile -Command "try { Add-Type -AssemblyName System.IO.Compression.FileSystem; $z = [IO.Compression.ZipFile]::OpenRead($env:ZIP); $n = @($z.Entries | Where-Object { $_.FullName -notmatch '[\\/]$' }).Count; $z.Dispose(); $f = @(Get-ChildItem -LiteralPath $env:ZIPSRC -Recurse -File -Force).Count; if ($n -eq $f) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 goto err_check

rem 消す直前にもう一度: コピーや zip の間にツールを起動したとき
call :find_running
if errorlevel 2 goto err_proc
if errorlevel 1 goto running_late

echo [5/5] 展開したフォルダと元のフォルダを消し消し...
rd /s /q "%ZIPSRC%"
rd /s /q "%SRC%"
if exist "%SRC%" goto left_src
if exist "%ZIPSRC%" goto left_zipsrc

echo.
echo 終わったよ。
echo 退避した zip: "%ZIP%"
echo 元に戻すときは、zip を展開してできた %NAME% フォルダの名前を .wfportal に変えて元の場所に置いてね。
echo ツールを完全に消すときは、このフォルダごと消せばいいから。……寂しいけど
goto done

:running
echo [エラー] ツールが動いてるよ。何も変更しないから、続けたいなら黒い画面（サーバー）を閉じてね。
goto fail

:running_late
echo [エラー] 何でツール動かすかな？途中で止めたよ。
echo コピーしたものが "%ZIPSRC%" に、作った zip が "%ZIP%" に残っているから、ツールを閉じてから消すか、もう一度実行してね。
goto fail

:err_proc
echo [エラー] あの、PowerShellっている？ツールが動いているかをわかんなかったんだけど。
goto fail

:no_src
echo [エラー] データ置き場がないよー。
goto done

:bad_path
echo [エラー] ここはあーしは片づけられないんだ。
echo 環境変数 WFPORTAL_DIR を確かめてね。
goto fail

:cancel
echo 中止したよ。
goto done

:left_work
echo [エラー] "%WORK%" が残ってるね。前にやったときに片付けなかったでしょー……。
echo 中身を確かめてから、要らなければ消してもう一度実行して。
goto fail

:err_stamp
echo [エラー] あの、日時取得できなかったんだけど。PowerShell、使える？
goto fail

:err_exists
echo [エラー] 同じ名前の退避先があるね: "%ZIPSRC%"
echo もう少し後で再実行してくれる？。
goto fail

:err_md
echo [エラー] userdata フォルダを作るのに失敗しちゃった。
goto fail

:err_copy
echo [エラー] コピーに失敗しちゃった。
echo コピーの途中のものが "%WORK%" に残ってるから、確認して消してね。
goto fail

:err_ren
echo [エラー] 名前を変えるの失敗しちゃった。
echo コピーしたものが "%WORK%" に残ってるよ。
goto fail

:err_zip
echo [エラー] zip を作れなかった。
echo コピーしたものが "%ZIPSRC%" に残ってるよ。
goto fail

:err_check
echo [エラー] zip の中身がコピーしたもの一致しないや
echo コピーしたものが "%ZIPSRC%" に、作った zip が "%ZIP%" に残ってるよ。
goto fail

:left_src
echo [エラー] 元のフォルダに消せないファイルが残っちゃった: "%SRC%"
echo 残ったものは手で消してね。退避した zip: "%ZIP%"
goto fail

:left_zipsrc
echo [エラー] 展開したフォルダを消せなかった: "%ZIPSRC%"
echo 手で消してねー。元のフォルダは消したから。退避した zip: "%ZIP%"
goto fail

rem ツールのサーバー・コマンド wfportal_ui.py wfportal.py が動いているか。0 = 動いていない / 1 = 動いている / 2 = 調べられない
rem ポートは --port で変えられるので、プロセスのコマンドラインで見る。py ランチャーと python の両方が当たる
:find_running
powershell -NoProfile -Command "try { $p = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'wfportal(_ui)?\.py' }); if ($p.Count -gt 0) { exit 1 } else { exit 0 } } catch { exit 2 }"
exit /b %errorlevel%

:fail
echo.
pause
endlocal
exit /b 1

:done
echo.
pause
endlocal
exit /b 0
