"""
AstralPrism Trading Engine
- Main orchestration loop
- Coordinates: Jupiter prices → Nemotron analysis → Demo trade execution
- Broadcasts real-time state via asyncio Queue to WebSocket clients
"""
import asyncio
import logging
import time
from collections import deque
from typing import Optional

from config import (
    ANALYSIS_INTERVAL_SEC,
    PRICE_POLL_INTERVAL,
    PRICE_HISTORY_MAX,
    MAX_SLIPPAGE_BPS,
    TRADING_PAIRS,
    TOKENS,
)
from jupiter_client import JupiterClient
from nemotron_client import NemotronClient
from solana_client import SolanaClient, DemoPortfolio

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self):
        self.jup      = JupiterClient()
        self.nem      = NemotronClient()
        self.sol_cli  = SolanaClient()
        self.portfolio = DemoPortfolio()

        # Price history: deque per token
        self.price_history: dict[str, deque] = {
            sym: deque(maxlen=PRICE_HISTORY_MAX) for sym in TRADING_PAIRS
        }
        self.current_prices: dict[str, float] = {}

        # State
        self.running          = False
        self.paused           = False
        self.last_signal:  Optional[dict] = None
        self.last_analysis_ts: float = 0.0
        self.tick_count:   int = 0
        self.error_log:    list = []

        # Broadcast queue for WebSocket clients
        self.broadcast_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._ws_clients: set = set()

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self):
        """Initialise wallet, request airdrop, start price and analysis loops."""
        logger.info("Starting AstralPrism Trading Engine...")
        await self.sol_cli.setup()

        if self.sol_cli.devnet_sol_balance < 0.1:
            logger.info("Requesting devnet airdrop...")
            await self.sol_cli.request_airdrop(1.0)

        self.running = True
        await asyncio.gather(
            self._price_loop(),
            self._analysis_loop(),
        )

    async def stop(self):
        self.running = False
        logger.info("Trading engine stopped.")

    def pause(self):
        self.paused = True
        logger.info("Bot paused (prices still updating).")

    def resume(self):
        self.paused = False
        logger.info("Bot resumed.")

    # ─── Price Loop ───────────────────────────────────────────────────────────

    async def _price_loop(self):
        async with self.jup:
            while self.running:
                try:
                    prices = await self.jup.get_prices(TRADING_PAIRS)
                    if prices:
                        self.current_prices = prices
                        for sym, px in prices.items():
                            self.price_history[sym].append(px)

                        self.portfolio.set_initial_value(prices)
                        self.tick_count += 1

                        await self._broadcast({
                            "type":     "price_update",
                            "prices":   prices,
                            "history":  {k: list(v) for k, v in self.price_history.items()},
                            "portfolio": self.portfolio.to_dict(prices),
                            "tick":     self.tick_count,
                            "ts":       time.time(),
                        })

                except Exception as e:
                    logger.error(f"Price loop error: {e}")
                    self.error_log.append({"ts": time.time(), "error": str(e)})

                await asyncio.sleep(PRICE_POLL_INTERVAL)

    # ─── Analysis Loop ────────────────────────────────────────────────────────

    async def _analysis_loop(self):
        # Stagger analysis start — let price history build first
        await asyncio.sleep(15)

        while self.running:
            now = time.time()
            if not self.paused and (now - self.last_analysis_ts) >= ANALYSIS_INTERVAL_SEC:
                try:
                    await self._run_analysis()
                    self.last_analysis_ts = now
                except Exception as e:
                    logger.error(f"Analysis loop error: {e}")
                    self.error_log.append({"ts": time.time(), "error": str(e)})

            await asyncio.sleep(2)

    async def _run_analysis(self):
        """One full analysis cycle: prices → Nemotron → optional trade."""
        if not self.current_prices:
            return

        history_snap = {k: list(v) for k, v in self.price_history.items()}

        # Broadcast "thinking" state
        await self._broadcast({
            "type":   "analysis_start",
            "ts":     time.time(),
            "model":  "nvidia/nemotron-3-super-120b-a12b",
        })

        # Ask Nemotron
        signal = await self.nem.analyze_market(
            prices       = self.current_prices,
            price_history= history_snap,
            portfolio    = self.portfolio.to_dict(self.current_prices),
            recent_trades= self.portfolio.trades[-3:],
        )
        self.last_signal = signal

        # Attempt trade execution if signal is not HOLD
        trade_record = {}
        if (
            signal.get("signal") in ("BUY", "SELL")
            and signal.get("confidence", 0) >= 0.45
            and not self.paused
        ):
            token = signal.get("token", "SOL")
            # Get fresh quote for the token
            if signal["signal"] == "BUY":
                quote = await self.jup.get_quote("USDC", token, 10.0, MAX_SLIPPAGE_BPS) if \
                        hasattr(self.jup, '_client') and self.jup._client else None
            else:
                quote = await self.jup.get_quote(token, "USDC", 0.1, MAX_SLIPPAGE_BPS) if \
                        hasattr(self.jup, '_client') and self.jup._client else None

            trade_record = self.portfolio.execute_demo_trade(
                signal = signal,
                quote  = quote or {},
                prices = self.current_prices,
            )

        await self._broadcast({
            "type":        "analysis_complete",
            "signal":      signal,
            "trade":       trade_record,
            "portfolio":   self.portfolio.to_dict(self.current_prices),
            "prices":      self.current_prices,
            "ts":          time.time(),
        })

    # ─── Manual Trade ─────────────────────────────────────────────────────────

    async def manual_trade(self, side: str, token: str, size_pct: float = 10) -> dict:
        """Trigger a manual demo trade from the dashboard."""
        if token not in self.current_prices:
            return {"error": f"Unknown token: {token}"}

        manual_signal = {
            "signal":          side.upper(),
            "token":           token,
            "confidence":      0.99,
            "marketCondition": "MANUAL",
            "riskLevel":       "LOW",
            "suggestedSizePct": size_pct,
            "reasoning":       f"Manual {side.upper()} triggered from dashboard.",
            "targetPrice":     self.current_prices[token],
            "stopLoss":        self.current_prices[token],
        }
        trade = self.portfolio.execute_demo_trade(manual_signal, {}, self.current_prices)
        await self._broadcast({
            "type":      "analysis_complete",
            "signal":    manual_signal,
            "trade":     trade,
            "portfolio": self.portfolio.to_dict(self.current_prices),
            "prices":    self.current_prices,
            "ts":        time.time(),
        })
        return trade

    # ─── WebSocket Broadcast ─────────────────────────────────────────────────

    def register_ws(self, ws):
        self._ws_clients.add(ws)

    def deregister_ws(self, ws):
        self._ws_clients.discard(ws)

    async def _broadcast(self, message: dict):
        """Push message to all connected WebSocket clients."""
        import json
        text = json.dumps(message, default=str)
        dead = set()
        for ws in list(self._ws_clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead

    def get_state(self) -> dict:
        """Full state snapshot for REST polling."""
        prices = self.current_prices
        return {
            "running":    self.running,
            "paused":     self.paused,
            "tick":       self.tick_count,
            "wallet":     self.sol_cli.public_key,
            "devnetSol":  self.sol_cli.devnet_sol_balance,
            "explorerUrl": self.sol_cli.explorer_url(),
            "portfolio":  self.portfolio.to_dict(prices),
            "prices":     prices,
            "history":    {k: list(v)[-30:] for k, v in self.price_history.items()},
            "lastSignal": self.last_signal,
            "trades":     self.portfolio.trades[-50:],
            "isDemo":     self.nem._mock_mode,
            "model":      "nvidia/nemotron-3-super-120b-a12b",
        }
