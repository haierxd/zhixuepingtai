"""学习状态评价。

由**答题快慢(主)+ 正确率 + 表情识别(预留)**综合判定学生当前的学习状态:
- good   专注良好
- normal 状态一般
- poor   状态欠佳(前端会给学生"现在状态不好"的提醒,教师端高亮)
- unknown 数据不足

答题快慢来源:每次测评记录的总用时 duration 与题量 n,得到"每题平均用时" sec_per_q,
再与基准 BASELINE_SEC_PER_Q 比较得到 pace_ratio(>1 偏慢,<1 偏快)。

表情识别为预留信号:emotion.available 为 True 时,这里会把情绪并入评分;当前恒为占位。
"""
from __future__ import annotations

from typing import Optional

BASELINE_SEC_PER_Q = 40.0     # 每题基准用时(秒),作为快慢的参照
RUSH_RATIO = 0.35             # 低于此视为"过快"
SLOW_RATIO = 2.6              # 高于此视为"过慢"
MAX_SAMPLES = 5               # 取最近多少次带计时的测评


def _emotion_block(emotion: Optional[dict]) -> dict:
    """统一的表情字段(预留)。emotion 为 None 表示模块未启用。"""
    if not emotion or not emotion.get("available"):
        return {"available": False, "label": None, "note": "表情识别未启用(预留)"}
    return {"available": True, "label": emotion.get("emotion"),
            "confidence": emotion.get("confidence", 0.0)}


def evaluate(samples: list[dict], emotion: Optional[dict] = None) -> dict:
    """samples: 最近在前的 [{sec_per_q, score, n, created_at}]。返回学习状态评价。"""
    timed = [s for s in samples if s.get("sec_per_q")][:MAX_SAMPLES]
    emo = _emotion_block(emotion)

    if not timed:
        return {
            "state": "unknown", "label": "数据不足",
            "reason": "完成一次带计时的测评后,这里会根据答题快慢给出学习状态评价。",
            "metrics": {"samples": 0}, "emotion": emo, "alert": False,
        }

    n = len(timed)
    avg_spq = sum(s["sec_per_q"] for s in timed) / n
    avg_score = sum(s.get("score", 0) for s in timed) / n
    pace = avg_spq / BASELINE_SEC_PER_Q
    rushing = sum(1 for s in timed if s["sec_per_q"] / BASELINE_SEC_PER_Q < RUSH_RATIO)
    sluggish = sum(1 for s in timed if s["sec_per_q"] / BASELINE_SEC_PER_Q > SLOW_RATIO)

    # 判定(答题快慢为主,正确率为辅)
    if pace < 0.4 and avg_score < 60:
        state, label = "poor", "状态欠佳"
        reason = "近几次答题偏快且正确率偏低,像是在赶进度或注意力分散,建议放慢节奏、专注作答。"
    elif sluggish >= max(2, n // 2 + 1) or pace > SLOW_RATIO:
        state, label = "poor", "状态欠佳"
        reason = "近几次答题明显偏慢,可能注意力不集中或遇到困难,建议先休息或回看教材。"
    elif 0.6 <= pace <= 1.8 and avg_score >= 70:
        state, label = "good", "专注良好"
        reason = "答题节奏稳定、正确率良好,状态不错,继续保持。"
    else:
        state, label = "normal", "状态一般"
        if avg_score < 60:
            reason = "正确率偏低,建议放慢节奏、巩固薄弱点。"
        elif pace < 0.5:
            reason = "答题偏快,注意别因急躁而失分。"
        else:
            reason = "状态平稳,保持节奏即可。"

    # 表情识别(预留):启用后在此叠加情绪对状态的修正
    # if emo["available"]: state = _blend_with_emotion(state, emo)

    return {
        "state": state, "label": label, "reason": reason,
        "metrics": {
            "avg_sec_per_q": round(avg_spq, 1),
            "pace_ratio": round(pace, 2),
            "avg_score": round(avg_score, 1),
            "samples": n, "rushing": rushing, "sluggish": sluggish,
        },
        "emotion": emo,
        "alert": state == "poor",
    }
