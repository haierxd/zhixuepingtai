"""Verify the configured first-stage services without retaining probe records.

Run from the project root: .venv/Scripts/python.exe -m scripts.check_stage1
"""
from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.database import TABLES, get_engine, mysql_url
from app.main import app
from app.rag import get_index


def check():
    settings = get_settings()
    if settings.database_backend != "mysql" or settings.vector_backend != "pgvector":
        raise ValueError("Select mysql and pgvector in .env before this check")
    report = {}
    engine = get_engine(mysql_url(settings))
    probe_id = "verify-" + uuid4().hex
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            table = TABLES["students"]
            conn.execute(table.insert().values(id=probe_id, name="验收临时记录"))
            assert conn.execute(select(table.c.name).where(table.c.id == probe_id)).scalar_one() == "验收临时记录"
        finally:
            transaction.rollback()
        assert conn.execute(select(table.c.id).where(table.c.id == probe_id)).first() is None
        report["mysql_write_rollback"] = "ok"
        report["tables"] = {
            name: conn.execute(select(func.count()).select_from(table)).scalar_one()
            for name, table in TABLES.items()
        }
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        info = health.json()
        assert info["index_ready"] and info["database"] == "mysql" and info["vector_backend"] == "pgvector"
        roster = client.get("/api/teacher/students", headers={"X-Teacher-Pass": settings.teacher_passcode})
        assert roster.status_code == 200
        assert len(roster.json()["students"]) == report["tables"]["students"]
        for path in ("/", "/legacy/", "/legacy/app.js", "/api/topics", "/api/profile", "/api/assignments"):
            assert client.get(path).status_code == 200, path
        # Use the same event loop that owns the application's lifespan.
        hits = client.portal.call(get_index().retrieve, "过拟合 正则化", 3)
        assert len(hits) == 3 and all(hit["text"] for hit in hits)
        report["pgvector_retrieval"] = "ok"
        report["api"] = "ok"
        report["topics"] = info["topics"]
        report["chunks"] = info["chunks"]
        report["chat_configured"] = info["configured"]
        report["embedding_provider"] = settings.embed_provider
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        check()
    except Exception as exc:
        # Connection errors can contain SQL parameters or credentials.
        print("First-stage check failed: " + type(exc).__name__)
        raise SystemExit(1)
