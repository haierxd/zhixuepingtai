"""测试统一走离线模式：不需要 Gemini 密钥，不访问外网，每个测试用一份新的空库。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from scripts import offline

TEACHER_PASS = "test-teacher-pass"


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    s = offline.enable(tmp_path_factory.mktemp("offline-data"))
    s.teacher_passcode = TEACHER_PASS   # 不依赖本机 .env 里的口令
    return s


@pytest.fixture()
def client(settings, tmp_path):
    settings.db_path = tmp_path / "tutor.db"
    settings.document_dir = tmp_path / "documents"
    from app.main import app
    with TestClient(app) as c:   # 进入时执行启动流程：建表，建默认学生，建知识索引
        assert c.post('/api/login', json={'username': 'demo', 'password': '888888'}).status_code == 200
        yield c


@pytest.fixture()
def teacher() -> dict:
    return {"X-Teacher-Pass": TEACHER_PASS}


def sse_events(resp) -> list[dict]:
    """把 /api/chat 的 SSE 响应拆成事件列表。"""
    return [json.loads(line[len("data: "):]) for line in resp.text.splitlines() if line.startswith("data: ")]
