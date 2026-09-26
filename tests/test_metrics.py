"""Prometheus 暴露端点与核心指标冒烟测试。"""


def test_metrics_endpoint_exposes_agent_metrics(client):
    client.get("/openapi.json")
    response = client.get("/metrics/")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "shine_agent_http_requests_total" in response.text
    assert "shine_agent_chat_duration_seconds" in response.text
    assert "shine_agent_tool_calls_total" in response.text
    assert "shine_agent_rag_search_duration_seconds" in response.text
