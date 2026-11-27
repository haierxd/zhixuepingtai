"""Course material drafts, immutable published versions and atomic publication."""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy import and_, select

from . import document_db as db
from .config import get_settings
from . import gemini
from .rag import load_topics

COURSE_ID = "default-course"
PUBLISHED = {"published", "read_only"}


def embedding_signature():
    s = get_settings()
    return hashlib.sha256(
        f"{s.embed_provider}|{s.embed_api_base}|{s.embed_model}|{s.embed_dim}|documents-v1".encode()
    ).hexdigest()


def document(document_id, conn=None):
    if conn is None:
        with db.engine().connect() as connection:
            return document(document_id, connection)
    row = conn.execute(select(db.documents).where(db.documents.c.id == document_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "课件不存在")
    return dict(row)


def version(document_id, version_id, conn=None):
    if conn is None:
        with db.engine().connect() as connection:
            return version(document_id, version_id, connection)
    row = conn.execute(select(db.versions).where(
        db.versions.c.id == version_id, db.versions.c.document_id == document_id,
    )).mappings().first()
    if row is None:
        raise HTTPException(404, "课件版本不存在")
    return dict(row)


def _public_version(row):
    result = dict(row)
    result.pop("file_key", None)
    result.pop("embedding_signature", None)
    result["has_file"] = bool(row.get("file_key"))
    return result


def detail(document_id):
    with db.engine().connect() as conn:
        doc = document(document_id, conn)
        history = conn.execute(select(db.versions).where(
            db.versions.c.document_id == document_id,
        ).order_by(db.versions.c.number.desc())).mappings().all()
        return {**doc, "versions": [_public_version(row) for row in history]}


def version_detail(document_id, version_id):
    with db.engine().connect() as conn:
        doc = document(document_id, conn)
        row = version(document_id, version_id, conn)
        page_rows = conn.execute(select(db.pages).where(db.pages.c.version_id == version_id)
                                 .order_by(db.pages.c.page_number)).mappings().all()
        return {**_public_version(row), "kind": doc["kind"], "topic_id": doc["topic_id"],
                "course_id": doc["course_id"], "active": doc["active_version_id"] == version_id,
                "pages": [dict(p) for p in page_rows]}


def list_documents(*, published_only=False):
    with db.engine().connect() as conn:
        result = []
        for row in conn.execute(select(db.documents).order_by(db.documents.c.updated_at.desc())).mappings():
            row = dict(row)
            vid = row["active_version_id"] if published_only else row["latest_version_id"]
            if not vid:
                continue
            latest = version(row["id"], vid, conn)
            result.append({**row, "title": latest["title"], "status": latest["status"],
                           "number": latest["number"], "page_count": latest["page_count"],
                           "text_pages": latest["text_pages"], "chunk_count": latest["chunk_count"],
                           "error": latest["error"], "version_id": vid})
        return result


def _markdown_blocks(text):
    """Keep fenced code, display maths and paragraphs together where possible."""
    blocks, current, fence, math = [], [], None, False
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^(`{3,}|~{3,})", stripped)
        if match and not math:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
        elif not fence and stripped.startswith("$$"):
            if stripped == "$$":
                math = not math
        current.append(line)
        if not stripped and not fence and not math:
            blocks.append("\n".join(current).strip())
            current = []
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def markdown_chunks(text):
    sections, current, heading, fence = [], [], "概述", None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
        if not fence and re.match(r"^#{1,6}\s+", line):
            if current:
                sections.append((heading, "\n".join(current)))
            heading = re.sub(r"^#+\s+", "", line).strip()[:255]
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append((heading, "\n".join(current)))
    output = []
    limit = get_settings().chunk_max_chars
    for section_index, (title, body) in enumerate(sections):
        pending = ""
        for block in _markdown_blocks(body):
            # Large code/math blocks stay whole; ordinary long prose gets windows.
            pieces = [block]
            if len(block) > limit and not block.lstrip().startswith(("```", "~~~", "$$")):
                pieces = [block[i:i + limit] for i in range(0, len(block), limit - 120)]
            for piece in pieces:
                if pending and len(pending) + len(piece) + 2 > limit:
                    output.append({"section": title, "section_anchor": f"section-{section_index}", "text": pending})
                    pending = ""
                pending = (pending + "\n\n" + piece).strip()
        if pending:
            output.append({"section": title, "section_anchor": f"section-{section_index}", "text": pending})
    return output


def parse(kind, content, filename):
    s = get_settings()
    if not content or len(content) > s.document_max_bytes:
        raise HTTPException(413 if content else 400, "文件为空或超过上传大小限制")
    if kind == "markdown":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(400, "Markdown 文件请使用 UTF-8 编码") from None
        if not text.strip() or "\x00" in text:
            raise HTTPException(400, "Markdown 正文不能为空，且不能包含二进制内容")
        return text, [], None
    if not content.startswith(b"%PDF-"):
        raise HTTPException(400, "文件内容不是有效 PDF")
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            return "", [], "PDF 已加密，请上传未加密的文件。"
        if len(reader.pages) > s.document_max_pages:
            raise HTTPException(413, f"PDF 超过 {s.document_max_pages} 页限制")
        page_rows = []
        for i, page in enumerate(reader.pages, 1):
            try:
                text = (page.extract_text() or "").strip()
                status = "text" if text else "no_text"
            except Exception:
                text, status = "", "failed"
            page_rows.append({"page_number": i, "text": text, "status": status})
        return "", page_rows, None
    except HTTPException:
        raise
    except Exception:
        return "", [], "PDF 损坏或无法解析，请更换文件。"


def save_draft(*, title, topic_id, content, filename, kind, document_id=None):
    title = title.strip()
    if not title or len(title) > 255:
        raise HTTPException(400, "课件标题不能为空且最多 255 字")
    topics = load_topics()
    if topic_id not in topics:
        raise HTTPException(400, "请选择已有知识点")
    if kind not in {"markdown", "pdf"}:
        raise HTTPException(400, "仅支持 PDF 和 Markdown")
    text, parsed_pages, error = parse(kind, content, filename)
    vid, now = "ver_" + uuid4().hex, time.time()
    file_key = None
    path = None
    if kind == "pdf":
        file_key = vid + ".pdf"
        directory = get_settings().document_dir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / file_key
        path.write_bytes(content)
    try:
        with db.engine().begin() as conn:
            number = 1
            if document_id:
                # Serialize concurrent version saves per document.
                conn.execute(db.documents.update().where(db.documents.c.id == document_id).values(updated_at=now))
                doc = document(document_id, conn)
                if doc["kind"] != kind or doc["topic_id"] != topic_id:
                    raise HTTPException(400, "同一课件的新版本需保留原格式和知识点")
                number = version(document_id, doc["latest_version_id"], conn)["number"] + 1
                conn.execute(db.documents.update().where(db.documents.c.id == document_id).values(
                    latest_version_id=vid, title=title, updated_at=now,
                ))
            else:
                document_id = "doc_" + uuid4().hex
                conn.execute(db.documents.insert().values(
                    id=document_id, course_id=COURSE_ID, topic_id=topic_id, title=title,
                    kind=kind, latest_version_id=vid, created_at=now, updated_at=now,
                ))
            conn.execute(db.versions.insert().values(
                id=vid, document_id=document_id, number=number, title=title,
                status="parse_failed" if error else "draft", markdown=text, file_key=file_key,
                filename=Path(filename or "讲义.md").name[:255], page_count=len(parsed_pages),
                text_pages=sum(p["status"] == "text" for p in parsed_pages),
                chunk_count=0, error=error, created_at=now,
            ))
            if parsed_pages:
                conn.execute(db.pages.insert(), [{"version_id": vid, **p} for p in parsed_pages])
    except Exception:
        if path:
            path.unlink(missing_ok=True)
        raise
    return detail(document_id)


def request_publish(document_id, version_id):
    with db.engine().begin() as conn:
        # CAS reserves one publishing slot without changing the active version.
        claimed = conn.execute(db.documents.update().where(
            db.documents.c.id == document_id, db.documents.c.publishing_version_id.is_(None),
        ).values(publishing_version_id=version_id, updated_at=time.time())).rowcount
        doc = document(document_id, conn)
        row = version(document_id, version_id, conn)
        if not claimed:
            raise HTTPException(409, "该课件正在发布，请稍后再试")
        if row["status"] in PUBLISHED:
            raise HTTPException(409, "该版本已经发布")
        if row["status"] == "parse_failed":
            raise HTTPException(400, "请先更换无法解析的文件")
        if row["status"] not in {"draft", "failed"}:
            raise HTTPException(409, "当前版本状态不能发布")
        conn.execute(db.versions.update().where(db.versions.c.id == version_id).values(status="indexing", error=None))


async def publish(document_id, version_id):
    try:
        doc = document(document_id)
        row = version_detail(document_id, version_id)
        pieces = []
        if doc["kind"] == "markdown":
            pieces = markdown_chunks(row["markdown"])
        else:
            for page in row["pages"]:
                if page["status"] != "text":
                    continue
                for start in range(0, len(page["text"]), 780):
                    pieces.append({"page_number": page["page_number"], "section_anchor": None,
                                   "section": f"第 {page['page_number']} 页",
                                   "text": page["text"][start:start + 900]})
        signature = embedding_signature()
        rows = [{"version_id": version_id, "chunk_id": i, "course_id": doc["course_id"],
                 "document_id": document_id, "topic_id": doc["topic_id"], "topic_title": row["title"],
                 "page_number": piece.get("page_number"), "section_anchor": piece.get("section_anchor"),
                 "section": piece["section"], "text": piece["text"]} for i, piece in enumerate(pieces)]
        vectors = []
        if rows:
            if not get_settings().embedding_configured:
                raise ValueError("embedding not configured")
            for start in range(0, len(rows), 32):
                vectors.extend(await gemini.embed_batch([
                    f"{item['topic_title']} · {item['section']}\n{item['text']}" for item in rows[start:start + 32]
                ]))
            matrix = np.asarray(vectors, dtype=np.float32)
            if (matrix.shape != (len(rows), get_settings().embed_dim)
                    or not np.isfinite(matrix).all() or np.any(np.linalg.norm(matrix, axis=1) == 0)):
                raise ValueError("invalid embeddings")
            if get_settings().vector_backend == "pgvector":
                from .document_vectors import save
                save(signature, rows, vectors)
            else:
                for item, vector in zip(rows, vectors):
                    item["vector_json"] = json.dumps(vector)
        if signature != embedding_signature():
            raise ValueError("embedding configuration changed")
        # PostgreSQL commit completes before MySQL makes this version visible.
        with db.engine().begin() as conn:
            claimed = conn.execute(db.documents.update().where(
                db.documents.c.id == document_id, db.documents.c.publishing_version_id == version_id,
            ).values(active_version_id=version_id, publishing_version_id=None, updated_at=time.time())).rowcount
            if not claimed:
                raise ValueError("publication claim lost")
            conn.execute(db.chunks.delete().where(db.chunks.c.version_id == version_id))
            if rows:
                conn.execute(db.chunks.insert(), rows)
            conn.execute(db.versions.update().where(db.versions.c.id == version_id).values(
                status="published" if rows else "read_only", chunk_count=len(rows),
                embedding_signature=signature, published_at=time.time(), error=None,
            ))
    except Exception:
        with db.engine().begin() as conn:
            conn.execute(db.documents.update().where(
                db.documents.c.id == document_id, db.documents.c.publishing_version_id == version_id,
            ).values(publishing_version_id=None))
            conn.execute(db.versions.update().where(db.versions.c.id == version_id).values(
                status="failed", error="索引建立失败。请检查向量服务配置后重试，原生效版本继续可用。",
            ))


async def retrieve(query, top_k=5, document_id=None):
    signature = embedding_signature()
    with db.engine().connect() as conn:
        statement = select(db.documents.c.active_version_id).join(
            db.versions, db.documents.c.active_version_id == db.versions.c.id,
        ).where(db.versions.c.embedding_signature == signature, db.versions.c.chunk_count > 0)
        if document_id:
            statement = statement.where(db.documents.c.id == document_id)
        active = list(conn.execute(statement).scalars())
        if not active:
            return []
        items = [dict(row) for row in conn.execute(select(db.chunks).where(
            db.chunks.c.version_id.in_(active),
        )).mappings()]
    if not items:
        return []
    vector = np.asarray(await gemini.embed_one(query, task_type="RETRIEVAL_QUERY"), dtype=np.float32)
    if vector.shape != (get_settings().embed_dim,) or not np.isfinite(vector).all() or not np.linalg.norm(vector):
        raise ValueError("invalid query embedding")
    if get_settings().vector_backend == "pgvector":
        from .document_vectors import search
        return search(signature, active, vector, top_k)
    scored = []
    for row in items:
        stored = np.asarray(json.loads(row.pop("vector_json")), dtype=np.float32)
        row["score"] = float(np.dot(stored, vector) / (np.linalg.norm(stored) * np.linalg.norm(vector)))
        scored.append(row)
    return sorted(scored, key=lambda row: -row["score"])[:top_k]


def file_path(document_id, version_id):
    row = version(document_id, version_id)
    if not row["file_key"]:
        raise HTTPException(404, "该课件没有 PDF 原件")
    directory = get_settings().document_dir.resolve()
    path = (directory / row["file_key"]).resolve()
    if path.parent != directory or not path.is_file():
        raise HTTPException(404, "PDF 原件不存在")
    return path
