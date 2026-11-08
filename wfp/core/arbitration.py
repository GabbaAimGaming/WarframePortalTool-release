"""仲裁(Arbitration): スケジュール(arbys.txt)の読み込み・今の枠と次の枠・ノードの情報

- スケジュールは browse.wf の arbys.txt(1 行 =「UNIX 時刻(秒・UTC。その 1 時間の始まり),ノードの内部名」)。
  取得はデータ更新とページのボタンのときだけ(`update_arbys`)。取れなければ前回分を使う
- ノード名・惑星・ミッションの種類・勢力は regions.json(データ更新で ExportRegions から作る)から引く。
  種類・勢力は Export の番号のまま持っていて、ここで `REGION_MISSIONS` `REGION_FACTIONS` のキーにする(表を直せばデータ更新なしで反映)
- 文字は値(種類・勢力のキー)で返し、画面の I18N(mode.<キー> / faction.<キー>)で名前にする
"""
from __future__ import annotations

import bisect
import time
from pathlib import Path

from wfp.core.common import ARBY_COUNT, ARBY_PICK, ARBY_SLOT, REGION_FACTIONS, REGION_MISSIONS, TextFailure, txt
from wfp.core.cycle import clock_offset
from wfp.drops.tables import node_mode
from wfp.fetch import arbys
from wfp.store import gamedata, userdata


class Schedule:
    """読み込んだスケジュール(始まりの時刻の昇順)"""

    def __init__(self, rows: list[tuple[int, str]]):
        self.starts = [r[0] for r in rows]
        self.nodes = [r[1] for r in rows]

    def __len__(self) -> int:
        return len(self.starts)

    @property
    def last(self) -> int | None:
        """最後の枠の始まり(無ければ None)"""
        return self.starts[-1] if self.starts else None

    def window(self, now: float, count: int = ARBY_COUNT) -> list[tuple[int, str]]:
        """今の枠(now を含む枠。無ければ飛ばす)から count 件。範囲の外なら空"""
        pos = bisect.bisect_right(self.starts, now) - 1
        begin = pos if pos >= 0 and now < self.starts[pos] + ARBY_SLOT else pos + 1
        return list(zip(self.starts[begin:begin + count], self.nodes[begin:begin + count]))


def parse_arbys(text: str) -> list[tuple[int, str]]:
    """arbys.txt の行を [(始まりの時刻, ノードの内部名)] にする。読めない行は飛ばす。
    並びは時刻の昇順にそろえ、同じ時刻が2回あれば先の行を使う"""
    rows: dict[int, str] = {}
    for line in (text or "").splitlines():
        start, sep, node = line.strip().partition(",")
        node = node.strip()
        if not sep or not node or any(c.isspace() for c in node):
            continue
        try:
            stamp = int(start)
        except ValueError:
            continue
        rows.setdefault(stamp, node)
    return sorted(rows.items())


def load_schedule(d: Path) -> Schedule | None:
    """保存済みのスケジュール。無い・行が無ければ None"""
    text = gamedata.read_arbys(d)
    sched = Schedule(parse_arbys(text)) if text is not None else None
    return sched if sched else None


def update_arbys(d: Path) -> Schedule:
    """スケジュールを取り直して保存する。取れない・行が無ければ例外(保存済みの分はそのまま)"""
    text = arbys.fetch_arbys()
    sched = Schedule(parse_arbys(text))
    if not sched:
        raise TextFailure(txt("err.arbys.none"))
    gamedata.save_arbys(d, text)
    return sched


def node_info(node: str, regions: dict) -> dict:
    """ノードの内部名 -> 表示用の値。regions.json に無ければ内部名のまま、種類・勢力は None。
    番号が表に無いときも種類・勢力は None で、番号(mission_index・faction_index)は返す(画面は「不明」と番号)。
    種類は NODE_MODES(惑星・ノードの英名)で付け替える(例: 火星の Tyana Pass は番号が防衛でもミラー防衛)"""
    r = regions.get(node)
    r = r if isinstance(r, dict) else {}
    mission_index, faction_index = r.get("mission_index"), r.get("faction_index")
    mission = REGION_MISSIONS.get(mission_index)
    if mission:
        mission = node_mode(r.get("planet") or "", r.get("node") or "", mission)
    return {"node": node, "node_name": r.get("node") or node, "node_ja": r.get("node_ja") or r.get("node") or node,
            "planet": r.get("planet") or "", "planet_ja": r.get("planet_ja") or r.get("planet") or "",
            "mission": mission, "mission_index": mission_index,
            "faction": REGION_FACTIONS.get(faction_index), "faction_index": faction_index}


def is_pick(info: dict) -> bool:
    """目立たせる仲裁か(ARBY_PICK の種類のどれか かつ 勢力のどれか)"""
    return info.get("mission") in ARBY_PICK["missions"] and info.get("faction") in ARBY_PICK["factions"]


def arby_view(sched: Schedule | None, regions: dict, now: float, count: int = ARBY_COUNT) -> dict:
    """表示用データ(ファイルに触らない)。rows は今の枠(あれば `current`)から count 件。目立たせる行は `pick`(`is_pick`)。
    out_of_range: スケジュールはあるが now より先の枠が無い(取り直しの案内)。
    regions_old: regions.json はあるが種類・勢力の番号が無い(この機能より前に作ったもの。データ更新の案内)"""
    rows = []
    for start, node in (sched.window(now, count) if sched else []):
        end = start + ARBY_SLOT
        info = node_info(node, regions)
        rows.append({"start": start, "end": end, "current": start <= now < end, "pick": is_pick(info), **info})
    return {"now": now, "has_schedule": sched is not None, "last": sched.last if sched else None,
            "out_of_range": sched is not None and not rows, "rows": rows,
            "regions_ok": bool(regions),
            "regions_old": bool(regions) and not any(isinstance(v, dict) and "mission_index" in v for v in regions.values())}


def arby_now(d: Path, now: float | None = None) -> float:
    """今の時刻(PC の時計のずれはサイクルの時刻合わせの値で補正する)"""
    return (time.time() if now is None else now) + clock_offset(userdata.load_cycles(d))


def arbitration_view(d: Path, sched: Schedule | None, now: float | None = None, count: int = ARBY_COUNT) -> dict:
    """画面・コマンド共通。sched は読み込み済みのスケジュール(API はキャッシュを渡す)"""
    return arby_view(sched, gamedata.read_regions(d), arby_now(d, now), count)
