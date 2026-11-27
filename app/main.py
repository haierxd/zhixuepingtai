"""智学 — FastAPI 入口:多学生学习端 + 教师管理端 + 静态前端。"""
from __future__ import annotations

import csv
import io
import json
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, emotion, evaluation, graph, state, store, tutor
from .config import WEB_DIR, get_settings
from .gemini import GeminiError, generate_json, stream_chat
from .rag import build_index, get_index

@asynccontextmanager
async def lifespan(app):
    await _startup()
    yield


app = FastAPI(title="智学 · 个性化学习指导与评价", version="1.2.0", lifespan=lifespan)


# --------- 请求模型 ---------
class ChatReq(BaseModel):
    message: str
    topic_id: Optional[str] = None


class QuizGenReq(BaseModel):
    topic_id: str
    n: int = 5


class QuizGradeReq(BaseModel):
    quiz_id: str
    answers: dict[str, str]
    elapsed_sec: Optional[float] = None              # 本次作答总用时(秒)
    question_times: Optional[dict[str, float]] = None  # 逐题用时(秒):{question_id: seconds}


class StudentCreateReq(BaseModel):
    name: str
    student_no: Optional[str] = ""
    grade: Optional[str] = "本科 2023 级"
    major: Optional[str] = "人工智能"
    username: Optional[str] = ""           # 账号(教师开账号);留空则取学号
    password: Optional[str] = ""           # 密码;留空则默认 888888


class StudentUpdateReq(BaseModel):
    name: Optional[str] = None
    student_no: Optional[str] = None
    grade: Optional[str] = None
    major: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None         # 非空则重置密码


class StudentLoginReq(BaseModel):
    username: str
    password: str


class TeacherLoginReq(BaseModel):
    passcode: str


class AssignReq(BaseModel):
    topic_id: str
    student_ids: Optional[list[str]] = None   # None 表示全班，指定学生时必须非空
    n: int = 5


# --------- 身份解析(轻量) ---------
def _teacher_ok(passcode: Optional[str]) -> bool:
    return bool(passcode) and passcode == get_settings().teacher_passcode


def current_student(
    request: Request,
    x_student_id: Optional[str] = Header(None),
    x_teacher_pass: Optional[str] = Header(None),
    student_id: Optional[str] = Query(None),
) -> str:
    """学生须持登录会话；教师持口令可指定 student_id 只读查看学情。"""
    if _teacher_ok(x_teacher_pass) and student_id and store.student_exists(student_id):
        return student_id
    if _teacher_ok(x_teacher_pass):
        return store.DEFAULT_STUDENT
    return auth.student(request)


def require_teacher(x_teacher_pass: Optional[str] = Header(None)) -> None:
    if not _teacher_ok(x_teacher_pass):
        raise HTTPException(401, "教师口令无效")


def student_state(sid: str) -> dict:
    """学习状态评价:答题快慢(主)+ 正确率 + 表情识别(预留)。

    state/label/metrics 取自近期测评的启发式聚合;summary 取最近一次测评的大模型解释(若有)。
    """
    st = state.evaluate(store.learning_samples(sid), emotion.latest(sid))
    latest = store.latest_quiz_state(sid)
    if latest and latest.get("summary"):
        st["summary"] = latest["summary"]
    return st


async def _startup() -> None:
    store.init_db()
    store.ensure_student()
    from .document_db import initialize
    initialize()
    s = get_settings()
    try:
        info = await build_index()
        print(f"[startup] 知识资料状态: {info}")
    except Exception as exc:
        print(f"[startup] 向量索引未就绪: {type(exc).__name__}")
    if not s.configured:
        print("[startup] 未配置聊天模型密钥，可查看已有资料和学习记录。")


# ========== 通用 ==========
@app.get("/api/health")
async def health() -> dict:
    idx = get_index()
    return {
        "ok": True,
        "configured": get_settings().configured,
        "index_ready": idx.ready,
        "topics": len(idx.topics),
        "chunks": len(idx.chunks),
        "model": get_settings().chat_model,
        "database": get_settings().database_backend,
        "vector_backend": get_settings().vector_backend,
        "embedding_configured": get_settings().embedding_configured,
        "embedding_model": get_settings().embed_model,
    }


