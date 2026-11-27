"""学生端接口：登录，知识图谱，阅读页，对话，测评闭环，学习报告。"""
from __future__ import annotations

from app import store

from .conftest import sse_events

STU = {"X-Student-Id": store.DEFAULT_STUDENT}


def test_health_shows_offline_index(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["configured"] and h["index_ready"]
    assert h["topics"] == 16 and h["chunks"] > 0
    assert h["model"] == "offline-fake"


def test_default_student_login(client):
    r = client.post("/api/login", json={"username": "demo", "password": "888888"})
    assert r.status_code == 200
    assert r.json()["id"] == store.DEFAULT_STUDENT
    assert client.post("/api/login", json={"username": "demo", "password": "wrong"}).status_code == 401


def test_graph_detail_and_reader(client):
    g = client.get("/api/graph", headers=STU).json()
    assert len(g["nodes"]) == 16
    assert g["recommendation"]
    detail = client.get("/api/topic/cnn", headers=STU).json()
    assert detail["outline"] and detail["prereqs"]
    content = client.get("/api/topic/backpropagation/content", headers=STU).json()
    assert content["sections"] and not content["body"].startswith("# ")
    assert content["prev"]["id"] == "neural-networks"
    assert content["next"]["id"] == "embeddings"
    assert client.get("/api/topic/no-such-topic", headers=STU).status_code == 404


def test_chat_streams_and_saves_history(client):
    r = client.post("/api/chat", json={"message": "反向传播和梯度下降有什么区别?"}, headers=STU)
    assert r.status_code == 200
    events = sse_events(r)
    assert events[0]["type"] == "meta" and events[0]["citations"]
    assert any(e["type"] == "delta" for e in events)
    assert events[-1]["type"] == "done"
    roles = [m["role"] for m in client.get("/api/history", headers=STU).json()["messages"]]
    assert roles[-2:] == ["user", "assistant"]


def test_quiz_generate_grade_review_and_mistakes(client):
    r = client.post("/api/quiz/generate", json={"topic_id": "cnn", "n": 5}, headers=STU)
    assert r.status_code == 200
    quiz_id, quiz = r.json()["quiz_id"], r.json()["quiz"]
    assert len(quiz["questions"]) == 5
    assert all("answer" not in q and "reference" not in q for q in quiz["questions"])

    answers = {q["id"]: ("A" if q["type"] == "choice" else "参数共享，局部感受野") for q in quiz["questions"]}
    graded = client.post("/api/quiz/grade", json={"quiz_id": quiz_id, "answers": answers,
                                                  "elapsed_sec": 200}).json()
    assert all(not x["correct"] for x in graded["results"] if x["type"] == "choice")
    assert graded["new_mastery"] == graded["overall"]   # 第一次观测直接取得分
    assert len(graded["state"]["per_question"]) == 5

    review = client.get(f"/api/quiz/{quiz_id}/review", headers=STU).json()
    assert review["score"] == graded["overall"]
    groups = client.get("/api/mistakes", headers=STU).json()["groups"]
    assert groups[0]["topic_id"] == "cnn"
    profile = client.get("/api/profile", headers=STU).json()
    assert profile["summary"]["quizzes_done"] == 1


def test_unsubmitted_quiz_review_does_not_reveal_answers(client):
    quiz = client.post('/api/quiz/generate', json={'topic_id': 'cnn', 'n': 3}).json()
    review = client.get(f"/api/quiz/{quiz['quiz_id']}/review")
    assert review.status_code == 200
    data = review.json()
    assert data['score'] is None and data['results'] == []
    for question in data['questions']:
        assert not {'answer', 'reference', 'explanation', 'rubric'} & question.keys()


def test_learning_report(client):
    report = client.get("/api/report", headers=STU).json()
    assert report["summary"] and report["suggestions"]
