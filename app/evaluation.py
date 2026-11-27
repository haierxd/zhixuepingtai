"""智能测评(题目中的"评价"):个性化出题 + 自动评分 + 学情反馈。

- 出题:以知识点正文为依据,按学生在该知识点的掌握度自适应难度。
- 评分:选择/判断题确定性判分;简答题由模型评分并给反馈。
- 评分后回写掌握度,实现"评价驱动个性化"的闭环。
"""
from __future__ import annotations

import copy
from typing import Optional

from .gemini import generate_json
from .rag import KnowledgeIndex

QUIZ_SYSTEM = """你是人工智能课程的出题老师,为本科生命题。要求:题目准确、有区分度、紧扣给定知识点正文;
中文命题,术语保留英文;不出超纲题;选择题四个选项且只有一个正确;简答题给出"参考答案要点"。只输出 JSON。"""

GRADE_SYSTEM = """你是严格而友善的助教,为学生的简答作答评分。依据"参考答案要点"按点给分,
0-100 分;指出答对的点与缺失/错误的点,语气克制专业,中文。只输出 JSON。"""


def _difficulty_hint(mastery_score: Optional[float]) -> str:
    if mastery_score is None or mastery_score < 40:
        return "该生此知识点较薄弱,请以基础概念题为主,降低难度,侧重直觉与定义。"
    if mastery_score < 75:
        return "该生此知识点中等,请出中等难度题,兼顾概念理解与简单应用。"
    return "该生此知识点掌握较好,请适当提高难度,加入综合应用或易错点辨析。"


async def generate_quiz(index: KnowledgeIndex, topic_id: str,
                        mastery_score: Optional[float], n: int = 5) -> dict:
    topic = index.topics.get(topic_id)
    if not topic:
        raise ValueError(f"未知知识点: {topic_id}")
    n_choice = max(2, n - 2)
    n_short = n - n_choice
    prompt = f"""知识点:《{topic.title}》({topic.title_en})

【知识点正文,命题须以此为依据】
{topic.body[:6000]}

【难度要求】
{_difficulty_hint(mastery_score)}

请命制 {n} 道题:其中 {n_choice} 道单选题(choice),{n_short} 道简答题(short)。
严格输出如下 JSON(不要加解释、不要 markdown 代码围栏):
{{
  "questions": [
    {{"id": "q1", "type": "choice", "stem": "题干", "options": ["A. ...","B. ...","C. ...","D. ..."], "answer": "B", "explanation": "为什么选它、其它选项错在哪"}},
    {{"id": "q2", "type": "short", "stem": "题干", "reference": "参考答案要点(分点)", "explanation": "评分关注点"}}
  ]
}}
注意:answer 必须是 options 中正确项的字母(A/B/C/D)。题目 id 用 q1..q{n}。"""
    data = await generate_json(prompt, QUIZ_SYSTEM, temperature=0.7)
    questions = data.get("questions", [])
    # 规范化
    for i, q in enumerate(questions, 1):
        q.setdefault("id", f"q{i}")
        q["type"] = "choice" if q.get("type") == "choice" else ("short" if q.get("type") == "short" else ("choice" if q.get("options") else "short"))
    full = {"topic_id": topic_id, "topic_title": topic.title, "questions": questions}
    return full


def public_quiz(full: dict) -> dict:
    """剥离答案/参考,返回给前端作答的版本。"""
    pub = copy.deepcopy(full)
    for q in pub["questions"]:
        q.pop("answer", None)
        q.pop("reference", None)
        q.pop("explanation", None)
    return pub


