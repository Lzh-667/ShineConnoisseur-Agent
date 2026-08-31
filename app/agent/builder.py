"""LangChain 1.x create_agent 组装：model + tools + checkpointer + 运行期上下文。"""

from functools import lru_cache

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agent.checkpointer import create_checkpointer
from app.agent.context import AgentContext
from app.agent.system_prompt import load_system_prompt
from app.config.settings import settings
from app.tools import TOOLS


@lru_cache
def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.7,
        timeout=60,
        max_retries=2,
    )


@lru_cache
def get_agent():
    return create_agent(
        model=get_llm(),
        tools=TOOLS,
        system_prompt=load_system_prompt(),
        checkpointer=create_checkpointer(),
        context_schema=AgentContext,
    )
