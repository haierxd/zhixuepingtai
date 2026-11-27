"""RAG:知识文档解析、分块、向量化、落盘索引与余弦检索。

设计要点:
- 按 Markdown 小节(## )切块,块内保留"主题 + 小节"上下文,利于召回。
- 索引带签名(文件指纹 + 模型 + 维度),知识库变动后自动重建。
- 向量在内存中归一化,检索用点积即余弦相似度。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .config import KNOWLEDGE_DIR, get_settings
from .gemini import embed_batch, embed_one


# ---------------- 文档解析 ----------------

@dataclass
class Topic:
    id: str
    title: str
    title_en: str
    difficulty: str
    tags: list[str]
    body: str
    chunk_count: int = 0


@dataclass
class Chunk:
    topic_id: str
    topic_title: str
    section: str
    text: str


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)
    if not m:
        return {}, raw
    meta_raw, body = m.group(1), m.group(2)
    meta: dict = {}
    for line in meta_raw.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            items = [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
            meta[key] = items
        else:
            meta[key] = val.strip("'\"")
    return meta, body


def load_topics() -> dict[str, Topic]:
    topics: dict[str, Topic] = {}
    if not KNOWLEDGE_DIR.exists():
        return topics
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        tid = meta.get("id") or path.stem
        topics[tid] = Topic(
            id=tid,
            title=meta.get("title", tid),
            title_en=meta.get("title_en", ""),
            difficulty=meta.get("difficulty", "进阶"),
            tags=meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
            body=body.strip(),
        )
    return topics


def _split_sections(body: str) -> list[tuple[str, str]]:
    """按二级标题(## )拆分为 (section_title, section_text)。"""
    parts = re.split(r"\n(?=##\s)", body)
    out: list[tuple[str, str]] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        first, _, rest = p.partition("\n")
        title = first.lstrip("#").strip() if first.startswith("##") else "概述"
        text = (rest if first.startswith("##") else p).strip()
        if text:
            out.append((title, text))
    return out


def _window(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def build_chunks(topics: dict[str, Topic]) -> list[Chunk]:
    s = get_settings()
    chunks: list[Chunk] = []
    for t in topics.values():
        n = 0
        for section, text in _split_sections(t.body):
            for piece in _window(text, s.chunk_max_chars, s.chunk_overlap):
                chunks.append(Chunk(t.id, t.title, section, piece))
                n += 1
        t.chunk_count = n
    return chunks


# ---------------- 索引 ----------------

def _signature(topics: dict[str, Topic]) -> str:
    s = get_settings()
    h = hashlib.sha256()
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    h.update(f"|{s.embed_provider}|{s.embed_api_base}|{s.embed_model}|{s.embed_dim}|{s.chunk_max_chars}|{s.chunk_overlap}|v2".encode())
    return h.hexdigest()


class KnowledgeIndex:
    def __init__(self) -> None:
        self.topics: dict[str, Topic] = {}
        self.chunks: list[Chunk] = []
        self.matrix: Optional[np.ndarray] = None   # (N, dim) 已归一化
        self.ready: bool = False
        self.signature: str | None = None

    # ---- 检索 ----
    async def retrieve(self, query: str, top_k: Optional[int] = None) -> list[dict]:
        limit = top_k or get_settings().retrieve_top_k
        legacy = await self._retrieve_legacy(query, limit)
        from . import documents
        material = await documents.retrieve(query, limit) if get_settings().embedding_configured else []
        return sorted(legacy + material, key=lambda item: -item["score"])[:limit]

    async def _retrieve_legacy(self, query: str, top_k: Optional[int] = None) -> list[dict]:
        if not self.ready or not self.chunks:
            return []
        top_k = top_k or get_settings().retrieve_top_k
        q = np.array(await embed_one(query, task_type="RETRIEVAL_QUERY"), dtype=np.float32)
        if q.shape != (get_settings().embed_dim,) or not np.isfinite(q).all():
            raise ValueError("Query embedding dimension mismatch")
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        q = q / qn
        if get_settings().vector_backend == "pgvector":
            from . import vector_store
            return vector_store.retrieve(self.signature, q, top_k)
        if self.matrix is None:
            return []
        scores = self.matrix @ q
        idx = np.argsort(-scores)[:top_k]
        results = []
        for i in idx:
            ch = self.chunks[int(i)]
            results.append({
                "topic_id": ch.topic_id,
                "topic_title": ch.topic_title,
                "section": ch.section,
                "text": ch.text,
                "score": float(scores[int(i)]),
            })
        return results

    def topic_list(self) -> list[dict]:
        return [
            {"id": t.id, "title": t.title, "title_en": t.title_en,
             "difficulty": t.difficulty, "tags": t.tags, "chunk_count": t.chunk_count}
            for t in self.topics.values()
        ]

    def topic_body(self, topic_id: str) -> Optional[str]:
        t = self.topics.get(topic_id)
        return t.body if t else None


_INDEX = KnowledgeIndex()


def get_index() -> KnowledgeIndex:
    return _INDEX


def _load_cache(sig: str) -> Optional[tuple[list[Chunk], np.ndarray]]:
    path = get_settings().index_path
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if data.get("signature") != sig:
        return None
    chunks = [Chunk(**c) for c in data["chunks"]]
    matrix = np.array(data["vectors"], dtype=np.float32)
    return chunks, matrix


def _save_cache(sig: str, chunks: list[Chunk], matrix: np.ndarray) -> None:
    path = get_settings().index_path
    path.write_text(json.dumps({
        "signature": sig,
        "chunks": [c.__dict__ for c in chunks],
        "vectors": matrix.tolist(),
    }, ensure_ascii=False), encoding="utf-8")


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


async def build_index(force: bool = False) -> dict:
    """构建/加载知识索引。返回统计信息。"""
    idx = _INDEX
    idx.ready = False
    idx.signature = None
    idx.matrix = None
    topics = load_topics()
    idx.topics = topics
    if not topics:
        idx.ready = False
        return {"topics": 0, "chunks": 0, "cached": False, "ready": False}

    chunks = build_chunks(topics)   # 同时回填 topic.chunk_count
    idx.chunks = chunks
    sig = _signature(topics)
    s = get_settings()
    if not s.embedding_configured:
        return {"topics": len(topics), "chunks": len(chunks), "cached": False, "ready": False}
    if s.vector_backend == "pgvector":
        from . import vector_store
        if not force and vector_store.cached_count(sig) == len(chunks):
            idx.signature = sig
            idx.ready = True
            return {"topics": len(topics), "chunks": len(chunks), "cached": True, "ready": True}

    cached = None if force or s.vector_backend == "pgvector" else _load_cache(sig)
    if cached is not None:
        idx.chunks, idx.matrix = cached[0], _normalize(cached[1])
        idx.ready = True
        return {"topics": len(topics), "chunks": len(idx.chunks), "cached": True, "ready": True}

    # 分批向量化(每批 64 条)
    texts = [f"{c.topic_title} · {c.section}\n{c.text}" for c in chunks]
    vectors: list[list[float]] = []
    for i in range(0, len(texts), 64):
        vectors.extend(await embed_batch(texts[i:i + 64], task_type="RETRIEVAL_DOCUMENT"))
    matrix = np.array(vectors, dtype=np.float32)
    if matrix.shape != (len(chunks), s.embed_dim) or not np.isfinite(matrix).all():
        raise ValueError("Embedding count/dimension mismatch or non-finite vectors")
    if np.any(np.linalg.norm(matrix, axis=1) == 0):
        raise ValueError("Embedding contains a zero vector")
    if s.vector_backend == "pgvector":
        vector_store.save(sig, chunks, vectors)
        idx.signature, idx.ready = sig, True
        return {"topics": len(topics), "chunks": len(chunks), "cached": False, "ready": True}
    _save_cache(sig, chunks, matrix)
    idx.chunks, idx.matrix = chunks, _normalize(matrix)
    idx.ready = True
    return {"topics": len(topics), "chunks": len(idx.chunks), "cached": False, "ready": True}
