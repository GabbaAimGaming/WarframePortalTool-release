# winocr.ps1 - Run the Windows built-in OCR (Windows.Media.Ocr) on an image and write JSON.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File winocr.ps1 -Image shot.png -Out result.json [-Langs en-US,ja-JP] [-Scale 2]
#   powershell -NoProfile -ExecutionPolicy Bypass -File winocr.ps1 -ListLanguages -Out langs.json
#
# Requires Windows 10/11 and "Windows PowerShell" 5.1 (powershell.exe). PowerShell 7 (pwsh) cannot load WinRT types.
# Output (UTF-8 JSON):
#   { "width": W, "height": H, "results": [ { "lang": "en-US", "lines": [ { "text": "...",
#       "words": [ { "text": "...", "x": 0, "y": 0, "w": 0, "h": 0 } ] } ] } ], "available": ["en-US", ...] }
# Coordinates are in the pixels of the original image (scaling is undone).
param(
    [string]$Image = "",
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Langs = "en-US,ja-JP",
    [double]$Scale = 2.0,
    [switch]$ListLanguages
)
$ErrorActionPreference = "Stop"

function Write-Result($obj) {
    $json = $obj | ConvertTo-Json -Depth 8 -Compress
    [System.IO.File]::WriteAllText($Out, $json, (New-Object System.Text.UTF8Encoding($false)))
}

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapTransform, Windows.Graphics, ContentType = WindowsRuntime]
    $null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]

    # WinRT IAsyncOperation<T> -> .NET Task<T> -> wait for the result
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq "IAsyncOperation``1" })[0]
    function Await($op, [Type]$type) {
        $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
        $null = $task.Wait(-1)
        return $task.Result
    }

    $available = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
    if ($ListLanguages) {
        Write-Result @{ available = $available; max = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension }
        exit 0
    }

    $path = (Resolve-Path -LiteralPath $Image).ProviderPath
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $w = [double]$decoder.PixelWidth
    $h = [double]$decoder.PixelHeight

    # Small text reads better when enlarged. Stay within the OCR size limit.
    $maxDim = [double][Windows.Media.Ocr.OcrEngine]::MaxImageDimension
    $s = [Math]::Max(1.0, [Math]::Min($Scale, $maxDim / [Math]::Max($w, $h)))
    $transform = New-Object Windows.Graphics.Imaging.BitmapTransform
    $transform.ScaledWidth = [uint32][Math]::Floor($w * $s)
    $transform.ScaledHeight = [uint32][Math]::Floor($h * $s)
    $transform.InterpolationMode = [Windows.Graphics.Imaging.BitmapInterpolationMode]::Fant
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync(
            [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
            [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,
            $transform,
            [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation,
            [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])

    # Pick engines: requested languages that are installed (same language family is accepted, e.g. en-GB for en-US)
    $engines = @()
    foreach ($want in ($Langs -split ",")) {
        $want = $want.Trim()
        if (-not $want) { continue }
        $base = $want.Split("-")[0]
        $hit = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages |
            Where-Object { $_.LanguageTag -eq $want } | Select-Object -First 1
        if (-not $hit) {
            $hit = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages |
                Where-Object { $_.LanguageTag.Split("-")[0] -eq $base } | Select-Object -First 1
        }
        if ($hit -and -not ($engines | Where-Object { $_.Tag -eq $hit.LanguageTag })) {
            $engines += [pscustomobject]@{ Tag = $hit.LanguageTag; Engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($hit) }
        }
    }
    if ($engines.Count -eq 0) {
        $e = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        if ($e) { $engines += [pscustomobject]@{ Tag = $e.RecognizerLanguage.LanguageTag; Engine = $e } }
    }
    if ($engines.Count -eq 0) { throw "No OCR language is installed. Add a language with OCR support in Windows Settings." }

    $results = @()
    foreach ($en in $engines) {
        $r = Await ($en.Engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines = @()
        foreach ($line in $r.Lines) {
            $words = @()
            foreach ($wd in $line.Words) {
                $b = $wd.BoundingRect
                $words += @{ text = $wd.Text; x = [Math]::Round($b.X / $s, 1); y = [Math]::Round($b.Y / $s, 1);
                    w = [Math]::Round($b.Width / $s, 1); h = [Math]::Round($b.Height / $s, 1) }
            }
            $lines += @{ text = $line.Text; words = $words }
        }
        $results += @{ lang = $en.Tag; lines = $lines }
    }
    Write-Result @{ width = $w; height = $h; scale = $s; results = $results; available = $available }
    exit 0
}
catch {
    Write-Result @{ error = $_.Exception.Message }
    exit 1
}
