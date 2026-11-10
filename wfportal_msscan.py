#!/usr/bin/env python3
"""wfportal_msscan - ゲームの「プロフィール → エクストラ」の装備一覧(の画像)から、マスター済みを読み取る(標準ライブラリのみ)

流れ:
  1. 画像を Windows の文字認識(wfportal_ocr.run_ocr_bytes)にかけ、単語ごとの文字と枠を受け取る(API 側で行う)
  2. ランク表記(「最大ランク」「ランク nn」)の単語を目印にタイルを組み立てる。目印の上にある単語を名前として集める
       - 「クリア済み」の行より上(「最も使用している装備」の段)は捨てる。行が無ければ切り抜いた画像として扱う
       - 上が見切れて月桂冠の位置が画像に無いタイルは数えない(skipped)
  3. 名前をマスター一覧の項目と照合する(Kitgun のプライマリ版・セカンダリ版は、選んでいるタブで絞る)
       - 名前は英語の文字認識の結果を優先する(日本語の文字認識は英字の I まわりを「灯」「旧」などの漢字に読み替えるため)。
         英語で引けないもの(カタカナが混ざるコンパニオン・Kドライブ・アンプ)は日本語の結果で引く
       - 英語の文字認識が無い PC では、英字の名前に混ざった漢字を英字に戻す表(MSSCAN_KANJI_LATIN)を通して引く
  4. 画像の画素から、月桂冠(右上の水色)とバー(名前の下の青い線)を調べ、ランク表記と合わせて判定する
       done = 3つとも済み / todo = 3つとも未 / unsure = 食い違い(要確認)

印を付けるのは画面側(既存の POST /api/mastery)。ここは読み取って判定するだけで、何も書き込まない。
寸法・色の値は 1920x1080 の実物のスクショで測ったもの(Project の mastery_scan_handoff.md §3)。
OCR の単語の枠の高さは、画素で測った文字の高さとほぼ同じ(実物の OCR 結果で確認。「最大ランク」で 16〜17.5)。
"""
from __future__ import annotations

import re
import struct
import unicodedata
import zlib

from wfp.core.errors import TextError
from wfp.core.i18n import txt
from wfp.core.matcher import NameMatcher
from wfp.core.ocr_chars import OCR_LIKE_L
from wfp.core.text import fold_ocr, ocr_key

# --------------------------------------------------------------------------
# 定数(ゲームの表示が変わったら、ここを直す)
# --------------------------------------------------------------------------

# ランク表記の語。英語表示はサンプルが無いので推測(実物が来たら直す)
MSSCAN_RANK_WORDS = {"max": ["最大ランク", "MAX RANK"], "rank": ["ランク", "RANK"]}
# 装備一覧のすぐ上にある行(これより上は「最も使用している装備」の段なので捨てる)。英語は不明
MSSCAN_CLEARED_WORDS = ["クリア済み"]
# 選んでいるタブ: キー -> 語と、そのタブに出るマスター一覧の項目。items の書き方:
#   "cat" = そのカテゴリー(ファウンダーへ付け替えた項目は元のカテゴリーで見る)/ "cat/variant" = Kitgun の区分 /
#   "cat:英名の小文字" = その id だけ(手で足した項目)/ None = 絞らない
# 表に無いタブ(Warframe・コンパニオンなど。文字は未確認)は「絞らない」扱い。英語表示の語は未確認なので入れていない
MSSCAN_TABS = {
    "all": {"words": ["すべて"], "items": None},
    "primary": {"words": ["プライマリ"], "items": ["primary", "kitgun/primary"]},
    "secondary": {"words": ["セカンダリ"], "items": ["secondary", "kitgun/secondary"]},
    "melee": {"words": ["近接"], "items": ["melee", "zaw"]},
    "vehicle": {"words": ["乗り物"], "items": ["archwing", "kdrive", "necramech", "extra:plexus"]},
    "amp": {"words": ["アンプ"], "items": ["amp", "extra:amp"]},
}

# 日本語の文字認識が、英字の名前の中の細い字(I など)と隣の字をまとめて読み替える漢字 -> 元の英字(実物の読み取りで確認したもの)
#   灯 = KI(LOKI・SKIAJATI)/ 旧 = IB(CALIBAN・EXCALIBUR・TIBERON・VINQUIBUS)/ 円 = PI(SPIRA)/ 刊 = TI(SKIAJATI)/ 日 = FI(TOMBFINGER)
#   打 = YT(CYTE-09)/ 望 = RI(TENET GRIGORI)
# 英字を含む名前にだけ使う(日本語名には使わない)。英語の文字認識が無い PC のための手当て
MSSCAN_KANJI_LATIN = {"灯": "KI", "旧": "IB", "円": "PI", "刊": "TI", "日": "FI", "打": "YT", "望": "RI"}

