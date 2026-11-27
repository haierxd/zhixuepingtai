"""MySQL schema and the small SQL adapter used by the existing store API."""
from __future__ import annotations

from functools import lru_cache
from sqlalchemy import (
    Column, Double, Integer, MetaData, String, Table, Text, create_engine, text,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.engine import URL

metadata = MetaData()
body_text = Text().with_variant(LONGTEXT(), "mysql")
students = Table(
    "students", metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("grade", String(255)), Column("major", String(255)),
    Column("created_at", Double), Column("student_no", String(128)),
    Column("username", String(255), unique=True),
    Column("password_hash", String(255)),
)
mastery = Table(
    "mastery", metadata,
    Column("student_id", String(64), primary_key=True),
    Column("topic_id", String(128), primary_key=True),
    Column("score", Double, server_default="0"),
    Column("attempts", Integer, server_default="0"), Column("updated_at", Double),
)
messages = Table(
    "messages", metadata,
    Column("id", String(64), primary_key=True),
    Column("student_id", String(64), index=True),
    Column("role", String(32)), Column("content", body_text),
    Column("citations", body_text), Column("created_at", Double),
)
quizzes = Table(
    "quizzes", metadata,
    Column("id", String(64), primary_key=True),
    Column("student_id", String(64), index=True),
    Column("topic_id", String(128)), Column("payload", body_text),
    Column("score", Double), Column("created_at", Double), Column("duration", Double),
)
events = Table(
    "events", metadata,
    Column("id", String(64), primary_key=True),
    Column("student_id", String(64), index=True),
    Column("kind", String(64)), Column("detail", body_text), Column("created_at", Double),
)
assignments = Table(
    "assignments", metadata,
    Column("id", String(64), primary_key=True),
    Column("student_id", String(64), index=True), Column("topic_id", String(128)),
    Column("topic_title", String(255)), Column("n", Integer, server_default="5"),
    Column("status", String(32), server_default="pending"),
    Column("score", Double), Column("created_at", Double), Column("done_at", Double),
)
TABLES = {t.name: t for t in metadata.sorted_tables}


def mysql_url(settings) -> URL:
    return URL.create(
        "mysql+pymysql", username=settings.mysql_user, password=settings.mysql_password,
        host=settings.mysql_host, port=settings.mysql_port, database=settings.mysql_database,
        query={"charset": "utf8mb4"},
    )


@lru_cache(maxsize=4)
def get_engine(url):
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})


class Record(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Result:
    def __init__(self, result):
        self.result = result
        self.rowcount = result.rowcount

    def fetchone(self):
        row = self.result.mappings().fetchone()
        return Record(row) if row is not None else None

    def fetchall(self):
        return [Record(r) for r in self.result.mappings().fetchall()]


class StoreConnection:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql: str, values=()):
        parts = sql.split("?")
        if len(parts) - 1 != len(values):
            raise ValueError("SQL placeholder count mismatch")
        statement = parts[0] + "".join(
            f":p{i}{part}" for i, part in enumerate(parts[1:])
        )
        return Result(self.conn.execute(text(statement), {
            f"p{i}": value for i, value in enumerate(values)
        }))
