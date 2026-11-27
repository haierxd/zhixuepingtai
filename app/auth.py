"""Revocable student sessions. A student id is a selector, never a credential."""
import hashlib
import secrets
import time

from fastapi import HTTPException, Request
from sqlalchemy import select

from . import document_db as db, store

COOKIE = "zx_student_session"
LIFETIME = 7 * 24 * 60 * 60


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def issue(sid):
    token = secrets.token_urlsafe(32)
    with db.engine().begin() as conn:
        conn.execute(db.sessions.delete().where(db.sessions.c.expires_at < time.time()))
        conn.execute(db.sessions.insert().values(
            token_hash=digest(token), student_id=sid, expires_at=time.time() + LIFETIME))
    return token


def token_from(request: Request):
    authorization = request.headers.get("Authorization", "")
    if authorization:
        return authorization[7:] if authorization.startswith("Bearer ") else ""
    return request.cookies.get(COOKIE, "")


def student(request: Request):
    token = token_from(request)
    if not token:
        raise HTTPException(401, "请先登录学生端")
    with db.engine().connect() as conn:
        sid = conn.execute(select(db.sessions.c.student_id).where(
            db.sessions.c.token_hash == digest(token), db.sessions.c.expires_at > time.time()
        )).scalar()
    if not sid or not store.student_exists(sid):
        raise HTTPException(401, "登录已失效，请重新登录")
    selector = request.headers.get("X-Student-Id")
    if selector and selector != sid:
        raise HTTPException(403, "不能访问其他学生的数据")
    return sid


def revoke(request: Request):
    with db.engine().begin() as conn:
        conn.execute(db.sessions.delete().where(db.sessions.c.token_hash == digest(token_from(request))))