MSSCAN_LAUREL_MIN = 0.12   # 月桂冠の範囲に占める水色の点の割合。マスター済みは 0.26〜0.59、未所持・空き枠は 0.00
MSSCAN_BAR_MIN = 0.9       # バーの青い点がタイル幅に占める割合。マスター済みは 1.00、未所持・空き枠は 0.00
MSSCAN_SCORE_SURE = 0.9    # 名前の一致度がこれ未満なら、済みに見えても要確認にする

# 寸法: ランク表記の文字(上端 Ry・高さ h・左端 Rx)からの相対位置。h の倍数
MSSCAN_TILE_LEFT = 0.23          # タイル左端 = Rx - 0.23h(約 4px)
MSSCAN_TILE_WIDTH = 10.8         # タイル幅 = 10.8h(列が2つ以上読めたら、列の間隔 x MSSCAN_PITCH_RATIO)
MSSCAN_PITCH_RATIO = 0.843
MSSCAN_LAUREL_TOP, MSSCAN_LAUREL_BOTTOM = 8.5, 6.6   # 月桂冠の範囲: 縦 Ry - 8.5h 〜 Ry - 6.6h
MSSCAN_LAUREL_WIDTH = 2.1                           # 横 タイル右端 - 2.1h 〜 タイル右端
MSSCAN_BAR_TOP, MSSCAN_BAR_BOTTOM = 1.2, 2.4        # バーを探す縦の範囲: Ry + 1.2h 〜 Ry + 2.4h(芯は 1.6〜1.9h)
MSSCAN_BAR_INSET = 3             # バーの左右の端はタイルの角で欠けるので、この px だけ内側を見る
MSSCAN_NAME_TOP = 4.2            # 名前を集める上限: Ry - 4.2h(3行まで)
MSSCAN_NAME_GAP = 0.8            # 名前の行どうし・目印とのすき間の上限(これより離れたら名前ではない)
MSSCAN_NAME_MIN_H = 0.4          # 名前に使う単語の高さの下限(h の倍数)。背の低いかな(ニ・ッ・ャ)は拾い、読点「,」(約 0.2h)は捨てる
MSSCAN_NAME_MAX_H = 1.6          # 名前に使う単語の高さの上限(h の倍数)


def laurel_pixel(red: int, green: int, blue: int) -> bool:
    """月桂冠の点(水色〜青緑)。灰色〜青の背景は green >= blue - 10 で、ピンクの背景は green - red で外れる"""
    return green >= 120 and green - red >= 30 and green >= blue - 10


def bar_pixel(red: int, green: int, blue: int) -> bool:
    """マスター済みのバーの点(青。芯は RGB(44,147,211))。未マスターのバーの色は不明"""
    return blue > 170 and 120 < green < 175 and red < 80


# --------------------------------------------------------------------------
# 1. PNG を読む(8bit の RGB / RGBA・インターレースなし)
# --------------------------------------------------------------------------

class Png:
    """読み込んだ画像。pixel(x, y) -> (r, g, b)。範囲外は None"""

    def __init__(self, width: int, height: int, bpp: int, rows: list[bytes]):
        self.width, self.height, self.bpp, self.rows = width, height, bpp, rows

    def pixel(self, x: int, y: int):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        row, pos = self.rows[y], x * self.bpp
        return row[pos], row[pos + 1], row[pos + 2]


def _add_bytes(num_a: int, num_b: int, low7: int, high1: int) -> int:
    """バイトごとの足し算(繰り上がりを隣のバイトに流さない。mod 256)。1行をまとめて大きな整数で計算して速くする"""
    return ((num_a & low7) + (num_b & low7)) ^ ((num_a ^ num_b) & high1)