# ========== 学生身份(账号密码登录) ==========
@app.post("/api/login")
async def student_login(req: StudentLoginReq, response: Response, request: Request) -> dict:
    """学生用账号密码登录。账号由教师在管理端开通。"""
    stu = store.authenticate(req.username, req.password)
    if not stu:
        raise HTTPException(401, "账号或密码错误")
    token = auth.issue(stu["id"])
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", max_age=auth.LIFETIME,
                        secure=request.url.scheme == "https")
    return {"token": token, "id": stu["id"], "name": stu["name"], "username": stu.get("username", ""),
            "grade": stu.get("grade", ""), "major": stu.get("major", ""),
            "student_no": stu.get("student_no", "")}


@app.get("/api/students")
async def students_list(_: None = Depends(require_teacher)) -> dict:
    return {"students": store.list_students()}


# ========== 学习状态(答题快慢 + 表情识别预留) ==========
@app.get("/api/state")
async def my_state(sid: str = Depends(current_student)) -> dict:
    return student_state(sid)


# ========== 表情识别(预留模块) ==========
@app.get("/api/emotion/status")
async def emotion_status() -> dict:
    return emotion.status()


@app.post("/api/emotion/frame")
async def emotion_frame(payload: dict | None = None, sid: str = Depends(auth.student)) -> dict:
    """预留接口:接收一帧并返回情绪结果。当前为占位,恒返回未启用。"""
    return emotion.analyze_frame(sid, (payload or {}).get("frame"))


# ========== 学情 / 知识点(按当前学生) ==========
@app.get("/api/topics")
async def topics(sid: str = Depends(current_student)) -> dict:
    idx = get_index()
    mastery = store.get_mastery(sid)
    items = []
    for t in idx.topic_list():
        m = mastery.get(t["id"], {"score": 0, "attempts": 0})
        items.append({**t, "mastery": round(m["score"], 1), "attempts": m["attempts"]})
    return {"topics": items}


@app.get("/api/graph")
async def knowledge_graph(sid: str = Depends(current_student)) -> dict:
    return graph.build_payload(store.get_mastery(sid))


@app.get("/api/path")
async def learning_path(sid: str = Depends(current_student)) -> dict:
    return {"recommendation": graph.build_payload(store.get_mastery(sid))["recommendation"]}


@app.get("/api/topic/{topic_id}")
async def topic_detail(topic_id: str, sid: str = Depends(current_student)) -> dict:
    detail = graph.topic_detail(topic_id, store.get_mastery(sid))
    if not detail:
        raise HTTPException(404, "未知知识点")
    return detail


@app.get("/api/topic/{topic_id}/content")
async def topic_content(topic_id: str, sid: str = Depends(current_student)) -> dict:
    detail = graph.topic_content(topic_id, store.get_mastery(sid))
    if not detail:
        raise HTTPException(404, "未知知识点")
    return detail


@app.get("/api/profile")
async def profile(sid: str = Depends(current_student)) -> dict:
    idx = get_index()
    student = store.get_student(sid)
    mastery = store.get_mastery(sid)
    cnt = store.counts(sid)
    topic_rows = []
    studied = [m["score"] for m in mastery.values()]
    for t in idx.topic_list():
        m = mastery.get(t["id"], {"score": 0, "attempts": 0})
        topic_rows.append({
            "id": t["id"], "title": t["title"], "difficulty": t["difficulty"],
            "mastery": round(m["score"], 1), "attempts": m["attempts"],
        })
    avg = round(sum(studied) / len(studied), 1) if studied else 0.0
    weak = sorted([r for r in topic_rows if r["attempts"] > 0 and r["mastery"] < 60],
                  key=lambda r: r["mastery"])[:5]
    return {
        "student": student,
        "summary": {
            "avg_mastery": avg,
            "topics_total": len(topic_rows),
            "topics_studied": len([m for m in mastery.values() if m["attempts"] > 0]),
            "questions_asked": cnt["questions_asked"],
            "quizzes_done": cnt["quizzes_done"],
        },
        "weak_topics": weak,
        "topics": topic_rows,
        "events": store.recent_events(sid, 12),
        "state": student_state(sid),
    }


@app.get("/api/history")
async def history(sid: str = Depends(current_student)) -> dict:
    return {"messages": store.recent_messages(sid, 40)}


