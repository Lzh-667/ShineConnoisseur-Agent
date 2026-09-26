"""Prometheus 指标定义与低基数记录辅助。"""

from prometheus_client import Counter, Histogram, make_asgi_app

HTTP_REQUESTS = Counter(
    "shine_agent_http_requests_total",
    "Agent HTTP requests.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "shine_agent_http_request_duration_seconds",
    "Agent HTTP request latency.",
    ("method", "route"),
)
CHAT_REQUESTS = Counter(
    "shine_agent_chat_requests_total",
    "Chat requests by mode and outcome.",
    ("mode", "status"),
)
CHAT_DURATION = Histogram(
    "shine_agent_chat_duration_seconds",
    "End-to-end chat latency.",
    ("mode", "status"),
    buckets=(0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
CHAT_FIRST_TOKEN = Histogram(
    "shine_agent_chat_first_token_seconds",
    "Streaming chat time to first token.",
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
TOOL_CALLS = Counter(
    "shine_agent_tool_calls_total",
    "Agent tool calls by tool and outcome.",
    ("tool", "status"),
)
TOOL_DURATION = Histogram(
    "shine_agent_tool_duration_seconds",
    "Agent tool execution latency.",
    ("tool",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
LLM_TOKENS = Counter(
    "shine_agent_llm_tokens_total",
    "LLM tokens consumed by direction.",
    ("direction",),
)
RAG_SEARCHES = Counter(
    "shine_agent_rag_searches_total",
    "RAG searches by method and outcome.",
    ("method", "status"),
)
RAG_SEARCH_DURATION = Histogram(
    "shine_agent_rag_search_duration_seconds",
    "RAG search latency by method.",
    ("method",),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
SYNC_RUNS = Counter(
    "shine_agent_sync_runs_total",
    "Background synchronization runs by kind and outcome.",
    ("kind", "status"),
)
SYNC_DURATION = Histogram(
    "shine_agent_sync_duration_seconds",
    "Background synchronization latency.",
    ("kind",),
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)


def metrics_app():
    """创建 Prometheus ASGI exporter，挂载到 `/metrics`。"""
    return make_asgi_app()
