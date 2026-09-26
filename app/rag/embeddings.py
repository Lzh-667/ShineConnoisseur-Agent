"""BGE-M3 向量化封装（SiliconFlow OpenAI 兼容 API）。

- 批量 32 条 + 指数退避重试
- 结果按文本 md5 缓存到 Redis（30 天），重同步不重复计费
"""

import hashlib
import json
import time

import httpx

from app.config.settings import settings
from app.services.redis_client import AgentRedisKeys, get_redis

BATCH_SIZE = 32
MAX_ATTEMPTS = 4


def _is_retryable(error: Exception) -> bool:
    """只重试瞬时错误；401/403 等确定性客户端错误应立即失败。"""
    if not isinstance(error, httpx.HTTPStatusError):
        return True
    status = error.response.status_code
    return status == 429 or status >= 500


def _embed_batch(texts: list[str]) -> list[list[float]]:
    last_err: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = httpx.post(
                f"{settings.siliconflow_base_url}/embeddings",
                headers={"Authorization": f"Bearer {settings.siliconflow_api_key}"},
                json={
                    "model": settings.siliconflow_embedding_model,
                    "input": texts,
                    "encoding_format": "float",
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            vectors = [d["embedding"] for d in data]
            if len(vectors) != len(texts) or any(len(v) != settings.embedding_dim for v in vectors):
                raise ValueError(f"embedding 返回维度与配置的 {settings.embedding_dim} 不一致")
            return vectors
        except Exception as e:
            last_err = e
            if not _is_retryable(e):
                break
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"embedding 调用失败: {last_err}")


def check_embedding_service() -> int:
    """执行一次不走缓存的最小探测，返回实际向量维度。"""
    return len(_embed_batch(["embedding health check"])[0])


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化，命中 Redis 缓存的文本不重复调用。"""
    r = get_redis()
    results: list[list[float] | None] = [None] * len(texts)
    missing: list[int] = []

    for i, t in enumerate(texts):
        key = AgentRedisKeys.EMBED_CACHE.format(hashlib.md5(t.encode("utf-8")).hexdigest())
        cached = r.get(key)
        if cached:
            results[i] = json.loads(cached)
        else:
            missing.append(i)

    for start in range(0, len(missing), BATCH_SIZE):
        idxs = missing[start:start + BATCH_SIZE]
        vecs = _embed_batch([texts[i] for i in idxs])
        for i, vec in zip(idxs, vecs):
            results[i] = vec
            key = AgentRedisKeys.EMBED_CACHE.format(
                hashlib.md5(texts[i].encode("utf-8")).hexdigest())
            r.set(key, json.dumps(vec), ex=AgentRedisKeys.EMBED_CACHE_TTL)

    return results  # type: ignore[return-value]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
