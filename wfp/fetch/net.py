"""ネットワーク取得(User-Agent・候補 URL を順に試す)"""
from __future__ import annotations

import urllib.request
from typing import Callable

from wfp.core.const import NET_CHUNK_BYTES
from wfp.core.i18n import txt
from wfp.core.log import say
from wfp.fetch import decode


# サイトによっては見慣れない User-Agent を拒否する(403)ため、ブラウザに近い名乗り方にする
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) wfportal/1.0"


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding", "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
            import gzip
            data = gzip.decompress(data)
    return data


def http_download(url: str, timeout: int = 60, on_chunk: Callable[[int], None] | None = None) -> bytes:
    """大きなファイル(ホイール・モデル)を NET_CHUNK_BYTES ずつ読む。読むたびに on_chunk(ここまでの量) を呼ぶ。
    中身をそのまま照合する(SHA-256)ので gzip は頼まない・ほどかない"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    parts, got = [], 0
    with urllib.request.urlopen(req, timeout=timeout) as r:
        while True:
            chunk = r.read(NET_CHUNK_BYTES)
            if not chunk:
                break
            parts.append(chunk)
            got += len(chunk)
            if on_chunk:
                on_chunk(got)
    return b"".join(parts)


def fetch_json(urls: list[str], verbose: bool = False) -> bytes:
    """候補 URL を順に試し、JSON として読めた最初の内容を返す。"""
    errors = []
    for url in urls:
        try:
            raw = http_get(url)
            decode.parse_json_bytes(raw)
            if verbose:
                say(txt("log.source", src=url), 1)
            return raw
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url} ({e})")
            if verbose:
                say(txt("log.failed.what", what=url, e=str(e)), 1)
    raise RuntimeError(" / ".join(errors))
