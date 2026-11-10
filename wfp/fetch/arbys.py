"""仲裁(Arbitration)のスケジュールの取得(browse.wf の arbys.txt)"""
from __future__ import annotations

from wfp.core.i18n import txt
from wfp.core.log import say
from wfp.core.const import ARBYS_URL
from wfp.fetch import net


def fetch_arbys() -> str:
    """arbys.txt を文字列で返す。取れなければ例外(行の検査は core.arbitration で行う)"""
    say(txt("log.get", file=ARBYS_URL), 1)
    return net.http_get(ARBYS_URL, timeout=120).decode("utf-8", "replace")
