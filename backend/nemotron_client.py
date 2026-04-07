"""
NVIDIA Nemotron 3 Super — AI Trade Signal Engine
Model: nvidia/nemotron-3-super-120b-a12b (128K context, reasoning + tool calling)
API:   integrate.api.nvidia.com/v1  (OpenAI-compatible)

Nemotron's reasoning mode is activated by passing `thinking` budget tokens.
We use it to deeply analyze DeFi market data and produce structured trade signals.
"""
import json
import logging
import time
from typing import Optional
import httpx
from config import NVIDIA_API_KEY, NVIDIA_BASE_URL, NEMOTRON_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are AstralPrism — an elite Solana DeFi trading AI powered by Nemotron 3 Super.
Your role: analyze real-time DEX market data from Jupiter aggregator and generate precise trade signals.

Output format — respond with ONLY valid JSON, no markdown fences:
{
  "signal": "BUY" | "SELL" | "HOLD",
  "token": "<symbol>",
  "confidence": <0.0-1.0>,
  "targetPrice": <float>,
  "stopLoss": <float>,
  "reasoning": "<concise 2-3 sentence explanation>",
  "marketCondition": "BULLISH" | "BEARISH" | "NEUTRAL" | "VOLATILE",
  "riskLevel": "LOW" | "MEDIUM" | "HIGH",
  "suggestedSizePct": <0-100>
}

