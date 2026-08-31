"""后端 REST API 客户端（写操作走这里，token 透传；阶段 4 完善）。"""

import httpx

from app.config.settings import settings


def post_backend(path: str, body: dict, token: str, timeout: float = 15.0) -> dict:
    """POST 后端接口，返回统一 Result 结构 {success, errorMsg, data, total}。"""
    headers = {"authorization": token} if token else {}
    resp = httpx.post(f"{settings.backend_url}{path}", json=body, headers=headers,
                      timeout=timeout)
    resp.raise_for_status()
    return resp.json()
