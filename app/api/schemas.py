"""API 请求/响应模型。响应格式统一为 {success, errorMsg, data, total}（与后端一致）。"""

from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    threadId: str | None = None  # null = 新建会话
    message: str
    extra: dict[str, Any] | None = None  # 可选页面上下文（如 {"movieId": 12}）


class ToolCallInfo(BaseModel):
    name: str
    args: dict[str, Any] | None = None
    summary: str | None = None


class SourceInfo(BaseModel):
    type: str  # movie | review
    id: int
    title: str
    score: float | None = None


class ChatData(BaseModel):
    threadId: str
    reply: str
    tools: list[ToolCallInfo] = []
    sources: list[SourceInfo] = []


def ok(data: Any = None, total: int | None = None) -> dict:
    return {"success": True, "errorMsg": None, "data": data, "total": total}


def fail(msg: str) -> dict:
    return {"success": False, "errorMsg": msg, "data": None, "total": None}
