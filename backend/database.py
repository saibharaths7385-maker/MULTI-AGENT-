import sqlite3
from contextlib import closing

from backend.settings import DATA, DB, WS

DATA.mkdir(parents=True, exist_ok=True)
WS.mkdir(parents=True, exist_ok=True)


def q(sql, args=()):
    with closing(sqlite3.connect(DB, timeout=15)) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(sql, args)
        connection.commit()
        return cursor.fetchall()


def initialize():
    q("""create table if not exists projects(
        id text primary key, name text, idea text, constraints text, status text,
        plan text, tokens integer default 0, fix_rounds integer default 0, created real
    )""")
    q("""create table if not exists events(
        id integer primary key autoincrement, project_id text, ts real, agent text,
        kind text, message text, data text
    )""")


initialize()
