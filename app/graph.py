"""知识图谱:前置依赖 DAG、层级、状态与个性化学习路径。

数据来源:app/knowledge_graph.json(由多智能体从知识库正文抽取的关系/概念/分类)。
- 用"规范教学顺序"把前置边裁成有向无环图(只保留 早→晚 的边),避免环。
- 层级 = 从根节点起的最长路径,用于前端分列布局。
- 状态由掌握度推导;推荐 = 前置已就绪且自身薄弱/未学的知识点。
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Optional

from .config import BASE_DIR
from .rag import get_index

GRAPH_FILE = BASE_DIR / "knowledge_graph.json"

# 规范教学顺序(仅用于裁环:仅保留 顺序靠前 -> 靠后 的前置边)
CANON_ORDER = [
    "ai-ml-overview", "supervised-unsupervised", "linear-regression",
    "logistic-classification", "loss-gradient-descent", "model-evaluation",
    "overfitting-regularization", "bias-variance-cv", "neural-networks",
    "backpropagation", "embeddings", "cnn", "rnn-lstm",
    "attention-transformer", "llm-pretrain-finetune-rag", "reinforcement-learning",
]
CATEGORY_ORDER = ["基础概念", "模型与优化", "评估与泛化", "神经网络", "序列与大模型"]


@lru_cache(maxsize=1)
def _raw() -> dict[str, dict]:
    if not GRAPH_FILE.exists():
        return {}
    try:
        data = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    nodes = data.get("nodes", data if isinstance(data, list) else [])
    return {n["id"]: n for n in nodes if "id" in n}


def reload() -> None:
    _raw.cache_clear()


def _order(tid: str) -> int:
    return CANON_ORDER.index(tid) if tid in CANON_ORDER else 999


def _acyclic_prereqs(raw: dict[str, dict]) -> dict[str, list[str]]:
    """裁成 DAG:仅保留 前置顺序 < 自身 的边,去重去自环去无效 id。"""
    valid = set(raw.keys())
    out: dict[str, list[str]] = {}
    for tid, rec in raw.items():
        kept = []
        for p in rec.get("prereqs", []):
            if p in valid and p != tid and _order(p) < _order(tid) and p not in kept:
                kept.append(p)
        out[tid] = kept
    return out


def _levels(prereqs: dict[str, list[str]]) -> dict[str, int]:
    """最长路径层级(根=0)。"""
    memo: dict[str, int] = {}

    def depth(n: str, seen: frozenset) -> int:
        if n in memo:
            return memo[n]
        ps = [p for p in prereqs.get(n, []) if p not in seen]
        d = 0 if not ps else 1 + max(depth(p, seen | {n}) for p in ps)
        memo[n] = d
        return d

    return {n: depth(n, frozenset()) for n in prereqs}


def _status(mastery: dict[str, dict], tid: str, prereqs: list[str]) -> tuple[str, float, int]:
    m = mastery.get(tid, {"score": 0, "attempts": 0})
    score, attempts = m["score"], m["attempts"]
    if attempts > 0:
        if score >= 75:
            st = "mastered"
        elif score >= 60:
            st = "learning"
        else:
            st = "weak"
    else:
        ready = all(mastery.get(p, {"score": 0})["score"] >= 60 for p in prereqs)
        st = "available" if ready else "locked"
    return st, round(score, 1), attempts


def build_payload(mastery: dict[str, dict]) -> dict:
    raw = _raw()
    idx = get_index()
    topics = idx.topics
    prereqs = _acyclic_prereqs(raw)
    levels = _levels(prereqs) if prereqs else {t: 0 for t in topics}

    # 反向边:每个节点的后继(它是谁的前置)
    leads_to: dict[str, list[str]] = {t: [] for t in topics}
    for tid, ps in prereqs.items():
        for p in ps:
            leads_to.setdefault(p, []).append(tid)

    nodes = []
    edges = []
    for tid in topics:
        t = topics[tid]
        rec = raw.get(tid, {})
        st, score, attempts = _status(mastery, tid, prereqs.get(tid, []))
        nodes.append({
            "id": tid,
            "title": t.title,
            "title_en": t.title_en,
            "difficulty": t.difficulty,
            "category": rec.get("category", "基础概念"),
            "summary": rec.get("summary", ""),
            "core_concepts": rec.get("core_concepts", []),
            "level": levels.get(tid, 0),
            "mastery": score,
            "attempts": attempts,
            "status": st,
            "prereqs": prereqs.get(tid, []),
        })
        for p in prereqs.get(tid, []):
            edges.append({"source": p, "target": tid})

    recommendation = recommend(mastery, nodes, prereqs)
    max_level = max((n["level"] for n in nodes), default=0)
    return {
        "nodes": nodes,
        "edges": edges,
        "max_level": max_level,
        "categories": [c for c in CATEGORY_ORDER if any(n["category"] == c for n in nodes)],
        "recommendation": recommendation,
    }


def recommend(mastery: dict[str, dict], nodes: list[dict], prereqs: dict[str, list[str]], k: int = 5) -> list[dict]:
    """推荐学习路径:前置就绪且自身薄弱/未学,薄弱优先,再按层级与难度。"""
    by_id = {n["id"]: n for n in nodes}
    diff_rank = {"入门": 0, "核心": 1, "进阶": 2}

    def ready(tid: str) -> bool:
        return all(by_id.get(p, {}).get("mastery", 0) >= 60 for p in prereqs.get(tid, []))

    cands = []
    for n in nodes:
        if n["status"] in ("weak", "available") and ready(n["id"]):
            # 优先级:薄弱(已学但分低)优先复习,其次新知识
            tier = 0 if n["status"] == "weak" else 1
            cands.append((tier, n["level"], diff_rank.get(n["difficulty"], 1), n))
    cands.sort(key=lambda x: (x[0], x[1], x[2]))
    out = []
    for tier, lvl, _, n in cands[:k]:
        reason = "薄弱,建议复习巩固" if tier == 0 else (
            "前置已就绪,可以开始学习" if n["prereqs"] else "适合作为起点"
        )
        out.append({"id": n["id"], "title": n["title"], "reason": reason, "status": n["status"]})
    return out


def topic_detail(tid: str, mastery: dict[str, dict]) -> Optional[dict]:
    idx = get_index()
    t = idx.topics.get(tid)
    if not t:
        return None
    raw = _raw()
    prereqs = _acyclic_prereqs(raw)
    rec = raw.get(tid, {})
    # 反向:后继
    succ = [x for x, ps in prereqs.items() if tid in ps]
    # 大纲:正文中的 ## 标题
    outline = []
    for line in t.body.splitlines():
        s = line.strip()
        if s.startswith("## "):
            outline.append(s[3:].strip())
    st, score, attempts = _status(mastery, tid, prereqs.get(tid, []))

    def brief(ids):
        return [{"id": i, "title": idx.topics[i].title} for i in ids if i in idx.topics]

    return {
        "id": tid, "title": t.title, "title_en": t.title_en, "difficulty": t.difficulty,
        "category": rec.get("category", "基础概念"), "summary": rec.get("summary", ""),
        "core_concepts": rec.get("core_concepts", []), "outline": outline,
        "mastery": score, "attempts": attempts, "status": st,
        "prereqs": brief(prereqs.get(tid, [])),
        "leads_to": brief(succ),
        "related": brief([r for r in rec.get("related", []) if r in idx.topics and r != tid]),
    }


def _strip_h1(body: str) -> str:
    """去掉正文开头的一级标题(阅读页页眉已展示标题,避免重复)。"""
    lines = body.splitlines()
    if lines and lines[0].lstrip().startswith("# ") and not lines[0].lstrip().startswith("## "):
        return "\n".join(lines[1:]).lstrip("\n")
    return body


def topic_content(tid: str, mastery: dict[str, dict]) -> Optional[dict]:
    """课程正文(电子书阅读页):完整 Markdown 正文 + 小节目录 + 上一课/下一课。"""
    idx = get_index()
    t = idx.topics.get(tid)
    if not t:
        return None
    raw = _raw()
    prereqs = _acyclic_prereqs(raw)
    rec = raw.get(tid, {})
    st, score, attempts = _status(mastery, tid, prereqs.get(tid, []))
    # 目录:正文中的 ## 二级标题
    sections = [s.strip()[3:].strip() for s in t.body.splitlines() if s.strip().startswith("## ")]
    # 上一课 / 下一课:按规范教学顺序,过滤到实际存在的知识点
    order = [x for x in CANON_ORDER if x in idx.topics]

    def nbr(i: int) -> Optional[dict]:
        return {"id": order[i], "title": idx.topics[order[i]].title} if 0 <= i < len(order) else None

    pos = order.index(tid) if tid in order else -1
    return {
        "id": tid, "title": t.title, "title_en": t.title_en,
        "difficulty": t.difficulty, "category": rec.get("category", "基础概念"),
        "summary": rec.get("summary", ""),
        "mastery": score, "attempts": attempts, "status": st,
        "sections": sections, "body": _strip_h1(t.body),
        "prev": nbr(pos - 1) if pos >= 0 else None,
        "next": nbr(pos + 1) if pos >= 0 else None,
    }
