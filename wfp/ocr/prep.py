"""文字認識の前処理(Pillow・numpy)。画像の読み込み・拡大・配列への変換・行の切り出し。

「標準ライブラリのみ」の例外(地図 §0): Pillow・numpy は**関数の中で import** する(ファイルの頭で import しない)。
入っていなければ OcrUnavailable にして、エンジンを「使えない」にするだけ(tests/test_layers.py が検査)。
配列は H×W×3 の uint8 で、色の並びは BGR(PP-OCR のモデルが BGR で学習しているため)。
"""
from __future__ import annotations

import io

from wfp.core.const import OCR_MAX_PIXELS, OCR_MAX_SIDE
from wfp.core.i18n import txt
from wfp.ocr.engine import OcrUnavailable


def need_module(name: str):
    """モジュールを読み込む。無ければ OcrUnavailable(err.ocr.module)"""
    import importlib
    try:
        return importlib.import_module(name)
    except ImportError:
        raise OcrUnavailable(txt("err.ocr.module", name=name))


def load_image(image_bytes: bytes):
    """画像のバイト列を Pillow で開いて RGB にする。画素数が OCR_MAX_PIXELS を超えたら OcrUnavailable"""
    pil_image = need_module("PIL.Image")
    try:
        img = pil_image.open(io.BytesIO(image_bytes))
        if img.width * img.height > OCR_MAX_PIXELS:
            raise OcrUnavailable(txt("err.ocr.toolarge", pixels=str(img.width * img.height)))
        return img.convert("RGB")
    except OcrUnavailable:
        raise
    except Exception as e:  # Pillow は形式ごとにいろいろな例外を出す
        raise OcrUnavailable(txt("err.ocr.image", msg=str(e)))


def scale_image(img, scale: float, max_side: int = OCR_MAX_SIDE):
    """拡大・縮小(LANCZOS)。長い辺が max_side を超えない範囲で。戻り値は (画像, 実際の倍率)"""
    pil_image = need_module("PIL.Image")
    long_side = max(img.width, img.height)
    ratio = min(scale, max_side / long_side) if long_side else 1.0
    if abs(ratio - 1.0) < 1e-6:
        return img, 1.0
    size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
    return img.resize(size, pil_image.Resampling.LANCZOS), ratio


def resize_to(img, width: int, height: int):
    """決めた大きさにする(縦横比は呼ぶ側で決める)"""
    pil_image = need_module("PIL.Image")
    return img.resize((max(1, width), max(1, height)), pil_image.Resampling.LANCZOS)


def to_bgr_array(img):
    """Pillow の RGB 画像 -> numpy の H×W×3(uint8・BGR)"""
    np = need_module("numpy")
    return np.ascontiguousarray(np.asarray(img, dtype=np.uint8)[:, :, ::-1])


def crop_box(img, box: tuple[int, int, int, int]):
    """枠 (左, 上, 右, 下) で切り出す(画像の外は詰める)"""
    left, top, right, bottom = box
    left, top = max(0, left), max(0, top)
    right, bottom = min(img.width, right), min(img.height, bottom)
    return img.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
