"""
Technical Indicators Engine
Pure Python — no external dependencies.
Computes RSI, EMA, MACD, Bollinger Bands, ATR from price tick history.
Also handles candle aggregation (ticks → OHLCV) and cross-token correlation.
"""
import math
from collections import deque
from typing import Optional


# ─── EMA ──────────────────────────────────────────────────────────────────────

def ema(prices: list[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    val = sum(prices[:period]) / period   # SMA seed
    for p in prices[period:]:
        val = p * k + val * (1 - k)
    return val


# ─── RSI ──────────────────────────────────────────────────────────────────────

def rsi(prices: list[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ─── MACD ─────────────────────────────────────────────────────────────────────

def macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> Optional[dict]:
    if len(prices) < slow + signal_period:
        return None

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    if ema_fast is None or ema_slow is None:
        return None

    macd_line = ema_fast - ema_slow

    # Build MACD line history for signal calculation
    macd_history = []
    for i in range(slow, len(prices) + 1):
        ef = ema(prices[:i], fast)
        es = ema(prices[:i], slow)
        if ef and es:
            macd_history.append(ef - es)

    signal_line = ema(macd_history, signal_period) if len(macd_history) >= signal_period else None
    histogram   = macd_line - signal_line if signal_line is not None else None

    return {
        "macd":      round(macd_line, 8),
        "signal":    round(signal_line, 8) if signal_line else None,
        "histogram": round(histogram, 8)   if histogram  else None,
        "bullish":   histogram > 0 if histogram is not None else None,
    }


# ─── Bollinger Bands ──────────────────────────────────────────────────────────

def bollinger(prices: list[float], period: int = 20, std_mult: float = 2.0) -> Optional[dict]:
    if len(prices) < period:
        return None

    window = prices[-period:]
    sma    = sum(window) / period
    std    = math.sqrt(sum((p - sma) ** 2 for p in window) / period)
    upper  = sma + std_mult * std
    lower  = sma - std_mult * std
    last   = prices[-1]
    bw     = (upper - lower) / sma if sma else 0   # bandwidth

    # %B: where is price within the band (0 = lower, 1 = upper)
    pct_b  = (last - lower) / (upper - lower) if (upper - lower) else 0.5

    return {
        "upper":    round(upper, 8),
        "middle":   round(sma, 8),
        "lower":    round(lower, 8),
        "bandwidth": round(bw * 100, 4),   # as %
        "pctB":     round(pct_b, 4),
        "overbought": pct_b > 0.95,
        "oversold":   pct_b < 0.05,
    }


# ─── All indicators combined ──────────────────────────────────────────────────

def compute_all(prices: list[float]) -> dict:
    """
    Run all indicators on a price history list.
    Returns a flat dict suitable for embedding in Nemotron prompts.
    """
    result: dict = {}

    rsi_val = rsi(prices)
    result["rsi"] = rsi_val
    if rsi_val is not None:
        result["rsiState"] = (
            "OVERSOLD"   if rsi_val < 30 else
            "OVERBOUGHT" if rsi_val > 70 else
            "NEUTRAL"
        )

    ema9  = ema(prices, 9)
    ema21 = ema(prices, 21)
    result["ema9"]  = round(ema9,  8) if ema9  else None
    result["ema21"] = round(ema21, 8) if ema21 else None
    if ema9 and ema21:
        result["emaCross"] = "GOLDEN" if ema9 > ema21 else "DEATH"

    macd_data = macd(prices)
    result["macd"] = macd_data

    bb = bollinger(prices)
    result["bollinger"] = bb

    # Simple momentum (last 5 ticks)
    if len(prices) >= 5:
        mom = (prices[-1] - prices[-5]) / prices[-5] * 100 if prices[-5] else 0
        result["momentum5"] = round(mom, 4)

    # Volatility proxy (std dev of last 20 ticks as % of mean)
    if len(prices) >= 20:
        window = prices[-20:]
        mean   = sum(window) / len(window)
        std    = math.sqrt(sum((p - mean) ** 2 for p in window) / len(window))
        result["volatility"] = round(std / mean * 100, 4) if mean else 0

    return result


# ─── Cross-token correlation ───────────────────────────────────────────────────

def pearson_correlation(a: list[float], b: list[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 5:
        return None
    a, b = a[-n:], b[-n:]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num  = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    den  = math.sqrt(
        sum((x - mean_a) ** 2 for x in a) *
        sum((x - mean_b) ** 2 for x in b)
    )
    return round(num / den, 3) if den else None


def compute_correlations(histories: dict[str, list[float]], base: str = "SOL") -> dict:
    """Compute Pearson correlation of each token with SOL."""
    base_hist = histories.get(base, [])
    result = {}
    for sym, hist in histories.items():
        if sym == base:
            continue
        corr = pearson_correlation(base_hist, hist)
        if corr is not None:
            result[sym] = corr
    return result


# ─── Candle Aggregator ─────────────────────────────────────────────────────────

class CandleAggregator:
    """
    Aggregates price ticks into OHLCV candles.
    Default: 1-minute candles (12 ticks × 5s interval).
    """
    def __init__(self, ticks_per_candle: int = 12):
        self.tpc     = ticks_per_candle
        self.candles: dict[str, list] = {}   # sym → list of {t, o, h, l, c, v}
        self._buf:    dict[str, list] = {}   # sym → current tick buffer

    def add_tick(self, sym: str, price: float, ts: float) -> Optional[dict]:
        """Add a price tick. Returns a completed candle if one just closed, else None."""
        if sym not in self._buf:
            self._buf[sym]   = []
            self.candles[sym] = []

        self._buf[sym].append((price, ts))

        if len(self._buf[sym]) >= self.tpc:
            ticks  = self._buf[sym]
            prices = [p for p, _ in ticks]
            candle = {
                "time":   int(ticks[0][1]),
                "open":   prices[0],
                "high":   max(prices),
                "low":    min(prices),
                "close":  prices[-1],
                "volume": len(prices) * 1000,
            }
            self.candles[sym].append(candle)
            # Keep last 200 candles
            if len(self.candles[sym]) > 200:
                self.candles[sym] = self.candles[sym][-200:]
            self._buf[sym] = []
            return candle

        return None

    def get_candles(self, sym: str, n: int = 100) -> list:
        return self.candles.get(sym, [])[-n:]

    def current_partial(self, sym: str) -> Optional[dict]:
        """Return the in-progress (not yet closed) candle."""
        buf = self._buf.get(sym, [])
        if not buf:
            return None
        prices = [p for p, _ in buf]
        return {
            "time":   int(buf[0][1]),
            "open":   prices[0],
            "high":   max(prices),
            "low":    min(prices),
            "close":  prices[-1],
            "volume": 0,
            "partial": True,
        }
