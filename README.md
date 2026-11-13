# AstralPrism DeFi Bot

An experimental Solana trading-bot prototype that asks an LLM for BUY / SELL / HOLD signals on live DEX prices and shows everything on a real-time dashboard.

> **Status: unvalidated learning prototype.** It has not been backtested and there is no evidence that its signals have any edge. Trades are simulated by default. Live mode exists but is experimental and has known safety gaps, so do not use it with real funds. Nothing here is financial advice.

Last substantial update: April 2026. Not under active development.

## What it does

1. Polls USD prices for SOL, JUP, BONK and WIF from the Jupiter Price API every 5 seconds (CoinGecko as a fallback).
2. Computes technical indicators from those price ticks.
3. Every 20 seconds, sends prices, indicators, correlations and portfolio state to NVIDIA's `nemotron-3-super-120b-a12b` model (OpenAI-compatible endpoint) and asks for a structured JSON signal.
4. Executes the signal against a **simulated portfolio** (default), or, if explicitly enabled, as a real Jupiter swap from a dedicated wallet.
5. Streams prices, candles, indicators, signals and trades to a browser dashboard over WebSocket.

```
Jupiter Price API -> Trading engine (Python) -> Nemotron signal (JSON)
                          |                          |
                   indicators / candles       demo portfolio (default)
                          |                   or live Jupiter swap (opt-in)
                   FastAPI + WebSocket
                          |
              Dashboard (TradingView Lightweight Charts)
```

If no `NVIDIA_API_KEY` is set, or the API call fails, the bot falls back to a simple rule-based scoring of the same indicators (labelled `[DEMO]`).

## Quick start (demo mode)

Requires Python 3.10 or newer.

```bash
git clone https://github.com/dedlYTiTAN/astralprism-defi-bot
cd astralprism-defi-bot
pip install -r requirements.txt

cp .env.example .env        # optional: add NVIDIA_API_KEY
cd backend
python main.py
```

Open http://localhost:8000. Leave `LIVE_MODE=false` (the default). In demo mode the bot starts with a simulated 2 SOL and 100 USDC.

## Configuration

Only four environment variables are read (see `backend/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `NVIDIA_API_KEY` | empty | Enables Nemotron signals. Without it the rule-based fallback is used. |
| `LIVE_MODE` | `false` | Enables real mainnet swaps. Experimental, see warning below. |
| `WALLET_PRIVATE_KEY` | empty | Base58 key for live mode. Only ever use a dedicated, nearly empty wallet. |
| `MAX_LOSS_USD` | `10` | Loss cap used by the live-mode risk checks. |

Other tuning values (analysis interval, poll interval, slippage, trade limits, demo balances) are constants in `backend/config.py`, not environment variables. The `JUPITER_API_KEY` and "Bot Tuning" lines in `.env.example` are not currently read by the code.

## Indicators

RSI(14), EMA 9/21 crossover, MACD(12, 26, 9), Bollinger Bands(20, 2 sigma), 5-tick momentum, volatility, and correlation with SOL, all in pure Python (`backend/indicators.py`). They are computed on the raw 5-second price ticks, not on candles, so a "14-period" RSI covers roughly 70 seconds of data. The dashboard aggregates ticks into 1-minute candles for display only.

## API

| Endpoint | Purpose |
|---|---|
| `GET /` | Dashboard |
| `GET /api/state` | Full bot state |
| `POST /api/bot/pause` | Toggle pause (prices keep updating) |
| `POST /api/trade` | Manual trade |
| `POST /api/airdrop` | Request a devnet SOL airdrop |
| `GET /api/trades` | Trade history |
| `GET /api/wallet` | Devnet wallet info |
| `WS /ws` | Real-time event stream |

The server has no authentication. Run it on your own machine only.

## Known limitations

- **Not validated.** No backtest, no forward test, no comparison against simple baselines or buy-and-hold.
- **Indicator settings are mismatched to the data.** Standard daily-chart parameters are applied to 5-second polls of memecoin prices, which are not executable prices.
- **Demo fills are optimistic.** Simulated trades fill at the polled mid price with no fees or slippage, and realised P&L is not tracked, so demo results will overstate real performance.
- **LLM output is not validated or logged for evaluation.** There is no schema check on the response and no record of signals against outcomes.
- **Live mode is experimental.** It has known safety gaps (no API authentication, and exit sizing and kill-switch behaviour that have not been tested). Do not use it with real funds.
- **No automated tests.**
- Uses the public Solana RPC endpoint, which is rate-limited.

## Files

| File | Purpose |
|---|---|
| `backend/main.py` | FastAPI server and WebSocket |
| `backend/trading_engine.py` | Price loop, analysis loop, trailing stops, trade execution |
| `backend/nemotron_client.py` | LLM prompt, response parsing, rule-based fallback |
| `backend/indicators.py` | Indicators, candle aggregation, correlations |
| `backend/jupiter_client.py` | Jupiter prices and quotes |
| `backend/solana_client.py` | Devnet wallet, airdrop, `DemoPortfolio` |
| `backend/live_portfolio.py` | Live balances and risk checks |
| `backend/trade_executor.py` | Builds, signs and sends Jupiter swaps |
| `backend/config.py` | Token registry and parameters |
| `frontend/` | Dashboard (HTML, CSS, JS) |

## Purpose

A learning project to explore LLM-assisted signal generation, Solana swap execution and real-time dashboards. It is not a trading system.
