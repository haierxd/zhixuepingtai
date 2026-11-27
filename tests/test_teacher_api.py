"""教师端接口：口令校验，开账号，改删学生，布置作业，导出名册。"""
from __future__ import annotations

from app import store
import pytest


def _create(client, teacher, **body) -> dict:
    r = client.post("/api/teacher/students", json={"name": "测试学生", **body}, headers=teacher)
    assert r.status_code == 200, r.text
    return r.json()


def _login(client, sid):
    username = store.get_student(sid)['username']
    assert client.post('/api/login', json={'username': username, 'password': '888888'}).status_code == 200


def test_teacher_routes_require_passcode(client, teacher):
    assert client.get("/api/teacher/overview").status_code == 401
    assert client.get("/api/teacher/overview", headers=teacher).status_code == 200
    assert client.post("/api/teacher/login", json={"passcode": "wrong"}).status_code == 401


def test_new_account_defaults_to_student_no_and_888888(client, teacher):
    stu = _create(client, teacher, student_no="2099000001")
    assert stu["username"] == "2099000001"
    assert client.post("/api/login", json={"username": "2099000001", "password": "888888"}).status_code == 200
    dup = client.post("/api/teacher/students", json={"name": "重号", "student_no": "2099000001"}, headers=teacher)
    assert dup.status_code == 400


def test_update_password_reset_and_delete(client, teacher):
    stu = _create(client, teacher, student_no="2099000002", password="first-pass")
    r = client.patch(f"/api/teacher/student/{stu['id']}", json={"major": "计算机", "password": "second-pass"},
                     headers=teacher)
    assert r.json()["major"] == "计算机"
    assert client.post("/api/login", json={"username": "2099000002", "password": "second-pass"}).status_code == 200

    store.update_mastery(stu["id"], "cnn", observed=70)
    assert client.post(f"/api/teacher/student/{stu['id']}/reset", headers=teacher).status_code == 200
    assert store.get_mastery(stu["id"]) == {}

    assert client.delete(f"/api/teacher/student/{stu['id']}", headers=teacher).status_code == 200
    assert not store.student_exists(stu["id"])
    assert client.delete(f"/api/teacher/student/{store.DEFAULT_STUDENT}", headers=teacher).status_code == 400


def test_assignment_is_completed_by_matching_quiz(client, teacher):
    stu = _create(client, teacher, student_no="2099000003")
    _login(client, stu['id'])
    me = {"X-Student-Id": stu["id"]}
    r = client.post("/api/teacher/assignments", json={"topic_id": "cnn", "student_ids": [stu["id"]]}, headers=teacher)
    assert r.json()["assigned"] == 1
    assert client.get("/api/assignments", headers=me).json()["pending"] == 1

    quiz = client.post("/api/quiz/generate", json={"topic_id": "cnn", "n": 3}, headers=me).json()
    answers = {q["id"]: ("B" if q["type"] == "choice" else "参数共享") for q in quiz["quiz"]["questions"]}
    assert client.post("/api/quiz/grade", json={"quiz_id": quiz["quiz_id"], "answers": answers}).status_code == 200
    mine = client.get("/api/assignments", headers=me).json()
    assert mine["pending"] == 0 and mine["assignments"][0]["status"] == "done"


@pytest.mark.parametrize("count", [1, 2])
def test_assignment_only_reaches_selected_students(client, teacher, count):
    students = [_create(client, teacher, student_no=f"20990001{i:02d}") for i in range(3)]
    selected = [s["id"] for s in students[:count]]
    r = client.post("/api/teacher/assignments",
                    json={"topic_id": "cnn", "n": 6, "student_ids": selected}, headers=teacher)
    assert r.status_code == 200
    assert r.json()["assigned"] == count
    for s in [*students, {"id": store.DEFAULT_STUDENT}]:
        _login(client, s['id'])
        mine = client.get("/api/assignments", headers={"X-Student-Id": s["id"]}).json()
        assert mine["pending"] == (1 if s["id"] in selected else 0)


def test_empty_assignment_selection_is_rejected_without_assigning_anyone(client, teacher):
    stu = _create(client, teacher, student_no="2099000201")
    r = client.post("/api/teacher/assignments",
                    json={"topic_id": "cnn", "student_ids": []}, headers=teacher)
    assert r.status_code == 400
    assert r.json()["detail"] == "请至少选择一名学生"
    for sid in (stu["id"], store.DEFAULT_STUDENT):
        _login(client, sid)
        assert client.get("/api/assignments", headers={"X-Student-Id": sid}).json()["pending"] == 0


def test_assignment_without_selection_still_reaches_whole_class(client, teacher):
    stu = _create(client, teacher, student_no="2099000202")
    r = client.post("/api/teacher/assignments", json={"topic_id": "cnn"}, headers=teacher)
    assert r.status_code == 200
    assert r.json()["assigned"] == 2
    for sid in (stu["id"], store.DEFAULT_STUDENT):
        _login(client, sid)
        assert client.get("/api/assignments", headers={"X-Student-Id": sid}).json()["pending"] == 1


def test_overview_insight_and_csv_export(client, teacher):
    store.update_mastery(store.DEFAULT_STUDENT, "cnn", observed=40)
    overview = client.get("/api/teacher/overview", headers=teacher).json()
    assert overview["summary"]["students"] == 1
    assert client.get("/api/teacher/insight", headers=teacher).json()["text"]
    csv = client.get("/api/teacher/export.csv", headers=teacher)
    assert csv.text.startswith("﻿姓名,学号")
