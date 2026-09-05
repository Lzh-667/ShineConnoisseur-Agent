"""总结工具 JSON 宽松解析测试。"""

from app.tools.summary_tools import _parse_json


def test_parse_plain_json():
    assert _parse_json('{"a": 1}') == {"a": 1}


def test_parse_markdown_wrapped():
    text = '```json\n{"overview": "好评", "positive": ["好"]}\n```'
    assert _parse_json(text)["overview"] == "好评"


def test_parse_json_with_surrounding_text():
    text = '分析结果如下：{"overview": "ok", "negative": []}（完）'
    assert _parse_json(text)["overview"] == "ok"


def test_parse_invalid_returns_none():
    assert _parse_json("这不是 JSON") is None
    assert _parse_json("") is None
