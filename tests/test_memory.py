"""画像摘要生成纯逻辑测试。"""

from app.memory.extractor import _summarize


def test_summarize_full():
    prefs = {
        "genrePrefs": {"科幻": 3, "剧情": 1},
        "directorPrefs": {"诺兰": 2},
        "ratingTendency": {"avg": 8.5, "count": 4, "min": 7, "max": 10},
        "favoriteCount": 5,
    }
    s = _summarize(prefs)
    assert "科幻" in s and "剧情" in s
    assert "诺兰" in s
    assert "8.5" in s
    assert "5 部" in s


def test_summarize_empty():
    prefs = {
        "genrePrefs": {}, "directorPrefs": {},
        "ratingTendency": {"avg": 0, "count": 0, "min": 0, "max": 0},
        "favoriteCount": 0,
    }
    assert _summarize(prefs) == "暂无足够行为数据"
