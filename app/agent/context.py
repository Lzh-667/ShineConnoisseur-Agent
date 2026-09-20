"""运行期上下文：通过 create_agent 的 context_schema 注入，工具用 ToolRuntime 读取。"""

from pydantic import BaseModel, Field


class AgentContext(BaseModel):
    user_id: int = 0
    thread_id: str = ""
    token: str = ""  # 后端登录 token（写操作透传用）
    page_context: dict = Field(default_factory=dict)  # 前端提供的非敏感页面上下文
