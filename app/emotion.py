"""表情识别(预留模块)。

⚠️ 本模块为**预留占位**,当前不做任何真实的表情识别。
仅对外暴露稳定的接口与数据结构,供后续接入摄像头/视觉模型时填充实现;
学习状态评价(state.py)会在 `available=True` 时把表情信号纳入综合评分。

后续接入方式(TODO):
- 在 `analyze_frame()` 内调用表情识别模型(如 onnx/mediapipe/第三方 API),
  返回 {emotion, valence, arousal, confidence};
- 用 `record()` 落库每位学生的最近表情;`latest()` 取回供 state.evaluate 使用;
- 把 EMOTION_ENABLED 置为 True 即可让上层自动启用。
"""
from __future__ import annotations

from typing import Optional

# 是否已启用真实表情识别。预留阶段恒为 False。
EMOTION_ENABLED = False

# 预留:情绪标签到"专注度增量"的映射(启用后由 state.evaluate 使用)
EMOTION_LABELS = ["focused", "neutral", "confused", "frustrated", "bored", "tired"]


def status() -> dict:
    """模块状态,供前端判断是否展示真实表情面板。"""
    return {
        "available": EMOTION_ENABLED,
        "module": "emotion",
        "labels": EMOTION_LABELS,
        "note": "表情识别模块已预留,尚未启用。接入视觉模型后将参与学习状态评价。",
    }


def analyze_frame(student_id: str, frame: Optional[str] = None) -> dict:
    """分析一帧画面并返回情绪结果。

    预留阶段:不处理 frame,直接返回未启用占位。
    接入后:在此调用模型,并可调用 record(student_id, result) 落库。
    """
    # TODO: 接入表情识别模型
    return {"available": False, "emotion": None, "confidence": 0.0,
            "note": "表情识别未启用(预留模块)"}


def record(student_id: str, result: dict) -> None:
    """预留:保存某学生的最近一次表情识别结果(当前不实现)。"""
    return None


def latest(student_id: str) -> Optional[dict]:
    """返回该学生最近一次表情识别结果;预留阶段恒为 None。

    state.evaluate 以此判断是否纳入表情信号。
    """
    return None
