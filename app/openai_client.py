"""OpenAI-compatible transport, independently configured for chat and embeddings."""
import json
import httpx
from .config import get_settings


def endpoint(base, route):
    base = base.rstrip("/")
    return base + ("" if base.endswith("/v1") else "/v1") + "/" + route


def headers(key):
    if not key:
        raise RuntimeError("模型密钥未配置")
    return {"Authorization": "Bearer " + key}


def check(response):
    if response.status_code != 200:
        raise RuntimeError(f"模型接口返回 HTTP {response.status_code}，请检查地址、模型、额度与密钥")


def messages(items, system):
    return [{"role": "system", "content": system}] + [
        {"role": "assistant" if m["role"] in ("assistant", "model") else "user",
         "content": m["content"]} for m in items
    ]


async def generate_json(prompt, system, temperature):
    s = get_settings()
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            endpoint(s.chat_api_base, "chat/completions"), headers=headers(s.chat_api_key),
            json={"model": s.chat_model, "messages": messages(
                [{"role": "user", "content": prompt}],
                system + "\nReturn only a JSON object."),
                "temperature": temperature, "max_tokens": 8192,
                "response_format": {"type": "json_object"}},
        )
    check(response)
    data = response.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError("模型输出超过长度限制，请减少题量后重试")
    result = json.loads(choice["message"]["content"])
    if not isinstance(result, dict):
        raise RuntimeError("模型没有返回 JSON 对象")
    return result


async def stream_chat(items, system, temperature):
    s = get_settings()
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST", endpoint(s.chat_api_base, "chat/completions"),
            headers=headers(s.chat_api_key),
            json={"model": s.chat_model, "messages": messages(items, system),
                  "temperature": temperature, "max_tokens": 2048, "stream": True},
        ) as response:
            check(response)
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                if not payload:
                    continue
                data = json.loads(payload)
                if data.get("error"):
                    raise RuntimeError("中转站返回流式生成错误")
                choices = data.get("choices", [])
                if choices:
                    text = choices[0].get("delta", {}).get("content")
                    if text:
                        yield text


async def embed_batch(texts):
    s = get_settings()
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            endpoint(s.embed_api_base, "embeddings"), headers=headers(s.embed_api_key),
            json={"model": s.embed_model, "input": texts, "dimensions": s.embed_dim},
        )
    check(response)
    rows = sorted(response.json()["data"], key=lambda item: item["index"])
    if [row["index"] for row in rows] != list(range(len(texts))):
        raise RuntimeError("向量接口返回的条目数量或序号不正确")
    return [row["embedding"] for row in rows]
