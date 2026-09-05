"""能力3：影评总结与正负面观点分析（内部用 deepseek-v4-flash 直调）。"""

import json

from langchain.tools import tool

from app.agent.llm import call_llm, get_reasoner_llm
from app.agent.system_prompt import load_prompt
from app.services import mysql


def _format_reviews(reviews: list[dict]) -> str:
    lines = []
    for r in reviews:
        lines.append(
            f"- [{r['nickName'] or '匿名'}] 评分 {r['rating']}/10，"
            f"点赞 {r['likeCount']}，标题《{r['title']}》：{r['content'][:400]}")
    return "\n".join(lines) or "（无）"


def _fetch(movie_id: int) -> tuple[str, list[dict]]:
    movie = mysql.get_movie_by_id(movie_id)
    if not movie:
        return "", []
    reviews = mysql.list_reviews_by_movie_all(movie_id, limit=50)
    return movie["title"], reviews


@tool
def summarize_reviews(movie_id: int, focus: str | None = None) -> str:
    """总结某部电影的站内影评：整体口碑、评分倾向、高赞观点、共识优点与批评点。
    参数 movie_id 为电影 id；focus 可选，指定关注的维度（如 剧情/演技/画面）。"""
    movie_title, reviews = _fetch(movie_id)
    if not movie_title:
        return f"电影(id:{movie_id})不存在或已下架"
    if not reviews:
        return f"《{movie_title}》暂无影评，无法总结。可建议用户先看看电影详情，或成为第一个写影评的人"

    prompt = load_prompt("summary.md").format(
        movie_title=movie_title,
        reviews=_format_reviews(reviews),
    )
    if focus:
        prompt += f"\n本次总结请重点围绕「{focus}」展开。"
    if len(reviews) < 3:
        prompt += "\n注意：影评数量较少，总结中要注明「站内影评较少，结论仅供参考」。"

    text = call_llm(get_reasoner_llm(), prompt)
    return (f"《{movie_title}》影评总结（共 {len(reviews)} 条影评）：\n" + text)


@tool
def analyze_review_sentiment(movie_id: int) -> str:
    """分析某部电影影评的正负面观点：输出 JSON，含 overview（口碑概括）、
    positive/negative/mixed（具体观点列表）、ratingStats（平均分/数量/最高最低分）。
    参数 movie_id 为电影 id。"""
    movie_title, reviews = _fetch(movie_id)
    if not movie_title:
        return f"电影(id:{movie_id})不存在或已下架"
    if not reviews:
        return json.dumps(
            {"overview": f"《{movie_title}》暂无影评", "positive": [], "negative": [],
             "mixed": [], "ratingStats": {"avg": 0, "count": 0, "high": 0, "low": 0}},
            ensure_ascii=False)

    prompt = load_prompt("sentiment.md").format(
        movie_title=movie_title,
        reviews=_format_reviews(reviews),
    )
    text = call_llm(get_reasoner_llm(), prompt)
    parsed = _parse_json(text)
    if parsed is not None:
        return json.dumps(parsed, ensure_ascii=False)
    return text


def _parse_json(text: str) -> dict | None:
    """宽松解析 LLM 输出的 JSON（容忍 markdown 代码块包裹）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


SUMMARY_TOOLS = [summarize_reviews, analyze_review_sentiment]
