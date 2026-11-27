"""Check configured chat and embedding services without printing credentials."""
import asyncio
import json
from app.config import get_settings
from app import gemini


async def check():
    s = get_settings()
    result = {}
    for name, configured in (("chat", s.configured), ("embedding", s.embedding_configured)):
        if not configured:
            result[name] = "missing_key"
            continue
        try:
            if name == "chat":
                reply = await gemini.generate_json('Return {"ok":true}', "Output a JSON object.")
                if not reply.get("ok"):
                    raise ValueError()
                stream = "".join([p async for p in gemini.stream_chat(
                    [{"role": "user", "content": "Reply OK."}], "Reply briefly.",
                )])
                if not stream.strip():
                    raise ValueError()
            else:
                vectors = await gemini.embed_batch(["model connection test"])
                if len(vectors) != 1 or len(vectors[0]) != s.embed_dim:
                    raise ValueError()
            result[name] = "ok"
        except Exception as exc:
            result[name] = "failed:" + type(exc).__name__
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    asyncio.run(check())
