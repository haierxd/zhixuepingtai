"""Exact cosine retrieval in PostgreSQL/pgvector; index publication is atomic."""
from __future__ import annotations

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from .config import get_settings


def connect():
    s = get_settings()
    return psycopg.connect(
        host=s.pg_host, port=s.pg_port, dbname=s.pg_database, user=s.pg_user,
        password=s.pg_password, connect_timeout=10,
    )


def initialize():
    with connect() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_indices (
                signature text PRIMARY KEY, model text NOT NULL,
                dimension integer NOT NULL, chunk_count integer NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                signature text NOT NULL REFERENCES knowledge_indices(signature) ON DELETE CASCADE,
                chunk_id integer NOT NULL, course_id text NOT NULL,
                document_id text NOT NULL, version_id text NOT NULL,
                topic_id text NOT NULL, topic_title text NOT NULL,
                section_anchor text NOT NULL, section text NOT NULL, body text NOT NULL,
                embedding vector NOT NULL, PRIMARY KEY (signature, chunk_id)
            )
        """)


def cached_count(signature):
    initialize()
    with connect() as conn:
        row = conn.execute(
            "SELECT chunk_count FROM knowledge_indices WHERE signature=%s", (signature,),
        ).fetchone()
        return row[0] if row is not None else None


def save(signature, chunks, vectors):
    s = get_settings()
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.shape != (len(chunks), s.embed_dim) or not np.isfinite(matrix).all():
        raise ValueError("Embedding count/dimension mismatch or non-finite vectors")
    if np.any(np.linalg.norm(matrix, axis=1) == 0):
        raise ValueError("Embedding contains a zero vector")
    initialize()
    with connect() as conn:
        register_vector(conn)
        conn.execute("DELETE FROM knowledge_indices WHERE signature=%s", (signature,))
        conn.execute(
            "INSERT INTO knowledge_indices(signature,model,dimension,chunk_count) VALUES(%s,%s,%s,%s)",
            (signature, s.embed_model, s.embed_dim, len(chunks)),
        )
        with conn.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO knowledge_chunks
                (signature,chunk_id,course_id,document_id,version_id,topic_id,topic_title,
                 section_anchor,section,body,embedding)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, [
                (signature, i, "default-course", chunk.topic_id, signature,
                 chunk.topic_id, chunk.topic_title, f"section-{i}", chunk.section,
                 chunk.text, vector.tolist())
                for i, (chunk, vector) in enumerate(zip(chunks, matrix))
            ])


def retrieve(signature, query_vector, top_k):
    with connect() as conn:
        register_vector(conn)
        rows = conn.execute("""
            SELECT topic_id,topic_title,section,body,1-(embedding <=> %s::vector) AS score
            FROM knowledge_chunks WHERE signature=%s
            ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s
        """, (query_vector.tolist(), signature, query_vector.tolist(), top_k)).fetchall()
    return [
        {"topic_id": row[0], "topic_title": row[1], "section": row[2],
         "text": row[3], "score": float(row[4])}
        for row in rows
    ]
