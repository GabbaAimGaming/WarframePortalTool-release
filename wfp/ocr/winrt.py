"""Windows OCR のエンジン(ocr/winocr.ps1 で Windows.Media.Ocr を呼ぶ)。2026-11-20 に wfportal_ocr.py の §1 から移した。

出力は今までと1バイトも変えない(結果の形は wfp/ocr/result.py。engine は run_ocr_bytes が付ける)。
テスト用: 環境変数 WFPORTAL_OCR_FAKE に保存した OCR の結果(JSON)のパスを入れると、それを返す。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from wfp.core import const
from wfp.core.const import OCR_DEFAULT_LANGS, OCR_ENGINE_WINRT, OCR_PS_SCRIPT, OCR_PS_TIMEOUT_LANGS, OCR_TIMEOUT
from wfp.core.i18n import txt
from wfp.ocr.engine import OcrEngine, OcrRequest, OcrUnavailable, unavailable
from wfp.store import build_images

FAKE_ENV = "WFPORTAL_OCR_FAKE"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: 黒い画面を出さない


def ps_script() -> Path:
    return const.APP_DIR.joinpath(*OCR_PS_SCRIPT)


def find_powershell() -> str | None:
    """Windows PowerShell 5.1 (powershell.exe)。PowerShell 7 (pwsh) は WinRT を読めないので使わない"""
    if os.name != "nt":
        return None
    root = os.environ.get("SystemRoot", r"C:\Windows")
    path = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(path) if path.exists() else shutil.which("powershell.exe")


def _fake_result(fake: str, args: list[str]) -> dict:
    data = json.loads(Path(fake).read_text(encoding="utf-8-sig"))
    data = data[0] if isinstance(data, list) else data
    return {"available": [r.get("lang") for r in data.get("results", [])]} if "-ListLanguages" in args else data


def _ps_command(args: list[str], out: str) -> list[str]:
    ps = find_powershell()
    if not ps:
        raise OcrUnavailable(txt("err.ocr.windows"))
    script = ps_script()
    if not script.exists():
        raise OcrUnavailable(txt("err.ocr.script", path=str(script)))
    return [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Out", out, *args]


def _run_ps(args: list[str], timeout: int) -> dict:
    fake = os.environ.get(FAKE_ENV)
    if fake:
        return _fake_result(fake, args)
    fd, out = tempfile.mkstemp(suffix=".json", prefix="wfocr_")
    os.close(fd)
    try:
        cmd = _ps_command(args, out)
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            raise OcrUnavailable(txt("err.ocr.timeout", sec=str(timeout)))
        text = Path(out).read_text(encoding="utf-8-sig") if Path(out).stat().st_size else ""
        data = json.loads(text) if text else {}
        if proc.returncode != 0 or "error" in data:
            msg = data.get("error") or proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
            raise OcrUnavailable(txt("err.ocr.failed", msg=msg))
        return data
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


def ocr_languages(timeout: int = OCR_PS_TIMEOUT_LANGS) -> list[str]:
    return _run_ps(["-ListLanguages"], timeout).get("available") or []


def run_ocr(image: Path, langs: str = OCR_DEFAULT_LANGS, scale: float = 2.0, timeout: int = OCR_TIMEOUT) -> dict:
    """画像のファイルを文字認識する(CLI の build analyze が使う)"""
    return _run_ps(["-Image", str(image), "-Langs", langs, "-Scale", str(scale)], timeout)


class WinrtEngine(OcrEngine):
    engine_id = OCR_ENGINE_WINRT

    def probe(self) -> dict:
        langs = ocr_languages()
        if not langs:
            return unavailable(txt("err.ocr.nolang"))
        return {"available": True, "reason": "", "langs": langs, "detail": {}}

    def recognize(self, image_bytes: bytes, req: OcrRequest) -> dict:
        ext = build_images.image_ext(image_bytes) or "png"
        fd, tmp = tempfile.mkstemp(suffix=f".{ext}", prefix="wfimg_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(image_bytes)
            return run_ocr(Path(tmp), langs=req.langs, scale=req.scale, timeout=req.timeout)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass


ENGINE = WinrtEngine()
