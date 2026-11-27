"""已知缺口：测试写的是应有的行为，现有代码还做不到，所以标成预期失败。

修好其中一项后，对应测试会意外通过，strict 模式把它报成失败，这时删掉那个测试上的 @gap 标记。
缺口的来龙去脉见 docs/接手指南.md 的待办一节。
"""
from __future__ import annotations

import pytest

gap = pytest.mark.xfail(strict=True, reason="已知缺口，见 docs/接手指南.md 待办")


def test_unanswered_choice_question_is_graded_as_wrong(client):
    # 空字符串是任何字符串的子串，evaluation.grade_quiz 判选项字母时会越界，接口返回 500
    quiz = client.post("/api/quiz/generate", json={"topic_id": "cnn", "n": 3},
                       headers={"X-Student-Id": "demo-student"}).json()
    r = client.post("/api/quiz/grade", json={"quiz_id": quiz["quiz_id"], "answers": {}})
    assert r.status_code == 200
    assert all(x["correct"] is False for x in r.json()["results"] if x["type"] == "choice")


def test_reindex_requires_teacher(client):
    assert client.post("/api/reindex").status_code in (401, 403)


def test_student_roster_requires_teacher(client):
    assert client.get("/api/students").status_code in (401, 403)


def test_anonymous_request_gets_no_student_data(client):
    client.cookies.clear()
    assert client.get("/api/profile").status_code == 401


def test_quiz_can_only_be_submitted_by_its_owner(client, teacher):
    owner = client.post("/api/teacher/students", json={"name": "甲", "student_no": "2099000101"}, headers=teacher).json()
    other = client.post("/api/teacher/students", json={"name": "乙", "student_no": "2099000102"}, headers=teacher).json()
    assert client.post('/api/login', json={'username': owner['username'], 'password': '888888'}).status_code == 200
    quiz = client.post("/api/quiz/generate", json={"topic_id": "cnn", "n": 3},
                       headers={"X-Student-Id": owner["id"]}).json()
    answers = {q["id"]: "B" for q in quiz["quiz"]["questions"]}
    assert client.post('/api/login', json={'username': other['username'], 'password': '888888'}).status_code == 200
    r = client.post("/api/quiz/grade", json={"quiz_id": quiz["quiz_id"], "answers": answers},
                    headers={"X-Student-Id": other["id"]})
    assert r.status_code in (403, 404)
