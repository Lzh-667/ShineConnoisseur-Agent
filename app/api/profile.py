"""用户画像接口（长期记忆调试/前端展示）。"""

from fastapi import APIRouter, Header, HTTPException

from app.api.schemas import ok
from app.memory import extractor
from app.services.auth import resolve_user

router = APIRouter()


@router.get("/profile/{user_id}")
async def get_profile(user_id: int, authorization: str | None = Header(default=None)):
    user = resolve_user(authorization)
    if user["userId"] == 0:
        raise HTTPException(status_code=401, detail="请先登录")
    if user["userId"] != user_id:
        raise HTTPException(status_code=403, detail="只能查看自己的画像")
    return ok(extractor.get_or_refresh(user_id))