def _unfilter(ftype: int, cur: bytes, prev: bytes, bpp: int, masks: tuple[int, int]) -> bytes:
    """PNG の1行のフィルターを戻す。None・Up・Sub は大きな整数でまとめて、Average・Paeth は1バイトずつ"""
    size = len(cur)
    low7, high1 = masks
    if ftype == 0:
        return cur
    if ftype == 2:  # Up
        total = _add_bytes(int.from_bytes(cur, "little"), int.from_bytes(prev, "little"), low7, high1)
        return total.to_bytes(size, "little")
    if ftype == 1:  # Sub: bpp ごとの累積和(倍々にずらして足す)
        full = (1 << (8 * size)) - 1
        total, step = int.from_bytes(cur, "little"), bpp
        while step < size:
            total = _add_bytes(total, (total << (8 * step)) & full, low7, high1)
            step *= 2
        return total.to_bytes(size, "little")
    out = bytearray(cur)
    if ftype == 3:  # Average
        for i in range(size):
            left = out[i - bpp] if i >= bpp else 0
            out[i] = (out[i] + ((left + prev[i]) >> 1)) & 255
        return bytes(out)
    if ftype == 4:  # Paeth
        for i in range(size):
            if i >= bpp:
                left, upleft = out[i - bpp], prev[i - bpp]
            else:
                left = upleft = 0
            up = prev[i]
            base = left + up - upleft
            d_left, d_up, d_ul = abs(base - left), abs(base - up), abs(base - upleft)
            pred = left if d_left <= d_up and d_left <= d_ul else up if d_up <= d_ul else upleft
            out[i] = (out[i] + pred) & 255
        return bytes(out)
    raise TextError(txt("err.msscan.png"))


def read_png(data: bytes) -> Png:
    """PNG(8bit の RGB / RGBA、インターレースなし)を読む。ほかの形式は TextError(err.msscan.png)"""
    bad = TextError(txt("err.msscan.png"))
    if not data or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise bad
    pos, header, idat = 8, None, []
    try:
        while pos + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[pos:pos + 8])
            body = data[pos + 8:pos + 8 + length]
            pos += 12 + length
            if kind == b"IHDR":
                header = struct.unpack(">IIBBBBB", body)
            elif kind == b"IDAT":
                idat.append(body)
            elif kind == b"IEND":
                break
        if not header:
            raise bad
        width, height, depth, color, _comp, _filt, interlace = header
        if depth != 8 or color not in (2, 6) or interlace != 0 or width <= 0 or height <= 0:
            raise bad
        bpp = 3 if color == 2 else 4
        stride = width * bpp
        raw = zlib.decompress(b"".join(idat))
    except (struct.error, zlib.error):
        raise bad
    if len(raw) < (stride + 1) * height:
        raise bad
    masks = (int.from_bytes(b"\x7f" * stride, "little"), int.from_bytes(b"\x80" * stride, "little"))
    rows, prev = [], bytes(stride)
    for y in range(height):
        start = y * (stride + 1)
        cur = _unfilter(raw[start], raw[start + 1:start + 1 + stride], prev, bpp, masks)
        rows.append(cur)
        prev = cur
    return Png(width, height, bpp, rows)


# --------------------------------------------------------------------------
# 2. 色を調べる
# --------------------------------------------------------------------------

def _inside(png: Png, x0: int, y0: int, x1: int, y1: int) -> bool:
    return 0 <= x0 < x1 <= png.width and 0 <= y0 < y1 <= png.height


def laurel_ratio(png: Png, box: tuple[float, float, float, float]) -> float | None:
    """範囲 (x0, y0, x1, y1) の中の月桂冠の点の割合。範囲が画像からはみ出すなら None(判定できない)"""
    x0, y0, x1, y1 = (int(round(val)) for val in box)
    if not _inside(png, x0, y0, x1, y1):
        return None
    hits = sum(1 for y in range(y0, y1) for x in range(x0, x1) if laurel_pixel(*png.pixel(x, y)))
    return hits / ((x1 - x0) * (y1 - y0))


def bar_ratio(png: Png, x0: float, x1: float, y0: float, y1: float) -> float | None:
    """縦 y0〜y1 を1行ずつ走査し、横 x0〜x1 に占める青い点の割合がいちばん大きい行の割合。はみ出すなら None"""
    x0, x1, y0, y1 = int(round(x0)), int(round(x1)), int(round(y0)), int(round(y1))
    if not _inside(png, x0, y0, x1, y1):
        return None
    best = max(sum(1 for x in range(x0, x1) if bar_pixel(*png.pixel(x, y))) for y in range(y0, y1))
    return best / (x1 - x0)


