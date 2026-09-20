"""API 请求/响应模型。响应格式统一为 {success, errorMsg, data, total}（与后端一致）。"""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    # 新会话必须由服务端生成 threadId，避免客户端复用未知历史。
    threadId: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    message: str = Field(min_length=1, max_length=4_000)
    extra: dict[str, Any] | None = Field(default=None, max_length=20)


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
