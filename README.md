# ShineConnoisseur Agent（光影鉴赏家 AI 助手）

电影影评社区平台的 AI Agent 服务，基于 **LangChain 1.x（create_agent）** + FastAPI。

## 能力规划（分阶段实施）

| 阶段 | 能力 | 状态 |
|------|------|------|
| 1 | 骨架 + 基础对话 + 查询工具（热门电影/热门影评/电影详情/影评列表/电影搜索/影评搜索） | ✅ 已完成 |
| 2 | ES 语义索引（BGE-M3 向量）+ RAG 混合检索（BM25+knn+RRF） | 待实施 |
| 3 | 推荐（条件/收藏/场景）+ 电影对比 + 观影计划 | 待实施 |
| 4 | 影评总结 + 正负面观点分析 + AI 辅助创作/发布 | 待实施 |
| 5 | 长期记忆（用户画像）+ 热门 tool 统计 + 打磨 | 待实施 |

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

统一响应格式 `{success, errorMsg, data, total}`（与后端一致），认证 header `authorization: <token>`（后端登录 token，无 Bearer）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agent/health` | 健康检查（mysql/redis/es/llm/embedding） |
| POST | `/api/agent/chat` | 非流式对话（body: `{threadId?, message, extra?}`） |
| POST | `/api/agent/chat/stream` | SSE 流式对话（event: message/tool/done/error） |
| GET | `/api/agent/sessions?current=` | 会话列表（需登录） |
| DELETE | `/api/agent/sessions/{threadId}` | 删除会话（需登录） |

## 架构

```
app/
├── api/          # FastAPI 路由（chat / sessions / admin）
├── agent/        # create_agent 组装：builder / checkpointer(SQLite) / system_prompt
├── tools/        # LangChain 工具（查询六件套起步，按阶段扩充）
├── rag/          # BGE-M3 embedding + ES 混合检索（阶段 2）
├── services/     # MySQL / Redis / ES / 后端 REST / 认证 / 会话
├── memory/       # 用户画像长期记忆（阶段 5）
└── prompts/      # 提示词模板（与代码分离）
```

数据访问约定：读操作直连 MySQL/ES/Redis（192.168.100.129），写操作调后端 REST API（token 透传）。
Redis Key 统一 `agent:` 前缀，常量收敛于 `services/redis_client.py::AgentRedisKeys`。
