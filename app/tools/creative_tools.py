"""能力4：AI 辅助创作（影评草稿/标题）与发布（走后端 REST）。"""

from langchain.tools import ToolRuntime, tool

from app.agent.llm import call_llm, get_llm
from app.agent.system_prompt import load_prompt
from app.services import mysql
from app.services.backend_api import post_backend
from app.tools.common import to_json


def _movie_context(movie_id: int) -> tuple[dict | None, str]:
    """电影详情 + 已有影评片段，作为创作参考上下文（RAG 注入）。"""
    movie = mysql.get_movie_by_id(movie_id)
    if not movie:
        return None, ""
    reviews = mysql.list_reviews_by_movie_all(movie_id, limit=3)
    ctx = (f"片名：{movie['title']}\n"
           f"类型：{movie.get('genre', '')}\n"
           f"导演：{movie.get('director', '')}\n"
           f"主演：{movie.get('actors', '')}\n"
           f"上映：{movie.get('releaseDate', '')}\n"
           f"简介：{movie.get('summary', '')}")
    if reviews:
        refs = "\n".join(f"- 已有影评《{r['title']}》(评分{r['rating']}): {r['content'][:150]}"
                         for r in reviews)
        ctx += f"\n\n站内已有影评参考：\n{refs}"
    return movie, ctx


@tool
def draft_review(movie_id: int, user_prompt: str | None = None,
                 rating: int | None = None) -> str:
    """根据电影信息和站内已有影评，帮用户起草一篇 200-400 字的影评。
    参数 movie_id 为电影 id；user_prompt 为用户的要求（如 风格/角度/字数/想强调的点）；
    rating 可选，用户想给的评分（1-10），草稿口吻会与之匹配。"""
    movie, ctx = _movie_context(movie_id)
    if not movie:
        return f"电影(id:{movie_id})不存在或已下架"

    prompt = load_prompt("review_draft.md").format(
        user_prompt=user_prompt or "无特殊要求，按你的专业判断写",
        rating=f"{rating} 分" if rating else "未定，草稿中不要出现具体分数",
        context=ctx,
    )
    text = call_llm(get_llm(), prompt)
    return f"《{movie['title']}》影评草稿（{len(text)}字）：\n" + text


@tool
def generate_review_title(movie_id: int, content: str | None = None) -> str:
    """为影评起标题：给出 3 个候选标题。参数 movie_id 为电影 id；
    content 可选，影评正文（有则结合正文起题）。"""
    movie = mysql.get_movie_by_id(movie_id)
    if not movie:
        return f"电影(id:{movie_id})不存在或已下架"

    prompt = load_prompt("title.md").format(
        movie_title=movie["title"],
        genre=movie.get("genre", ""),
        content=content or "（无正文，基于电影本身起题）",
    )
    text = call_llm(get_llm(), prompt)
    return f"《{movie['title']}》候选标题：\n" + text


@tool
def publish_review(runtime: ToolRuntime, movie_id: int, title: str, content: str,
                   rating: int, spoiler: int = 0) -> str:
    """把影评发布到站内（真实写入后端数据库）。**调用前必须已获得用户的明确确认**，
    并向用户复述将要发布的内容概要。参数：movie_id 电影 id；title 标题；content 正文；
    rating 评分 1-10；spoiler 是否剧透 0否/1是。发布后电影评分计数会更新。"""
    user = runtime.context
    if user.user_id == 0:
        return "发布失败：当前是游客，请先登录后再发布影评"
    if not (1 <= rating <= 10):
        return "发布失败：评分必须在 1-10 之间"

    resp = post_backend(
        f"/reviews/publish/{movie_id}",
        body={"rating": rating, "title": title, "content": content, "spoiler": spoiler},
        token=user.token,
    )
    if resp.get("success"):
        return "发布成功！影评已上线，可在站内「我的影评」中查看"
    err = resp.get("errorMsg") or "未知错误"
    if "数据已存在" in err:
        return ("发布失败：你在该电影下已经发布过影评（每人每片限一条）。"
                "如需修改请到站内编辑，我可以帮你重新起草内容")
    return f"发布失败：{err}"


CREATIVE_TOOLS = [draft_review, generate_review_title, publish_review]
