"""
NVIDIA Nemotron 3 Super — AI Trade Signal Engine (v2)
Model: nvidia/nemotron-3-super-120b-a12b

v2 improvements:
- Full technical indicator data (RSI, MACD, EMA, Bollinger) injected into prompt
- Cross-token correlation context
- Structured reasoning via Nemotron thinking mode
- Trailing stop and target precision
"""
import json
import logging
import random
import time
from typing import Optional
import httpx
from config import NVIDIA_API_KEY, NVIDIA_BASE_URL, NEMOTRON_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are AstralPrism — an elite Solana DeFi quant trader powered by NVIDIA Nemotron 3 Super.
You receive real-time price data AND full technical analysis (RSI, MACD, EMA crossovers, Bollinger Bands) from Jupiter DEX.

Your edge: combine multi-indicator confluence with market microstructure to generate high-quality signals.

Respond ONLY with valid JSON — no markdown, no extra text:
{
  "signal":          "BUY" | "SELL" | "HOLD",
  "token":           "<symbol>",
  "confidence":      <0.0-1.0>,
  "targetPrice":     <float>,
  "stopLoss":        <float>,
  "trailPct":        <0.005-0.05>,
  "reasoning":       "<2-3 sentence explanation citing specific indicators>",
  "marketCondition": "BULLISH" | "BEARISH" | "NEUTRAL" | "VOLATILE" | "RANGING",
  "riskLevel":       "LOW" | "MEDIUM" | "HIGH",
  "suggestedSizePct": <0-25>,
  "indicatorScore":  <-1.0 to 1.0>
}

