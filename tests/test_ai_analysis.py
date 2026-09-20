"""AI 分析测试：不请求真实 DeepSeek，验证上下文、密钥处理和响应解析。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quant_demo.data.realtime import RealtimeQuote
from quant_demo.web.ai_analysis import call_deepseek
from quant_demo.web.server import ApiError, QuantDemoApplication


ROOT = Path(__file__).parents[1]


def application() -> QuantDemoApplication:
    return QuantDemoApplication(
        ROOT / "config/demo.json",
        ROOT / "examples/demo_daily.csv",
        enable_realtime=True,
    )


@patch("quant_demo.web.server.get_realtime_quotes")
def test_market_snapshot_prefers_network_quote(mock_quotes: MagicMock) -> None:
    mock_quotes.return_value = {
        "510300.SH": RealtimeQuote(
            "510300.SH", "沪深300ETF", 4.58, 4.53, 4.55, 4.60, 4.52, 1000, "20260918150000"
        )
    }

    result = application().market_snapshot("510300.SH")

    assert result["is_realtime_quote"] is True
    assert result["price"] == 4.58
    assert result["quote_time"] == "20260918150000"
    assert result["return_20d"] is not None
    assert "财务" in result["limitations"]


@patch("quant_demo.web.ai_analysis.urllib.request.urlopen")
def test_deepseek_key_is_only_sent_as_bearer_header(mock_urlopen: MagicMock) -> None:
    response = MagicMock()
    response.read.return_value = json.dumps(
        {
            "model": "deepseek-flash",
            "choices": [{"message": {"content": "分析结果"}}],
            "usage": {"total_tokens": 123},
        }
    ).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = response

    result = call_deepseek("sk-secret", "510300.SH", "分析风险", {"price": 4.58})
    request = mock_urlopen.call_args.args[0]
    body = json.loads(request.data.decode("utf-8"))

    assert request.get_header("Authorization") == "Bearer sk-secret"
    assert "sk-secret" not in json.dumps(body, ensure_ascii=False)
    assert body["model"] == "deepseek-flash"
    assert result["answer"] == "分析结果"


def test_ai_analysis_requires_key_and_question() -> None:
    with pytest.raises(ApiError, match="API Key"):
        application().analyze_symbol(
            {"symbol": "510300.SH", "api_key": "", "question": "分析风险"}
        )
