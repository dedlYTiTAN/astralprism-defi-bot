"""
LivePortfolio — Real mainnet portfolio tracker with hard $10 loss cap.

Syncs balances directly from Solana RPC after each trade.
Enforces risk limits before every execution.
"""
import logging
import time
from collections import deque
from config import MAX_LOSS_USD, MIN_CONFIDENCE_LIVE, MAX_TRADE_PCT, MIN_SOL_FOR_FEES

logger = logging.getLogger(__name__)


class LivePortfolio:
    def __init__(self):
        self.balances: dict[str, float] = {}  # symbol → real balance
        self.initial_value_usd: float = 0.0   # set on first sync
        self.trades: list = []
        self.loss_cap_usd = MAX_LOSS_USD
        self.halted = False
        self.halt_reason = ""

        # Trade throttle
        self._trade_timestamps: deque = deque(maxlen=10)
        self._trades_this_minute = 0
        self._minute_start = time.time()

    # ─── Value tracking ───────────────────────────────────────────────────────

    def current_value_usd(self, prices: dict[str, float]) -> float:
        total = 0.0
        for sym, bal in self.balances.items():
            if sym == "USDC":
                total += bal
            elif sym in prices:
                total += bal * prices[sym]
        return total

    def pnl_usd(self, prices: dict) -> float:
        if self.initial_value_usd == 0:
            return 0.0
        return self.current_value_usd(prices) - self.initial_value_usd

    def loss_remaining_usd(self, prices: dict) -> float:
        """How much more we can lose before the cap kicks in."""
        pnl = self.pnl_usd(prices)
        return self.loss_cap_usd + pnl   # positive = budget left, 0 or negative = halt

    def set_initial_value(self, prices: dict):
        if self.initial_value_usd == 0 and self.balances:
            self.initial_value_usd = self.current_value_usd(prices)
            logger.info(f"[LIVE] Initial portfolio value: ${self.initial_value_usd:.4f}")

    # ─── Risk checks ─────────────────────────────────────────────────────────

    def check_risk(self, signal: dict, prices: dict) -> tuple[bool, str]:
        """
        Returns (allowed: bool, reason: str).
        Called before every live trade.
        """
        if self.halted:
            return False, f"Bot halted: {self.halt_reason}"

        # 1. Hard loss cap
        remaining = self.loss_remaining_usd(prices)
        if remaining <= 0:
            self._halt(f"${self.loss_cap_usd:.2f} loss cap hit — shutting down")
            return False, self.halt_reason

        # 2. Minimum confidence
        confidence = signal.get("confidence", 0)
        if confidence < MIN_CONFIDENCE_LIVE:
            return False, f"Confidence {confidence:.0%} below {MIN_CONFIDENCE_LIVE:.0%} threshold"

        # 3. SOL fee reserve
        sol_bal = self.balances.get("SOL", 0)
        if sol_bal < MIN_SOL_FOR_FEES:
            return False, f"SOL balance too low for fees ({sol_bal:.5f} SOL)"

        # 4. Trade throttle (max 2 per minute)
        now = time.time()
        if now - self._minute_start >= 60:
            self._minute_start = now
            self._trades_this_minute = 0
        if self._trades_this_minute >= 2:
            return False, "Trade throttle: max 2 trades/minute"

        # 5. HOLD signal
        if signal.get("signal") == "HOLD":
            return False, "Signal is HOLD"

        return True, "OK"

    def compute_trade_size(
        self,
        side: str,
        token: str,
        prices: dict,
        size_pct: float = None,
    ) -> float:
        """
        Compute safe trade size in UI units.
        Capped at MAX_TRADE_PCT of portfolio and remaining loss budget.
        """
        size_pct = min(size_pct or 0.15, MAX_TRADE_PCT)
        remaining_risk = self.loss_remaining_usd(prices)

        if side == "BUY":
            usdc_bal   = self.balances.get("USDC", 0)
            max_spend  = min(usdc_bal * size_pct, remaining_risk)
            price      = prices.get(token, 0)
            if token == "USDC" or price == 0:
                return round(max_spend, 4)
            return round(max_spend / price, 6)

        elif side == "SELL":
            if token == "SOL":
                sol_bal   = max(self.balances.get("SOL", 0) - MIN_SOL_FOR_FEES, 0)
                return round(sol_bal * size_pct, 6)
            else:
                tok_bal   = self.balances.get(token, 0)
                return round(tok_bal * size_pct, 6)

        return 0.0

    # ─── Trade recording ─────────────────────────────────────────────────────

    def record_trade(self, exec_result: dict, signal: dict, new_balances: dict):
        """Called after a successful on-chain swap to update state."""
        self._trades_this_minute += 1
        self._trade_timestamps.append(time.time())

        trade = {
            "id":          len(self.trades) + 1,
            "timestamp":   exec_result.get("ts", time.time()),
            "side":        signal.get("signal"),
            "token":       exec_result.get("inputSymbol"),
            "outputToken": exec_result.get("outputSymbol"),
            "inAmount":    exec_result.get("inputAmount"),
            "outAmount":   exec_result.get("outAmount"),
            "priceImpact": exec_result.get("priceImpact"),
            "confidence":  signal.get("confidence"),
            "condition":   signal.get("marketCondition"),
            "signature":   exec_result.get("signature", "")[:20] + "...",
            "explorerUrl": exec_result.get("explorerUrl", ""),
            "status":      "CONFIRMED" if exec_result.get("success") else "FAILED",
            "isLive":      True,
        }
        self.trades.append(trade)

        # Sync balances
        if new_balances:
            self.balances = new_balances
            logger.info(f"[LIVE] Balances updated: {new_balances}")

        return trade

    # ─── Halt ─────────────────────────────────────────────────────────────────

    def _halt(self, reason: str):
        if not self.halted:
            self.halted = True
            self.halt_reason = reason
            logger.critical(f"[LIVE] ⚠ BOT HALTED: {reason}")

    # ─── Serialise ────────────────────────────────────────────────────────────

    def to_dict(self, prices: dict) -> dict:
        val = self.current_value_usd(prices)
        pnl = self.pnl_usd(prices)
        return {
            "balances":       {k: round(v, 8) for k, v in self.balances.items()},
            "totalValueUSD":  round(val, 4),
            "initialValue":   round(self.initial_value_usd, 4),
            "pnl":            round(pnl, 4),
            "pnlPct":         round((pnl / self.initial_value_usd * 100) if self.initial_value_usd else 0, 4),
            "lossCapUSD":     round(self.loss_cap_usd, 2),
            "lossRemaining":  round(self.loss_remaining_usd(prices), 4),
            "halted":         self.halted,
            "haltReason":     self.halt_reason,
            "tradeCount":     len(self.trades),
            "isLive":         True,
            # Convenience aliases for dashboard compatibility
            "sol":            round(self.balances.get("SOL", 0), 6),
            "usdc":           round(self.balances.get("USDC", 0), 4),
        }