# ========== 个性化对话(SSE 流式) ==========
@app.post("/api/chat")
async def chat(req: ChatReq, sid: str = Depends(auth.student)):
    if not get_settings().configured:
        raise HTTPException(503, "未配置 GEMINI_API_KEY")
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(400, "消息为空")
    idx = get_index()

    query = msg
    if req.topic_id and req.topic_id in idx.topics:
        query = f"{idx.topics[req.topic_id].title} {msg}"
    chunks = await idx.retrieve(query) if idx.ready else []

    profile_text = tutor.summarize_profile(store.get_mastery(sid), idx)
    context_text = tutor.format_context(chunks)
    system = tutor.build_system_prompt(profile_text, context_text)
    citations = tutor.citations_from_chunks(chunks, idx)

    history_msgs = store.recent_messages(sid, 10)
    store.add_message(sid, "user", msg)
    convo = [{"role": m["role"], "content": m["content"]} for m in history_msgs]
    convo.append({"role": "user", "content": msg})

    async def gen():
        yield f"data: {json.dumps({'type': 'meta', 'citations': citations}, ensure_ascii=False)}\n\n"
        full = []
        try:
            async for delta in stream_chat(convo, system):
                full.append(delta)
                yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
        except GeminiError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
            return
        answer = "".join(full)
        store.add_message(sid, "assistant", answer, citations)
        for tid in tutor.involved_topics(chunks):
            store.update_mastery(sid, tid, observed=58, weight=0.12)
        if chunks:
            store.log_event(sid, "chat", {"q": msg[:40], "topics": [c["title"] for c in citations]})
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ========== 智能测评 ==========
@app.post("/api/quiz/generate")
async def quiz_generate(req: QuizGenReq, sid: str = Depends(auth.student)) -> dict:
    if not get_settings().configured:
        raise HTTPException(503, "未配置 GEMINI_API_KEY")
    idx = get_index()
    if req.topic_id not in idx.topics:
        raise HTTPException(404, "未知知识点")
    mastery = store.get_mastery(sid).get(req.topic_id, {}).get("score")
    try:
        full = await evaluation.generate_quiz(idx, req.topic_id, mastery, n=max(3, min(8, req.n)))
    except (GeminiError, ValueError) as exc:
        raise HTTPException(502, f"出题失败: {exc}")
    qid = store.save_quiz(sid, req.topic_id, full, score=None)
    store.log_event(sid, "quiz_start", {"topic": full["topic_title"]})
    return {"quiz_id": qid, "quiz": evaluation.public_quiz(full)}


@app.post("/api/quiz/grade")
async def quiz_grade(req: QuizGradeReq, sid: str = Depends(auth.student)) -> dict:
    rec = store.get_quiz(req.quiz_id)
    if not rec or rec["student_id"] != sid:
        raise HTTPException(404, "测评不存在")
    full = rec["payload"]
    try:
        graded = await evaluation.grade_quiz(full, req.answers)
        evalu = await evaluation.feedback_summary(graded["topic_title"], graded["overall"], graded["results"])
    except GeminiError as exc:
        raise HTTPException(502, f"评分失败: {exc}")
    graded["feedback"] = evalu
    sid = rec["student_id"]
    new_mastery = store.update_mastery(sid, graded["topic_id"], observed=graded["overall"], weight=0.5)
    graded["new_mastery"] = new_mastery

    # ----- 本次测评的学习状态评价(逐题用时 + 对错 → 启发式判定 + 大模型简短解释) -----
    qtimes = req.question_times or {}
    per_q = []
    for i, r in enumerate(graded["results"], 1):
        correct = r.get("correct") if r.get("type") == "choice" else (r.get("score", 0) >= 60)
        per_q.append({"id": r["id"], "idx": i, "type": r.get("type"),
                      "time_sec": round(float(qtimes.get(r["id"], 0) or 0), 1),
                      "correct": correct, "score": r.get("score")})
    nq = len(graded["results"]) or 1
    total_time = req.elapsed_sec or (sum(p["time_sec"] for p in per_q) or None)
    spq = (total_time / nq) if total_time else None
    quiz_state = state.evaluate([{"sec_per_q": spq, "score": graded["overall"], "n": nq}])
    try:
        summary = await evaluation.analyze_state(graded["topic_title"], graded["overall"], per_q,
                                                 pace_hint=quiz_state.get("reason", ""))
    except GeminiError:
        summary = ""
    quiz_state["summary"] = summary or quiz_state.get("reason", "")
    quiz_state["per_question"] = per_q
    graded["state"] = quiz_state

    # 持久化逐题结果 + 本次学习状态(供"测评回顾/错题本"复盘)
    full["results"] = graded["results"]
    full["overall"] = graded["overall"]
    full["feedback"] = evalu
    full["state"] = quiz_state
    full["question_times"] = {p["id"]: p["time_sec"] for p in per_q}
    store.set_quiz_score(req.quiz_id, graded["overall"], full, duration=req.elapsed_sec)
    store.log_event(sid, "quiz_done", {"topic": graded["topic_title"], "score": graded["overall"], "quiz_id": req.quiz_id})
    store.complete_assignment(sid, graded["topic_id"], graded["overall"])  # 若有对应作业则标记完成
    return graded


