"""会话管理：列表 / 删除（需登录）。"""

from fastapi import APIRouter, Header, HTTPException

from app.api.schemas import fail, ok
from app.services.auth import resolve_user
from app.services.session_store import delete_session, get_session, list_sessions

router = APIRouter()


@router.get("/sessions")
async def sessions(current: int = 1, authorization: str | None = Header(default=None)):
    user = resolve_user(authorization)
    if user["userId"] == 0:
        return fail("请先登录")
    page, total = list_sessions(user["userId"], current)
    return ok({"list": page, "hasMore": current * 10 < total})


@router.delete("/sessions/{thread_id}")
async def remove_session(thread_id: str, authorization: str | None = Header(default=None)):
    user = resolve_user(authorization)
    if user["userId"] == 0:
        raise HTTPException(status_code=401, detail="请先登录")
    meta = get_session(thread_id)
    if not meta:
        return fail("会话不存在")
    if str(meta.get("userId")) != str(user["userId"]):
        raise HTTPException(status_code=403, detail="无权操作该会话")
    delete_session(thread_id)
    return ok()
