"""知识库与知识图谱的数据检查：改了 app/knowledge 或 knowledge_graph.json 之后先跑这里。"""
from __future__ import annotations

from app import graph, rag
from app.config import KNOWLEDGE_DIR, get_settings


def test_every_knowledge_file_has_frontmatter():
    files = sorted(KNOWLEDGE_DIR.glob("*.md"))
    assert files
    for p in files:
        meta, body = rag._parse_frontmatter(p.read_text(encoding="utf-8"))
        assert meta.get("id") == p.stem, p.name
        assert meta.get("title"), p.name
        assert meta.get("difficulty") in ("入门", "核心", "进阶"), p.name
        assert body.strip(), p.name


def test_topics_teaching_order_and_graph_cover_the_same_ids():
    topics = rag.load_topics()
    assert set(topics) == set(graph.CANON_ORDER)
    assert set(graph._raw()) == set(topics)


def test_graph_categories_are_known():
    for tid, node in graph._raw().items():
        assert node.get("category") in graph.CATEGORY_ORDER, tid


def test_chunks_respect_size_limit():
    chunks = rag.build_chunks(rag.load_topics())
    assert chunks
    assert all(len(c.text) <= get_settings().chunk_max_chars for c in chunks)


def test_prerequisites_follow_teaching_order_and_levels():
    prereqs = graph._acyclic_prereqs(graph._raw())
    levels = graph._levels(prereqs)
    for tid, ps in prereqs.items():
        for p in ps:
            assert graph.CANON_ORDER.index(p) < graph.CANON_ORDER.index(tid)
            assert levels[p] < levels[tid]