@app.post("/api/reindex")
async def reindex(_: None = Depends(require_teacher)) -> dict:
    return await build_index(force=True)


# ========== 测评回顾 / 错题本 / 学习报告 / 作业(学生) ==========
@app.get("/api/quizzes")
async def my_quizzes(sid: str = Depends(current_student)) -> dict:
    return {"quizzes": store.list_quizzes(sid)}


@app.get("/api/quiz/{quiz_id}/review")
async def quiz_review(quiz_id: str, sid: str = Depends(current_student)) -> dict:
    rec = store.get_quiz(quiz_id)
    if not rec or rec["student_id"] != sid:
        raise HTTPException(404, "测评不存在")
    p = rec["payload"]
    if rec["score"] is None:
        return {"topic_id": rec["topic_id"], "topic_title": p.get("topic_title", ""),
                "score": None, "questions": evaluation.public_quiz(p).get("questions", []),
                "results": [], "state": None, "question_times": {}}
    return {"topic_id": rec["topic_id"], "topic_title": p.get("topic_title", ""),
            "score": rec["score"], "questions": p.get("questions", []), "results": p.get("results", []),
            "state": p.get("state"), "question_times": p.get("question_times", {})}


@app.get("/api/mistakes")
async def my_mistakes(sid: str = Depends(current_student)) -> dict:
    return {"groups": store.mistakes(sid)}


@app.get("/api/assignments")
async def my_assignments(sid: str = Depends(current_student)) -> dict:
    return {"assignments": store.assignments_for_student(sid), "pending": store.pending_assignments(sid)}


@app.get("/api/report")
async def learning_report(sid: str = Depends(current_student)) -> dict:
    if not get_settings().configured:
        raise HTTPException(503, "未配置 GEMINI_API_KEY")
    idx = get_index()
    mastery = store.get_mastery(sid)
    student = store.get_student(sid)
    profile_text = tutor.summarize_profile(mastery, idx)
    cnt = store.counts(sid)
    quizzes = store.list_quizzes(sid, 10)
    qz_text = "、".join(f"{q['topic_title']}{q['score']:.0f}分" for q in quizzes[:6]) or "暂无测评"
    prompt = (f"学生{student['name']}的学情:\n{profile_text}\n累计提问{cnt['questions_asked']}次,完成测评{cnt['quizzes_done']}次,"
              f"近期测评:{qz_text}。\n请生成一份个性化阶段学习报告。以 JSON 返回:"
              '{"summary":"2-3句总体评述","highlights":["亮点1","亮点2"],"weak":["薄弱1","薄弱2"],"suggestions":["下一步建议1","建议2","建议3"]}。中文,克制专业,不用 emoji。')
    try:
        data = await generate_json(prompt, "你是学习分析助手,基于学情生成简洁、可执行的个性化学习报告。只输出 JSON。", temperature=0.5)
    except GeminiError as exc:
        raise HTTPException(502, f"生成失败: {exc}")
    return data


# ========== 教师管理端 ==========
@app.post("/api/teacher/login")
async def teacher_login(req: TeacherLoginReq) -> dict:
    if not _teacher_ok(req.passcode):
        raise HTTPException(401, "口令无效")
    return {"ok": True}


@app.get("/api/teacher/overview")
async def teacher_overview(_: None = Depends(require_teacher)) -> dict:
    idx = get_index()
    across = store.topic_mastery_across()
    topics = []
    for t in idx.topic_list():
        d = across.get(t["id"])
        topics.append({"id": t["id"], "title": t["title"], "difficulty": t["difficulty"],
                       "avg": d["avg"] if d else 0.0, "studied": d["studied"] if d else 0})
    topics.sort(key=lambda r: (r["studied"] == 0, r["avg"]))
    # 全班学习状态:每生计算一次,复用于分布统计 / 状态列表 / 待关注标注
    roster = store.list_students()
    state_by_id = {s["id"]: student_state(s["id"]) for s in roster}
    name_by_id = {s["id"]: s["name"] for s in roster}
    state_counts = {"good": 0, "normal": 0, "poor": 0, "unknown": 0}
    for st in state_by_id.values():
        state_counts[st["state"]] = state_counts.get(st["state"], 0) + 1
    _rank = {"poor": 0, "normal": 1, "good": 2, "unknown": 3}
    states = sorted(
        [{"id": sid, "name": name_by_id[sid], "state": st["state"], "label": st["label"],
          "summary": st.get("summary") or st.get("reason", ""), "metrics": st.get("metrics", {})}
         for sid, st in state_by_id.items()],
        key=lambda x: (_rank.get(x["state"], 9), -(x["metrics"].get("samples", 0))),
    )
    struggling = store.struggling_students()
    for s in struggling:
        st = state_by_id.get(s["id"]) or student_state(s["id"])
        s["state"] = {"state": st["state"], "label": st["label"]}
    return {
        "summary": store.cohort_summary(),
        "topics": topics,
        "struggling": struggling,
        "activity": store.recent_activity_all(12),
        "inactive": store.inactive_students(3),
        "state_counts": state_counts,
        "states": states,
    }