# --------------------------------------------------------------------------
# 3. 文字の正規化(OCR の読み違いをそろえる。正規化そのものは wfp/core/text の fold_ocr・ocr_key、表は wfp/core/ocr_chars)
# --------------------------------------------------------------------------

_LIKE_L = str.maketrans(OCR_LIKE_L)


def ms_key(text: str) -> str:
    """名前の照合キー: wfp.core.text の ocr_key(記号・空白を落とし 0/o 1/l をそろえる)のあとに fold_ocr をかける。
    ocr_key は記号を消してから 1/l をそろえるので、I の読み違いの | ! は先に l にしておく(消えると「LOKI」が「lok」になる)"""
    return fold_ocr(ocr_key(text.translate(_LIKE_L)))


def latinize(text: str) -> str:
    """英字を含む名前の中の、英字の読み違いの漢字(MSSCAN_KANJI_LATIN)を英字に戻す。英字が無ければそのまま"""
    if not re.search(r"[A-Za-z]", text):
        return text
    return "".join(MSSCAN_KANJI_LATIN.get(ch, ch) for ch in text)


def _bottom(word: dict) -> float:
    return word["y"] + word["h"]


def _right(words: list[dict]) -> float:
    return max(word["x"] + word["w"] for word in words)


def _number(text: str) -> int | None:
    norm = unicodedata.normalize("NFKC", text).translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1"}))
    return int(norm) if re.fullmatch(r"\d{1,2}", norm) else None


# --------------------------------------------------------------------------
# 4. 画面の部品を探す
# --------------------------------------------------------------------------

def _lines(result: dict) -> list[list[dict]]:
    """OCR の行ごとの単語(文字の無い単語は除く)"""
    out = []
    for line in result.get("lines") or []:
        words = [word for word in (line.get("words") or []) if isinstance(word, dict) and str(word.get("text", "")).strip()] \
            if isinstance(line, dict) else []
        if words:
            out.append(words)
    return out


def _find_run(words: list[dict], target: str) -> tuple[int, int] | None:
    """単語の並びの中で、つなげると target(fold_ocr 済み)になる連続した範囲 [i, j) の最初のもの。
    日本語は1文字ずつ別の単語になる(「最 大 ラ ン ク」)のでつなげて比べる"""
    for i in range(len(words)):
        joined = ""
        for j in range(i, len(words)):
            joined += fold_ocr(words[j]["text"])
            if joined == target:
                return i, j + 1
            if not target.startswith(joined):
                break
    return None


def grid_top(result: dict) -> tuple[float, float] | None:
    """「クリア済み」の行の (上端, 下端)。無ければ None(切り抜いた画像として扱う)"""
    found = []
    for words in _lines(result):
        for label in MSSCAN_CLEARED_WORDS:
            run = _find_run(words, fold_ocr(label))
            if run:
                part = words[run[0]:run[1]]
                found.append((min(word["y"] for word in part), max(_bottom(word) for word in part)))
    return min(found) if found else None


def read_tab(result: dict, near: tuple[float, float] | None, above: float | None) -> str | None:
    """選んでいるタブのキー(MSSCAN_TABS)。タブの文字は「クリア済み」と同じ高さの行にゴミと混ざって出るので、その付近の行から探す。
    near = 「クリア済み」の行の (上端, 下端)。無ければ above(いちばん上のタイルの上端)より上の行を見る"""
    for words in _lines(result):
        top, bottom = min(word["y"] for word in words), max(_bottom(word) for word in words)
        if near:
            band = near[1] - near[0]
            if bottom < near[0] - band or top > near[1] + band:
                continue
        elif above is None or bottom > above:
            continue
        text = fold_ocr("".join(word["text"] for word in words))
        for key, tab in MSSCAN_TABS.items():
            if any(fold_ocr(label) in text for label in tab["words"]):
                return key
    return None


