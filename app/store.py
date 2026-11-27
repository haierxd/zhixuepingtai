"""学生学情持久化(SQLite,标准库):档案、掌握度、对话历史、测评、学习事件。

掌握度 mastery.score ∈ [0,100]:个性化的核心数据,由测评与对话共同更新。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from .config import get_settings

DEFAULT_STUDENT = "demo-student"
DEFAULT_PASSWORD = "888888"   # 历史/演示学生的默认登录密码


def _now() -> float:
    return time.time()


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ---------- 密码哈希(标准库 PBKDF2,无三方依赖) ----------

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, 120000)
    return f"pbkdf2_sha256$120000${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _public(d: dict) -> dict:
    """去掉敏感字段(密码哈希)后再对外返回。"""
    d = dict(d)
    d.pop("password_hash", None)
    return d


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    s = get_settings()
    if s.database_backend == "mysql":
        from .database import StoreConnection, get_engine, mysql_url
        with get_engine(mysql_url(s)).begin() as conn:
            yield StoreConnection(conn)
        return
    conn = sqlite3.connect(get_settings().db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    if get_settings().database_backend == "mysql":
        from .database import get_engine, metadata, mysql_url
        metadata.create_all(get_engine(mysql_url(get_settings())))
        with _conn() as c:
            _ensure_accounts(c)
        return
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                grade TEXT,
                major TEXT,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS mastery (
                student_id TEXT,
                topic_id TEXT,
                score REAL DEFAULT 0,
                attempts INTEGER DEFAULT 0,
                updated_at REAL,
                PRIMARY KEY (student_id, topic_id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                student_id TEXT,
                role TEXT,
                content TEXT,
                citations TEXT,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS quizzes (
                id TEXT PRIMARY KEY,
                student_id TEXT,
                topic_id TEXT,
                payload TEXT,
                score REAL,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                student_id TEXT,
                kind TEXT,
                detail TEXT,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                student_id TEXT,
                topic_id TEXT,
                topic_title TEXT,
                n INTEGER DEFAULT 5,
                status TEXT DEFAULT 'pending',
                score REAL,
                created_at REAL,
                done_at REAL
            );
            """
        )
        # 幂等迁移:逐列添加(已存在则忽略)
        for tbl, col, decl in [
            ("students", "student_no", "TEXT"),
            ("students", "username", "TEXT"),       # 账号(教师开账号 / 学生登录)
            ("students", "password_hash", "TEXT"),  # 密码哈希
            ("quizzes", "duration", "REAL"),        # 本次测评用时(秒),用于答题快慢/学习状态
        ]:
            try:
                c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
        # 幂等迁移:为历史学生补默认账号,确保账号密码登录可用
        _ensure_accounts(c)


def _ensure_accounts(c) -> None:
        rows = c.execute("SELECT id, student_no, username FROM students").fetchall()
        used = {r["username"] for r in rows if r["username"]}
        default_ph = hash_password(DEFAULT_PASSWORD)
        for r in rows:
            if r["username"]:
                continue
            uname = "demo" if r["id"] == DEFAULT_STUDENT else ((r["student_no"] or "").strip() or f"user{r['id'][-6:]}")
            base, k = uname, 1
            while uname in used:
                uname = f"{base}_{k}"; k += 1
            used.add(uname)
            c.execute("UPDATE students SET username=?, password_hash=? WHERE id=?",
                      (uname, default_ph, r["id"]))


def ensure_student(student_id: str = DEFAULT_STUDENT, name: str = "同学",
                   grade: str = "本科 2023 级", major: str = "人工智能") -> dict:
    with _conn() as c:
        row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if row is None:
            # 默认演示学生:用户名 demo,密码 888888(账号密码登录可直接用)
            uname = "demo" if student_id == DEFAULT_STUDENT else f"user{student_id[-6:]}"
            c.execute(
                "INSERT INTO students(id,name,grade,major,username,password_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                (student_id, name, grade, major, uname, hash_password(DEFAULT_PASSWORD), _now()),
            )
            return {"id": student_id, "name": name, "grade": grade, "major": major, "username": uname}
        return _public(dict(row))


