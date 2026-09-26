"""Embedding API 的重试与快速失败策略。"""

import httpx
import pytest

from app.config.settings import settings
from app.rag import embeddings


def _response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        request=httpx.Request("POST", "https://example.test/embeddings"),
        json=payload or {"error": "failed"},
    )


def test_embed_batch_does_not_retry_unauthorized(monkeypatch):
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _response(401)

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="401 Unauthorized"):
        embeddings._embed_batch(["test"])

    assert calls == 1


def test_embed_batch_retries_rate_limit_then_succeeds(monkeypatch):
    responses = [
        _response(429),
        _response(200, {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}),
    ]
    monkeypatch.setattr(embeddings.httpx, "post", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(embeddings.time, "sleep", lambda _: None)
    monkeypatch.setattr(settings, "embedding_dim", 2)

    assert embeddings._embed_batch(["test"]) == [[0.1, 0.2]]
