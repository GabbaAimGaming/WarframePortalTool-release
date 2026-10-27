"""公式ファンキットのロゴ素材の取得・展開"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from wfp.core.common import FANKIT_LOGOS_URL, FANKIT_PAGE, TextFailure, error_text, say, txt
from wfp.core import common
from wfp.fetch import net


LOGO_EXTS = (".png", ".eps", ".svg", ".jpg", ".jpeg", ".ai", ".pdf")


LOGO_MAX_BYTES = 300 * 1024 * 1024  # 想定より極端に大きいときは止める


def logos_dirs(d: Path | None = None) -> list[Path]:
    """ロゴ素材の置き場の候補(優先順)。ツールのフォルダに書けなければデータ置き場を使う"""
    dirs = [common.APP_DIR / "assets" / "Logos"]
    if d is not None:
        dirs.append(d / "Logos")
    return dirs


def find_logos_dir(d: Path | None = None) -> Path | None:
    """取得済みのロゴ素材の置き場(LotusFlower.png がある所)。無ければ None"""
    for p in logos_dirs(d):
        if (p / "LotusFlower.png").is_file():
            return p
    return None


def extract_logos(raw: bytes, dest: Path) -> int:
    """Dropbox のフォルダ zip からロゴ画像だけを dest に展開する。展開したファイル数を返す。

    zip の中の先頭の "Logos/" は取り除き、Focus/ や Syndicates/ などのサブフォルダはそのまま残す。
    画像以外のファイルや、dest の外に出る名前(../ など)は無視する。
    """
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise TextFailure(txt("err.logo.notzip"))
    count = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > LOGO_MAX_BYTES:
            raise TextFailure(txt("err.logo.toolarge"))
        dest_root = dest.resolve()
        for info in infos:
            parts = [x for x in info.filename.replace("\\", "/").split("/") if x not in ("", ".")]
            if parts and parts[0].lower() == "logos":
                parts = parts[1:]
            if not parts or ".." in parts or not parts[-1].lower().endswith(LOGO_EXTS):
                continue
            out = dest.joinpath(*parts)
            if dest_root not in out.resolve().parents:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(info))
            count += 1
    if count == 0:
        raise TextFailure(txt("err.logo.noimage"))
    return count


def fetch_logos(d: Path | None = None, force: bool = False) -> Path | None:
    """公式ファンキットの Logos を取得して保存する。失敗しても例外にせず None を返す(ツールはロゴ無しで動く)"""
    have = find_logos_dir(d)
    if have and not force:
        say(txt("log.logo.have", dir=str(have)))
        return have
    say(txt("log.fetching.logo"))
    say(txt("log.logo.from", url=FANKIT_PAGE), 1)
    try:
        raw = net.http_get(FANKIT_LOGOS_URL, timeout=180)
    except Exception as e:  # noqa: BLE001
        say(txt("log.logo.failed", e=error_text(e)), 1)
        say(txt("log.logo.later"), 1)
        return None
    last_err = None
    for dest in logos_dirs(d):
        try:
            n = extract_logos(raw, dest)
            say(txt("log.logo.saved", n=str(n), dir=str(dest)), 1)
            say(txt("log.logo.rights"), 1)
            return dest
        except PermissionError as e:
            last_err = e  # ツールのフォルダに書けないときは次の候補へ
        except Exception as e:  # noqa: BLE001
            last_err = e
            break
    say(txt("log.logo.savefail", e=error_text(last_err) if last_err else ""), 1)
    say(txt("log.logo.later"), 1)
    return None