async def grade_quiz(full: dict, answers: dict[str, str]) -> dict:
    """answers: {question_id: 学生作答}。返回逐题结果 + 总分 + 反馈。"""
    questions = full["questions"]
    results: list[dict] = []

    # 简答题集中送模型评分
    short_qs = [q for q in questions if q.get("type") == "short"]
    short_grades: dict[str, dict] = {}
    if short_qs:
        items = []
        for q in short_qs:
            items.append({
                "id": q["id"],
                "stem": q["stem"],
                "reference": q.get("reference", ""),
                "student_answer": (answers.get(q["id"], "") or "(未作答)"),
            })
        prompt = (
            "请为以下简答题作答评分,每题 0-100 分,并给出 feedback(指出答对与缺失的要点)。\n"
            "只输出 JSON:{\"grades\":[{\"id\":\"q2\",\"score\":80,\"feedback\":\"...\"}]}\n\n"
            f"题目与作答:\n{_json(items)}"
        )
        graded = await generate_json(prompt, GRADE_SYSTEM, temperature=0.2)
        for g in graded.get("grades", []):
            short_grades[g.get("id")] = {"score": float(g.get("score", 0)), "feedback": g.get("feedback", "")}

    total = 0.0
    for q in questions:
        qid = q["id"]
        stu = (answers.get(qid, "") or "").strip()
        if q.get("type") == "choice":
            correct = (q.get("answer", "") or "").strip().upper()
            picked = stu.strip().upper()
            # 容忍学生提交 "B" 或 "B. xxx" 或整条选项文本
            picked_letter = picked[0] if picked and picked[0] in "ABCD" else ""
            is_ok = picked_letter == correct
            score = 100.0 if is_ok else 0.0
            results.append({
                "id": qid, "type": "choice", "correct": is_ok,
                "your": stu, "answer": correct, "score": score,
                "explanation": q.get("explanation", ""),
            })
        else:
            g = short_grades.get(qid, {"score": 0.0, "feedback": "未能评分。"})
            results.append({
                "id": qid, "type": "short", "score": g["score"],
                "your": stu, "reference": q.get("reference", ""),
                "feedback": g["feedback"], "explanation": q.get("explanation", ""),
            })
        total += results[-1]["score"]

    overall = round(total / len(questions), 1) if questions else 0.0
    return {
        "topic_id": full["topic_id"],
        "topic_title": full.get("topic_title", ""),
        "overall": overall,
        "results": results,
    }


async def feedback_summary(topic_title: str, overall: float, results: list[dict]) -> str:
    """生成一段面向该学生的个性化评语与下一步建议。"""
    brief = []
    for r in results:
        ok = r.get("correct")
        tag = "✓" if (ok is True or (r.get("score", 0) >= 60 and r.get("type") == "short")) else "✗"
        brief.append(f"{tag} {r['id']}({r.get('score')}分)")
    prompt = (
        f"学生刚完成《{topic_title}》测评,总分 {overall}。逐题表现:{' '.join(brief)}。\n"
        "请用 3-4 句话给出个性化评语:先肯定,再点出最该补的薄弱处,最后给一条具体的下一步学习建议。"
        "中文,克制专业,不用 emoji。只输出评语文本(不要 JSON)。"
    )
    from .gemini import generate_json as _gj  # 复用通道但要纯文本,这里改用简单封装
    # 直接复用 stream 不便,这里用 generate_json 让其返回 {"text": "..."}
    data = await _gj(prompt + '\n以 JSON 返回:{"text":"评语"}', GRADE_SYSTEM, temperature=0.5)
    return data.get("text", "")


STATE_SYSTEM = """你是学习状态分析助手。依据学生本次测评的"逐题用时与对错",从答题快慢、是否在某些题卡顿、
是否敷衍/认真等角度,客观分析其当下学习状态。语气克制专业,中文,不用 emoji。只输出 JSON。"""


async def analyze_state(topic_title: str, overall: float, per_question: list[dict],
                        pace_hint: str = "") -> str:
    """基于逐题用时 + 对错,让模型给出一段简短的学习状态解释概括(60 字内)。"""
    lines = []
    for q in per_question:
        kind = "选择" if q.get("type") == "choice" else "简答"
        c = q.get("correct")
        verdict = "答对" if c is True else ("答错" if c is False else f"{q.get('score', '-')}分")
        t = q.get("time_sec")
        ts = f"{t:.0f}秒" if isinstance(t, (int, float)) and t else "用时未知"
        lines.append(f"第{q.get('idx')}题({kind},{ts},{verdict})")
    detail = ";".join(lines) or "无逐题数据"
    prompt = (
        f"学生刚完成《{topic_title}》测评,总分 {overall}。逐题用时与对错:{detail}。"
        f"{('整体节奏:' + pace_hint) if pace_hint else ''}\n"
        "请据此用一段话(60 字内)简短概括其本次学习状态:指出答题偏快/偏慢/平稳、是否在某些题卡顿或可能敷衍,"
        '并给一句中肯提醒。以 JSON 返回:{"summary":"..."}'
    )
    data = await generate_json(prompt, STATE_SYSTEM, temperature=0.4)
    return (data.get("summary") or "").strip()


def _json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)
