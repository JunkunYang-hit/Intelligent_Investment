"""策略模块共享的技术指标函数库。

约定：

- 只使用 Python 标准库，不依赖 pandas / numpy / TA-Lib；
- 输入为按时间升序排列的价格序列，输出与输入等长；
- 预热期（历史数据不足的位置）以 ``None`` 占位，不返回 NaN；
- ``result[i]`` 只依赖 ``values[:i+1]``，天然无未来数据泄漏；
- 输入序列为空时返回空列表。
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import pstdev
from typing import NamedTuple, Optional

# result[i] 为 None 表示第 i 根 Bar 时指标尚未度过预热期。
Series = list[Optional[float]]


class MacdResult(NamedTuple):
    """MACD 三条曲线，均与输入价格序列等长。"""

    macd: Series
    signal: Series
    histogram: Series


class BollingerBands(NamedTuple):
    """布林带三条轨道，均与输入价格序列等长。"""

    middle: Series
    upper: Series
    lower: Series


class StochasticResult(NamedTuple):
    """随机指标 %K 与 %D 两条曲线，均与输入价格序列等长。"""

    k: Series
    d: Series


def _require_same_length(*series: Sequence[float]) -> None:
    lengths = {len(item) for item in series}
    if len(lengths) > 1:
        raise ValueError("输入序列长度必须一致")


def sma(values: Sequence[float], window: int) -> Series:
    """简单移动平均：``result[i] = mean(values[i-window+1 .. i])``。

    前 ``window - 1`` 个位置为 None。``window`` 必须大于 0。
    """
    if window < 1:
        raise ValueError("window 必须大于 0")
    result: Series = [None] * len(values)
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            result[i] = running / window
    return result


def ema(values: Sequence[float], period: int) -> Series:
    """指数移动平均，平滑系数 ``alpha = 2 / (period + 1)``。

    首个有效值取前 ``period`` 个数据的 SMA 作为种子，之后按
    ``ema[i] = alpha * values[i] + (1 - alpha) * ema[i-1]`` 递推。
    前 ``period - 1`` 个位置为 None。``period`` 必须大于 0。
    """
    if period < 1:
        raise ValueError("period 必须大于 0")
    result: Series = [None] * len(values)
    if len(values) < period:
        return result
    alpha = 2.0 / (period + 1)
    previous = sum(values[:period]) / period
    result[period - 1] = previous
    for i in range(period, len(values)):
        previous = alpha * values[i] + (1.0 - alpha) * previous
        result[i] = previous
    return result


def rsi(values: Sequence[float], period: int = 14) -> Series:
    """Wilder 相对强弱指标，取值范围 [0, 100]。

    基于相邻收盘价涨跌幅，平均涨跌幅按 Wilder 平滑递推。首个有效值出现在
    索引 ``period``（需要 ``period + 1`` 个价格），之前的位置为 None。
    平均跌幅为 0 时：平均涨幅也为 0 返回 50（多空平衡），否则返回 100。
    ``period`` 必须大于 0。
    """
    if period < 1:
        raise ValueError("period 必须大于 0")
    result: Series = [None] * len(values)
    if len(values) <= period:
        return result
    total_gain = 0.0
    total_loss = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        if change > 0:
            total_gain += change
        else:
            total_loss -= change
    average_gain = total_gain / period
    average_loss = total_loss / period
    result[period] = _rsi_value(average_gain, average_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        gain = change if change > 0 else 0.0
        loss = -change if change < 0 else 0.0
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
        result[i] = _rsi_value(average_gain, average_loss)
    return result


def _rsi_value(average_gain: float, average_loss: float) -> float:
    if average_loss == 0.0:
        return 50.0 if average_gain == 0.0 else 100.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def macd(
    values: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MacdResult:
    """MACD：快线（fast EMA - slow EMA）、信号线（快线的 EMA）与柱线。

    快线首个有效值在索引 ``slow_period - 1``；信号线首个有效值在索引
    ``slow_period + signal_period - 2``；柱线 = 快线 - 信号线。
    必须满足 ``0 < fast_period < slow_period`` 且 ``signal_period > 0``。
    """
    if fast_period < 1 or slow_period < 1 or signal_period < 1:
        raise ValueError("fast_period、slow_period、signal_period 都必须大于 0")
    if fast_period >= slow_period:
        raise ValueError("fast_period 必须小于 slow_period")
    fast = ema(values, fast_period)
    slow = ema(values, slow_period)
    macd_line: Series = [
        f - s if f is not None and s is not None else None for f, s in zip(fast, slow)
    ]
    signal_line: Series = [None] * len(values)
    first_valid = next((i for i, item in enumerate(macd_line) if item is not None), len(values))
    valid_tail = macd_line[first_valid:]
    for offset, item in enumerate(ema([v for v in valid_tail if v is not None], signal_period)):
        signal_line[first_valid + offset] = item
    histogram: Series = [
        m - s if m is not None and s is not None else None
        for m, s in zip(macd_line, signal_line)
    ]
    return MacdResult(macd=macd_line, signal=signal_line, histogram=histogram)


def bollinger_bands(
    values: Sequence[float],
    period: int = 20,
    std_multiplier: float = 2.0,
) -> BollingerBands:
    """布林带：中轨为 SMA，上下轨为中轨加减 ``std_multiplier`` 倍总体标准差。

    首个有效值在索引 ``period - 1``。必须满足 ``period > 1`` 且
    ``std_multiplier > 0``。
    """
    if period < 2:
        raise ValueError("period 必须大于 1")
    if std_multiplier <= 0:
        raise ValueError("std_multiplier 必须大于 0")
    middle = sma(values, period)
    upper: Series = [None] * len(values)
    lower: Series = [None] * len(values)
    for i, center in enumerate(middle):
        if center is None:
            continue
        deviation = pstdev(values[i - period + 1 : i + 1])
        upper[i] = center + std_multiplier * deviation
        lower[i] = center - std_multiplier * deviation
    return BollingerBands(middle=middle, upper=upper, lower=lower)


def momentum(values: Sequence[float], lookback: int) -> Series:
    """N 日动量：``result[i] = values[i] / values[i-lookback] - 1``。

    前 ``lookback`` 个位置为 None。``lookback`` 必须大于 0；
    基准价格（``values[i-lookback]``）必须大于 0。
    """
    if lookback < 1:
        raise ValueError("lookback 必须大于 0")
    result: Series = [None] * len(values)
    for i in range(lookback, len(values)):
        base = values[i - lookback]
        if base <= 0:
            raise ValueError("动量基准价格必须大于 0")
        result[i] = values[i] / base - 1.0
    return result


def highest(values: Sequence[float], window: int) -> Series:
    """滚动最高值：``result[i] = max(values[i-window+1 .. i])``。

    前 ``window - 1`` 个位置为 None。``window`` 必须大于 0。
    """
    if window < 1:
        raise ValueError("window 必须大于 0")
    result: Series = [None] * len(values)
    for i in range(window - 1, len(values)):
        result[i] = max(values[i - window + 1 : i + 1])
    return result


def lowest(values: Sequence[float], window: int) -> Series:
    """滚动最低值：``result[i] = min(values[i-window+1 .. i])``。

    前 ``window - 1`` 个位置为 None。``window`` 必须大于 0。
    """
    if window < 1:
        raise ValueError("window 必须大于 0")
    result: Series = [None] * len(values)
    for i in range(window - 1, len(values)):
        result[i] = min(values[i - window + 1 : i + 1])
    return result


def true_range(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> Series:
    """真实波幅 TR，首个有效值在索引 0（等于当日 high - low）。

    ``TR[0] = highs[0] - lows[0]``；之后
    ``TR[i] = max(high-low, |high-prev_close|, |low-prev_close|)``。
    三条输入序列长度必须一致。
    """
    _require_same_length(highs, lows, closes)
    result: Series = [None] * len(highs)
    for i in range(len(highs)):
        if i == 0:
            result[i] = highs[0] - lows[0]
        else:
            previous_close = closes[i - 1]
            result[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - previous_close),
                abs(lows[i] - previous_close),
            )
    return result


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> Series:
    """Wilder 平均真实波幅 ATR。

    首个有效值在索引 ``period - 1``，取前 ``period`` 个 TR 的算术平均作为种子，
    之后按 ``atr[i] = (atr[i-1] * (period - 1) + TR[i]) / period`` 递推。
    ``period`` 必须大于 0；三条输入序列长度必须一致。
    """
    if period < 1:
        raise ValueError("period 必须大于 0")
    tr = true_range(highs, lows, closes)
    result: Series = [None] * len(highs)
    if len(highs) < period:
        return result
    values = [item for item in tr if item is not None]
    previous = sum(values[:period]) / period
    result[period - 1] = previous
    for i in range(period, len(highs)):
        previous = (previous * (period - 1) + values[i]) / period
        result[i] = previous
    return result


def stochastic(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    k_period: int = 14,
    d_period: int = 3,
) -> StochasticResult:
    """随机指标（Stochastic Oscillator）%K 与 %D，取值范围 [0, 100]。

    ``%K[i] = (close - 窗口最低价) / (窗口最高价 - 窗口最低价) * 100``，
    窗口内最高价为 0 价差时返回 50（多空平衡）；%D 为 %K 的 ``d_period`` 日 SMA。
    %K 首个有效值在索引 ``k_period - 1``，%D 首个有效值在索引
    ``k_period + d_period - 2``。``k_period``、``d_period`` 必须大于 0；
    三条输入序列长度必须一致。
    """
    if k_period < 1 or d_period < 1:
        raise ValueError("k_period、d_period 都必须大于 0")
    _require_same_length(highs, lows, closes)
    k_line: Series = [None] * len(closes)
    for i in range(k_period - 1, len(closes)):
        window_high = max(highs[i - k_period + 1 : i + 1])
        window_low = min(lows[i - k_period + 1 : i + 1])
        price_range = window_high - window_low
        if price_range == 0.0:
            k_line[i] = 50.0
        else:
            k_line[i] = (closes[i] - window_low) / price_range * 100.0
    d_line: Series = [None] * len(closes)
    first_valid = k_period - 1
    valid_tail = [item for item in k_line[first_valid:] if item is not None]
    for offset, item in enumerate(sma(valid_tail, d_period)):
        d_line[first_valid + offset] = item
    return StochasticResult(k=k_line, d=d_line)


def rolling_std(values: Sequence[float], window: int) -> Series:
    """滚动总体标准差：``result[i] = pstdev(values[i-window+1 .. i])``。

    前 ``window - 1`` 个位置为 None。``window`` 必须大于 1。
    """
    if window < 2:
        raise ValueError("window 必须大于 1")
    result: Series = [None] * len(values)
    for i in range(window - 1, len(values)):
        result[i] = pstdev(values[i - window + 1 : i + 1])
    return result


def zscore(values: Sequence[float], window: int) -> Series:
    """滚动 Z 分数：``result[i] = (values[i] - 窗口均值) / 窗口总体标准差``。

    窗口标准差为 0（价格完全不变）时返回 0（无偏离）。前 ``window - 1``
    个位置为 None。``window`` 必须大于 1。
    """
    if window < 2:
        raise ValueError("window 必须大于 1")
    means = sma(values, window)
    deviations = rolling_std(values, window)
    result: Series = [None] * len(values)
    for i in range(len(values)):
        mean = means[i]
        deviation = deviations[i]
        if mean is None or deviation is None:
            continue
        result[i] = 0.0 if deviation == 0.0 else (values[i] - mean) / deviation
    return result