Rules:
- HIGH confidence (>0.75) only when RSI + MACD + EMA all align
- Never BUY when RSI > 75 (overbought) unless strong divergence
- Never SELL when RSI < 25 (oversold) unless strong divergence
- HOLD when indicators conflict or volatility is extreme
- trailPct: trailing stop distance (0.01 = 1%)
- indicatorScore: composite of all TA signals (-1 = full bear, +1 = full bull)
- Always cite the specific indicator that triggered the signal in reasoning
"""


class NemotronClient:
    def __init__(self):
        self._mock_mode = not bool(NVIDIA_API_KEY)
        if self._mock_mode:
            logger.warning("NVIDIA_API_KEY not set — running in DEMO mode with TA-driven signals")
        self._last_signal: Optional[dict] = None
        self._call_count = 0

    async def analyze_market(
        self,
        prices: dict[str, float],
        price_history: dict[str, list],
        indicators: dict[str, dict],
        correlations: dict[str, float],
        portfolio: dict,
        recent_trades: list,
    ) -> dict:
        if self._mock_mode:
            return self._generate_ta_signal(prices, price_history, indicators)

        prompt = self._build_prompt(
            prices, price_history, indicators, correlations, portfolio, recent_trades
        )

        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                payload = {
                    "model": NEMOTRON_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature": 0.15,
                    "top_p": 0.7,
                    "max_tokens": 600,
                    "stream": False,
                }

                resp = await client.post(
                    f"{NVIDIA_BASE_URL}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {NVIDIA_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()

                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]

                signal = json.loads(content)
                self._last_signal = signal
                self._call_count += 1
                logger.info(f"Nemotron: {signal['signal']} {signal['token']} "
                            f"conf={signal['confidence']:.2f} score={signal.get('indicatorScore', '?')}")
                return signal

        except json.JSONDecodeError as e:
            logger.error(f"Nemotron JSON parse error: {e}")
            return self._generate_ta_signal(prices, price_history, indicators)
        except Exception as e:
            logger.error(f"Nemotron API error: {e}")
            return self._generate_ta_signal(prices, price_history, indicators)

    def _build_prompt(
        self,
        prices: dict,
        history: dict,
        indicators: dict,
        correlations: dict,
        portfolio: dict,
        recent_trades: list,
    ) -> str:
        lines = ["=== SOLANA DEX MARKET DATA — Jupiter Aggregator ===\n"]

        # Prices
        lines.append("CURRENT PRICES (USD):")
        for sym, px in prices.items():
            ind = indicators.get(sym, {})
            rsi_v = ind.get("rsi", "—")
            ema_x = ind.get("emaCross", "—")
            lines.append(f"  {sym}: ${px:.6f}  |  RSI={rsi_v}  |  EMA={ema_x}")

        # Detailed indicators per token
        lines.append("\nTECHNICAL INDICATORS:")
        for sym, ind in indicators.items():
            lines.append(f"\n  [{sym}]")
            lines.append(f"    RSI(14):     {ind.get('rsi', '—')} [{ind.get('rsiState', '—')}]")
            lines.append(f"    EMA 9/21:    {ind.get('ema9', '—')} / {ind.get('ema21', '—')} [{ind.get('emaCross', '—')} CROSS]")
            macd_d = ind.get("macd") or {}
            if macd_d:
                bull = "↑ BULLISH" if macd_d.get("bullish") else "↓ BEARISH"
                lines.append(f"    MACD:        {macd_d.get('macd','—')} | Signal={macd_d.get('signal','—')} | Hist={macd_d.get('histogram','—')} [{bull}]")
            bb = ind.get("bollinger") or {}
            if bb:
                zone = "OVERBOUGHT" if bb.get("overbought") else "OVERSOLD" if bb.get("oversold") else "MIDDLE"
                lines.append(f"    Bollinger:   U={bb.get('upper','—')} M={bb.get('middle','—')} L={bb.get('lower','—')} %B={bb.get('pctB','—')} [{zone}]")
            lines.append(f"    Momentum5:   {ind.get('momentum5', '—')}%")
            lines.append(f"    Volatility:  {ind.get('volatility', '—')}%")

        # Correlations
        if correlations:
            lines.append(f"\nSOL CORRELATIONS (last 30 ticks):")
            for sym, corr in correlations.items():
                lines.append(f"  {sym}: {corr:+.3f}")

        # Portfolio
        lines.append(f"\nPORTFOLIO STATE:")
        lines.append(f"  SOL: {portfolio.get('sol', 0):.5f} | USDC: ${portfolio.get('usdc', 0):.2f}")
        lines.append(f"  P&L: ${portfolio.get('pnl', 0):+.4f} ({portfolio.get('pnlPct', 0):+.3f}%)")

        # Recent trades
        if recent_trades:
            lines.append("\nRECENT TRADES (last 3):")
            for t in recent_trades[-3:]:
                lines.append(f"  {t.get('side')} {t.get('token')} conf={t.get('confidence','?')}")

        lines.append("\nAnalyse all indicators for confluence. Output JSON only.")
        return "\n".join(lines)

    def _generate_ta_signal(
        self,
        prices: dict,
        history: dict,
        indicators: dict,
    ) -> dict:
        """
        Deterministic TA-driven signal for demo mode.
        Scores each token and picks the best setup.
        """
        best_token = "SOL"
        best_score = 0.0
        token_scores = {}

        for sym, ind in indicators.items():
            if not ind:
                continue
            score = 0.0

            # RSI component
            rsi_v = ind.get("rsi")
            if rsi_v is not None:
                if rsi_v < 35:   score += 0.3    # oversold → buy pressure
                elif rsi_v > 65: score -= 0.3    # overbought → sell pressure
                elif rsi_v < 50: score += 0.1
                else:            score -= 0.1

            # EMA cross
            ema_x = ind.get("emaCross")
            if ema_x == "GOLDEN": score += 0.25
            elif ema_x == "DEATH": score -= 0.25

            # MACD
            macd_d = ind.get("macd") or {}
            if macd_d.get("bullish") is True:   score += 0.2
            elif macd_d.get("bullish") is False: score -= 0.2

            # Bollinger
            bb = ind.get("bollinger") or {}
            if bb.get("oversold"):   score += 0.15
            elif bb.get("overbought"): score -= 0.15

            # Momentum
            mom = ind.get("momentum5", 0)
            score += max(-0.15, min(0.15, mom / 10))

            token_scores[sym] = round(score, 3)
            if abs(score) > abs(best_score):
                best_score = score
                best_token = sym

        price = prices.get(best_token, 0)
        vol   = indicators.get(best_token, {}).get("volatility", 0.5) or 0.5
        ind   = indicators.get(best_token, {})
        rsi_v = ind.get("rsi", 50)

        # Signal
        if best_score > 0.25:
            side, condition = "BUY", "BULLISH"
            confidence = min(0.50 + best_score * 0.4, 0.88)
            target     = price * (1 + vol / 100 * 2)
            stop       = price * (1 - vol / 100 * 1.5)
            trail_pct  = round(max(0.008, vol / 1000), 4)
            reason = (
                f"[DEMO] RSI={rsi_v} ({ind.get('rsiState','—')}), "
                f"EMA={ind.get('emaCross','—')}, "
                f"MACD={'bullish' if (ind.get('macd') or {}).get('bullish') else 'neutral'}. "
                f"Composite score +{best_score:.2f} — bullish confluence."
            )
        elif best_score < -0.25:
            side, condition = "SELL", "BEARISH"
            confidence = min(0.50 + abs(best_score) * 0.4, 0.85)
            target     = price * (1 - vol / 100 * 2)
            stop       = price * (1 + vol / 100 * 1.5)
            trail_pct  = 0.012
            reason = (
                f"[DEMO] RSI={rsi_v} ({ind.get('rsiState','—')}), "
                f"EMA={ind.get('emaCross','—')}, "
                f"MACD={'bearish' if not (ind.get('macd') or {}).get('bullish') else 'neutral'}. "
                f"Composite score {best_score:.2f} — bearish confluence."
            )
        else:
            side, condition = "HOLD", "NEUTRAL"
            confidence = 0.55 + random.uniform(-0.05, 0.05)
            target     = price
            stop       = price * 0.98
            trail_pct  = 0.01
            reason = (
                f"[DEMO] Mixed signals — RSI={rsi_v}, "
                f"EMA={ind.get('emaCross','—')}. "
                f"No clear confluence (score={best_score:.2f}). Waiting for setup."
            )

        risk = "HIGH" if vol > 2.0 else "MEDIUM" if vol > 0.8 else "LOW"
        size = 8 if risk == "HIGH" else 15 if risk == "MEDIUM" else 22

        return {
            "signal":          side,
            "token":           best_token,
            "confidence":      round(confidence + random.uniform(-0.02, 0.02), 3),
            "targetPrice":     round(target, 8),
            "stopLoss":        round(stop, 8),
            "trailPct":        trail_pct,
            "reasoning":       reason,
            "marketCondition": condition,
            "riskLevel":       risk,
            "suggestedSizePct": size,
            "indicatorScore":  round(best_score, 3),
            "tokenScores":     token_scores,
            "isDemo":          True,
        }
