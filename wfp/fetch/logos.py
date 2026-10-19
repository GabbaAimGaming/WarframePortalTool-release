"""公式ファンキットのロゴ素材の取得・展開"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from wfp.core.common import FANKIT_LOGOS_URL, FANKIT_PAGE
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
        raise RuntimeError("ダウンロードした内容が zip ではありませんでした(配布元の仕様が変わった可能性があります)")
    count = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > LOGO_MAX_BYTES:
            raise RuntimeError("展開後のサイズが大きすぎるため中止しました")
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
        raise RuntimeError("zip の中にロゴ画像が見つかりませんでした")
    return count


def fetch_logos(d: Path | None = None, force: bool = False) -> Path | None:
    """公式ファンキットの Logos を取得して保存する。失敗しても例外にせず None を返す(ツールはロゴ無しで動く)"""
    have = find_logos_dir(d)
    if have and not force:
        print(f"ロゴ素材は取得済みです: {have}")
        return have
    print("公式ファンキット(Warframe Fan Kit)のロゴ素材を取得中...")
    print(f"  配布元: Digital Extremes 公式 ({FANKIT_PAGE})")
    try:
        raw = net.http_get(FANKIT_LOGOS_URL, timeout=180)
    except Exception as e:  # noqa: BLE001
        print(f"  失敗しました: {e}")
        print("  ※ロゴ無しでもツールは使えます。あとで「python wfportal.py logos」で取り直せます。")
        return None
    last_err = None
    for dest in logos_dirs(d):
        try:
            n = extract_logos(raw, dest)
            print(f"  {n} ファイルを保存しました -> {dest}")
            print("  ※ロゴ素材の権利は Digital Extremes にあります。個人の利用にとどめ、再配布しないでください。")
            return dest
        except PermissionError as e:
            last_err = e  # ツールのフォルダに書けないときは次の候補へ
        except Exception as e:  # noqa: BLE001
            last_err = e
            break
    print(f"  保存に失敗しました: {last_err}")
    print("  ※ロゴ無しでもツールは使えます。あとで「python wfportal.py logos」で取り直せます。")
    return None
