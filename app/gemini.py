"""Gemini REST 封装:流式对话、结构化 JSON、批量向量。

只依赖 httpx,不引入官方 SDK,便于在受限环境部署。
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx

from .config import get_settings


class GeminiError(RuntimeError):
    pass


def _key() -> str:
    s = get_settings()
    key = s.chat_api_key or s.gemini_api_key
    if not key:
        raise GeminiError("未配置 GEMINI_API_KEY,请在 .env 中设置。")
    return key


def _contents(messages: list[dict]) -> list[dict]:
    """把 [{role, content}] 转成 Gemini contents 结构。role: user|assistant。"""
    out: list[dict] = []
    for m in messages:
        role = "model" if m["role"] in ("assistant", "model") else "user"
        out.append({"role": role, "parts": [{"text": m["content"]}]})
    return out


async def stream_chat(
    messages: list[dict],
    system: str,
    *,
    temperature: float = 0.6,
    thinking_budget: Optional[int] = 0,
) -> AsyncIterator[str]:
    """以 SSE 流式返回模型文本增量。thinking_budget=0 关闭思考以降低首字延迟。"""
    s = get_settings()
    if s.chat_provider == "openai":
        from . import openai_client
        try:
            async for part in openai_client.stream_chat(messages, system, temperature):
                yield part
        except (RuntimeError, httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise GeminiError("对话调用失败: " + _safe_error(exc)) from None
        return
    url = f"{s.chat_api_base}/models/{s.chat_model}:streamGenerateContent"
    body: dict = {
        "contents": _contents(messages),
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 2048},
    }
    if thinking_budget is not None:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": thinking_budget}

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream(
            "POST", url, params={"key": _key(), "alt": "sse"}, json=body
        ) as resp:
            if resp.status_code != 200:
                raise GeminiError(f"Gemini 流式调用失败 [HTTP {resp.status_code}]")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload in ("", "[DONE]"):
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for cand in chunk.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        if part.get("thought"):
                            continue
                        text = part.get("text")
                        if text:
                            yield text


async def generate_json(prompt: str, system: str, *, temperature: float = 0.4,
                        thinking_budget: Optional[int] = None) -> dict:
    """要求模型返回严格 JSON(用于出题与评分)。"""
    s = get_settings()
    if s.chat_provider == "openai":
        from . import openai_client
        try:
            return await openai_client.generate_json(prompt, system, temperature)
        except (RuntimeError, httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise GeminiError("结构化生成失败: " + _safe_error(exc)) from None
    url = f"{s.chat_api_base}/models/{s.chat_model}:generateContent"
    body: dict = {
        "contents": _contents([{"role": "user", "content": prompt}]),
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            # 8192:gemini-3.5-flash 为思考模型,思考 token 会占用输出预算;
            # 4096 时长题(如出题)常被思考挤占导致 JSON 截断(MAX_TOKENS),故上调。
            "maxOutputTokens": 8192,
        },
    }
    if thinking_budget is not None:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": thinking_budget}

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(url, params={"key": _key()}, json=body)
    if resp.status_code != 200:
        raise GeminiError(f"Gemini 调用失败 [HTTP {resp.status_code}]")
    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise GeminiError(f"无法解析模型 JSON 返回: {exc}; 原始: {str(data)[:300]}")


async def embed_batch(texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """批量向量化。task_type: RETRIEVAL_DOCUMENT(入库) / RETRIEVAL_QUERY(检索)。"""
    s = get_settings()
    if s.embed_provider == "local":
        import hashlib
        vectors = []
        for text in texts:
            vec = [0.0] * s.embed_dim
            compact = "".join(text.lower().split())
            grams = [compact[i:i + 2] for i in range(len(compact) - 1)] or [compact]
            for gram in grams:
                digest = hashlib.md5(gram.encode("utf-8")).digest()
                vec[int.from_bytes(digest[:4], "little") % s.embed_dim] += 1.0
            vectors.append(vec)
        return vectors
    if s.embed_provider == "openai":
        from . import openai_client
        try:
            return await openai_client.embed_batch(texts)
        except (RuntimeError, httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise GeminiError("向量调用失败: " + _safe_error(exc)) from None
    url = f"{s.embed_api_base}/models/{s.embed_model}:batchEmbedContents"
    model_path = f"models/{s.embed_model}"
    requests = [
        {
            "model": model_path,
            "content": {"parts": [{"text": t}]},
            "taskType": task_type,
            "outputDimensionality": s.embed_dim,
        }
        for t in texts
    ]
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        key = s.embed_api_key or s.gemini_api_key
        if not key:
            raise GeminiError("未配置向量模型密钥 EMBED_API_KEY / GEMINI_API_KEY")
        resp = await client.post(url, params={"key": key}, json={"requests": requests})
    if resp.status_code != 200:
        raise GeminiError(f"向量化失败 [HTTP {resp.status_code}]")
    data = resp.json()
    return [e["values"] for e in data.get("embeddings", [])]


async def embed_one(text: str, *, task_type: str = "RETRIEVAL_QUERY") -> list[float]:
    out = await embed_batch([text], task_type=task_type)
    return out[0]


def _safe_error(exc):
    if isinstance(exc, httpx.HTTPError):
        return type(exc).__name__ + "，请检查网络及接口地址"
    if isinstance(exc, (KeyError, IndexError, ValueError)):
        return "接口响应格式不符合约定"
    s = get_settings()
    detail = str(exc)
    for key in (s.chat_api_key, s.embed_api_key, s.gemini_api_key):
        if key:
            detail = detail.replace(key, "[redacted]")
    return detail[:250]
