"""个性化辅导:根据学情 + RAG 上下文组装提示词。

体现题目的"个性化指导":同一问题,对薄弱知识点会多铺垫直觉、放慢节奏;
对已掌握的知识点则深入拓展。
"""
from __future__ import annotations

from .rag import KnowledgeIndex

TUTOR_PERSONA = """你是「智学」的个性化学习导师,服务于人工智能 / 计算机方向的本科生。

教学原则:
1. 个性化:依据下方【学情画像】调整深浅——对薄弱知识点先建立直觉、多举例、放慢;对已掌握的知识点可直接深入或拓展。
2. 启发式:鼓励学生思考,必要时先反问一句引导,再给出讲解,而非直接灌输答案。
3. 准确为先:优先使用【知识库参考】中的内容作答,确保与主流教材一致;参考不足时可基于可靠知识补充,并说明这是补充。
4. 循序渐进:概念—直觉—例子—小结;较长回答可用要点或编号。
5. 收尾给"下一步建议":针对该学生,提示接下来可以学什么、做哪类练习。

语气规范(克制 / 专业 / 有力量感):
- 专业、克制、自信;中文为主,专业术语保留英文(如 gradient descent)。
- 不使用 emoji,不使用感叹号堆叠,不浮夸营销腔。
- 称呼学生用"你"。
"""


def summarize_profile(mastery: dict[str, dict], index: KnowledgeIndex) -> str:
    """把掌握度转成给模型看的学情画像文本。"""
    topics = index.topics
    if not mastery:
        return "该学生暂无历史学情数据(首次使用)。请按入门者对待,适当探查其基础。"

    rows = []
    for tid, m in mastery.items():
        t = topics.get(tid)
        name = t.title if t else tid
        rows.append((name, m["score"], m["attempts"]))
    rows.sort(key=lambda r: r[1])

    weak = [f"{n}({s:.0f}分)" for n, s, _ in rows if s < 60][:5]
    strong = [f"{n}({s:.0f}分)" for n, s, _ in rows if s >= 80][:5]

    lines = ["学生各知识点掌握度(0-100,越低越薄弱):"]
    if weak:
        lines.append("· 薄弱(需重点辅导):" + "、".join(weak))
    if strong:
        lines.append("· 已较好掌握:" + "、".join(strong))
    if not weak and not strong:
        lines.append("· 整体处于中等水平,可正常推进。")
    return "\n".join(lines)


def format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "(本次未检索到高度相关的知识库内容,请基于可靠知识谨慎作答,并提示学生该问题可能超出当前课程范围。)"
    blocks = []
    for i, c in enumerate(chunks, 1):
        blocks.append(f"[参考{i}] 《{c['topic_title']}》— {c['section']}\n{c['text']}")
    return "\n\n".join(blocks)


def build_system_prompt(profile_text: str, context_text: str) -> str:
    return (
        f"{TUTOR_PERSONA}\n\n"
        f"【学情画像】\n{profile_text}\n\n"
        f"【知识库参考】(用于本次回答,请优先采信)\n{context_text}\n\n"
        f"现在请基于以上学情与参考,回答学生的问题。"
    )


def citations_from_chunks(chunks: list[dict], index: KnowledgeIndex) -> list[dict]:
    """按 topic 去重,生成引用列表(供前端展示来源)。"""
    seen: dict[str, dict] = {}
    for c in chunks:
        tid = c["topic_id"]
        key = (f"{c['document_id']}:{c['version_id']}:{c.get('page_number')}:{c.get('section_anchor')}"
               if c.get("document_id") else tid)
        if key not in seen:
            t = index.topics.get(tid)
            seen[key] = {
                "topic_id": tid,
                "title": c["topic_title"],
                "title_en": t.title_en if t else "",
                "sections": [c["section"]],
                "score": round(c["score"], 3),
            }
            if c.get("document_id"):
                seen[key].update({name: c.get(name) for name in (
                    "document_id", "version_id", "course_id", "chunk_id", "page_number", "section_anchor",
                )})
        else:
            if c["section"] not in seen[key]["sections"]:
                seen[key]["sections"].append(c["section"])
    return list(seen.values())


def involved_topics(chunks: list[dict], min_score: float = 0.35) -> list[str]:
    """从检索结果中识别本次对话涉及的、相关度足够的知识点(用于学情更新)。"""
    out: list[str] = []
    for c in chunks:
        if c["score"] >= min_score and c["topic_id"] not in out:
            out.append(c["topic_id"])
    return out