@app.get("/api/teacher/topic/{topic_id}")
async def teacher_topic(topic_id: str, _: None = Depends(require_teacher)) -> dict:
    idx = get_index()
    t = idx.topics.get(topic_id)
    if not t:
        raise HTTPException(404, "未知知识点")
    rows = store.topic_breakdown(topic_id)
    studied = [r for r in rows if r["attempts"] > 0]
    avg = round(sum(r["score"] for r in studied) / len(studied), 1) if studied else 0.0
    return {
        "id": topic_id, "title": t.title, "title_en": t.title_en, "difficulty": t.difficulty,
        "avg": avg, "studied": len(studied),
        "mastered": len([r for r in studied if r["status"] == "mastered"]),
        "weak": len([r for r in studied if r["status"] == "weak"]),
        "students": rows,
    }


@app.get("/api/teacher/student/{sid}/diagnose")
async def teacher_diagnose(sid: str, _: None = Depends(require_teacher)) -> dict:
    if not store.student_exists(sid):
        raise HTTPException(404, "学生不存在")
    if not get_settings().configured:
        raise HTTPException(503, "未配置 GEMINI_API_KEY")
    idx = get_index()
    student = store.get_student(sid)
    profile_text = tutor.summarize_profile(store.get_mastery(sid), idx)
    prompt = (f"学生{student['name']}的学情画像:\n{profile_text}\n"
              "请作为助教给出针对该生的一对一诊断与辅导建议(160字内):指出其薄弱链路与可能卡点,"
              "并给出 2-3 条具体的辅导/练习建议。中文,克制专业,不用 emoji。以 JSON 返回:{\"text\":\"诊断\"}")
    try:
        data = await generate_json(prompt, "你是经验丰富的助教,针对单个学生学情给出可操作的辅导诊断。只输出 JSON。", temperature=0.5)
    except GeminiError as exc:
        raise HTTPException(502, f"生成失败: {exc}")
    return {"text": data.get("text", "")}


@app.post("/api/teacher/assignments")
async def teacher_assign(req: AssignReq, _: None = Depends(require_teacher)) -> dict:
    if req.student_ids == []:
        raise HTTPException(400, "请至少选择一名学生")
    idx = get_index()
    if req.topic_id not in idx.topics:
        raise HTTPException(404, "未知知识点")
    title = idx.topics[req.topic_id].title
    targets = req.student_ids if req.student_ids is not None else [s["id"] for s in store.list_students()]
    n = 0
    for sid in targets:
        if store.student_exists(sid):
            store.create_assignment(sid, req.topic_id, title, max(3, min(8, req.n)))
            n += 1
    return {"assigned": n, "topic": title}


@app.get("/api/teacher/assignments")
async def teacher_assignments(_: None = Depends(require_teacher)) -> dict:
    return {"assignments": store.assignments_overview()}


@app.get("/api/teacher/export.csv")
async def teacher_export(_: None = Depends(require_teacher)) -> Response:
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM,兼容 Excel
    w = csv.writer(buf)
    w.writerow(["姓名", "学号", "专业", "年级", "平均掌握度", "已学知识点", "薄弱数", "累计提问", "完成测评", "最近活跃"])
    import time as _t
    for s in store.roster_with_stats():
        last = ""
        if s.get("last_active"):
            last = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(s["last_active"]))
        w.writerow([s.get("name", ""), s.get("student_no", ""), s.get("major", ""), s.get("grade", ""),
                    s.get("avg_mastery", 0), s.get("topics_studied", 0), s.get("weak_count", 0),
                    s.get("questions_asked", 0), s.get("quizzes_done", 0), last])
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=class_roster.csv"})


