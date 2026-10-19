"""ビルド画像の保存・検査・削除"""
from __future__ import annotations

import re
from pathlib import Path


IMAGE_DIR = "build_images"


IMAGE_MAX_BYTES = 20 * 1024 * 1024


IMAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")


IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def image_ext(data: bytes) -> str | None:
    """中身(先頭のバイト列)から画像の種類を判定する。拡張子や申告は信用しない。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_build_image(d: Path, data: bytes) -> str:
    if len(data) > IMAGE_MAX_BYTES:
        raise ValueError(f"画像が大きすぎます(上限 {IMAGE_MAX_BYTES // 1024 // 1024}MB)。")
    ext = image_ext(data)
    if not ext:
        raise ValueError("PNG / JPEG / GIF / WebP の画像を選んでください。")
    import uuid
    folder = d / IMAGE_DIR
    folder.mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (folder / name).write_bytes(data)
    return name


def build_image_path(d: Path, name: str) -> Path | None:
    if not IMAGE_NAME_RE.match(name or ""):
        return None
    p = d / IMAGE_DIR / name
    return p if p.is_file() else None


def delete_build_images(d: Path, names_: list[str]) -> None:
    for n in names_:
        if p := build_image_path(d, n):
            p.unlink(missing_ok=True)
