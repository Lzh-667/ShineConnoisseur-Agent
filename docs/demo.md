# ShineConnoisseur Agent 演示手册

## 演示目标

用 3～5 分钟证明这不是单纯的模型 API 封装，而是一条可观测、可降级、可评测的业务链路。

## 启动与验收

```bash
# 仓库根目录
docker compose --profile ai up -d --build
docker compose --profile ai ps

# Agent 子模块
ruff check app tests scripts run.py
pytest -q
```

启用真实依赖测试时：

```bash
RUN_INTEGRATION=1 pytest -q -m integration tests/integration
```

## 推荐演示脚本

### 1. 语义检索与来源引用

提问：“我想看一部讲普通人在高墙里仍不放弃希望的电影。”

展示重点：自然语言没有直接写片名；Agent 调用 `semantic_search`；界面展示电影来源；说明
BM25 与 BGE-M3 KNN 并行召回后由客户端 RRF 融合，ES 异常时降级到 MySQL LIKE。

### 2. 结构化条件与语义组合

提问：“推荐一部 1994 年上映的王家卫爱情片。”

展示重点：年份从查询中提取为 `releaseYear` 精确过滤，而导演、类型等文本仍参与检索，避免
把精确条件完全交给向量相似度。

### 3. 个性化推荐

登录有收藏记录的账号后提问：“根据我的喜好推荐今晚适合看的电影。”

展示重点：Redis 登录态、收藏和评分聚合出的长期画像、会话上下文注入，以及推荐结果中对
已收藏/已评分电影的排除。

### 4. 辅助创作与受控写操作

提问：“帮我写一篇《肖申克的救赎》的影评草稿。”

展示重点：先读取站内电影与影评信息，再生成草稿；发布操作通过 Spring Boot API 并透传用户
Token，而不是由 Agent 直接写业务数据库。

## 面试讲解顺序

1. 为什么拆成独立 Agent 服务：Python 生态适配模型编排，同时复用现有 Java 业务系统。
2. 为什么选择客户端 RRF：当前 Elasticsearch 基础版不提供服务端 RRF。
3. 如何处理可靠性：限流、超时、会话所有权、索引增量游标、分布式锁和检索降级。
4. 如何证明效果：人工标注 ID 的 Hit@K、Recall@K、MRR、nDCG@K；LLM 判官只作辅助。
5. 已知取舍：当前 SQLite checkpoint 适合单实例演示，多实例生产部署应迁移到共享存储。

## 录屏检查清单

- 浏览器同时展示回答、工具状态与来源卡片。
- 终端展示服务均为 healthy，但不要展示 `.env` 或任何密钥。
- 打开 `/metrics/` 展示低基数指标，不展示用户 ID、查询内容或 thread ID。
- 最后展示 RAG 评测表和 CI 测试结果，全程控制在 5 分钟以内。