@app.get("/api/teacher/students")
async def teacher_students(_: None = Depends(require_teacher)) -> dict:
    roster = store.roster_with_stats()
    for s in roster:
        st = student_state(s["id"])
        s["state"] = {"state": st["state"], "label": st["label"], "reason": st["reason"]}
    return {"students": roster}


@app.post("/api/teacher/students")
async def teacher_create(req: StudentCreateReq, _: None = Depends(require_teacher)) -> dict:
    if not (req.name or "").strip():
        raise HTTPException(400, "姓名不能为空")
    try:
        return store.create_student(req.name, req.student_no or "", req.grade or "本科 2023 级",
                                    req.major or "人工智能", username=req.username or "",
                                    password=req.password or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.patch("/api/teacher/student/{sid}")
async def teacher_update(sid: str, req: StudentUpdateReq, _: None = Depends(require_teacher)) -> dict:
    if not store.student_exists(sid):
        raise HTTPException(404, "学生不存在")
    # 账号唯一性校验(改了用户名且与他人冲突时拒绝)
    if req.username and req.username.strip():
        cur = store.get_student(sid)
        if req.username.strip() != (cur.get("username") or "") and store.username_exists(req.username):
            raise HTTPException(400, f"账号「{req.username.strip()}」已存在")
    store.update_student(sid, name=req.name, student_no=req.student_no, grade=req.grade,
                         major=req.major, username=req.username)
    if req.password:
        store.set_credentials(sid, password=req.password)
    return store.get_student(sid)


@app.delete("/api/teacher/student/{sid}")
async def teacher_delete(sid: str, _: None = Depends(require_teacher)) -> dict:
    if sid == store.DEFAULT_STUDENT:
        raise HTTPException(400, "默认演示学生不可删除")
    from .learning import reset_student_data
    reset_student_data(sid)
    store.delete_student(sid)
    return {"ok": True}


@app.post("/api/teacher/student/{sid}/reset")
async def teacher_reset(sid: str, _: None = Depends(require_teacher)) -> dict:
    if not store.student_exists(sid):
        raise HTTPException(404, "学生不存在")
    store.reset_student(sid)
    from .learning import reset_student_data
    reset_student_data(sid, remove_materials=False)
    return {"ok": True}


@app.get("/api/teacher/insight")
async def teacher_insight(_: None = Depends(require_teacher)) -> dict:
    idx = get_index()
    across = store.topic_mastery_across()
    rows = sorted(
        [(d["avg"], idx.topics[tid].title, d["studied"]) for tid, d in across.items() if tid in idx.topics]
    )
    if not rows:
        return {"text": "暂无足够学情数据。待学生开始学习与测评后,这里会给出针对全班薄弱点的教学建议。"}
    weakest = rows[:5]
    summary = "、".join(f"{title}(均分{avg}, {n}人已学)" for avg, title, n in weakest)
    prompt = (f"以下是一个班级在各知识点上的平均掌握度(满分100),从弱到强:{summary}。"
              "请作为助教给出一段简洁的教学建议(150字内):点出全班最该集中讲解/复习的 2-3 个知识点,"
              "以及具体教学侧重与练习建议。中文,克制专业,不用 emoji。以 JSON 返回:{\"text\":\"建议\"}")
    try:
        data = await generate_json(prompt, "你是经验丰富的助教,基于班级学情给出可操作的教学建议。只输出 JSON。", temperature=0.5)
    except GeminiError as exc:
        raise HTTPException(502, f"生成失败: {exc}")
    return {"text": data.get("text", "")}


# ========== 静态前端 ==========
from .document_routes import router as document_router
app.include_router(document_router)
from .learning import router as learning_router
app.include_router(learning_router)


@app.get("/api/session")
def session(sid: str = Depends(auth.student)):
    return store.get_student(sid)


@app.post("/api/logout")
def logout(request: Request, response: Response):
    auth.revoke(request)
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.get("/student/")
@app.get("/teacher/")
def workspace_entry():
    from .config import PROJECT_DIR
    return FileResponse(PROJECT_DIR / "frontend" / "dist" / "index.html", headers={"Cache-Control": "no-cache"})

app.mount("/legacy", StaticFiles(directory=str(WEB_DIR), html=True), name="legacy")
from .config import PROJECT_DIR
frontend_dist = PROJECT_DIR / "frontend" / "dist"
app.mount("/", StaticFiles(directory=str(frontend_dist if frontend_dist.is_dir() else WEB_DIR), html=True), name="web")
