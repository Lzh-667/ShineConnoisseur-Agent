"""推荐引擎纯逻辑单元测试（不依赖外部中间件）。"""

from app.services.recommendation import _in_year_range, hot_score, match_scene


def _movie(release_date=None, rating_count=0, rating_sum=0, genre="", region=""):
    return {"id": 1, "title": "t", "releaseDate": release_date,
            "ratingCount": rating_count, "ratingSum": rating_sum,
            "rating": 0, "genre": genre, "region": region}


def test_in_year_range_range():
    m = _movie(release_date="1994-09-10")
    assert _in_year_range(m, "1990-2000")
    assert not _in_year_range(m, "2000-2010")
    assert _in_year_range(m, "1994")
    assert not _in_year_range(m, "1995")
    assert _in_year_range(m, ">1990")
    assert not _in_year_range(m, ">2000")
    assert _in_year_range(m, "<2000")
    assert not _in_year_range(m, "<1990")
    assert _in_year_range(m, None)
    assert _in_year_range(m, "随便写的")


def test_in_year_range_no_date():
    assert _in_year_range(_movie(), "1990-2000")


def test_hot_score():
    assert hot_score(_movie(rating_count=5, rating_sum=40)) == 5 * 10 + 40


def test_match_scene():
    template, name = match_scene("周末和女朋友看什么")
    assert name == "约会"
    assert "爱情" in template["genres"]
    assert "恐怖" in template["exclude_genres"]

    template, name = match_scene("想烧脑的悬疑片")
    assert name == "悬疑"
    assert "悬疑" in template["genres"]

    template, name = match_scene("随便看看")
    assert name == "通用"
    assert template["genres"] == []


def test_match_scene_healing_excludes_thriller():
    template, _ = match_scene("心情低落想被治愈")
    assert "惊悚" in template["exclude_genres"]
    assert "悬疑" in template["exclude_genres"]
