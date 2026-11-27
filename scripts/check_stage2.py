"""Exercise the running local material API and remove only this run's probes."""
import json
import time
from io import BytesIO
from uuid import uuid4

import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select

from app.config import get_settings
from app import document_db as db
from app.document_vectors import connect


def check():
    settings = get_settings()
    assert settings.database_backend == "mysql" and settings.vector_backend == "pgvector"
    created = []
    files = []
    prefix = "验收临时课件-" + uuid4().hex
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{settings.port}",
                          headers={"X-Teacher-Pass": settings.teacher_passcode}, timeout=30) as client:
            topic_id = client.get("/api/topics").json()["topics"][0]["id"]
            payload = BytesIO()
            writer = PdfWriter()
            page = writer.add_blank_page(width=612, height=792)
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 72 720 Td (Regularization reduces overfitting.) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
            writer.write(payload)
            report = {}
            for kind in ("markdown", "pdf"):
                data = {"title": prefix + kind, "topic_id": topic_id}
                if kind == "markdown":
                    data["markdown"] = "# Regularization\n\nRegularization reduces overfitting.\n\n## Validation\n\nCompare validation error with training error."
                    response = client.post("/api/teacher/documents", data=data)
                else:
                    response = client.post("/api/teacher/documents", data=data,
                                           files={"file": ("probe.pdf", payload.getvalue(), "application/pdf")})
                response.raise_for_status()
                doc = response.json()
                created.append(doc["id"])
                vid = doc["latest_version_id"]
                published = client.post(f"/api/teacher/documents/{doc['id']}/versions/{vid}/publish")
                published.raise_for_status()
                for _ in range(30):
                    state = client.get(f"/api/teacher/documents/{doc['id']}").json()
                    current = next(row for row in state["versions"] if row["id"] == vid)
                    if current["status"] != "indexing":
                        break
                    time.sleep(0.2)
                assert current["status"] == "published", current["status"]
                assert state["active_version_id"] == vid
                result = client.post("/api/documents/search", json={"query": "Regularization overfitting", "document_id": doc["id"]})
                result.raise_for_status()
                hits = result.json()["chunks"]
                assert hits and all(row["version_id"] == vid for row in hits)
                if kind == "pdf":
                    assert hits[0]["page_number"] == 1
                    original = client.get(f"/api/documents/{doc['id']}/versions/{vid}/file")
                    assert original.status_code == 200 and original.content == payload.getvalue()
                report[kind] = {"publish": "ok", "pgvector_retrieval": "ok", "chunks": current["chunk_count"]}
        print(json.dumps(report))
    finally:
        if created:
            with db.engine().begin() as conn:
                owned = list(conn.execute(select(db.documents.c.id).where(
                    db.documents.c.id.in_(created), db.documents.c.title.like(prefix + "%"),
                )).scalars())
                version_ids = list(conn.execute(select(db.versions.c.id).where(db.versions.c.document_id.in_(owned))).scalars())
                files = list(conn.execute(select(db.versions.c.file_key).where(
                    db.versions.c.document_id.in_(owned), db.versions.c.file_key.is_not(None),
                )).scalars())
                with connect() as pg:
                    pg.execute("DELETE FROM document_vectors WHERE document_id=ANY(%s)", (owned,))
                conn.execute(db.chunks.delete().where(db.chunks.c.document_id.in_(owned)))
                conn.execute(db.pages.delete().where(db.pages.c.version_id.in_(version_ids)))
                conn.execute(db.versions.delete().where(db.versions.c.document_id.in_(owned)))
                conn.execute(db.documents.delete().where(db.documents.c.id.in_(owned)))
            directory = settings.document_dir.resolve()
            for key in files:
                path = (directory / key).resolve()
                if path.parent == directory:
                    path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        check()
    except Exception as exc:
        print("Stage-two check failed: " + type(exc).__name__)
        raise SystemExit(1)