Guidelines:
- Base decisions on price momentum, liquidity depth, and cross-token correlation
- HIGH confidence only when multiple indicators align
- Account for Solana DEX liquidity and price impact
- suggestedSizePct: % of portfolio to allocate (never exceed 25% in HIGH risk)
- Be conservative — preserve capital on testnet as if it were real funds
"""


class NemotronClient:
    def __init__(self):
        self._mock_mode = not bool(NVIDIA_API_KEY)
        if self._mock_mode:
            logger.warning("NVIDIA_API_KEY not set — running in DEMO mode with simulated signals")
        self._last_signal: Optional[dict] = None
        self._call_count = 0

    async def analyze_market(
        self,
        prices: dict[str, float],
        price_history: dict[str, list],
        portfolio: dict,
        recent_trades: list,
    ) -> dict:
        """
        Send market state to Nemotron 3 Super for trade signal generation.
        Returns structured signal dict.
        """
        if self._mock_mode:
            return self._generate_demo_signal(prices, price_history)

        prompt = self._build_market_prompt(prices, price_history, portfolio, recent_trades)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = {
                    "model": NEMOTRON_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature": 0.2,   # Low temp for decisive signals
                    "top_p": 0.7,
                    "max_tokens": 512,
                    "stream": False,
                    # Nemotron thinking budget — use reasoning tokens
                    "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 1024}},
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
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()

                # Strip any accidental markdown fences
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]

                signal = json.loads(content)
                self._last_signal = signal
                self._call_count += 1
                logger.info(f"Nemotron signal: {signal['signal']} {signal['token']} "
                            f"confidence={signal['confidence']:.2f}")
                return signal

        except json.JSONDecodeError as e:
            logger.error(f"Nemotron returned invalid JSON: {e}")
            return self._generate_demo_signal(prices, price_history)
        except httpx.HTTPStatusError as e:
            logger.error(f"Nemotron API error {e.response.status_code}: {e.response.text[:200]}")
            return self._generate_demo_signal(prices, price_history)
        except Exception as e:
            logger.error(f"Nemotron unexpected error: {e}")
            return self._generate_demo_signal(prices, price_history)

    def _build_market_prompt(
        self,
        prices: dict,
        history: dict,
        portfolio: dict,
        recent_trades: list,
    ) -> str:
        """Build a rich market context prompt for Nemotron."""
        lines = ["=== SOLANA DEX MARKET DATA (via Jupiter) ===\n"]

        # Current prices
        lines.append("CURRENT PRICES (USDC):")
        for sym, price in prices.items():
            lines.append(f"  {sym}: ${price:.6f}")

        # Price momentum (last 10 ticks)
        lines.append("\nPRICE MOMENTUM (last 10 observations):")
        for sym, hist in history.items():
            if len(hist) >= 2:
                ticks = hist[-10:]
                change_pct = ((ticks[-1] - ticks[0]) / ticks[0] * 100) if ticks[0] else 0
                volatility  = (max(ticks) - min(ticks)) / ticks[0] * 100 if ticks[0] else 0
                lines.append(f"  {sym}: {change_pct:+.2f}% change, {volatility:.2f}% range")

        # Portfolio state
        lines.append(f"\nPORTFOLIO:")
        lines.append(f"  SOL balance:  {portfolio.get('sol', 0):.4f} SOL")
        lines.append(f"  USDC balance: ${portfolio.get('usdc', 0):.2f}")
        lines.append(f"  Total P&L:    ${portfolio.get('pnl', 0):+.2f}")

        # Recent trades
        if recent_trades:
            lines.append("\nRECENT TRADES (last 3):")
            for t in recent_trades[-3:]:
                lines.append(f"  {t.get('side')} {t.get('size')} {t.get('token')} "
                             f"@ ${t.get('price', 0):.4f} → {t.get('pnl', 'pending')}")

        lines.append("\nGenerate a trade signal based on this data. Respond in JSON only.")
        return "\n".join(lines)

    def _generate_demo_signal(self, prices: dict, history: dict) -> dict:
        """
        Deterministic demo signal based on momentum math.
        Used when NVIDIA_API_KEY is not configured.
        """
        import math, random

        # Pick the token with strongest recent momentum
        best_token = "SOL"
        best_momentum = 0.0
        signals_by_token = {}

        for sym, hist in history.items():
            if len(hist) < 5:
                continue
            recent  = hist[-5:]
            change  = (recent[-1] - recent[0]) / recent[0] if recent[0] else 0
            vol     = (max(recent) - min(recent)) / recent[0] if recent[0] else 0
            signals_by_token[sym] = {"momentum": change, "volatility": vol}
            if abs(change) > abs(best_momentum):
                best_momentum = change
                best_token = sym

        price = prices.get(best_token, 0)
        info  = signals_by_token.get(best_token, {})
        mom   = info.get("momentum", 0)
        vol   = info.get("volatility", 0)

        if mom > 0.003:
            side      = "BUY"
            condition = "BULLISH"
            confidence = min(0.55 + abs(mom) * 10, 0.85)
            target     = price * 1.015
            stop       = price * 0.985
        elif mom < -0.003:
            side      = "SELL"
            condition = "BEARISH"
            confidence = min(0.55 + abs(mom) * 10, 0.82)
            target     = price * 0.985
            stop       = price * 1.015
        else:
            side      = "HOLD"
            condition = "NEUTRAL"
            confidence = 0.60
            target     = price
            stop       = price * 0.98

        risk = "HIGH" if vol > 0.02 else "MEDIUM" if vol > 0.01 else "LOW"

        # Add small random noise so dashboard feels live
        confidence += random.uniform(-0.03, 0.03)
        confidence = round(max(0.35, min(0.92, confidence)), 3)

        return {
            "signal":          side,
            "token":           best_token,
            "confidence":      confidence,
            "targetPrice":     round(target, 6),
            "stopLoss":        round(stop, 6),
            "reasoning":       (
                f"[DEMO MODE] {best_token} shows {mom*100:+.2f}% momentum over last 5 ticks "
                f"with {vol*100:.2f}% volatility. {condition} conditions suggest "
                f"{'accumulation' if side == 'BUY' else 'distribution' if side == 'SELL' else 'patience'}."
            ),
            "marketCondition": condition,
            "riskLevel":       risk,
            "suggestedSizePct": 10 if risk == "HIGH" else 15 if risk == "MEDIUM" else 20,
            "isDemo":          True,
        }
