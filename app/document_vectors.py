"""Immutable document version vectors; active IDs are selected from MySQL."""
import numpy as np
from pgvector.psycopg import register_vector
from .vector_store import connect


def initialize(conn):
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute("""CREATE TABLE IF NOT EXISTS document_vectors (
        signature text NOT NULL, version_id text NOT NULL, chunk_id integer NOT NULL,
        course_id text NOT NULL, document_id text NOT NULL, topic_id text NOT NULL,
        topic_title text NOT NULL, page_number integer, section_anchor text,
        section text NOT NULL, body text NOT NULL, embedding vector NOT NULL,
        PRIMARY KEY(signature, version_id, chunk_id)
    )""")


def save(signature, rows, vectors):
    with connect() as conn:
        initialize(conn)
        register_vector(conn)
        conn.execute("DELETE FROM document_vectors WHERE signature=%s AND version_id=%s",
                     (signature, rows[0]["version_id"]))
        with conn.cursor() as cursor:
            cursor.executemany("""INSERT INTO document_vectors
                (signature,version_id,chunk_id,course_id,document_id,topic_id,topic_title,
                 page_number,section_anchor,section,body,embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [
                (signature, row["version_id"], row["chunk_id"], row["course_id"], row["document_id"],
                 row["topic_id"], row["topic_title"], row["page_number"], row["section_anchor"],
                 row["section"], row["text"], np.asarray(vec, dtype=np.float32))
                for row, vec in zip(rows, vectors)
            ])


def search(signature, version_ids, vector, top_k):
    with connect() as conn:
        register_vector(conn)
        rows = conn.execute("""SELECT version_id,chunk_id,course_id,document_id,topic_id,topic_title,
            page_number,section_anchor,section,body,1-(embedding <=> %s::vector)
            FROM document_vectors WHERE signature=%s AND version_id=ANY(%s)
            ORDER BY embedding <=> %s::vector,version_id,chunk_id LIMIT %s""",
            (vector, signature, version_ids, vector, top_k)).fetchall()
    keys = ("version_id", "chunk_id", "course_id", "document_id", "topic_id", "topic_title",
            "page_number", "section_anchor", "section", "text", "score")
    return [dict(zip(keys, row)) for row in rows]
