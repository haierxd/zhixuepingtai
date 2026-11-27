"""学情模型：掌握度滑动平均，知识点状态阈值，学习状态判定。改这些规则会直接改变画像与推荐。"""
from __future__ import annotations

import pytest

from app import graph, state, store


def test_mastery_first_observation_then_moving_average(client):
    sid = store.DEFAULT_STUDENT
    assert store.update_mastery(sid, "cnn", observed=80, weight=0.5) == 80.0
    assert store.update_mastery(sid, "cnn", observed=40, weight=0.5) == 60.0
    assert store.update_mastery(sid, "cnn", observed=100, weight=0.12) == 64.8
    assert store.get_mastery(sid)["cnn"]["attempts"] == 3


def test_mastery_observation_is_clamped(client):
    assert store.update_mastery(store.DEFAULT_STUDENT, "cnn", observed=150) == 100.0


@pytest.mark.parametrize("score,attempts,prereq_scores,expected", [
    (75, 1, [], "mastered"),
    (74.9, 1, [], "learning"),
    (60, 2, [], "learning"),
    (59.9, 1, [], "weak"),
    (0, 0, [], "available"),
    (0, 0, [60, 90], "available"),
    (0, 0, [59, 90], "locked"),
])
def test_topic_status_thresholds(score, attempts, prereq_scores, expected):
    mastery = {"t": {"score": score, "attempts": attempts}}
    prereqs = []
    for i, ps in enumerate(prereq_scores):
        mastery[f"p{i}"] = {"score": ps, "attempts": 1}
        prereqs.append(f"p{i}")
    assert graph._status(mastery, "t", prereqs)[0] == expected


def test_learning_state_needs_timed_quizzes():
    assert state.evaluate([])["state"] == "unknown"


def test_learning_state_good_for_steady_pace_and_high_score():
    st = state.evaluate([{"sec_per_q": 40, "score": 85}] * 3)
    assert st["state"] == "good" and not st["alert"]


def test_learning_state_poor_for_rushing_with_low_score():
    st = state.evaluate([{"sec_per_q": 10, "score": 40}] * 3)
    assert st["state"] == "poor" and st["alert"]


def test_learning_state_poor_for_very_slow_answers():
    assert state.evaluate([{"sec_per_q": 120, "score": 80}] * 3)["state"] == "poor"
