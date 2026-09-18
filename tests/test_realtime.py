"""实时行情模块测试：解析器（离线，注入应答）+ 代码映射。"""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from quant_demo.data.realtime import (
    RealtimeQuote,
    _from_tencent_code,
    _to_tencent_code,
    get_realtime_quotes,
)


class TestCodeMapping:
    def test_to_tencent_code(self) -> None:
        assert _to_tencent_code("600000.SH") == "sh600000"
        assert _to_tencent_code("000001.SZ") == "sz000001"
        assert _to_tencent_code("0700.HK") == "hk00700"
        assert _to_tencent_code("AAPL.US") == "usAAPL.OQ"

    def test_from_tencent_code(self) -> None:
        assert _from_tencent_code("sh600000") == "600000.SH"
        assert _from_tencent_code("hk00700") == "0700.HK"      # 5位补零 -> 内部4位约定
        assert _from_tencent_code("hk09988") == "9988.HK"

    def test_invalid_symbol(self) -> None:
        with pytest.raises(ValueError):
            _to_tencent_code("600000.TW")


# 构造与真实接口一致的应答：~分隔，关键位次 3现价 4昨收 5今开 6成交量 30时间 33最高 34最低
def _row(code: str, name: str, price: str, pre: str, open_: str,
         vol: str, ts: str, high: str, low: str) -> str:
    f = ["1", name, code[2:], price, pre, open_, vol] + [""] * 23
    f.append(ts)          # 30
    f += ["", ""]         # 31 32
    f += [high, low]      # 33 34
    return f'v_{code}="' + "~".join(f) + '";'


_SAMPLE = (
    _row("sh600000", "浦发银行", "9.07", "9.06", "9.05", "517593", "20260918161458", "9.15", "9.00") + "\n"
    + _row("sh600900", "长江电力", "28.27", "28.46", "28.33", "718975", "20260918161432", "28.60", "28.10") + "\n"
    + _row("sz000001", "停牌股", "0.00", "0.00", "0.00", "0", "20260918160000", "0.00", "0.00") + "\n"
)


class TestParser:
    @patch("quant_demo.data.realtime.urllib.request.urlopen")
    def test_parses_normal_quotes(self, mock_urlopen) -> None:
        mock_urlopen.return_value = SimpleNamespace(
            read=lambda: _SAMPLE.encode("gbk")
        )
        quotes = get_realtime_quotes(["600000.SH", "600900.SH", "000001.SZ"])
        assert set(quotes) == {"600000.SH", "600900.SH"}   # 停牌股被剔除
        q = quotes["600000.SH"]
        assert isinstance(q, RealtimeQuote)
        assert q.name == "浦发银行"
        assert q.price == 9.07
        assert q.pre_close == 9.06
        assert q.open == 9.05
        assert q.time == "20260918161458"

    @patch("quant_demo.data.realtime.urllib.request.urlopen")
    def test_empty_response(self, mock_urlopen) -> None:
        mock_urlopen.return_value = SimpleNamespace(read=lambda: b"")
        assert get_realtime_quotes(["600000.SH"]) == {}

    def test_empty_symbols(self) -> None:
        assert get_realtime_quotes([]) == {}
