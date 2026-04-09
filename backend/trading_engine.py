"""
AstralPrism Trading Engine v2
- Price loop: ticks → candles + indicators + correlations
- Analysis loop: TA-enriched Nemotron signals
- Trailing stop management
- Live/demo trade execution
- WebSocket broadcast
"""
import asyncio
import logging
import time
from collections import deque
from typing import Optional
import httpx

from config import (
    ANALYSIS_INTERVAL_SEC,
    PRICE_POLL_INTERVAL,
    PRICE_HISTORY_MAX,
    MAX_SLIPPAGE_BPS,
    MAX_LOSS_USD,
    TRADING_PAIRS,
    TOKENS,
    LIVE_MODE,
    WALLET_PRIVATE_KEY,
)
from jupiter_client import JupiterClient
from nemotron_client import NemotronClient
from solana_client import SolanaClient, DemoPortfolio
from live_portfolio import LivePortfolio
from indicators import (
    compute_all,
    compute_correlations,
    CandleAggregator,
)

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self):
        self.jup       = JupiterClient()
        self.nem       = NemotronClient()
        self.sol_cli   = SolanaClient()
        self.candles   = CandleAggregator(ticks_per_candle=12)  # 12×5s = 1 min candle

        # Live mode setup
        self.live_mode  = LIVE_MODE
        self.executor   = None
        self.live_port  = None

        if self.live_mode and WALLET_PRIVATE_KEY:
            try:
                from solders.keypair import Keypair
                import base58
                kp = Keypair.from_bytes(base58.b58decode(WALLET_PRIVATE_KEY))
                from trade_executor import TradeExecutor
                self.executor  = TradeExecutor(kp)
                self.live_port = LivePortfolio()
                logger.warning(f"[LIVE MODE] Wallet: {str(kp.pubkey())}")
            except Exception as e:
                logger.error(f"Failed to load live wallet: {e} — falling back to DEMO")
                self.live_mode = False
        elif self.live_mode:
            logger.error("LIVE_MODE=true but WALLET_PRIVATE_KEY not set — falling back to DEMO")
            self.live_mode = False

        self.portfolio = self.live_port if self.live_mode else DemoPortfolio()

        # Price & indicator history
        self.price_history:  dict[str, deque] = {s: deque(maxlen=PRICE_HISTORY_MAX) for s in TRADING_PAIRS}
        self.indicators:     dict[str, dict]  = {}
        self.correlations:   dict[str, float] = {}
        self.current_prices: dict[str, float] = {}

        # Trailing stop tracking: token → {"entry": float, "highest": float, "trailPct": float}
        self._trailing:   dict[str, dict]  = {}

        # State
        self.running           = False
        self.paused            = False
        self.last_signal:      Optional[dict] = None
        self.last_analysis_ts: float = 0.0
        self.tick_count:       int   = 0
        self.error_log:        list  = []
        self._ws_clients:      set   = set()

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self):
        logger.info(f"Starting AstralPrism Engine [{'LIVE' if self.live_mode else 'DEMO'}]")

        if self.live_mode and self.executor:
            async with httpx.AsyncClient(timeout=10.0) as client:
                bals = await self.executor.get_token_balances(client)
                if bals:
                    self.live_port.balances = bals
                    logger.info(f"[LIVE] Synced balances: {bals}")
        else:
            await self.sol_cli.setup()
            if self.sol_cli.devnet_sol_balance < 0.1:
                await self.sol_cli.request_airdrop(1.0)

        self.running = True
        await asyncio.gather(
            self._price_loop(),
            self._analysis_loop(),
            self._trailing_stop_loop(),
        )

    async def stop(self):
        self.running = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    # ─── Price Loop ───────────────────────────────────────────────────────────

    async def _price_loop(self):
        async with self.jup:
            while self.running:
                try:
                    prices = await self.jup.get_prices(TRADING_PAIRS)
                    if prices:
                        self.current_prices = prices
                        now = time.time()

                        new_candles = {}
                        for sym, px in prices.items():
                            self.price_history[sym].append(px)
                            candle = self.candles.add_tick(sym, px, now)
                            if candle:
                                new_candles[sym] = candle

                        # Recompute indicators
                        for sym in TRADING_PAIRS:
                            hist = list(self.price_history[sym])
                            if len(hist) >= 15:
                                self.indicators[sym] = compute_all(hist)

                        # Correlations
                        if all(len(list(self.price_history[s])) >= 10 for s in TRADING_PAIRS):
                            self.correlations = compute_correlations(
                                {s: list(self.price_history[s]) for s in TRADING_PAIRS}
                            )

                        self.portfolio.set_initial_value(prices) if hasattr(self.portfolio, 'set_initial_value') else None
                        self.tick_count += 1

                        payload = {
                            "type":         "price_update",
                            "prices":       prices,
                            "history":      {k: list(v) for k, v in self.price_history.items()},
                            "indicators":   self.indicators,
                            "correlations": self.correlations,
                            "portfolio":    self.portfolio.to_dict(prices),
                            "tick":         self.tick_count,
                            "ts":           now,
                        }
                        if new_candles:
                            payload["newCandles"] = new_candles
                        payload["partialCandles"] = {
                            sym: self.candles.current_partial(sym)
                            for sym in TRADING_PAIRS
                            if self.candles.current_partial(sym)
                        }

                        await self._broadcast(payload)

                except Exception as e:
                    logger.error(f"Price loop: {e}")
                    self.error_log.append({"ts": time.time(), "error": str(e)})

                await asyncio.sleep(PRICE_POLL_INTERVAL)

    # ─── Analysis Loop ────────────────────────────────────────────────────────

    async def _analysis_loop(self):
        await asyncio.sleep(20)   # let history build

        while self.running:
            now = time.time()
            if (
                not self.paused
                and (now - self.last_analysis_ts) >= ANALYSIS_INTERVAL_SEC
                and self.current_prices
                and self.indicators
            ):
                try:
                    await self._run_analysis()
                    self.last_analysis_ts = now
                except Exception as e:
                    logger.error(f"Analysis loop: {e}")

            await asyncio.sleep(2)

    async def _run_analysis(self):
        history_snap = {k: list(v) for k, v in self.price_history.items()}

        await self._broadcast({"type": "analysis_start", "ts": time.time(), "model": NEMOTRON_MODEL})

        signal = await self.nem.analyze_market(
            prices       = self.current_prices,
            price_history= history_snap,
            indicators   = self.indicators,
            correlations = self.correlations,
            portfolio    = self.portfolio.to_dict(self.current_prices),
            recent_trades= (
                self.live_port.trades[-3:] if self.live_mode
                else self.portfolio.trades[-3:]
            ),
        )
        self.last_signal = signal

        # Update trailing stop if applicable
        tok = signal.get("token")
        if signal.get("signal") == "BUY" and tok not in self._trailing:
            self._trailing[tok] = {
                "entry":    self.current_prices.get(tok, 0),
                "highest":  self.current_prices.get(tok, 0),
                "trailPct": signal.get("trailPct", 0.015),
            }

        # Execute trade
        trade_record = {}
        if signal.get("signal") in ("BUY", "SELL") and not self.paused:
            if self.live_mode:
                trade_record = await self._execute_live_trade(signal)
            elif signal.get("confidence", 0) >= 0.45:
                quote = None
                try:
                    if signal["signal"] == "BUY":
                        quote = await self.jup.get_quote("USDC", tok, 10.0, MAX_SLIPPAGE_BPS)
                    else:
                        quote = await self.jup.get_quote(tok, "USDC", 0.1, MAX_SLIPPAGE_BPS)
                except Exception:
                    pass
                trade_record = self.portfolio.execute_demo_trade(
                    signal=signal, quote=quote or {}, prices=self.current_prices
                )

        await self._broadcast({
            "type":        "analysis_complete",
            "signal":      signal,
            "trade":       trade_record,
            "portfolio":   self.portfolio.to_dict(self.current_prices),
            "indicators":  self.indicators,
            "prices":      self.current_prices,
            "ts":          time.time(),
        })

    # ─── Trailing Stop Loop ───────────────────────────────────────────────────

    async def _trailing_stop_loop(self):
        """Check trailing stops every 10 seconds."""
        while self.running:
            await asyncio.sleep(10)
            if not self.current_prices or self.paused:
                continue

            to_remove = []
            for sym, state in list(self._trailing.items()):
                price = self.current_prices.get(sym)
                if not price:
                    continue

                # Update highest
                if price > state["highest"]:
                    state["highest"] = price

                stop_price = state["highest"] * (1 - state["trailPct"])

                if price <= stop_price:
                    logger.info(f"[TRAIL STOP] {sym} hit: {price:.6f} <= {stop_price:.6f}")
                    stop_signal = {
                        "signal":          "SELL",
                        "token":           sym,
                        "confidence":      0.95,
                        "marketCondition": "TRAILING_STOP",
                        "riskLevel":       "LOW",
                        "suggestedSizePct": 100,   # exit full position
                        "reasoning":       f"Trailing stop triggered. High={state['highest']:.6f}, Stop={stop_price:.6f} ({state['trailPct']*100:.1f}% trail).",
                        "targetPrice":     price,
                        "stopLoss":        price,
                        "trailPct":        state["trailPct"],
                        "indicatorScore":  -0.9,
                        "isTrailingStop":  True,
                    }

                    if self.live_mode:
                        await self._execute_live_trade(stop_signal)
                    else:
                        self.portfolio.execute_demo_trade(stop_signal, {}, self.current_prices)

                    await self._broadcast({
                        "type":     "trailing_stop_triggered",
                        "token":    sym,
                        "price":    price,
                        "stopAt":   stop_price,
                        "signal":   stop_signal,
                        "portfolio": self.portfolio.to_dict(self.current_prices),
                        "ts":       time.time(),
                    })
                    to_remove.append(sym)

            for sym in to_remove:
                self._trailing.pop(sym, None)

    # ─── Live Trade Execution ─────────────────────────────────────────────────

    async def _execute_live_trade(self, signal: dict) -> dict:
        prices  = self.current_prices
        allowed, reason = self.live_port.check_risk(signal, prices)
        if not allowed:
            await self._broadcast({"type": "trade_blocked", "reason": reason, "ts": time.time()})
            return {}

        token = signal.get("token", "SOL")
        side  = signal["signal"]
        size  = self.live_port.compute_trade_size(
            side, token, prices, size_pct=signal.get("suggestedSizePct", 15) / 100
        )
        if size <= 0:
            return {}

        if side == "BUY":
            input_sym, output_sym = "USDC", token
            input_amt = size * prices.get(token, 1)
        else:
            input_sym, output_sym = token, "USDC"
            input_amt = size

        if input_amt < 0.01:
            return {}

        await self._broadcast({"type": "trade_pending", "side": side, "token": token, "size": size, "ts": time.time()})

        exec_result = await self.executor.execute_swap(input_sym, output_sym, input_amt)

        if exec_result.get("success"):
            async with httpx.AsyncClient(timeout=10.0) as client:
                new_bals = await self.executor.get_token_balances(client)
            trade = self.live_port.record_trade(exec_result, signal, new_bals or {})

            if self.live_port.halted:
                await self._broadcast({"type": "bot_halted", "reason": self.live_port.halt_reason, "ts": time.time()})

            # Clear trailing stop if we just sold
            if side == "SELL":
                self._trailing.pop(token, None)
            return trade
        else:
            await self._broadcast({"type": "trade_failed", "error": exec_result.get("error"), "ts": time.time()})
            return {}

    # ─── Manual Trade ─────────────────────────────────────────────────────────

    async def manual_trade(self, side: str, token: str, size_pct: float = 10) -> dict:
        if token not in self.current_prices:
            return {"error": f"Unknown token: {token}"}

        manual_signal = {
            "signal": side.upper(), "token": token, "confidence": 0.99,
            "marketCondition": "MANUAL", "riskLevel": "LOW",
            "suggestedSizePct": size_pct,
            "reasoning": f"Manual {side.upper()} from dashboard.",
            "targetPrice": self.current_prices[token],
            "stopLoss": self.current_prices[token],
            "trailPct": 0.015, "indicatorScore": 0,
        }

        if self.live_mode:
            trade = await self._execute_live_trade(manual_signal)
        else:
            trade = self.portfolio.execute_demo_trade(manual_signal, {}, self.current_prices)

        await self._broadcast({
            "type": "analysis_complete", "signal": manual_signal,
            "trade": trade, "portfolio": self.portfolio.to_dict(self.current_prices),
            "prices": self.current_prices, "ts": time.time(),
        })
        return trade

    # ─── WebSocket ────────────────────────────────────────────────────────────

    def register_ws(self, ws):
        self._ws_clients.add(ws)

    def deregister_ws(self, ws):
        self._ws_clients.discard(ws)

    async def _broadcast(self, message: dict):
        import json
        text = json.dumps(message, default=str)
        dead = set()
        for ws in list(self._ws_clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead

    # ─── State ────────────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        prices = self.current_prices

        if self.live_mode and self.live_port:
            wallet_addr  = self.executor.pubkey
            explorer_url = f"https://solscan.io/account/{wallet_addr}"
            devnet_sol   = self.live_port.balances.get("SOL", 0)
            trades       = self.live_port.trades[-50:]
            portfolio    = self.live_port.to_dict(prices)
        else:
            wallet_addr  = self.sol_cli.public_key
            explorer_url = self.sol_cli.explorer_url()
            devnet_sol   = self.sol_cli.devnet_sol_balance
            trades       = self.portfolio.trades[-50:]
            portfolio    = self.portfolio.to_dict(prices)

        # Include candle history for all tokens
        candle_data = {
            sym: self.candles.get_candles(sym, 100)
            for sym in TRADING_PAIRS
        }

        return {
            "running":      self.running,
            "paused":       self.paused,
            "tick":         self.tick_count,
            "wallet":       wallet_addr,
            "devnetSol":    devnet_sol,
            "explorerUrl":  explorer_url,
            "portfolio":    portfolio,
            "prices":       prices,
            "history":      {k: list(v)[-60:] for k, v in self.price_history.items()},
            "indicators":   self.indicators,
            "correlations": self.correlations,
            "candles":      candle_data,
            "lastSignal":   self.last_signal,
            "trades":       trades,
            "trailing":     {k: {**v, "stopPrice": v["highest"] * (1 - v["trailPct"])} for k, v in self._trailing.items()},
            "isDemo":       self.nem._mock_mode,
            "isLive":       self.live_mode,
            "model":        NEMOTRON_MODEL,
            "lossCapUSD":   MAX_LOSS_USD if self.live_mode else None,
        }


NEMOTRON_MODEL = "nvidia/nemotron-3-super-120b-a12b"
