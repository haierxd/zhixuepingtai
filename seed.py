"""填充一份「一个班」的演示学情:多名学生 + 教师端可用的聚合数据。

保留 林知遥(默认演示学生,内容最丰富),另加 5 名水平/活跃度各异的学生,
使教师端总览/名册/掌握热力/待关注/活动流一进去就有实在内容。
幂等:先清空再写。运行:./.venv/bin/python seed.py
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from app import store
from app.config import get_settings

DAY = 86400
NOW = time.time()

ORDER = ["ai-ml-overview", "supervised-unsupervised", "linear-regression", "logistic-classification",
         "loss-gradient-descent", "model-evaluation", "overfitting-regularization", "bias-variance-cv",
         "neural-networks", "backpropagation", "embeddings", "cnn", "rnn-lstm",
         "attention-transformer", "llm-pretrain-finetune-rag", "reinforcement-learning"]
TITLE = {
    "ai-ml-overview": "人工智能与机器学习概览", "supervised-unsupervised": "监督学习与无监督学习",
    "linear-regression": "线性回归", "logistic-classification": "逻辑回归与分类",
    "loss-gradient-descent": "损失函数与梯度下降", "model-evaluation": "模型评估指标",
    "overfitting-regularization": "过拟合、欠拟合与正则化", "bias-variance-cv": "偏差-方差权衡与交叉验证",
    "neural-networks": "神经网络基础(MLP与激活函数)", "backpropagation": "反向传播",
    "embeddings": "词向量与表示学习", "cnn": "卷积神经网络 CNN", "rnn-lstm": "循环神经网络 RNN 与 LSTM",
    "attention-transformer": "注意力机制与 Transformer", "llm-pretrain-finetune-rag": "大语言模型:预训练、微调与 RAG",
    "reinforcement-learning": "强化学习基础",
}


def uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


def ts(days_ago: float) -> float:
    return NOW - days_ago * DAY


CIT = lambda tid, secs: {"topic_id": tid, "title": TITLE[tid], "title_en": "", "sections": secs, "score": 0.74}

# 林知遥(默认学生)的丰富对话
LZY_CHATS = [
    (5.2, "为什么逻辑回归用交叉熵损失,而不是像线性回归那样用 MSE?",
     "好问题,这正是初学者最容易混淆的点。\n\n关键在于**配合 sigmoid 时损失函数的形状**:\n\n- 对逻辑回归用 **MSE**,由于经过非线性 sigmoid,损失关于参数是**非凸**的,容易卡在局部极小。\n- 改用**交叉熵**后损失重新**凸**,有唯一全局最优;对 sigmoid 求导后梯度形式简洁:$\\frac{\\partial L}{\\partial w}=(\\hat{y}-y)x$。\n\n一句话:**交叉熵让分类问题的优化既凸又高效**。",
     [CIT("logistic-classification", ["三、关键公式 / 原理"]), CIT("loss-gradient-descent", ["二、核心知识点"])]),
    (2.0, "梯度下降里学习率太大会怎样?太小呢?",
     "用「下山」比喻最好理解——学习率就是**每步迈多大**:\n\n- **太大**:可能跨过谷底,在两侧**震荡**甚至**发散**。\n- **太小**:**收敛极慢**,易卡在平坦区。\n\n实践常用**学习率调度**或 **Adam** 缓解。",
     [CIT("loss-gradient-descent", ["一、概念与直觉", "三、关键公式 / 原理"])]),
    (0.3, "反向传播到底在算什么?它和梯度下降是一回事吗?",
     "不是一回事:\n\n- **反向传播**用**链式法则高效计算梯度**,本身不更新参数。\n- **梯度下降**是拿到梯度后按 $w:=w-\\eta\\nabla L$ **更新参数**的优化算法。\n\n流程:前向算损失 → 反向算梯度 → 梯度下降更新,循环往复。",
     [CIT("backpropagation", ["一、概念与直觉"]), CIT("loss-gradient-descent", ["三、关键公式 / 原理"])]),
]

# 一组通用问答,供其它学生填充(topic_id, 问题, 简短回答)
POOL = {
    "linear-regression": ("线性回归的最小二乘是什么意思?", "最小二乘就是让**预测值与真实值的平方误差之和最小**,对应在高斯噪声假设下的极大似然估计。可用正规方程闭式求解,也可用梯度下降迭代。"),
    "logistic-classification": ("sigmoid 函数有什么作用?", "**sigmoid 把任意实数压到 (0,1)**,从而把线性输出解释为属于正类的概率,是逻辑回归做二分类的关键。"),
    "model-evaluation": ("精确率和召回率有什么区别?", "**精确率**关注「预测为正的里有多少真对」,**召回率**关注「真正的正例里被找出多少」。二者常此消彼长,用 **F1** 折中。"),
    "neural-networks": ("为什么神经网络需要激活函数?", "没有激活函数,多层线性叠加仍是线性,无法拟合复杂函数。**激活函数(如 ReLU)引入非线性**,赋予网络逼近任意函数的能力。"),
    "supervised-unsupervised": ("监督和无监督学习的本质区别?", "**监督学习有标签**(学输入到输出的映射,如分类/回归),**无监督无标签**(发现数据内在结构,如聚类/降维)。"),
    "cnn": ("卷积神经网络为什么适合图像?", "**卷积核参数共享 + 局部感受野**,能高效提取平移不变的局部特征,层层堆叠形成层次化表示,非常契合图像。"),
}


def main() -> None:
    store.init_db()
    db = get_settings().db_path
    conn = sqlite3.connect(db, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    cur = conn.cursor()

    # 清空所有演示数据(整个班重建)
    for tbl in ("messages", "mastery", "quizzes", "events", "assignments", "students"):
        cur.execute(f"DELETE FROM {tbl}")

    def add_student(sid, name, no, scores, chats, quiz_topics, recency, grade="本科 2023 级", major="人工智能", created=40):
        """scores: 与 ORDER 对齐的分数列表(0=未学);chats:[(days,tid)];quiz_topics:[(days,tid,score)];recency:活跃近度(天)。"""
        cur.execute("INSERT INTO students(id,name,grade,major,student_no,created_at) VALUES(?,?,?,?,?,?)",
                    (sid, name, grade, major, no, ts(created)))
        for tid, sc in zip(ORDER, scores):
            if sc > 0:
                cur.execute("INSERT INTO mastery(student_id,topic_id,score,attempts,updated_at) VALUES(?,?,?,?,?)",
                            (sid, tid, float(sc), 1 if sc < 60 else 2, ts(recency)))
        for days, tid in chats:
            q, a = (None, None)
            if isinstance(tid, tuple):  # 直接给(问,答,引用)
                q, a, cits = tid
            else:
                q, a = POOL[tid]; cits = [CIT(tid, ["二、核心知识点"])]
            cur.execute("INSERT INTO messages(id,student_id,role,content,citations,created_at) VALUES(?,?,?,?,?,?)",
                        (uid("msg"), sid, "user", q, "[]", ts(days)))
            cur.execute("INSERT INTO messages(id,student_id,role,content,citations,created_at) VALUES(?,?,?,?,?,?)",
                        (uid("msg"), sid, "assistant", a, json.dumps(cits, ensure_ascii=False), ts(days) + 30))
            cur.execute("INSERT INTO events(id,student_id,kind,detail,created_at) VALUES(?,?,?,?,?)",
                        (uid("ev"), sid, "chat", json.dumps({"q": q[:40], "topics": [c["title"] for c in cits]}, ensure_ascii=False), ts(days) + 30))
        for days, tid, sc in quiz_topics:
            title = TITLE[tid]
            ok = sc >= 70
            questions = [
                {"id": "q1", "type": "choice", "stem": f"关于《{title}》,下列说法正确的是?",
                 "options": ["A. 一个常见但错误的理解", "B. 符合该知识点的正确表述", "C. 张冠李戴的概念", "D. 以偏概全的说法"],
                 "answer": "B", "explanation": "B 准确对应该知识点的核心定义,其余选项是常见误区。"},
                {"id": "q2", "type": "short", "stem": f"请简述《{title}》的关键思想及其作用。",
                 "reference": "需覆盖该知识点的核心定义、关键机制与典型应用。", "explanation": "按要点给分:定义、机制、应用各占一部分。"},
            ]
            results = [
                {"id": "q1", "type": "choice", "correct": ok, "your": "B" if ok else "A", "answer": "B",
                 "score": 100 if ok else 0, "explanation": questions[0]["explanation"]},
                {"id": "q2", "type": "short", "score": min(100, max(25, sc)), "your": "(作答略)",
                 "reference": questions[1]["reference"],
                 "feedback": "答出了主要要点,表述较完整。" if ok else "要点覆盖不全,建议重新梳理核心定义与机制。"},
            ]
            payload = {"topic_id": tid, "topic_title": title, "questions": questions,
                       "results": results, "overall": float(sc), "feedback": ""}
            cur.execute("INSERT INTO quizzes(id,student_id,topic_id,payload,score,created_at) VALUES(?,?,?,?,?,?)",
                        (uid("quiz"), sid, tid, json.dumps(payload, ensure_ascii=False), float(sc), ts(days)))
            cur.execute("INSERT INTO events(id,student_id,kind,detail,created_at) VALUES(?,?,?,?,?)",
                        (uid("ev"), sid, "quiz_start", json.dumps({"topic": TITLE[tid]}, ensure_ascii=False), ts(days) - 200))
            cur.execute("INSERT INTO events(id,student_id,kind,detail,created_at) VALUES(?,?,?,?,?)",
                        (uid("ev"), sid, "quiz_done", json.dumps({"topic": TITLE[tid], "score": sc}, ensure_ascii=False), ts(days)))

    # 林知遥(默认学生,主)——中上水平、活跃
    add_student(store.DEFAULT_STUDENT, "林知遥", "2023210001",
                [88, 85, 90, 80, 72, 68, 65, 52, 58, 45, 0, 0, 0, 0, 0, 0],
                [(d, c) for d, c in [(5.2, LZY_CHATS[0][1:]), (2.0, LZY_CHATS[1][1:]), (0.3, LZY_CHATS[2][1:])]],
                [(5.0, "linear-regression", 90), (4.0, "logistic-classification", 80),
                 (3.0, "overfitting-regularization", 65), (1.0, "loss-gradient-descent", 72)],
                recency=0.3)

    # 顾沛宁——尖子生,掌握度高、活跃
    add_student(uid("stu"), "顾沛宁", "2023210002",
                [92, 90, 88, 86, 84, 82, 80, 78, 76, 72, 68, 64, 0, 0, 0, 0],
                [(1.2, "cnn"), (0.5, "neural-networks")],
                [(3.0, "neural-networks", 88), (2.0, "backpropagation", 85), (0.6, "cnn", 84)],
                recency=0.5)

    # 周屿——中等,稳步推进
    add_student(uid("stu"), "周屿", "2023210003",
                [84, 80, 76, 70, 66, 60, 54, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                [(2.4, "model-evaluation"), (1.1, "logistic-classification")],
                [(4.0, "linear-regression", 78), (1.5, "model-evaluation", 64)],
                recency=1.1)

    # 苏轻寒——薄弱、待关注(多门低分)
    add_student(uid("stu"), "苏轻寒", "2023210004",
                [58, 52, 48, 44, 40, 36, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                [(3.5, "linear-regression")],
                [(5.0, "linear-regression", 46), (2.5, "logistic-classification", 38)],
                recency=2.5)

    # 江临——刚起步
    add_student(uid("stu"), "江临", "2023210005",
                [55, 46, 40, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                [(1.0, "supervised-unsupervised")],
                [(1.0, "supervised-unsupervised", 50)],
                recency=1.0)

    # 蒋斯年——新生,几乎未开始
    add_student(uid("stu"), "蒋斯年", "2023210006",
                [38, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                [], [], recency=6.0)

    # 作业:给几名学生布置待办测评(教师端"作业"/学生端"待办"演示)
    def assign(name, tid):
        row = cur.execute("SELECT id FROM students WHERE name=?", (name,)).fetchone()
        if row:
            cur.execute("INSERT INTO assignments(id,student_id,topic_id,topic_title,n,status,created_at) VALUES(?,?,?,?,?,?,?)",
                        (uid("asg"), row[0], tid, TITLE[tid], 5, "pending", ts(0.5)))
    assign("林知遥", "backpropagation")
    assign("苏轻寒", "linear-regression")
    assign("江临", "logistic-classification")
    assign("周屿", "model-evaluation")

    conn.commit()
    conn.close()

    roster = store.roster_with_stats()
    summ = store.cohort_summary()
    print("✓ 已注入班级演示数据")
    print(f"  班级:{summ['students']} 名学生 · 班级均掌握 {summ['avg_mastery']} · 近24h活跃 {summ['active_24h']} · 累计测评 {summ['quizzes_done']}")
    for r in roster:
        print(f"  - {r['name']:<6}{r.get('student_no',''):>12}  均掌握 {r['avg_mastery']:>5}  已学 {r['topics_studied']:>2}  薄弱 {r['weak_count']}  提问 {r['questions_asked']}  测评 {r['quizzes_done']}")


if __name__ == "__main__":
    main()
