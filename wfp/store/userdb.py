"""利用者データの置き場(SQLite): テーブルの作成・前の JSON からの引っ越し・バックアップ・壊れたときの復旧

ほかのモジュールは userdata.py の load_* / save_* を使う(ここを直接使うのは store の中と、起動・バックアップの呼び出しだけ)。

- 本体は <データ置き場>/userdata.db、バックアップは同じ中身の userdata_backup.db
- 書き込みのたびに meta の revision を 1 つ増やす。バックアップは起動したとき(ready)と、画面のサーバーでは
  USERDB_BACKUP_INTERVAL 秒ごと(start_backup_timer)に、本体の revision がバックアップと違っていれば写す
- 前の JSON(<種類>.json)があれば取り込んで <種類>_bk.json に名前を変える(すでにあれば _bk_2 …)。
  元の名前で置き直せば、次に起動したときにその種類だけ取り込み直す(今の中身は置き換わる)
- 壊れていたら: ① バックアップから戻す(壊れた本体は userdata_broken_<日時>.db に残す。ログだけ出して続ける)
  ② 戻せなければ、本体・バックアップの読める方(両方読めれば本体)から種類ごとに JSON(前の形)を
  userdata_export_<日時>/ に書き出し、UserDbBroken で止める(本体には触らない。次に開くときも同じく止まる)
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from wfp.core.errors import TextFailure
from wfp.core.i18n import txt
from wfp.core.log import say
from wfp.core.const import USERDB_BACKUP_FILE, USERDB_BACKUP_INTERVAL, USERDB_FILE, USERDB_SCHEMA_VERSION, USERDB_TIMEOUT

# 利用者データの種類 → 保存の形。前のファイルは <種類>.json
#   ids:   id の集合(テーブル id_sets)          ranks: 名前 → 整数(ranks)
#   items: 並び順のある JSON の一覧(list_items)  doc:   JSON 1つ(docs)
USER_KINDS = {
    "mods_owned": "ids", "mastered": "ids", "quests_done": "ids", "invasion_parts": "ids", "baro_owned": "ids",
    "arcanes_owned": "ranks",
    "builds": "items",
    "cycles": "doc", "duviri_adjust": "doc", "baro_seen": "doc",
}
# 取り込む・書き出すときの JSON の型(前のファイルの形)
_SHAPE_TYPES = {"ids": list, "ranks": dict, "items": list, "doc": dict}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (meta_key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS id_sets (kind TEXT NOT NULL, item_id TEXT NOT NULL, PRIMARY KEY (kind, item_id));
CREATE TABLE IF NOT EXISTS ranks (kind TEXT NOT NULL, name TEXT NOT NULL, rank_value INTEGER NOT NULL, PRIMARY KEY (kind, name));
CREATE TABLE IF NOT EXISTS list_items (kind TEXT NOT NULL, pos INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (kind, pos));
CREATE TABLE IF NOT EXISTS docs (doc_key TEXT PRIMARY KEY, data TEXT NOT NULL);
"""


class UserDbError(TextFailure):
    """利用者データの置き場を使えない(文はテキスト指定)。画面はエラー文、CLI はメッセージにして止める"""


class UserDbBroken(UserDbError):
    """壊れていて、バックアップからも戻せなかった(読めた分は書き出し済み)"""


def db_path(d: Path) -> Path:
    return d / USERDB_FILE


def backup_path(d: Path) -> Path:
    return d / USERDB_BACKUP_FILE


# --------------------------------------------------------------------------
# 開く・読む・書く
# --------------------------------------------------------------------------
_READY: set[str] = set()          # このプロセスで準備(検査・引っ越し・起動時のバックアップ)を済ませた本体のパス
_READY_LOCK = threading.RLock()


def _connect(path: Path) -> sqlite3.Connection:
    # isolation_level=None: トランザクションは自分で BEGIN / COMMIT する
    return sqlite3.connect(str(path), timeout=USERDB_TIMEOUT, isolation_level=None)


