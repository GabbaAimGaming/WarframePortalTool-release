"""PP-OCRv6 のエンジン(onnxruntime)。検出(DB)→ 行の切り出し → 認識(CTC)→ 結果の形(wfp/ocr/result.py)へ。

「標準ライブラリのみ」の例外(地図 §0): Pillow・numpy・onnxruntime は**関数の中で読み込む**(prep.need_module)。
OpenCV は使わない(依存を3つに絞る)ので、検出の後処理(つながった領域・枠の広げ方)は numpy で書く。
日英を1回で読むので results は1つ(lang = OCR_LANG_MULTI)。今の解析は**単語ごとの枠**に頼っているので、
認識の時刻ごとの文字の位置から単語の枠を作る(英数字は空白で区切る・かな漢字は1文字 = 1単語。Windows OCR に合わせる)。
モデルは <データ置き場>/ocr_runtime/models/<段>/(wfp/ocr/runtime)。文字の表は認識の inference.yml の character_dict。
"""
from __future__ import annotations

import json
import os
import threading
import unicodedata
from pathlib import Path

from wfp.core.const import (
    OCR_ENGINE_PPOCR, OCR_LANG_MULTI, PPOCR_BOX_THRESH, PPOCR_DET_MEAN, PPOCR_DET_MULTIPLE, PPOCR_DET_SIDE, PPOCR_DET_STD,
    PPOCR_DET_THRESH, PPOCR_MIN_BOX, PPOCR_PROVIDERS, PPOCR_REC_BATCH, PPOCR_REC_HEIGHT, PPOCR_REC_MAX_WIDTH,
    PPOCR_REC_MIN_SCORE, PPOCR_THREADS, PPOCR_TIERS, PPOCR_UNCLIP,
)
from wfp.core.i18n import txt
from wfp.ocr import prep, runtime
from wfp.ocr.engine import OcrEngine, OcrRequest, OcrUnavailable, unavailable
from wfp.ocr.winrt import FAKE_ENV

# ---- 文字の表(inference.yml。標準ライブラリに YAML の読み手が無いので、character_dict の並びだけ読む) ----


def _yaml_scalar(raw: str) -> str:
    """YAML の1つの値(引用符つき・なし)を文字にする"""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return json.loads(raw)
    return raw


def parse_char_dict(yml_text: str) -> list[str]:
    """inference.yml の PostProcess.character_dict(ブロック形式の並び)を読む。見つからなければ空"""
    lines = yml_text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "character_dict:"), None)
    if start is None:
        return []
    chars, item_indent = [], None
    for line in lines[start + 1:]:
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if not stripped.startswith("-") or (item_indent is not None and indent != item_indent):
            break
        item_indent = indent
        chars.append(_yaml_scalar(stripped[1:]))
    return chars


# ---- 検出(DB) ----


def det_size(width: int, height: int, speed: str) -> tuple[int, int]:
    """検出に渡す大きさ: 長い辺を PPOCR_DET_SIDE[speed] までに縮め、32 の倍数にそろえる"""
    side = PPOCR_DET_SIDE.get(speed, PPOCR_DET_SIDE["accurate"])
    ratio = min(1.0, side / max(width, height))
    snap = lambda v: max(PPOCR_DET_MULTIPLE, int(round(v * ratio / PPOCR_DET_MULTIPLE)) * PPOCR_DET_MULTIPLE)  # noqa: E731
    return snap(width), snap(height)


def det_tensor(img, speed: str):
    """検出の入力(1×3×H×W・float32)と、縮めた倍率 (横, 縦)"""
    np = prep.need_module("numpy")
    det_w, det_h = det_size(img.width, img.height, speed)
    arr = prep.to_bgr_array(prep.resize_to(img, det_w, det_h)).astype(np.float32) / 255.0
    arr = (arr - np.array(PPOCR_DET_MEAN, np.float32)) / np.array(PPOCR_DET_STD, np.float32)
    return arr.transpose(2, 0, 1)[None].astype(np.float32), (det_w / img.width, det_h / img.height)


def mask_runs(mask) -> list[tuple[int, int, int]]:
    """2値の地図の、行ごとの連続区間 (行, 始め, 終わり(含まない))。行の順・左からの順"""
    np = prep.need_module("numpy")
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), np.int8)
    padded[:, 1:-1] = mask
    diff = np.diff(padded, axis=1)
    starts, ends = np.argwhere(diff == 1), np.argwhere(diff == -1)
    return [(int(s[0]), int(s[1]), int(e[1])) for s, e in zip(starts, ends)]


