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
    q("""create table if not exists users(
        id integer primary key autoincrement,
        username text not null unique collate nocase,
        email text not null unique collate nocase,
        pw_hash text not null,
        created real
    )""")
    q("""create table if not exists password_resets(
        token_hash text primary key, user_id integer not null, expires real not null
    )""")
    q("""create table if not exists projects(
        id text primary key, name text, idea text, constraints text, status text,
        plan text, tokens integer default 0, fix_rounds integer default 0, created real,
        user_id integer
    )""")
    # Older databases were created before accounts existed.
    columns = {row["name"] for row in q("pragma table_info(projects)")}
    if "user_id" not in columns:
        q("alter table projects add column user_id integer")
    q("create index if not exists projects_user on projects(user_id, created)")
    q("""create table if not exists events(
        id integer primary key autoincrement, project_id text, ts real, agent text,
        kind text, message text, data text
    )""")


initialize()
