"""运行期上下文：通过 create_agent 的 context_schema 注入，工具用 ToolRuntime 读取。"""

from pydantic import BaseModel


class AgentContext(BaseModel):
    user_id: int = 0
    thread_id: str = ""