def _find(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def connected_boxes(mask) -> list[tuple[int, int, int, int]]:
    """つながった領域(斜めもつながりとみなす)ごとの外接の四角 (左, 上, 右, 下)。右・下は含む"""
    runs = mask_runs(mask)
    parent = list(range(len(runs)))
    prev, cur, cur_row = [], [], -1
    for idx, (row, start, end) in enumerate(runs):
        if row != cur_row:
            prev, cur, cur_row = (cur if row == cur_row + 1 else []), [], row
        for j in prev:
            if runs[j][1] <= end and start <= runs[j][2]:  # 斜めも含めて重なる(終わりは含まないので <=)
                parent[_find(parent, j)] = _find(parent, idx)
        cur.append(idx)
    boxes: dict[int, list[int]] = {}
    for idx, (row, start, end) in enumerate(runs):
        box = boxes.setdefault(_find(parent, idx), [start, row, end - 1, row])
        box[0], box[1], box[2], box[3] = min(box[0], start), min(box[1], row), max(box[2], end - 1), max(box[3], row)
    return [tuple(b) for b in boxes.values()]


def unclip(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """枠を外へ広げる(DB と同じ: 広げる幅 = 面積 × 割合 / 周の長さ)"""
    left, top, right, bottom = box
    width, height = right - left + 1, bottom - top + 1
    dist = width * height * PPOCR_UNCLIP / (2 * (width + height))
    return left - dist, top - dist, right + dist, bottom + dist


def find_boxes(prob, ratios: tuple[float, float], size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    """確率の地図 -> 元の画像の枠 (左, 上, 右, 下)。上から下・左から右に並べる"""
    mask = prob > PPOCR_DET_THRESH
    out = []
    for left, top, right, bottom in connected_boxes(mask):
        if min(right - left + 1, bottom - top + 1) < PPOCR_MIN_BOX:
            continue
        if float(prob[top:bottom + 1, left:right + 1].mean()) < PPOCR_BOX_THRESH:
            continue
        ex_left, ex_top, ex_right, ex_bottom = unclip((left, top, right, bottom))
        out.append((max(0, int(ex_left / ratios[0])), max(0, int(ex_top / ratios[1])),
                    min(size[0], int(round((ex_right + 1) / ratios[0]))), min(size[1], int(round((ex_bottom + 1) / ratios[1])))))
    return sorted(out, key=lambda b: (b[1], b[0]))


# ---- 認識(CTC) ----


def rec_array(img, box: tuple[int, int, int, int]):
    """行を切り出して高さ PPOCR_REC_HEIGHT にした配列(3×H×W・float32・(x/255 − 0.5)/0.5)と倍率"""
    np = prep.need_module("numpy")
    line = prep.crop_box(img, box)
    scale = PPOCR_REC_HEIGHT / line.height
    width = min(PPOCR_REC_MAX_WIDTH, max(1, int(round(line.width * scale))))
    arr = prep.to_bgr_array(prep.resize_to(line, width, PPOCR_REC_HEIGHT)).astype(np.float32) / 255.0
    return ((arr - 0.5) / 0.5).transpose(2, 0, 1), width / line.width


def ctc_decode(probs, chars: list[str]) -> list[tuple[str, int, float]]:
    """1行の (時刻 × 文字の種類) の確率 -> [(文字, 時刻, 確からしさ)]。0 は空白の印、末尾の1つは空白の文字"""
    idx, conf = probs.argmax(axis=1), probs.max(axis=1)
    table = [""] + list(chars) + [" "]
    out = []
    for step in range(len(idx)):
        k = int(idx[step])
        if k == 0 or (step and k == int(idx[step - 1])) or k >= len(table):
            continue
        out.append((table[k], step, float(conf[step])))
    return out


def is_wide(ch: str) -> bool:
    """かな・漢字など全角の文字(1文字 = 1単語にする)"""
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _group_chars(placed: list[tuple[str, float]]) -> list[list[tuple[str, float]]]:
    """(文字, 中心の x) を単語にまとめる: 空白で区切る・全角の文字は1文字ずつ"""
    groups, cur = [], []
    for ch, x in placed:
        if ch.isspace() or is_wide(ch):
            if cur:
                groups.append(cur)
            cur = []
            if is_wide(ch):
                groups.append([(ch, x)])
            continue
        cur.append((ch, x))
    if cur:
        groups.append(cur)
    return groups


def to_words(placed: list[tuple[str, float]], box: tuple[int, int, int, int]) -> list[dict]:
    """(文字, 中心の x) と行の枠 -> 単語(text・x・y・w・h)。単語の横は端の文字の中心から文字の間隔の半分まで"""
    left, top, right, bottom = box
    xs = [x for ch, x in placed if not ch.isspace()]
    half = (xs[-1] - xs[0]) / (len(xs) - 1) / 2 if len(xs) > 1 else (bottom - top) / 2
    words = []
    for group in _group_chars(placed):
        x0 = max(left, group[0][1] - half)
        x1 = min(right, group[-1][1] + half)
        words.append({"text": "".join(ch for ch, _ in group), "x": round(x0, 1), "y": round(float(top), 1),
                      "w": round(max(0.0, x1 - x0), 1), "h": round(float(bottom - top), 1)})
    return words


def line_out(decoded: list[tuple[str, int, float]], steps: int, batch_width: int, scale: float,
             box: tuple[int, int, int, int]) -> dict | None:
    """1行の復号の結果 -> 結果の形の行。確からしさが低い・空の行は None"""
    if not decoded or sum(c for _, _, c in decoded) / len(decoded) < PPOCR_REC_MIN_SCORE:
        return None
    step_px = batch_width / steps / scale  # 時刻1つぶんの元の画像の幅
    placed = [(ch, min(box[2], box[0] + (step + 0.5) * step_px)) for ch, step, _ in decoded]
    text = " ".join("".join(ch for ch, _ in placed).split())
    words = to_words(placed, box)
    return {"text": text, "words": words} if text and words else None


def recognize_lines(models, img, boxes: list[tuple[int, int, int, int]]) -> list[dict]:
    """行の枠ごとに認識する。幅の近い行をまとめて PPOCR_REC_BATCH 件ずつ(右を 0 で埋める)。並びは枠の順"""
    np = prep.need_module("numpy")
    arrays = [rec_array(img, box) for box in boxes]
    order = sorted(range(len(boxes)), key=lambda i: arrays[i][0].shape[2])
    lines: list[dict | None] = [None] * len(boxes)
    for pos in range(0, len(order), PPOCR_REC_BATCH):
        chunk = order[pos:pos + PPOCR_REC_BATCH]
        batch_width = max(arrays[i][0].shape[2] for i in chunk)
        batch = np.zeros((len(chunk), 3, PPOCR_REC_HEIGHT, batch_width), np.float32)
        for row, i in enumerate(chunk):
            batch[row, :, :, :arrays[i][0].shape[2]] = arrays[i][0]
        probs = models.rec.run(None, {models.rec_input: batch})[0]
        for row, i in enumerate(chunk):
            lines[i] = line_out(ctc_decode(probs[row], models.chars), probs.shape[1], batch_width, arrays[i][1], boxes[i])
    return [line for line in lines if line]


# ---- モデルの読み込みとエンジン ----


class Models:
    """検出・認識のセッションと文字の表(プロセスで1回だけ作って使い回す)"""

    def __init__(self, paths: dict[str, dict[str, Path]]):
        ort = prep.need_module("onnxruntime")
        opts = ort.SessionOptions()
        if PPOCR_THREADS:
            opts.intra_op_num_threads = PPOCR_THREADS
        self.det = ort.InferenceSession(str(paths["det"]["inference.onnx"]), opts, providers=list(PPOCR_PROVIDERS))
        self.rec = ort.InferenceSession(str(paths["rec"]["inference.onnx"]), opts, providers=list(PPOCR_PROVIDERS))
        self.det_input = self.det.get_inputs()[0].name
        self.rec_input = self.rec.get_inputs()[0].name
        self.chars = parse_char_dict(paths["rec"]["inference.yml"].read_text(encoding="utf-8"))
        if not self.chars:
            raise OcrUnavailable(txt("err.ocr.ppocr.dict"))


def detect(models: Models, img, speed: str) -> list[tuple[int, int, int, int]]:
    tensor, ratios = det_tensor(img, speed)
    prob = models.det.run(None, {models.det_input: tensor})[0]
    return find_boxes(prob[0, 0], ratios, (img.width, img.height))


class PpocrEngine(OcrEngine):
    engine_id = OCR_ENGINE_PPOCR

    def __init__(self):
        self.data_dir: Path | None = None
        self.tier = PPOCR_TIERS[0]
        self._models: Models | None = None
        self._lock = threading.Lock()

    def configure(self, data_dir: Path, tier: str) -> bool:
        """データ置き場と段を決める。変わったら True(読み込んだモデルを捨てる)"""
        tier = tier if tier in PPOCR_TIERS else PPOCR_TIERS[0]
        if (self.data_dir, self.tier) == (data_dir, tier):
            return False
        with self._lock:
            self.data_dir, self.tier, self._models = data_dir, tier, None
        return True

    def cache_key(self) -> str:
        return f"ppocr-v6-{self.tier}"

    def probe(self) -> dict:
        if os.environ.get(FAKE_ENV) or self.data_dir is None:  # テストで保存した結果を使うときは winrt
            return unavailable(txt("err.ocr.ppocr.models"))
        runtime.activate(self.data_dir)
        missing = runtime.missing_module()
        if missing:
            return unavailable(txt("err.ocr.module", name=missing))
        if not runtime.models_ready(self.data_dir, self.tier):
            return unavailable(txt("err.ocr.ppocr.models"))
        return {"available": True, "reason": "", "langs": [OCR_LANG_MULTI], "detail": {"tier": self.tier}}

    def models(self) -> Models:
        with self._lock:
            if self._models is None:
                self._models = Models(runtime.model_paths(self.data_dir, self.tier))
            return self._models

    def recognize(self, image_bytes: bytes, req: OcrRequest) -> dict:
        """req.scale・langs は使わない(検出は長い辺の上限で縮め、認識は元の画像から切り出す)"""
        models = self.models()
        img = prep.load_image(image_bytes)
        lines = recognize_lines(models, img, detect(models, img, req.speed))
        return {"width": img.width, "height": img.height, "scale": 1.0, "engine": self.engine_id,
                "results": [{"lang": OCR_LANG_MULTI, "lines": lines}], "available": [OCR_LANG_MULTI]}


ENGINE = PpocrEngine()
