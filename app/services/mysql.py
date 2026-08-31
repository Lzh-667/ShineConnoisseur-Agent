"""MySQL 直连数据访问层：agent 所有只读工具的取数地基。

约定：
- 电影/影评/评论状态过滤：status=1 表示正常（影评 0=用户删除 2=封禁）
- 电影评分 = rating_sum / rating_count（保留 1 位小数）
- 分页 current 从 1 起，每页 10 条（与后端一致）
"""

from sqlalchemy import create_engine, text

from app.config.settings import settings

_engine = None

PAGE_SIZE = 10


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.mysql_url,
            pool_size=5,
            max_overflow=10,
            pool_recycle=3600,
            pool_pre_ping=True,
        )
    return _engine


def _rows(sql: str, **params) -> list[dict]:
    with get_engine().connect() as conn:
        result = conn.execute(text(sql), params)
        return [dict(r._mapping) for r in result]


def _row(sql: str, **params) -> dict | None:
    rows = _rows(sql, **params)
    return rows[0] if rows else None


def _movie_dict(row: dict) -> dict:
    count = row.get("rating_count") or 0
    total = row.get("rating_sum") or 0
    return {
        "id": row["id"],
        "title": row["title"],
        "originalTitle": row.get("original_title"),
        "cover": row.get("cover"),
        "director": row.get("director"),
        "actors": row.get("actors"),
        "genre": row.get("genre"),
        "region": row.get("region"),
        "language": row.get("language"),
        "releaseDate": str(row["release_date"]) if row.get("release_date") else None,
        "duration": row.get("duration"),
        "summary": row.get("summary"),
        "rating": round(total / count, 1) if count else 0,
        "ratingCount": count,
    }


def _review_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "rating": row["rating"],
        "title": row["title"],
        "content": row["content"],
        "spoiler": row["spoiler"],
        "userId": row["user_id"],
        "userName": row.get("username"),
        "nickName": row.get("nickname"),
        "avatar": row.get("avatar"),
        "likeCount": row["like_count"],
        "commentCount": row["comment_count"],
        "movieId": row["movie_id"],
        "movieTitle": row.get("movie_title"),
        "createTime": str(row["create_time"]) if row.get("create_time") else None,
    }


# ---------- 电影 ----------

MOVIE_COLUMNS = (
    "id, title, original_title, cover, director, actors, genre, region, language,"
    " release_date, duration, summary, rating_sum, rating_count"
)


def get_movie_by_id(movie_id: int) -> dict | None:
    row = _row(f"SELECT {MOVIE_COLUMNS} FROM movie WHERE id=:id AND status=1", id=movie_id)
    return _movie_dict(row) if row else None


def get_movies_by_ids(movie_ids: list[int]) -> list[dict]:
    if not movie_ids:
        return []
    rows = _rows(
        f"SELECT {MOVIE_COLUMNS} FROM movie WHERE id IN :ids AND status=1",
        ids=tuple(movie_ids),
    )
    by_id = {r["id"]: _movie_dict(r) for r in rows}
    return [by_id[i] for i in movie_ids if i in by_id]


def search_movies_like(keyword: str, genre: str | None, region: str | None,
                       current: int = 1) -> list[dict]:
    """MySQL LIKE 降级搜索（镜像后端 searchMovies 降级逻辑）。"""
    sql = f"SELECT {MOVIE_COLUMNS} FROM movie WHERE status=1 AND title LIKE :kw"
    params: dict = {"kw": f"%{keyword}%"}
    if genre:
        sql += " AND genre LIKE :genre"
        params["genre"] = f"%{genre}%"
    if region:
        sql += " AND region LIKE :region"
        params["region"] = f"%{region}%"
    sql += " ORDER BY release_date DESC LIMIT :limit OFFSET :offset"
    params["limit"] = PAGE_SIZE
    params["offset"] = (current - 1) * PAGE_SIZE
    return [_movie_dict(r) for r in _rows(sql, **params)]


# ---------- 影评 ----------

