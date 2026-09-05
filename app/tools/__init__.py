"""全部 agent 工具聚合导出。"""

from app.tools.creative_tools import CREATIVE_TOOLS
from app.tools.memory_tools import MEMORY_TOOLS
from app.tools.query_tools import QUERY_TOOLS
from app.tools.rag_tools import RAG_TOOLS
from app.tools.recommend_tools import RECOMMEND_TOOLS
from app.tools.summary_tools import SUMMARY_TOOLS

TOOLS = [
    *QUERY_TOOLS,
    *RAG_TOOLS,
    *RECOMMEND_TOOLS,
    *SUMMARY_TOOLS,
    *CREATIVE_TOOLS,
    *MEMORY_TOOLS,
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
