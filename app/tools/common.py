"""工具公共辅助：运行期上下文读取、结果格式化。"""

import json

from langchain.tools import ToolRuntime


def get_context(runtime: ToolRuntime):
    """读取 invoke 时注入的 AgentContext（含 user_id / thread_id）。"""
    return runtime.context


def to_json(data) -> str:
    """把工具结果序列化为 LLM 可读的 JSON 文本（中文不转义）。"""
    return json.dumps(data, ensure_ascii=False, default=str)


def to_error(msg: str) -> str:
    return f"查询失败：{msg}。请告知用户站内暂未收录或稍后重试。"