REVIEW_COLUMNS = (
    "r.id, r.user_id, r.movie_id, r.rating, r.title, r.content, r.spoiler,"
    " r.like_count, r.comment_count, r.create_time,"
    " u.username, u.nickname, u.avatar, m.title AS movie_title"
)


def list_reviews_by_movie(movie_id: int, current: int = 1) -> list[dict]:
    rows = _rows(
        f"SELECT {REVIEW_COLUMNS} FROM review r"
        " JOIN user u ON u.id = r.user_id"
        " JOIN movie m ON m.id = r.movie_id"
        " WHERE r.movie_id=:movie_id AND r.status=1"
        " ORDER BY r.like_count DESC, r.create_time DESC"
        " LIMIT :limit OFFSET :offset",
        movie_id=movie_id, limit=PAGE_SIZE, offset=(current - 1) * PAGE_SIZE,
    )
    return [_review_dict(r) for r in rows]


def get_review_by_id(review_id: int) -> dict | None:
    row = _row(
        f"SELECT {REVIEW_COLUMNS} FROM review r"
        " JOIN user u ON u.id = r.user_id"
        " JOIN movie m ON m.id = r.movie_id"
        " WHERE r.id=:rid AND r.status=1",
        rid=review_id,
    )
    return _review_dict(row) if row else None


def get_reviews_by_ids(review_ids: list[int]) -> list[dict]:
    if not review_ids:
        return []
    rows = _rows(
        f"SELECT {REVIEW_COLUMNS} FROM review r"
        " JOIN user u ON u.id = r.user_id"
        " JOIN movie m ON m.id = r.movie_id"
        " WHERE r.id IN :ids AND r.status=1",
        ids=tuple(review_ids),
    )
    by_id = {r["id"]: _review_dict(r) for r in rows}
    return [by_id[i] for i in review_ids if i in by_id]


def search_reviews_like(keyword: str, spoiler: int | None, current: int = 1) -> list[dict]:
    """MySQL LIKE 降级搜索（镜像后端 searchReviews 降级逻辑）。"""
    sql = (
        f"SELECT {REVIEW_COLUMNS} FROM review r"
        " JOIN user u ON u.id = r.user_id"
        " JOIN movie m ON m.id = r.movie_id"
        " WHERE r.status=1 AND (r.title LIKE :kw OR r.content LIKE :kw)"
    )
    params: dict = {"kw": f"%{keyword}%"}
    if spoiler is not None:
        sql += " AND r.spoiler=:spoiler"
        params["spoiler"] = spoiler
    sql += " ORDER BY r.like_count DESC, r.create_time DESC LIMIT :limit OFFSET :offset"
    params["limit"] = PAGE_SIZE
    params["offset"] = (current - 1) * PAGE_SIZE
    return [_review_dict(r) for r in _rows(sql, **params)]


def list_reviews_by_movie_all(movie_id: int, limit: int = 50) -> list[dict]:
    """某电影全部影评（总结/分析用，最多 limit 条）。"""
    rows = _rows(
        f"SELECT {REVIEW_COLUMNS} FROM review r"
        " JOIN user u ON u.id = r.user_id"
        " JOIN movie m ON m.id = r.movie_id"
        " WHERE r.movie_id=:movie_id AND r.status=1"
        " ORDER BY r.like_count DESC, r.create_time DESC LIMIT :limit",
        movie_id=movie_id, limit=limit,
    )
    return [_review_dict(r) for r in rows]


# ---------- 用户行为（推荐/画像用）----------

def get_user_favorite_movie_ids(user_id: int) -> list[int]:
    rows = _rows(
        "SELECT movie_id FROM movie_favorite WHERE user_id=:uid ORDER BY create_time DESC",
        uid=user_id,
    )
    return [r["movie_id"] for r in rows]


def get_user_rated_movies(user_id: int) -> list[dict]:
    return _rows(
        "SELECT movie_id, rating FROM review WHERE user_id=:uid AND status=1",
        uid=user_id,
    )