def _is_corrupt(err: BaseException) -> bool:
    """「データベースではない」「壊れている」の例外か。ロック待ちなど(OperationalError ほかの仲間)は入れない"""
    return type(err) is sqlite3.DatabaseError


def ready(d: Path) -> Path:
    """本体を使える状態にする(このプロセスで最初の1回だけ): 検査・復旧・テーブル作成・引っ越し・起動時のバックアップ"""
    path = db_path(d)
    key = str(path.resolve())
    with _READY_LOCK:
        if key not in _READY:
            _prepare(d)
            _READY.add(key)
    return path


def forget(d: Path) -> None:
    """準備済みの印を外す(次に開くときに検査し直す)"""
    with _READY_LOCK:
        _READY.discard(str(db_path(d).resolve()))


def _with_recovery(d: Path, action):
    """action() を行い、本体が壊れていた例外なら検査し直して(バックアップから戻して)もう1回だけ行う"""
    try:
        return action()
    except sqlite3.DatabaseError as err:
        if not _is_corrupt(err):
            raise
        forget(d)
        return action()


@contextmanager
def reading(d: Path):
    conn = _connect(ready(d))
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def writing(d: Path):
    """書き込みのトランザクション。始めるときにほかの書き込みを待ち(BEGIN IMMEDIATE)、抜けるときに revision を増やして確定する。
    中で例外が出たら何も書かずに戻す"""
    conn = _connect(ready(d))
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            _bump_revision(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def read_kind(d: Path, kind: str):
    """種類 kind の中身(ids は set・ranks は dict・items は list・doc は dict か None)"""
    def action():
        with reading(d) as conn:
            return read_rows(conn, kind)
    return _with_recovery(d, action)


def write_kind(d: Path, kind: str, value) -> None:
    """種類 kind の中身をまるごと置き換える"""
    def action():
        with writing(d) as conn:
            write_rows(conn, kind, value)
    _with_recovery(d, action)


@contextmanager
def editing_kind(d: Path, kind: str, clean=lambda value: value):
    """読む → 変える → 書くを1つのトランザクションで行う。開くときにほかの書き込みを待ち(BEGIN IMMEDIATE)、
    clean(読み出した値) を返す。抜けるときにその値(その場で変えたもの)を書いて確定する。中で例外が出たら何も書かない"""
    def start():
        conn = _connect(ready(d))
        try:
            conn.execute("BEGIN IMMEDIATE")
            return conn, clean(read_rows(conn, kind))
        except BaseException:
            conn.close()  # 確定していないので書いたものは無い
            raise
    conn, value = _with_recovery(d, start)
    try:
        try:
            yield value
            write_rows(conn, kind, value)
            _bump_revision(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def read_rows(conn: sqlite3.Connection, kind: str):
    shape = USER_KINDS[kind]
    if shape == "ids":
        return {row[0] for row in conn.execute("SELECT item_id FROM id_sets WHERE kind = ?", (kind,))}
    if shape == "ranks":
        return {row[0]: row[1] for row in conn.execute("SELECT name, rank_value FROM ranks WHERE kind = ? ORDER BY name", (kind,))}
    if shape == "items":
        return [json.loads(row[0]) for row in conn.execute("SELECT data FROM list_items WHERE kind = ? ORDER BY pos", (kind,))]
    row = conn.execute("SELECT data FROM docs WHERE doc_key = ?", (kind,)).fetchone()
    return json.loads(row[0]) if row else None


def write_rows(conn: sqlite3.Connection, kind: str, value) -> None:
    """種類 kind の中身をまるごと置き換える(トランザクションの中で呼ぶ)"""
    shape = USER_KINDS[kind]
    if shape == "ids":
        conn.execute("DELETE FROM id_sets WHERE kind = ?", (kind,))
        conn.executemany("INSERT OR IGNORE INTO id_sets (kind, item_id) VALUES (?, ?)", [(kind, str(x)) for x in value])
    elif shape == "ranks":
        conn.execute("DELETE FROM ranks WHERE kind = ?", (kind,))
        conn.executemany("INSERT INTO ranks (kind, name, rank_value) VALUES (?, ?, ?)",
                         [(kind, str(name), int(rank)) for name, rank in value.items()])
    elif shape == "items":
        conn.execute("DELETE FROM list_items WHERE kind = ?", (kind,))
        conn.executemany("INSERT INTO list_items (kind, pos, data) VALUES (?, ?, ?)",
                         [(kind, pos, json.dumps(item, ensure_ascii=False)) for pos, item in enumerate(value)])
    else:
        conn.execute("INSERT OR REPLACE INTO docs (doc_key, data) VALUES (?, ?)", (kind, json.dumps(value, ensure_ascii=False)))


def _bump_revision(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE meta_key = 'revision'")


def revision(path: Path) -> int | None:
    """ファイルの revision(書き込みの回数)。無い・読めなければ None"""
    if not path.exists():
        return None
    try:
        conn = _connect(path)
        try:
            row = conn.execute("SELECT value FROM meta WHERE meta_key = 'revision'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else None


# --------------------------------------------------------------------------
# 準備(検査・復旧・テーブル作成・引っ越し)
# --------------------------------------------------------------------------
def _prepare(d: Path) -> None:
    main, bk = db_path(d), backup_path(d)
    if main.exists():
        if not _healthy(main):
            _recover(d)
    elif bk.exists():  # 本体だけ無い(消してしまった): バックアップから戻す
        _recover(d)
    conn = _connect(main)
    try:
        _create(conn)
        _migrate(d, conn)
    finally:
        conn.close()
    backup_if_changed(d)


def _healthy(path: Path) -> bool:
    """PRAGMA quick_check が ok か。壊れていれば False(ロック待ちの失敗などはそのまま例外にする)"""
    try:
        conn = _connect(path)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as err:
        if not _is_corrupt(err):
            raise
        return False
    return bool(row) and row[0] == "ok"


def _create(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta (meta_key, value) VALUES ('schema_version', ?)", (str(USERDB_SCHEMA_VERSION),))
    conn.execute("INSERT OR IGNORE INTO meta (meta_key, value) VALUES ('revision', '0')")
    ver = conn.execute("SELECT value FROM meta WHERE meta_key = 'schema_version'").fetchone()[0]
    if int(ver) > USERDB_SCHEMA_VERSION:
        raise UserDbError(txt("err.userdb.newer"))


def legacy_value(f: Path, kind: str):
    """前の JSON の中身(形が違う・読めなければ None)。値の細かい検査は読み出す側(userdata の load_*)で行う"""
    try:
        raw = json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    shape = USER_KINDS[kind]
    if not isinstance(raw, _SHAPE_TYPES[shape]):
        return None
    if shape == "ids":
        return [x for x in raw if isinstance(x, str)]
    if shape == "ranks":
        return {str(k): v for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool)}
    if shape == "items":
        return [x for x in raw if isinstance(x, dict)]
    return raw


def free_name(path: Path) -> Path:
    """path が空いていればそのまま、あれば名前に _2 _3 … を付けた空いている名前"""
    if not path.exists():
        return path
    num = 2
    while True:
        cand = path.with_name(f"{path.stem}_{num}{path.suffix}")
        if not cand.exists():
            return cand
        num += 1


def _migrate(d: Path, conn: sqlite3.Connection) -> None:
    """前の JSON を取り込み、<種類>_bk.json に名前を変える。読めないファイルは取り込まずに名前だけ変える"""
    for kind in USER_KINDS:
        legacy = d / f"{kind}.json"
        if not legacy.exists():
            continue
        value = legacy_value(legacy, kind)
        if value is not None:
            conn.execute("BEGIN IMMEDIATE")
            try:
                write_rows(conn, kind, value)
                _bump_revision(conn)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        bk = free_name(d / f"{kind}_bk.json")
        try:
            legacy.rename(bk)
        except FileNotFoundError:  # ほかのプロセスが先に取り込んで名前を変えた
            continue
        if value is None:
            say(txt("log.userdb.legacy_broken", file=legacy.name, bk=bk.name))
        else:
            say(txt("log.userdb.migrated", kind=kind, file=bk.name))


# --------------------------------------------------------------------------
# バックアップ
# --------------------------------------------------------------------------
def copy_db(src: Path, dst: Path) -> None:
    """src を dst に写す(一時ファイルに書いてから置き換えるので、途中で落ちても dst は前のまま)"""
    tmp = dst.with_name(dst.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    src_conn, tmp_conn = _connect(src), _connect(tmp)
    try:
        src_conn.backup(tmp_conn)
    finally:
        tmp_conn.close()
        src_conn.close()
    os.replace(tmp, dst)


def backup_if_changed(d: Path) -> bool:
    """本体の revision がバックアップと違えば、本体を検査してからバックアップに写す。写したら True。
    失敗してもログを出すだけ(例外にしない)。本体の検査で問題があれば写さず、次に開くときに検査し直す"""
    main, bk = db_path(d), backup_path(d)
    try:
        if not main.exists():
            return False
        main_rev = revision(main)
        if main_rev is not None and bk.exists() and revision(bk) == main_rev:
            return False
        if not _healthy(main):
            say(txt("log.userdb.check_failed"))
            forget(d)
            return False
        copy_db(main, bk)
        return True
    except (sqlite3.Error, OSError) as err:
        say(txt("log.userdb.backup_failed", e=str(err)))
        return False


def start_backup_timer(d: Path, interval: float = USERDB_BACKUP_INTERVAL) -> threading.Event:
    """interval 秒ごとに backup_if_changed する(画面のサーバー用)。返り値の Event を set すると止まる"""
    stop = threading.Event()

    def loop():
        while not stop.wait(interval):
            try:
                backup_if_changed(d)
            except Exception as err:  # noqa: BLE001  裏の処理なので止めない
                say(txt("log.userdb.backup_failed", e=str(err)))

    threading.Thread(target=loop, name="userdb-backup", daemon=True).start()
    return stop


# --------------------------------------------------------------------------
# 復旧
# --------------------------------------------------------------------------
def _stamp(path: Path) -> str:
    """ファイルの更新日時(書き出し先の名前に使う。同じ壊れたファイルなら同じ名前になる)"""
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d-%H%M%S")


def _move_db(src: Path, dst: Path) -> None:
    """DB とその書きかけの記録(-journal)を一緒に名前を変える"""
    src.rename(dst)
    journal = src.with_name(src.name + "-journal")
    if journal.exists():
        journal.rename(dst.with_name(dst.name + "-journal"))


def _recover(d: Path) -> None:
    """① バックアップから戻す。② 戻せなければ読める分を JSON に書き出して UserDbBroken で止める"""
    main, bk = db_path(d), backup_path(d)
    stamp = _stamp(main if main.exists() else bk)
    if bk.exists() and _healthy(bk):
        broken = None
        if main.exists():
            broken = free_name(d / f"userdata_broken_{stamp}.db")
            _move_db(main, broken)
        copy_db(bk, main)
        if broken is not None:
            say(txt("log.userdb.restored", file=broken.name))
        return
    out = d / f"userdata_export_{stamp}"
    if not out.exists():
        export_json(out, [main, bk])
    raise UserDbBroken(txt("err.userdb.broken", dir=str(out)))


def export_json(out: Path, sources: list[Path]) -> list[str]:
    """種類ごとに、sources の先頭から読めたファイルの中身を前の形の JSON(<種類>.json)にして out に書く。書いた種類を返す"""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for kind in USER_KINDS:
        value = None
        for src in sources:
            value = _read_quietly(src, kind)
            if value is not None:
                break
        if value is None:
            continue
        if isinstance(value, set):
            value = sorted(value)
        (out / f"{kind}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(kind)
    return written


def _read_quietly(path: Path, kind: str):
    """壊れているかもしれないファイルから種類 kind を読む。無い・読めない・入っていなければ None"""
    if not path.exists():
        return None
    try:
        conn = _connect(path)
        try:
            value = read_rows(conn, kind)
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        return None
    return value if value else None

