"""LLM 工厂与直调辅助（独立模块，避免 tools ↔ builder 循环导入）。"""

from functools import lru_cache

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.config.settings import settings


@lru_cache
def get_llm() -> ChatOpenAI:
    """主循环模型（支持 function calling）。"""
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.7,
        timeout=60,
        max_retries=2,
    )


@lru_cache
def get_reasoner_llm() -> ChatOpenAI:
    """纯文本任务模型（总结/分析/创作），不支持 function calling，不进 agent 工具循环。"""
    return ChatOpenAI(
        model=settings.deepseek_reasoner_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.3,
        timeout=120,
        max_retries=2,
    )


def call_llm(llm: ChatOpenAI, prompt: str) -> str:
    resp = llm.invoke([HumanMessage(content=prompt)])
    return resp.content if isinstance(resp.content, str) else str(resp.content)
