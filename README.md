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

会话安全约定：新会话必须省略 `threadId`，由服务端生成；后续请求只能使用属于当前登录用户（或当前游客 cookie）的既有会话。删除会话会同时删除 LangGraph checkpoint 历史。

管理接口全部要求管理员认证。`POST /api/agent/tools/{toolName}` 默认关闭，仅在受控调试环境把 `ADMIN_TOOL_INVOKE_ENABLED=true` 后可用。

## 测试与 CI

```bash
.venv/Scripts/ruff check app tests scripts run.py   # lint
.venv/Scripts/python -m pytest -q                   # 76 个单测，全部 mock 外部依赖
```

GitHub Actions（`.github/workflows/ci.yml`）：push/PR 时自动跑 lint + pytest，不依赖任何中间件。

测试分层：工具层（mock MySQL/Redis/ES/LLM，覆盖降级分支）、API 层（TestClient + FakeAgent，覆盖限流/SSE/鉴权）、
RRF 纯逻辑、token 用量统计。

## RAG 评估

```bash
.venv/Scripts/python scripts/eval_rag.py             # 混合 vs BM25 vs 向量：延迟 + LLM 判官命中率
.venv/Scripts/python scripts/eval_rag.py --skip-judge
```

需 ES 向量索引已同步。数据集 `scripts/eval_dataset.json`（30 条自然语言查询），
LLM 判官逐条判断「检索结果能否回答查询」，输出各方法平均/P50/P95 延迟与命中率（`--out` 可导出 JSON）。

## ES 语义检索说明

- 索引：`movie_vec` / `review_vec`（dense_vector 1024 维 BGE-M3 + IK 分词文本字段，不动后端原索引）
- 同步：电影启动全量 + 每日一次；影评增量轮询（5 分钟，游标存 Redis `agent:sync:review:cursor`）
- 检索：BM25（与后端同加权）+ knn（cosine）+ **客户端 RRF 融合**（ES 8.15 基础版不支持服务端 RRF），ES 异常降级 MySQL LIKE
- embedding 结果按文本 md5 缓存 Redis 30 天，重同步不重复计费

## 架构

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

数据访问约定：读操作直连 MySQL/ES/Redis（192.168.100.129），写操作调后端 REST API（token 透传）。
Redis Key 统一 `agent:` 前缀，常量收敛于 `services/redis_client.py::AgentRedisKeys`。
