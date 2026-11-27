"""seed.py 演示班级。seed 只写学情不写账号，账号要等服务启动时补上，所以先 seed 再启动服务。"""
from __future__ import annotations

from app import store


def test_seed_writes_demo_class_and_startup_adds_accounts(client):
    import seed

    seed.main()
    students = store.list_students()
    assert len(students) == 6
    assert all(not s.get("username") for s in students)

    store.init_db()   # 服务启动时执行的同一步
    by_name = {s["name"]: s for s in store.list_students()}
    assert by_name["林知遥"]["username"] == "demo"
    assert by_name["顾沛宁"]["username"] == "2023210002"
    assert client.post("/api/login", json={"username": "2023210002", "password": "888888"}).status_code == 200