def get_student(student_id: str = DEFAULT_STUDENT) -> dict:
    return ensure_student(student_id)


# ---------- 多学生 ----------

def student_exists(sid: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM students WHERE id=?", (sid,)).fetchone() is not None


def username_exists(username: str) -> bool:
    u = (username or "").strip()
    if not u:
        return False
    with _conn() as c:
        return c.execute("SELECT 1 FROM students WHERE username=?", (u,)).fetchone() is not None


def authenticate(username: str, password: str) -> Optional[dict]:
    """账号密码校验。成功返回学生档案,失败返回 None。"""
    u = (username or "").strip()
    if not u:
        return None
    with _conn() as c:
        row = c.execute("SELECT * FROM students WHERE username=?", (u,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return dict(row)


def set_credentials(sid: str, username: Optional[str] = None, password: Optional[str] = None) -> None:
    sets, vals = [], []
    if username is not None and username.strip():
        sets.append("username=?"); vals.append(username.strip())
    if password:
        sets.append("password_hash=?"); vals.append(hash_password(password))
    if not sets:
        return
    vals.append(sid)
    with _conn() as c:
        c.execute(f"UPDATE students SET {', '.join(sets)} WHERE id=?", (*vals,))


def create_student(name: str, student_no: str = "", grade: str = "本科 2023 级",
                   major: str = "人工智能", username: str = "", password: str = "") -> dict:
    """新建学生账号。username 默认取学号;password 默认 888888。username 需唯一。"""
    sid = _uid("stu")
    uname = (username or student_no or "").strip() or f"user{sid[-6:]}"
    if username_exists(uname):
        raise ValueError(f"账号「{uname}」已存在,请换一个")
    pw = (password or "").strip() or DEFAULT_PASSWORD
    with _conn() as c:
        c.execute(
            "INSERT INTO students(id,name,grade,major,student_no,username,password_hash,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (sid, name.strip() or "同学", grade, major, student_no.strip(), uname, hash_password(pw), _now()),
        )
    return {"id": sid, "name": name, "grade": grade, "major": major,
            "student_no": student_no, "username": uname}


def list_students() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM students ORDER BY created_at ASC").fetchall()
    return [_public(dict(r)) for r in rows]


def update_student(sid: str, **fields) -> bool:
    allowed = {"name", "grade", "major", "student_no", "username"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not sets:
        return False
    cols = ", ".join(f"{k}=?" for k in sets)
    with _conn() as c:
        cur = c.execute(f"UPDATE students SET {cols} WHERE id=?", (*sets.values(), sid))
        return cur.rowcount > 0


def reset_student(sid: str) -> None:
    with _conn() as c:
        for t in ("mastery", "messages", "quizzes", "events"):
            c.execute(f"DELETE FROM {t} WHERE student_id=?", (sid,))


def delete_student(sid: str) -> None:
    reset_student(sid)
    with _conn() as c:
        c.execute("DELETE FROM students WHERE id=?", (sid,))


# ---------- 教师端聚合 ----------

def _student_stats(c: sqlite3.Connection, sid: str) -> dict:
    mrows = c.execute("SELECT score, attempts FROM mastery WHERE student_id=?", (sid,)).fetchall()
    studied = [r for r in mrows if r["attempts"] > 0]
    avg = round(sum(r["score"] for r in studied) / len(studied), 1) if studied else 0.0
    weak = len([r for r in studied if r["score"] < 60])
    q = c.execute("SELECT COUNT(*) n FROM messages WHERE student_id=? AND role='user'", (sid,)).fetchone()["n"]
    qz = c.execute("SELECT COUNT(*) n FROM quizzes WHERE student_id=? AND score IS NOT NULL", (sid,)).fetchone()["n"]
    last = c.execute("SELECT MAX(created_at) m FROM events WHERE student_id=?", (sid,)).fetchone()["m"]
    return {"avg_mastery": avg, "topics_studied": len(studied), "weak_count": weak,
            "questions_asked": q, "quizzes_done": qz, "last_active": last}


def roster_with_stats() -> list[dict]:
    with _conn() as c:
        students = [_public(dict(r)) for r in c.execute("SELECT * FROM students ORDER BY created_at ASC").fetchall()]
        out = [{**s, **_student_stats(c, s["id"])} for s in students]
    out.sort(key=lambda r: (r["last_active"] is None, -(r["last_active"] or 0)))
    return out


def cohort_summary() -> dict:
    cutoff = _now() - 86400
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) n FROM students").fetchone()["n"]
        avg = c.execute("SELECT AVG(score) a FROM mastery WHERE attempts>0").fetchone()["a"]
        active = c.execute("SELECT COUNT(DISTINCT student_id) n FROM events WHERE created_at>=?", (cutoff,)).fetchone()["n"]
        qz = c.execute("SELECT COUNT(*) n FROM quizzes WHERE score IS NOT NULL").fetchone()["n"]
    return {"students": n, "avg_mastery": round(avg, 1) if avg else 0.0, "active_24h": active, "quizzes_done": qz}


def topic_mastery_across() -> dict[str, dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT topic_id, AVG(score) a, COUNT(*) n FROM mastery WHERE attempts>0 GROUP BY topic_id"
        ).fetchall()
    return {r["topic_id"]: {"avg": round(r["a"], 1), "studied": r["n"]} for r in rows}


def struggling_students(limit: int = 6) -> list[dict]:
    cand = [r for r in roster_with_stats()
            if r["topics_studied"] > 0 and (r["avg_mastery"] < 60 or r["weak_count"] >= 2)]
    cand.sort(key=lambda r: (r["avg_mastery"], -r["weak_count"]))
    return cand[:limit]


def recent_activity_all(limit: int = 15) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT e.kind, e.detail, e.created_at, e.student_id, s.name FROM events e "
            "JOIN students s ON e.student_id=s.id ORDER BY e.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"kind": r["kind"], "detail": json.loads(r["detail"]), "created_at": r["created_at"],
             "student": r["name"], "student_id": r["student_id"]} for r in rows]


# ---------- 掌握度 ----------

def get_mastery(student_id: str = DEFAULT_STUDENT) -> dict[str, dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM mastery WHERE student_id=?", (student_id,)).fetchall()
    return {r["topic_id"]: {"score": r["score"], "attempts": r["attempts"]} for r in rows}


def update_mastery(student_id: str, topic_id: str, observed: float, weight: float = 0.5) -> float:
    """用指数滑动平均把一次观测(0-100)并入掌握度,返回新分数。"""
    observed = max(0.0, min(100.0, float(observed)))
    with _conn() as c:
        row = c.execute(
            "SELECT score, attempts FROM mastery WHERE student_id=? AND topic_id=?",
            (student_id, topic_id),
        ).fetchone()
        if row is None:
            new_score = observed
            c.execute(
                "INSERT INTO mastery(student_id,topic_id,score,attempts,updated_at) VALUES(?,?,?,?,?)",
                (student_id, topic_id, new_score, 1, _now()),
            )
        else:
            new_score = (1 - weight) * row["score"] + weight * observed
            c.execute(
                "UPDATE mastery SET score=?, attempts=attempts+1, updated_at=? "
                "WHERE student_id=? AND topic_id=?",
                (new_score, _now(), student_id, topic_id),
            )
    return round(new_score, 1)


# ---------- 对话历史 ----------

def add_message(student_id: str, role: str, content: str,
                citations: Optional[list] = None) -> str:
    mid = _uid("msg")
    with _conn() as c:
        c.execute(
            "INSERT INTO messages(id,student_id,role,content,citations,created_at) VALUES(?,?,?,?,?,?)",
            (mid, student_id, role, content, json.dumps(citations or [], ensure_ascii=False), _now()),
        )
    return mid


def recent_messages(student_id: str, limit: int = 12) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content, citations, created_at FROM messages "
            "WHERE student_id=? ORDER BY created_at DESC, CASE role WHEN 'assistant' THEN 1 ELSE 0 END DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
    out = [
        {"role": r["role"], "content": r["content"],
         "citations": json.loads(r["citations"] or "[]"), "created_at": r["created_at"]}
        for r in rows
    ]
    out.reverse()
    return out


# ---------- 测评 ----------

def save_quiz(student_id: str, topic_id: str, payload: dict,
              score: Optional[float] = None) -> str:
    qid = _uid("quiz")
    with _conn() as c:
        c.execute(
            "INSERT INTO quizzes(id,student_id,topic_id,payload,score,created_at) VALUES(?,?,?,?,?,?)",
            (qid, student_id, topic_id, json.dumps(payload, ensure_ascii=False), score, _now()),
        )
    return qid


def get_quiz(qid: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM quizzes WHERE id=?", (qid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def set_quiz_score(qid: str, score: float, payload: dict, duration: Optional[float] = None) -> None:
    """落分并记录本次测评用时(秒)。duration 为空时回退为 提交时刻-生成时刻。"""
    with _conn() as c:
        if duration is None or duration <= 0:
            row = c.execute("SELECT created_at FROM quizzes WHERE id=?", (qid,)).fetchone()
            if row and row["created_at"]:
                duration = max(0.0, _now() - float(row["created_at"]))
        c.execute(
            "UPDATE quizzes SET score=?, payload=?, duration=? WHERE id=?",
            (score, json.dumps(payload, ensure_ascii=False), duration, qid),
        )


def learning_samples(student_id: str, limit: int = 8) -> list[dict]:
    """最近若干次已评分测评的答题快慢样本,供学习状态评价(state.evaluate)。

    返回 [{sec_per_q, score, n, created_at}],最近在前。无计时的旧测评 sec_per_q 为 None。
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT payload, score, created_at, duration FROM quizzes "
            "WHERE student_id=? AND score IS NOT NULL ORDER BY created_at DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        try:
            n = len(json.loads(r["payload"]).get("questions", []))
        except Exception:
            n = 0
        dur = r["duration"]
        spq = (dur / n) if (dur and n) else None
        out.append({"sec_per_q": spq, "score": r["score"] or 0.0, "n": n, "created_at": r["created_at"]})
    return out


def latest_quiz_state(student_id: str) -> Optional[dict]:
    """最近一次已评分测评里持久化的学习状态(含大模型解释),供学情概览展示。"""
    with _conn() as c:
        row = c.execute(
            "SELECT payload FROM quizzes WHERE student_id=? AND score IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1", (student_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload"]).get("state")
    except Exception:
        return None


# ---------- 事件 / 活动日志 ----------

def log_event(student_id: str, kind: str, detail: dict) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO events(id,student_id,kind,detail,created_at) VALUES(?,?,?,?,?)",
            (_uid("ev"), student_id, kind, json.dumps(detail, ensure_ascii=False), _now()),
        )


def recent_events(student_id: str, limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT kind, detail, created_at FROM events WHERE student_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
    return [{"kind": r["kind"], "detail": json.loads(r["detail"]), "created_at": r["created_at"]} for r in rows]


def counts(student_id: str) -> dict[str, int]:
    with _conn() as c:
        msg = c.execute("SELECT COUNT(*) n FROM messages WHERE student_id=? AND role='user'", (student_id,)).fetchone()["n"]
        qz = c.execute("SELECT COUNT(*) n FROM quizzes WHERE student_id=? AND score IS NOT NULL", (student_id,)).fetchone()["n"]
    return {"questions_asked": msg, "quizzes_done": qz}


# ---------- 测评回顾 / 错题本 ----------

def list_quizzes(student_id: str, limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, topic_id, payload, score, created_at FROM quizzes "
            "WHERE student_id=? AND score IS NOT NULL ORDER BY created_at DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        try:
            p = json.loads(r["payload"])
        except json.JSONDecodeError:
            p = {}
        out.append({"id": r["id"], "topic_id": r["topic_id"], "topic_title": p.get("topic_title", ""),
                    "score": r["score"], "created_at": r["created_at"],
                    "n": len(p.get("questions", []))})
    return out


def mistakes(student_id: str) -> list[dict]:
    """聚合所有已评分测评中的错题,按知识点分组。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT topic_id, payload, created_at FROM quizzes WHERE student_id=? AND score IS NOT NULL ORDER BY created_at DESC",
            (student_id,),
        ).fetchall()
    groups: dict[str, dict] = {}
    for r in rows:
        try:
            p = json.loads(r["payload"])
        except json.JSONDecodeError:
            continue
        results = {x.get("id"): x for x in p.get("results", [])}
        for q in p.get("questions", []):
            res = results.get(q.get("id"))
            if not res:
                continue
            wrong = (res.get("correct") is False) if q.get("type") == "choice" else (res.get("score", 100) < 60)
            if not wrong:
                continue
            g = groups.setdefault(r["topic_id"], {"topic_id": r["topic_id"], "topic_title": p.get("topic_title", ""), "items": []})
            if len(g["items"]) < 6:
                g["items"].append({
                    "stem": q.get("stem", ""), "type": q.get("type"),
                    "your": res.get("your", ""), "answer": q.get("answer", ""),
                    "reference": q.get("reference", ""), "explanation": q.get("explanation", ""),
                    "feedback": res.get("feedback", ""), "score": res.get("score"),
                    "created_at": r["created_at"],
                })
    return list(groups.values())


# ---------- 知识点下钻 / 预警 ----------

def topic_breakdown(topic_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT s.id, s.name, s.student_no, m.score, m.attempts FROM students s "
            "LEFT JOIN mastery m ON m.student_id=s.id AND m.topic_id=? ORDER BY s.created_at ASC",
            (topic_id,),
        ).fetchall()
    out = []
    for r in rows:
        score, att = (r["score"] or 0.0), (r["attempts"] or 0)
        if att == 0:
            st = "new"
        elif score >= 75:
            st = "mastered"
        elif score >= 60:
            st = "learning"
        else:
            st = "weak"
        out.append({"id": r["id"], "name": r["name"], "student_no": r["student_no"],
                    "score": round(score, 1), "attempts": att, "status": st})
    out.sort(key=lambda r: (r["attempts"] == 0, r["score"]))
    return out


def inactive_students(days: float = 3.0) -> list[dict]:
    cutoff = _now() - days * 86400
    with _conn() as c:
        rows = c.execute(
            "SELECT s.id, s.name, MAX(e.created_at) last FROM students s "
            "LEFT JOIN events e ON e.student_id=s.id GROUP BY s.id HAVING last IS NULL OR last < ? ORDER BY last ASC",
            (cutoff,),
        ).fetchall()
    return [{"id": r["id"], "name": r["name"], "last_active": r["last"]} for r in rows]


# ---------- 作业 / 任务 ----------

def create_assignment(student_id: str, topic_id: str, topic_title: str, n: int = 5) -> str:
    aid = _uid("asg")
    with _conn() as c:
        c.execute("INSERT INTO assignments(id,student_id,topic_id,topic_title,n,status,created_at) VALUES(?,?,?,?,?,?,?)",
                  (aid, student_id, topic_id, topic_title, n, "pending", _now()))
    return aid


def assignments_for_student(student_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM assignments WHERE student_id=? ORDER BY status='done', created_at DESC", (student_id,)).fetchall()
    return [dict(r) for r in rows]


def pending_assignments(student_id: str) -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) n FROM assignments WHERE student_id=? AND status='pending'", (student_id,)).fetchone()["n"]


def complete_assignment(student_id: str, topic_id: str, score: float) -> None:
    """把该生该知识点最早的未完成作业标记为已完成。"""
    with _conn() as c:
        row = c.execute("SELECT id FROM assignments WHERE student_id=? AND topic_id=? AND status='pending' ORDER BY created_at ASC LIMIT 1",
                        (student_id, topic_id)).fetchone()
        if row:
            c.execute("UPDATE assignments SET status='done', score=?, done_at=? WHERE id=?", (score, _now(), row["id"]))


def assignments_overview() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT a.*, s.name FROM assignments a JOIN students s ON a.student_id=s.id ORDER BY a.created_at DESC LIMIT 100"
        ).fetchall()
    return [dict(r) for r in rows]
