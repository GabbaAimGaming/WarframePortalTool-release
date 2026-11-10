"""名前一覧に対するあいまい一致(文字認識の結果を名前に当てる)。

wfp の外の画面の読み取り(wfportal_ocr のビルド画像・wfportal_msscan のマスター一覧)で共用する。
照合のキーは core/text の ocr_key(文字認識の英数字の取り違えをそろえる)。2026-11-10 に wfportal_ocr から移した
"""
from __future__ import annotations

from difflib import SequenceMatcher

from wfp.core.text import ocr_key


class NameMatcher:
    """名前一覧に対するあいまい一致。長さの近い候補だけを比べるので 1000 件程度なら十分速い"""

    def __init__(self, entries: list[tuple[str, str, object]]):  # (種類, 名前, 付随情報)
        self.exact: dict[str, tuple] = {}
        self.by_len: dict[int, list[tuple]] = {}
        for kind, name, info in entries:
            k = ocr_key(name)
            if len(k) < 3 or k in self.exact:
                continue
            self.exact[k] = (kind, name, info)
            self.by_len.setdefault(len(k), []).append((k, kind, name, info))

    @staticmethod
    def threshold(n: int) -> float:
        return 1.01 if n <= 4 else 0.9 if n <= 7 else 0.86  # 短い名前は完全一致のみ

    def match(self, text: str):
        k = ocr_key(text)
        if len(k) < 3:
            return None
        if k in self.exact:
            kind, name, info = self.exact[k]
            return 1.0, kind, name, info, k
        need = self.threshold(len(k))
        if need > 1:
            return None
        sm = SequenceMatcher(autojunk=False)
        sm.set_seq2(k)
        best = None
        for n in range(int(len(k) * 0.8), int(len(k) * 1.25) + 2):
            for kk, kind, name, info in self.by_len.get(n, ()):
                sm.set_seq1(kk)
                if sm.real_quick_ratio() < need or sm.quick_ratio() < need:
                    continue
                r = sm.ratio()
                if r >= need and (best is None or r > best[0]):
                    best = (r, kind, name, info, kk)
        return best
