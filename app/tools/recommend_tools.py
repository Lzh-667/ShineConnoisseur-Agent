"""能力2：推荐与对比工具。"""

from langchain.tools import ToolRuntime, tool

from app.services import recommendation
from app.tools.common import to_json


@tool
def recommend_by_conditions(genres: list[str] | None = None, min_rating: float = 0,
                            region: str | None = None, year_range: str | None = None,
                            count: int = 5) -> str:
    """按条件推荐电影：类型（genres，如 ["科幻","悬疑"]，任一命中即可）、最低评分
    （min_rating，1-10 分制）、地区（region，如 美国/日本）、年代（year_range，
    如 "1990-2000"、">2000"、"1994"）。按站内热度排序。count 为推荐条数（默认 5）。
    用户没有明确给条件时不要用这个工具，用 recommend_for_scene 或 recommend_by_favorites。"""
    results = recommendation.recommend_by_conditions(
        genres=genres, min_rating=min_rating, region=region,
        year_range=year_range, count=count)
    if not results:
        return "没有符合这些条件的电影，建议放宽条件（降低评分要求或去掉类型限制）再试"
    return to_json({"results": results})


@tool
def recommend_by_favorites(runtime: ToolRuntime, count: int = 5) -> str:
    """根据当前用户的收藏记录推荐电影：聚合用户收藏电影的类型偏好，推荐同类型且
    用户未收藏、未评分的电影。新用户（无收藏）自动按热度兜底推荐。count 为条数（默认 5）。"""
    user_id = runtime.context.user_id
    if user_id == 0:
        return "当前是游客，没有收藏记录。建议先按场景推荐（recommend_for_scene）或直接按条件推荐"
    data = recommendation.recommend_by_favorites(user_id, count)
    return to_json(data)


@tool
def recommend_for_scene(runtime: ToolRuntime, scene: str, count: int = 5) -> str:
    """按具体场景推荐电影：scene 为用户描述的场景或心情，如「周末和女朋友看」「全家一起看」
    「心情低落想被治愈」「想烧脑的悬疑片」「一个人深夜看」等。count 为条数（默认 5）。
    会自动排除用户已收藏的电影。"""
    exclude_ids: set[int] = set()
    user_id = runtime.context.user_id
    if user_id != 0:
        from app.services import mysql

        exclude_ids = set(mysql.get_user_favorite_movie_ids(user_id))
    data = recommendation.recommend_for_scene(scene, count, exclude_ids)
    return to_json(data)


@tool
def compare_movies(movie_ids: list[int]) -> str:
    """对比多部电影：movie_ids 为电影 id 列表（2-5 部）。
    返回各电影的评分、类型、地区、导演、演员、上映日期、片长、简介等字段，供对比呈现。"""
    if len(movie_ids) < 2:
        return "对比至少需要 2 部电影，请先用搜索/推荐工具找到电影 id"
    data = recommendation.compare_movies(movie_ids[:5])
    return to_json(data)


RECOMMEND_TOOLS = [
    recommend_by_conditions,
    recommend_by_favorites,
    recommend_for_scene,
    compare_movies,
]
