"""LangChain 1.x create_agent 组装：model + tools + middleware + checkpointer + 运行期上下文。"""

from functools import lru_cache

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware

from app.agent.checkpointer import create_checkpointer
from app.agent.context import AgentContext
from app.agent.llm import get_llm
from app.agent.middleware import ProfileInjectionMiddleware, ToolUsageMiddleware
from app.agent.system_prompt import load_system_prompt
from app.tools import TOOLS


@lru_cache
def get_agent():
    return create_agent(
        model=get_llm(),
        tools=TOOLS,
        system_prompt=load_system_prompt(),
        middleware=[
            ProfileInjectionMiddleware(),
            ToolUsageMiddleware(),
            SummarizationMiddleware(
                model=get_llm(),
                trigger=("tokens", 60000),
                keep=("messages", 20),
            ),
        ],
        checkpointer=create_checkpointer(),
        context_schema=AgentContext,
    )
