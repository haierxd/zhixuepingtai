"""Versioned course material metadata, separate from the legacy migration tables."""
from __future__ import annotations

from functools import lru_cache
from sqlalchemy import Column, Double, Integer, MetaData, String, Table, Text, create_engine
from sqlalchemy.dialects.mysql import LONGTEXT

from .config import get_settings
from .database import get_engine, mysql_url

metadata = MetaData()
body = Text().with_variant(LONGTEXT(), "mysql")
documents = Table(
    "documents", metadata,
    Column("id", String(64), primary_key=True),
    Column("course_id", String(64), nullable=False),
    Column("topic_id", String(128), nullable=False),
    Column("title", String(255), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("active_version_id", String(64)),
    Column("latest_version_id", String(64), nullable=False),
    Column("publishing_version_id", String(64)),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
)
versions = Table(
    "document_versions", metadata,
    Column("id", String(64), primary_key=True),
    Column("document_id", String(64), nullable=False, index=True),
    Column("number", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("title", String(255), nullable=False),
    Column("markdown", body),
    Column("file_key", String(128)),
    Column("filename", String(255)),
    Column("page_count", Integer, nullable=False),
    Column("text_pages", Integer, nullable=False),
    Column("chunk_count", Integer, nullable=False),
    Column("error", Text),
    Column("embedding_signature", String(64)),
    Column("created_at", Double, nullable=False),
    Column("published_at", Double),
)
pages = Table(
    "document_pages", metadata,
    Column("version_id", String(64), primary_key=True),
    Column("page_number", Integer, primary_key=True),
    Column("text", body, nullable=False),
    Column("status", String(32), nullable=False),
)
chunks = Table(
    "document_chunks", metadata,
    Column("version_id", String(64), primary_key=True),
    Column("chunk_id", Integer, primary_key=True),
    Column("course_id", String(64), nullable=False),
    Column("document_id", String(64), nullable=False),
    Column("topic_id", String(128), nullable=False),
    Column("topic_title", String(255), nullable=False),
    Column("page_number", Integer),
    Column("section_anchor", String(128)),
    Column("section", String(255), nullable=False),
    Column("text", body, nullable=False),
    Column("vector_json", body),
)

sessions = Table(
    "auth_sessions", metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("student_id", String(64), nullable=False, index=True),
    Column("expires_at", Double, nullable=False),
)
personal_documents = Table(
    "personal_documents", metadata,
    Column("id", String(64), primary_key=True),
    Column("student_id", String(64), nullable=False, index=True),
    Column("title", String(255), nullable=False),
    Column("payload", body, nullable=False),
    Column("created_at", Double, nullable=False),
)
learning_records = Table(
    "learning_records", metadata,
    Column("id", String(64), primary_key=True),
    Column("student_id", String(64), nullable=False, index=True),
    Column("material_id", String(128), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("payload", body, nullable=False),
    Column("updated_at", Double, nullable=False),
)


@lru_cache(maxsize=8)
def _sqlite_engine(path):
    return create_engine("sqlite:///" + str(path), connect_args={"check_same_thread": False, "timeout": 30})


def engine():
    s = get_settings()
    return get_engine(mysql_url(s)) if s.database_backend == "mysql" else _sqlite_engine(s.db_path)


def initialize():
    metadata.create_all(engine())
    # This application runs a single API worker. Interrupted background jobs are
    # made retryable on startup; the previous active version is never changed.
    with engine().begin() as conn:
        conn.execute(versions.update().where(versions.c.status == "indexing").values(
            status="failed", error="服务重启导致索引中断，请重新发布。",
        ))
        conn.execute(documents.update().where(documents.c.publishing_version_id.is_not(None)).values(
            publishing_version_id=None,
        ))
