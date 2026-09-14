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
                       key=lambda kv: kv[1], reverse=True)[start:end + 1]
        if withscores:
            return [(m, float(s)) for m, s in items]
        return [m for m, _ in items]

    def zincrby(self, key, amount, member):
        cur = float(self.zsets.setdefault(key, {}).get(member, 0))
        self.zsets[key][member] = cur + amount
        return cur + amount

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
