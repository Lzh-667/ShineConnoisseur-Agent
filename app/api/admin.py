"""运维接口：健康检查等。"""

from fastapi import APIRouter

from app.api.schemas import ok
from app.config.settings import settings
from app.services import es_client, mysql
from app.services.redis_client import get_redis

router = APIRouter()


@router.get("/health")
async def health():
    checks = {}

    try:
        mysql._rows("SELECT 1")
        checks["mysql"] = "ok"
    except Exception as e:
        checks["mysql"] = f"fail: {e}"

    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"fail: {e}"

    try:
        checks["es"] = "ok" if es_client.ping() else "fail: ping=false"
    except Exception as e:
        checks["es"] = f"fail: {e}"

    checks["llm"] = "ok" if settings.deepseek_api_key else "fail: DEEPSEEK_API_KEY 未配置"
    checks["embedding"] = "ok" if settings.siliconflow_api_key else "fail: SILICONFLOW_API_KEY 未配置"

    return ok(checks)
