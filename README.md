# ShineConnoisseur Agent（光影鉴赏家 AI 助手）

电影影评社区平台的 AI Agent 服务，基于 **LangChain 1.x（create_agent）** + FastAPI。

[![CI](https://github.com/Lzh-667/ShineConnoisseur-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Lzh-667/ShineConnoisseur-Agent/actions/workflows/ci.yml)

## 能力规划（分阶段实施）

| 阶段 | 能力 | 状态 |
|------|------|------|
| 1 | 骨架 + 基础对话 + 查询工具（热门电影/热门影评/电影详情/影评列表/电影搜索/影评搜索） | ✅ 已完成 |
| 2 | ES 语义索引（BGE-M3 向量）+ RAG 混合检索（BM25+knn+客户端RRF） | ✅ 已完成 |
| 3 | 推荐（条件/收藏/场景）+ 电影对比 + 观影计划 | ✅ 已完成 |
| 4 | 影评总结 + 正负面观点分析 + AI 辅助创作/发布 | ✅ 已完成 |
| 5 | 长期记忆（用户画像）+ 热门 tool 统计 + 限流 + 单元测试 | ✅ 已完成 |
| 6 | Prometheus 可观测性 + 真实中间件集成测试 + RAG 评测 | ✅ 已完成 |

年份类电影查询会提取四位年份并对向量索引中的 `releaseYear` 做结构化过滤；同步过程同时保留
`originalTitle` 与上映年份，避免把精确条件完全交给语义相似度猜测。

## 快速开始

```bash
cd agent
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows；Linux 用 .venv/bin/pip
cp .env.example .env                            # 填入 DEEPSEEK_API_KEY / SILICONFLOW_API_KEY
.venv/Scripts/python run.py                     # 启动，端口 8001
```

环境变量中已配置 `DEEPSEEK_API_KEY` / `SILICONFLOW_API_KEY` 时，.env 中可不填。

## 接口

统一响应格式 `{success, errorMsg, data, total}`（与后端一致）。普通聊天使用用户登录
`authorization` token；管理接口必须使用后端管理员登录产生的 token。两者均兼容裸 token 和
`Bearer <token>` 形式。游客首次聊天会得到 `HttpOnly` 的 `agent_guest_id` cookie，用于隔离其会话。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agent/health` | 健康检查（mysql/redis/es/llm/embedding） |
| POST | `/api/agent/chat` | 非流式对话（body: `{threadId?, message, extra?}`） |
| POST | `/api/agent/chat/stream` | SSE 流式对话（event: message/tool/source/done/error） |
| GET | `/api/agent/sessions?current=` | 会话列表（需登录） |
| DELETE | `/api/agent/sessions/{threadId}` | 删除会话（需登录） |
| POST | `/api/agent/es/sync?type=all\|movie\|review` | 手动触发 ES 向量索引同步 |
| POST | `/api/agent/tools/{toolName}` | 直接调用某个工具（调试/快捷能力） |
| GET | `/api/agent/tool-stats?month=YYYYMM` | 热门 tool 调用排行（Redis ZSet 月维度） |
| GET | `/api/agent/usage/session/{threadId}` | 单会话 token 用量与估算成本 |
| GET | `/api/agent/usage/daily?days=7` | 最近 N 天全站 token 用量与估算成本 |
| GET | `/api/agent/profile/{userId}` | 用户画像（长期记忆，需登录且仅限本人） |
| GET | `/metrics/` | Prometheus 指标（请求/对话/工具/RAG/Token/同步） |

会话安全约定：新会话必须省略 `threadId`，由服务端生成；后续请求只能使用属于当前登录用户（或当前游客 cookie）的既有会话。删除会话会同时删除 LangGraph checkpoint 历史。

管理接口全部要求管理员认证。`POST /api/agent/tools/{toolName}` 默认关闭，仅在受控调试环境把 `ADMIN_TOOL_INVOKE_ENABLED=true` 后可用。

## 测试与 CI

```bash
.venv/Scripts/ruff check app tests scripts run.py   # lint
.venv/Scripts/python -m pytest -q                   # 单元测试（真实依赖测试默认跳过）
$env:RUN_INTEGRATION="1"; .venv/Scripts/python -m pytest -q -m integration tests/integration
```

GitHub Actions（`.github/workflows/ci.yml`）：push/PR 时运行 lint、单元测试，并启动隔离的
MySQL/Redis/Elasticsearch 容器执行真实依赖集成测试。

测试分层：工具层（mock MySQL/Redis/ES/LLM，覆盖降级分支）、API 层（TestClient + FakeAgent，覆盖限流/SSE/鉴权）、
RRF 纯逻辑、token 用量统计。

最近一次本地验收：**91 个单元测试通过**。CI 另配置 **4 个真实依赖集成测试**，除中间件
连通性与 Redis 会话读写外，还覆盖真实 Elasticsearch 写入 → BM25/KNN/RRF → LangChain
工具结构化输出的完整检索链路；该链路用固定测试向量替代外部付费 Embedding API。

## RAG 评估

```bash
.venv/Scripts/python scripts/eval_rag.py             # 混合 vs BM25 vs 向量：延迟 + LLM 判官命中率
.venv/Scripts/python scripts/eval_rag.py --skip-judge
.venv/Scripts/python scripts/eval_rag.py --out reports/rag.json --markdown-out reports/rag.md
.venv/Scripts/python scripts/eval_rag.py --prewarm-embeddings --skip-judge \
  --out reports/rag-warm.json --markdown-out reports/rag-warm.md
.venv/Scripts/python scripts/eval_rag.py --methods bm25 --skip-judge \
  --out reports/rag-bm25.json --markdown-out reports/rag-bm25.md
```

评测会先检查 ES、Embedding API，以及启用判官时的 LLM API；无效密钥会立即失败且不会写入误导性报告。
`--methods` 可用于单独评测 `bm25`、`knn` 或 `hybrid`（逗号分隔）。
`--prewarm-embeddings` 会批量填充 Redis 查询向量缓存，用于测量稳定态检索延迟；报告会明确标注是否预热。
判官会在一次调用中同时比较同一查询的所有检索方法，减少随机偏差；当前 26 条数据集只需
26 次判官调用，而不是按三种检索方法分别调用 78 次。

需 ES 向量索引已同步。数据集 `scripts/eval_dataset.json` 包含人工标注的相关文档 ID 和查询
类别。评测输出 Hit@K、Recall@K、MRR、nDCG@K 以及平均/P50/P95 延迟；LLM 判官是可选的
辅助指标，不作为人工标注指标的替代（`--out` 可导出逐查询 JSON）。

当前人工标注数据集的 BM25 基线（2026-09-26，Top 5，26 条查询）：

| 方法 | Hit@5 | Recall@5 | MRR | nDCG@5 | 平均延迟 | P95 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 76.9% | 67.9% | 0.662 | 0.642 | 35.7 ms | 41.2 ms |

可复查的逐查询结果见 [`reports/rag-labeled-bm25.md`](reports/rag-labeled-bm25.md) 与
[`reports/rag-labeled-bm25.json`](reports/rag-labeled-bm25.json)。KNN/Hybrid 的新口径结果需
在 Embedding 服务可用时重新执行，不沿用旧数据推断。

历史 Docker 稳定态评测（2026-09-26，旧版 30 条查询，Top 5，Embedding 缓存已预热，
仅使用 LLM 判官）：

| 方法 | 判官命中率 | 平均延迟 | P95 |
|---|---:|---:|---:|
| BM25 | 43.3% | 22.9 ms | 30.4 ms |
| KNN | 66.7% | 23.1 ms | 26.2 ms |
| Hybrid RRF | **66.7%** | 47.3 ms | 57.8 ms |

在该历史判官口径下，KNN 与 Hybrid 均比 BM25 高 **23.3 个百分点**，Hybrid 未超过 KNN
且延迟更高，因此不将其表述为全面优于 KNN。旧版详细结果见
[`reports/rag-full.md`](reports/rag-full.md) 与 [`reports/rag-full.json`](reports/rag-full.json)。

## ES 语义检索说明

- 索引：`movie_vec` / `review_vec`（dense_vector 1024 维 BGE-M3 + IK 分词文本字段，不动后端原索引）
- 同步：电影启动全量 + 每日一次；影评增量轮询（5 分钟，游标存 Redis `agent:sync:review:cursor`）
- 检索：BM25（与后端同加权）+ knn（cosine）+ **客户端 RRF 融合**（ES 8.15 基础版不支持服务端 RRF），ES 异常降级 MySQL LIKE
- embedding 结果按文本 md5 缓存 Redis 30 天，重同步不重复计费

## 架构

完整组件图、对话时序图、可靠性设计和 PromQL 示例见
[架构文档](docs/architecture.md)。

面试演示流程、代表性问题和讲解要点见 [演示手册](docs/demo.md)。

```
app/
├── api/          # FastAPI 路由（chat / sessions / admin）
├── agent/        # create_agent 组装：builder / checkpointer(SQLite) / system_prompt
├── tools/        # LangChain 工具（查询六件套起步，按阶段扩充）
├── rag/          # BGE-M3 embedding + ES 混合检索（阶段 2）
├── services/     # MySQL / Redis / ES / 后端 REST / 认证 / 会话
├── memory/       # 用户画像长期记忆（规则聚合 + 惰性刷新 + 对话偏好提取）
└── prompts/      # 提示词模板（与代码分离）
```

数据访问约定：读操作通过环境变量配置的 MySQL/ES/Redis 连接，写操作调用后端 REST API（token 透传）。
Redis Key 统一 `agent:` 前缀，常量收敛于 `services/redis_client.py::AgentRedisKeys`。
