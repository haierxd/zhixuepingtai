"""离线模式：用本地假模型替换 Gemini，不需要密钥，也不访问外网。

供本地开发与自动测试使用，app 目录下的代码不做任何改动。
- 向量：按字符二元组散列成固定维度的向量，检索结果和真实模型不同，但流程完整。
- 对话：固定模板回答，带上检索到的参考小节。
- 出题，评分，评语，学习报告：固定模板的 JSON。
- 数据放在 app/data/offline/，与真实模式的 app/data/ 分开，互不覆盖。

用法，在仓库根目录执行：
    .venv/bin/python -m scripts.offline            启动服务，浏览器打开 http://127.0.0.1:8000
    .venv/bin/python -m scripts.offline --seed     先写入演示班级再启动
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import AsyncIterator, Optional

from app.config import DATA_DIR, Settings, get_settings

# 对话逐段输出的间隔秒数，启动服务时设为 0.02 让界面看得出流式效果，测试时为 0
STREAM_DELAY = 0.0


# ---------------- 假向量 ----------------

def _vector(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    t = re.sub(r"\s+", "", text.lower())
    grams = [t[i:i + 2] for i in range(len(t) - 1)] or [t]
    for g in grams:
        h = int.from_bytes(hashlib.md5(g.encode("utf-8")).digest()[:4], "little")
        vec[h % dim] += 1.0
    return vec


async def embed_batch(texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    dim = get_settings().embed_dim
    return [_vector(t, dim) for t in texts]


async def embed_one(text: str, *, task_type: str = "RETRIEVAL_QUERY") -> list[float]:
    return (await embed_batch([text], task_type=task_type))[0]


# ---------------- 假对话 ----------------

async def stream_chat(messages: list[dict], system: str, *, temperature: float = 0.6,
                      thinking_budget: Optional[int] = 0) -> AsyncIterator[str]:
    question = messages[-1]["content"] if messages else ""
    refs = re.findall(r"\[参考\d+\] 《(.+?)》— (.+)", system)
    parts = ["离线模式：这是假模型的固定回答，只用来走通对话流程。", f"收到的问题：{question}"]
    if refs:
        parts.append("检索到的参考小节：" + "，".join(f"《{t}》{s}" for t, s in refs[:3]))
    if "资料学习辅导 Agent" in system:
        excerpt = system.split("[参考1]", 1)[-1].split("\n", 1)[-1]
        parts.append("当前选区原文：\n" + excerpt[:1500])
    text = "\n\n".join(parts)
    for i in range(0, len(text), 12):
        if STREAM_DELAY:
            await asyncio.sleep(STREAM_DELAY)
        yield text[i:i + 12]


# ---------------- 假结构化输出 ----------------

def _quiz(prompt: str, n: int, n_choice: int, n_short: int) -> dict:
    m = re.search(r"知识点:《(.+?)》", prompt)
    title = m.group(1) if m else "该知识点"
    questions = []
    for i in range(1, n + 1):
        if i <= n_choice:
            questions.append({
                "id": f"q{i}", "type": "choice",
                "stem": f"离线示例题 {i}：关于《{title}》，下列说法正确的是？",
                "options": ["A. 常见的错误理解", "B. 正确的表述", "C. 混淆的概念", "D. 以偏概全的说法"],
                "answer": "B", "explanation": "离线示例：B 是正确表述，其余选项是常见误区。",
            })
        else:
            questions.append({
                "id": f"q{i}", "type": "short",
                "stem": f"离线示例题 {i}：简述《{title}》的核心思想。",
                "reference": "离线示例要点：定义，关键机制，典型应用。",
                "explanation": "离线示例：按要点给分。",
            })
    return {"questions": questions}


def _grades(prompt: str) -> dict:
    items = json.loads(prompt.split("题目与作答:\n", 1)[1])
    grades = []
    for it in items:
        ans = (it.get("student_answer") or "").strip()
        score = 0 if ans in ("", "(未作答)") else min(100, 40 + 2 * len(ans))
        grades.append({"id": it["id"], "score": score, "feedback": "离线模式：按作答长度给的示例分数。"})
    return {"grades": grades}


async def generate_json(prompt: str, system: str, *, temperature: float = 0.4,
                        thinking_budget: Optional[int] = None) -> dict:
    if "资料诊断 Agent" in system:
        payload = json.loads(prompt.split("题目与作答：\n", 1)[1].split("\nJSON:", 1)[0])
        q = payload["question"]
        return {"diagnosis": q.get("misconceptions", {}).get(payload["student_answer"], ""),
                "evidence": q.get("evidence", "")}
    if "资料出题 Agent" in system:
        title = prompt.split("资料标题：", 1)[-1].split("\n", 1)[0]
        excerpt = prompt.split("资料正文：\n", 1)[-1].split("\n只命制", 1)[0]
        sentence = next((s.strip() for s in excerpt.splitlines() if s.strip() and not s.startswith("#")), excerpt[:120])[:180]
        retry = "复练知识点：" in prompt
        return {"question": {
            "stem": ("离线复练：重新核对原文，哪一项表述有资料支持？" if retry else "离线自测：以下哪项与当前资料原文一致？"),
            "options": ["A. 只要训练集表现好，就证明泛化能力好。" if "训练" in excerpt else "A. 资料中的结论在任何条件下都无条件成立。",
                        "B. " + sentence, "C. 不需要结合原文中的条件。", "D. 不同概念可以直接混用。"],
            "answer": "B", "explanation": "离线演示题：B 摘自当前原文，请结合上下文核对。",
            "concept": title, "evidence": sentence,
            "misconceptions": {"A": "把训练集表现等同于泛化能力，忽略了验证数据的作用。" if "训练" in excerpt else "忽略了资料结论的适用条件。",
                                "C": "忽略了原文的上下文条件。", "D": "将不同概念混为一谈。"},
        }}
    m = re.search(r"请命制 (\d+) 道题:其中 (\d+) 道单选题\(choice\),(\d+) 道简答题\(short\)", prompt)
    if m:
        return _quiz(prompt, int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if "请为以下简答题作答评分" in prompt:
        return _grades(prompt)
    if '"highlights"' in prompt:
        return {"summary": "离线模式：示例学习报告。", "highlights": ["示例亮点"],
                "weak": ["示例薄弱点"], "suggestions": ["示例建议一", "示例建议二"]}
    if '{"summary":"..."}' in prompt:
        return {"summary": "离线模式：示例学习状态概括。"}
    return {"text": "离线模式：示例文字。"}


# ---------------- 启用 ----------------

def enable(data_dir: Optional[Path] = None) -> Settings:
    """把 Gemini 调用全部换成本地假模型，数据目录换到 data_dir。须在服务启动之前调用。"""
    from app import evaluation, gemini, main, rag

    s = get_settings()
    s.database_backend = "sqlite"
    s.vector_backend = "json"
    s.chat_provider = "gemini"
    s.embed_provider = "gemini"
    s.gemini_api_key = "offline"          # 让 configured 为真，接口不再返回 503
    s.chat_model = "offline-fake"         # /api/health 显示这个名字，一眼可知是离线模式
    s.embed_model = "offline-fake-embedding"  # 向量缓存签名随之不同，不会被真实模式误用
    d = Path(data_dir) if data_dir else DATA_DIR / "offline"
    d.mkdir(parents=True, exist_ok=True)
    s.db_path = d / "tutor.db"
    s.index_path = d / "kb_index.json"
    s.document_dir = d / "documents"

    for mod in (gemini, rag, main, evaluation):
        for name, fake in (("stream_chat", stream_chat), ("generate_json", generate_json),
                           ("embed_batch", embed_batch), ("embed_one", embed_one)):
            if hasattr(mod, name):
                setattr(mod, name, fake)
    return s


def main() -> None:
    global STREAM_DELAY
    ap = argparse.ArgumentParser(description="离线模式启动智学，不需要 Gemini 密钥")
    ap.add_argument("--seed", action="store_true", help="启动前写入演示班级，会清空离线库里的全部数据")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    s = enable()
    STREAM_DELAY = 0.02
    if args.seed:
        import seed
        seed.main()

    import uvicorn
    from app.main import app
    print(f"[offline] 离线模式，数据目录 {s.db_path.parent}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