def _anchors(result: dict) -> list[dict]:
    """ランク表記の単語(目印)。{x, y, h, rank: "max" or 数字 or None(数字が読めない)}"""
    out = []
    targets = [(kind, fold_ocr(label)) for kind in ("max", "rank") for label in MSSCAN_RANK_WORDS[kind]]
    for words in _lines(result):
        used: set[int] = set()
        for kind, target in targets:
            start = 0
            while start < len(words):
                run = _find_run(words[start:], target)
                if not run:
                    break
                first, last = run[0] + start, run[1] + start
                start = last
                span = set(range(first, last))
                if used & span:  # 「最大ランク」の中の「ランク」
                    continue
                used |= span
                part = words[first:last]
                height = sorted(word["h"] for word in part)[len(part) // 2]
                rank = "max"
                if kind == "rank":
                    nxt = words[last] if last < len(words) else None
                    rank = _number(nxt["text"]) if nxt and nxt["x"] - _right(part) < 3 * height else None
                    if rank is not None:
                        used.add(last)
                out.append({"x": part[0]["x"], "y": min(word["y"] for word in part), "h": height, "rank": rank})
    return out


def _pitch(anchors: list[dict]) -> float | None:
    """列の間隔。同じ段の目印の横の差から求める(1列しか読めなければ None)"""
    diffs = [(other["x"] - one["x"], one["h"]) for one in anchors for other in anchors
             if abs(one["y"] - other["y"]) < one["h"] and other["x"] - one["x"] > 8 * one["h"]]
    if not diffs:
        return None
    base = min(dist for dist, _ in diffs)
    est = sorted(dist / max(1, round(dist / base)) for dist, _ in diffs)
    pitch, height = est[len(est) // 2], diffs[0][1]
    return pitch if 10 * height <= pitch <= 16 * height else None


def _name_rows(words: list[dict], anchor: dict, left: float, right: float) -> list[list[dict]]:
    """目印の上で、タイルの横の範囲にある単語を、下から上へ行ごとに集める(すき間が空いたら止める)。
    OCR の1行が隣のタイルの名前とつながることがある(「CERAMICDAGGER CHESA クプロウ」)ので、行ではなく単語で集める"""
    height, top = anchor["h"], anchor["y"]
    cand = [word for word in words if left <= word["x"] + word["w"] / 2 <= right
            and MSSCAN_NAME_MIN_H * height <= word["h"] <= MSSCAN_NAME_MAX_H * height
            and _bottom(word) <= top + 0.3 * height and word["y"] >= top - MSSCAN_NAME_TOP * height]
    cand.sort(key=lambda word: -_bottom(word))
    rows, edge = [], top
    while cand:
        if edge - _bottom(cand[0]) > MSSCAN_NAME_GAP * height:
            break
        mid = cand[0]["y"] + cand[0]["h"] / 2
        row = [word for word in cand if abs(word["y"] + word["h"] / 2 - mid) < 0.5 * height]
        cand = [word for word in cand if word not in row]
        rows.append(sorted(row, key=lambda word: word["x"]))
        edge = min(word["y"] for word in row)
    return rows[::-1]


def find_tiles(result: dict, others: list[dict] | None = None) -> tuple[list[dict], int]:
    """タイルの一覧と、数え外した(上が見切れた)タイルの数。目印(ランク表記)と「クリア済み」は result から探す。
    タイル: {name_lines: [行の文字], name_alts: [others の結果ごとの行の文字], rank, anchor: (x, y, h),
             box: (左, 上, 右, 下), laurel: 範囲, bar: (x0, x1, y0, y1)}
    others = ほかの言語の OCR の結果(英語など)。同じタイルの範囲の単語を名前の候補として集める"""
    top = grid_top(result)
    floor = top[1] if top else 0
    anchors = [anc for anc in _anchors(result) if anc["y"] >= floor]
    pitch = _pitch(anchors)
    words = [word for line in _lines(result) for word in line]
    other_words = [[word for line in _lines(res) for word in line] for res in others or []]
    tiles, skipped = [], 0
    for anc in sorted(anchors, key=lambda anc: (round(anc["y"] / (2 * anc["h"])), anc["x"])):
        height = anc["h"]
        left = anc["x"] - MSSCAN_TILE_LEFT * height
        right = left + (pitch * MSSCAN_PITCH_RATIO if pitch else MSSCAN_TILE_WIDTH * height)
        laurel = (right - MSSCAN_LAUREL_WIDTH * height, anc["y"] - MSSCAN_LAUREL_TOP * height,
                  right, anc["y"] - MSSCAN_LAUREL_BOTTOM * height)
        if laurel[1] < floor:  # 上が見切れている(月桂冠の位置が隠れている)
            skipped += 1
            continue
        bar_btm = anc["y"] + MSSCAN_BAR_BOTTOM * height
        as_lines = lambda pool: [" ".join(word["text"] for word in row) for row in _name_rows(pool, anc, left, right)]
        tiles.append({"name_lines": as_lines(words), "name_alts": [as_lines(pool) for pool in other_words],
                      "rank": anc["rank"], "anchor": (anc["x"], anc["y"], height),
                      "box": (left, laurel[1], right, bar_btm), "laurel": laurel,
                      "bar": (left + MSSCAN_BAR_INSET, right - MSSCAN_BAR_INSET, anc["y"] + MSSCAN_BAR_TOP * height, bar_btm)})
    return tiles, skipped


# --------------------------------------------------------------------------
# 5. 名前の照合
# --------------------------------------------------------------------------

class MasteryIndex:
    """マスター一覧の項目を名前(en・ja)で引く索引。同じ名前の項目(Kitgun のプライマリ版・セカンダリ版など)は1つのキーにまとめる

    NameMatcher(core/matcher)は同じキーの2つ目以降を捨てるので、キーごとに項目をまとめてから1回だけ登録する。
    NameMatcher には照合キー(ms_key 済み)を名前として渡す(ocr_key をかけ直しても変わらない)"""

    def __init__(self, items: list[dict]):
        self.groups: dict[str, list[dict]] = {}
        for item in items:
            for name in {item.get("en") or "", item.get("ja") or ""}:
                key = ms_key(name)
                if key and item not in self.groups.setdefault(key, []):
                    self.groups[key].append(item)
        self.matcher = NameMatcher([("mastery", key, key) for key in self.groups])

    def lookup(self, text: str) -> tuple[list[dict], float]:
        key = ms_key(text)
        if key in self.groups:  # 3文字未満のキーも完全一致なら引く(NameMatcher は3文字未満を登録しない)
            return list(self.groups[key]), 1.0
        hit = self.matcher.match(key)
        return (list(self.groups[hit[3]]), hit[0]) if hit else ([], 0.0)


def build_index(items: list[dict]) -> MasteryIndex:
    return MasteryIndex(items)


def tab_allows(tab: str | None, item: dict) -> bool:
    """選んでいるタブに、その項目が出るか(表に無いタブ・タブが読めないときは常に True)"""
    rule = MSSCAN_TABS.get(tab or "", {}).get("items")
    if rule is None:
        return True
    base = item["id"].split(":", 1)[0]  # ファウンダーへ付け替えた項目は元のカテゴリーで見る
    for spec in rule:
        if ":" in spec:
            if item["id"] == spec:
                return True
        elif "/" in spec:
            cat, variant = spec.split("/", 1)
            if base == cat and item.get("variant") == variant:
                return True
        elif base == spec:
            return True
    return False


def _lookup_tokens(tokens: list[str], keep: int, index: MasteryIndex) -> tuple[list[dict], float, str]:
    """先頭の語を1つずつ落としながら引く(名前の上のゴミ・アークウイング系のマークの誤読を外す)。
    長いほうから試して最初に当たったものを使う(「DUAL CODA / TORXICA」を TORXICA 単体で引かないため)。
    最後の keep 語(最後の行)は落とさない。英字を含む名前は、漢字の読み違いを戻したものでも引く"""
    limit = len(tokens) - keep
    while limit < len(tokens) - 1 and len(ms_key(tokens[limit])) <= 2:  # 最後の行の頭の短い語(マークの誤読)も落としてよい
        limit += 1
    for start in range(0, max(1, limit + 1)):
        text = " ".join(tokens[start:])
        if not text:
            break
        found, score = index.lookup(text)
        if not found and latinize(text) != text:
            found, score = index.lookup(latinize(text))
        if found:
            return found, score, text
    return [], 0.0, " ".join(tokens)


def match_tile(name_lines: list[str], index: MasteryIndex, tab: str | None,
               alts: list[list[str]] | None = None) -> tuple[list[dict], float, str, bool]:
    """名前の照合 -> (候補, 一致度, 照合に使った文字, タブと食い違ったか)。
    alts(ほかの言語の OCR の名前。英語を先に)を先に試し、一致度が MSSCAN_SCORE_SURE 以上ならそれを使う。
    どれも届かなければ一致度のいちばん高いもの"""
    best = ([], 0.0, " ".join(" ".join(name_lines).split()))
    for lines in [*(alts or []), name_lines]:
        tokens = " ".join(lines).split()
        if not tokens:
            continue
        keep = len(lines[-1].split()) if lines else 0
        found, score, read = _lookup_tokens(tokens, keep, index)
        if found and score >= MSSCAN_SCORE_SURE:
            best = (found, score, read)
            break
        if found and score > best[1]:
            best = (found, score, read)
    found, score, read = best
    if not found:
        return [], 0.0, read, False
    allowed = [item for item in found if tab_allows(tab, item)]
    return (allowed, score, read, False) if allowed else (found, score, read, True)


# --------------------------------------------------------------------------
# 6. 判定とまとめ
# --------------------------------------------------------------------------

def judge(laurel: float, bar: float, rank, item: dict | None) -> tuple[str, dict]:
    """(状態, 手がかり)。状態は done(3つとも済み)/ todo(3つとも未)/ unsure(食い違い)。
    ランクは「最大ランク」か、数字が項目の最大ランク(rank。Kuva などは 40)以上なら済み"""
    need = item.get("rank", 30) if item else 30
    signals = {"laurel": laurel >= MSSCAN_LAUREL_MIN, "bar": bar >= MSSCAN_BAR_MIN,
               "rank": rank == "max" or (isinstance(rank, int) and rank >= need)}
    vals = set(signals.values())
    return ("done" if vals == {True} else "todo" if vals == {False} else "unsure"), signals


def choose_result(ocr_data: dict) -> dict:
    """OCR の結果(言語ごとに1つ)のうち、ランク表記がいちばん多く読めたもの"""
    results = [res for res in ocr_data.get("results") or [] if isinstance(res, dict)]
    return max(results, key=lambda res: len(_anchors(res)), default={"lines": []})


def name_results(ocr_data: dict, chosen: dict) -> list[dict]:
    """名前を先に試す、ほかの言語の OCR の結果(英語を先に)。目印に使った結果は含めない"""
    others = [res for res in ocr_data.get("results") or [] if isinstance(res, dict) and res is not chosen]
    return sorted(others, key=lambda res: not str(res.get("lang", "")).lower().startswith("en"))


def _brief(item: dict, mastered: set[str]) -> dict:
    return {"id": item["id"], "en": item["en"], "ja": item["ja"], "cat": item["cat"],
            "variant": item.get("variant", ""), "done": item["id"] in mastered}


def analyze_mastery(ocr_data: dict, png: Png, index: MasteryIndex, mastered: set[str]) -> dict:
    """API の返り値: {tab, tiles: [...], unknown: [名前が引けないが済みに見えるタイルの文字], skipped,
    english: 英語の文字認識の結果があったか(無ければ画面で英語の追加をすすめる)}

    tiles の state: done(付けてよい)/ unsure(要確認。reason = mismatch 手がかりの食い違い・multi 候補が複数・
    low 一致度が低い・tab タブと食い違い)。todo(3つとも未)は返さない(自動では外さない方針なので使い道が無い)"""
    result = choose_result(ocr_data)
    tiles, skipped = find_tiles(result, name_results(ocr_data, result))
    tab = read_tab(result, grid_top(result), min((tile["box"][1] for tile in tiles), default=None))
    out, unknown = [], []
    for tile in tiles:
        laurel = laurel_ratio(png, tile["laurel"])
        bar = bar_ratio(png, *tile["bar"])
        if laurel is None or bar is None:  # 画像からはみ出している(切り抜き・画像の端)
            skipped += 1
            continue
        found, score, read, off_tab = match_tile(tile["name_lines"], index, tab, tile.get("name_alts"))
        state, signals = judge(laurel, bar, tile["rank"], found[0] if len(found) == 1 else None)
        if not found:
            if state == "done":
                unknown.append(read)
            continue
        if state == "todo":
            continue
        reason = "mismatch" if state == "unsure" else None
        if len(found) > 1:
            state, reason = "unsure", "multi"
        elif off_tab:
            state, reason = "unsure", "tab"
        elif score < MSSCAN_SCORE_SURE and state == "done":
            state, reason = "unsure", "low"
        row = {**_brief(found[0], mastered), "score": round(score, 3), "read": read, "state": state, "reason": reason,
               "signals": {**signals, "laurel_ratio": round(laurel, 3), "bar_ratio": round(bar, 3), "rank_read": tile["rank"]}}
        if len(found) > 1:
            row["ids"] = [_brief(item, mastered) for item in found]
        out.append(row)
    english = any(str(res.get("lang", "")).lower().startswith("en") for res in ocr_data.get("results") or [] if isinstance(res, dict))
    return {"tab": tab, "tiles": out, "unknown": unknown, "skipped": skipped, "english": english}
