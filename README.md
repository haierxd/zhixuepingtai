# 智学：基于大语言模型的个性化学习指导与评价

> 学生入口为 `/student/`，教师入口为 `/teacher/`。保留原有学习与教学功能，新增个人资料、选区辅导、资料自测复练、收藏与阅读进度。

面向人工智能和计算机方向本科生的教学辅助 Demo。大语言模型作底座，结合检索增强 RAG 与学情建模，提供个性化学习对话，智能测评，知识图谱与课程阅读，以及教师端的全班学情监控。

## 核心能力

| 能力 | 说明 |
|---|---|
| 个性化对话辅导 | 导师按实时掌握度调整讲解深浅，薄弱处多铺垫，已掌握处深入 |
| 检索增强 RAG | 回答基于课程知识库检索，并标注来源 |
| 智能测评 | 按掌握度自适应命题，自动评分，个性化反馈，结果回写学情 |
| 学情画像 | 掌握度，薄弱知识点，学习轨迹，学习状态 |
| 知识图谱与课程阅读 | 16 个知识点按前置依赖排成路线图，每个知识点有完整课程正文 |
| 教师管理端 | 班级总览，掌握热力，学生管理，布置作业，AI 教学建议，导出 CSV |

## 技术架构

```
浏览器单页应用 frontend/（Vue，学生端与教师端独立入口）
   ├─ 资料学习：个人资料、选区问答、自测复练与学习记录
   └─ 复用 web/app.js：原有学习、测评与教师管理功能
   │  REST 与 SSE 流式
FastAPI app/main.py
   ├─ gemini.py      Gemini 流式对话，结构化 JSON，批量向量
   ├─ rag.py         知识库分块，向量化，索引缓存，余弦检索
   ├─ tutor.py       学情画像与检索结果拼成系统提示词
   ├─ evaluation.py  出题，评分，评语
   ├─ graph.py       知识图谱，学习路径，课程正文
   ├─ state.py       学习状态评价
   └─ store.py       SQLite，全部 SQL
知识库 app/knowledge/*.md，16 篇 AI/ML 课程文档
```

对话，出题，评分用 gemini-3.5-flash，向量用 gemini-embedding-001，768 维。

## 本地运行

需要 Python 3.12，与线上一致。命令都在仓库根目录执行。

准备环境，只做一次：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Windows 把 `.venv/bin/` 换成 `.venv\Scripts\`。国内网络装依赖慢时加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

新版前端需要 Node.js。首次运行或修改前端后，在 `frontend` 目录执行 `npm ci`、`npm run build`，再回到项目根目录启动后端。

### 离线模式

Windows 上可以直接在项目根目录双击 **启动智学.cmd**：服务就绪后自动打开浏览器。如果 8081 已被占用，会换一个可用端口。双击 **关闭智学.cmd** 停止由启动按钮启动的服务。手动用 PowerShell 启动的服务请回到原终端按 `Ctrl+C`。

不需要 Gemini 密钥，不访问 Google。模型换成本地假模型，回答和题目是固定模板，用于开发界面和走通流程。

```bash
.venv/bin/python -m scripts.offline --port 8080
```

浏览器打开 http://127.0.0.1:8080 ，选择学生端或教师端。学生账号 demo，密码 888888，教师口令默认 888888（以 `.env` 为准）。数据在 app/data/offline/。仅在需要重建演示班级时加 `--seed`，它会清空并重写离线数据。

### 真实模式

调用 Gemini，需要密钥，本机要能访问 generativelanguage.googleapis.com。国内网络把 HTTPS_PROXY 环境变量设成代理地址。

```bash
cp .env.example .env              # 把 GEMINI_API_KEY 改成真实密钥
.venv/bin/python seed.py          # 可选：写入演示班级，会清空 app/data/tutor.db 的全部数据
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

首次启动先为知识库建向量索引，几秒到几十秒，视网络而定，之后命中缓存。启动日志出现“知识索引就绪”后即可访问。

## 测试

```bash
.venv/bin/python -m pytest
```

测试全部离线运行，覆盖原有学习与教学接口、资料学习流程、学生会话和个人资料权限。
