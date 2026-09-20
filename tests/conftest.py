"""测试公共设施：FakeRedis 与常用 fixture（所有测试不依赖外部中间件）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


class FakeRedis:
    """覆盖 agent 代码用到的 Redis 命令子集的极简内存实现。"""

    def __init__(self):
        self.strings: dict = {}
        self.counters: dict = {}
        self.hashes: dict = {}
        self.zsets: dict = {}
        self.expires: dict = {}

    def get(self, key):
        return self.strings.get(key)

    def set(self, key, value, ex=None):
        self.strings[key] = value

    def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def eval(self, script, numkeys, key, now_ms, window_ms, limit, member):
        # 仅实现聊天滑动窗口脚本所需语义。
        if self.counters.get(key, 0) >= int(limit):
            return 0
        cutoff = int(now_ms) - int(window_ms)
        zset = self.zsets.setdefault(key, {})
        for value, score in list(zset.items()):
            if score <= cutoff:
                del zset[value]
        if len(zset) >= int(limit):
            return 0
        zset[member] = int(now_ms)
        return 1

    def expire(self, key, seconds):
        self.expires[key] = seconds

    def exists(self, key):
        return key in self.hashes or key in self.strings

    def delete(self, *keys):
        for k in keys:
            self.hashes.pop(k, None)
            self.strings.pop(k, None)
            self.zsets.pop(k, None)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hset(self, key, mapping=None, **kw):
        mapping = {**(mapping or {}), **kw}
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

    def hincrby(self, key, field, amount):
        cur = int(self.hashes.get(key, {}).get(field, 0))
        self.hashes.setdefault(key, {})[field] = str(cur + amount)
        return cur + amount

    def zrevrange(self, key, start, end, withscores=False):
        items = sorted(self.zsets.get(key, {}).items(),
                       key=lambda kv: kv[1], reverse=True)
        items = items[start:] if end == -1 else items[start:end + 1]
        if withscores:
            return [(m, float(s)) for m, s in items]
        return [m for m, _ in items]

    def zincrby(self, key, amount, member):
        cur = float(self.zsets.setdefault(key, {}).get(member, 0))
        self.zsets[key][member] = cur + amount
        return cur + amount

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    def zrem(self, key, *members):
        zset = self.zsets.get(key, {})
        for member in members:
            zset.pop(member, None)

    def scan(self, cursor=0, match=None, count=None):
        keys = [k for k in self.hashes if match is None or match.replace("*", "") in k]
        return 0, keys

    def ping(self):
        return True

    def close(self):
        pass


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def client():
    # 不用 with 上下文，避免触发 lifespan 连接真实 MySQL/Redis/ES
    return TestClient(app)


@pytest.fixture(autouse=True)
def default_admin_auth(monkeypatch):
    """除鉴权用例外，管理接口测试统一模拟有效管理员令牌。"""
    monkeypatch.setattr("app.api.admin.resolve_admin",
                        lambda token: {"adminId": 1, "username": "admin", "token": "admin-token"})


@pytest.fixture(autouse=True)
def default_review_insight_cache(monkeypatch, fake_redis):
    """测试不触碰真实 Redis；缓存行为仍由 FakeRedis 覆盖。"""
    monkeypatch.setattr("app.tools.summary_tools.get_redis", lambda: fake_redis)
