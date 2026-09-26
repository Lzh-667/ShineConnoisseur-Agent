"""真实中间件连通性与基础读写测试。

默认跳过；设置 RUN_INTEGRATION=1 后运行，CI 会启动隔离的服务容器。
"""

import os
import uuid

import pytest

from app.services import es_client, mysql
from app.services.redis_client import get_redis
from app.services.session_store import delete_session, get_session, list_sessions, touch_session

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1",
                       reason="set RUN_INTEGRATION=1 to run live dependency tests"),
]


def test_mysql_connection_executes_real_query():
    rows = mysql._rows("SELECT 1 AS value")
    assert rows == [{"value": 1}]


def test_redis_connection_and_session_round_trip():
    redis = get_redis()
    assert redis.ping()

    thread_id = uuid.uuid4().hex
    owner_id = f"integration:{uuid.uuid4().hex}"
    touch_session(thread_id, owner_id, "集成测试会话")
    try:
        assert get_session(thread_id)["ownerId"] == owner_id
        sessions, total = list_sessions(owner_id)
        assert total == 1
        assert sessions[0]["threadId"] == thread_id
    finally:
        delete_session(thread_id, owner_id)


def test_elasticsearch_connection_is_reachable():
    assert es_client.ping()
