"""
AstralPrism DeFi Bot — FastAPI Server
Endpoints:
  GET  /          → Dashboard HTML
  GET  /api/state → Full bot state (JSON)
  POST /api/bot/start  → Start the bot
  POST /api/bot/pause  → Pause/resume trading (prices keep updating)
  POST /api/trade      → Manual demo trade
  POST /api/airdrop    → Request devnet SOL airdrop
  WS   /ws         → Real-time event stream
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from trading_engine import TradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

engine = TradingEngine()
_engine_task: asyncio.Task | None = None

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine_task
    logger.info("Starting trading engine background task...")
    _engine_task = asyncio.create_task(engine.start())
    yield
    engine.running = False
    if _engine_task:
        _engine_task.cancel()


app = FastAPI(
    title="AstralPrism DeFi Bot",
    description="Nemotron 3 Super + Jupiter DEX + Solana Devnet",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ─── REST Endpoints ───────────────────────────────────────────────────────────

@app.get("/")
async def root():
    html_path = FRONTEND_DIR / "index.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    return JSONResponse({"status": "running", "message": "AstralPrism DeFi Bot API"})


@app.get("/api/state")
async def get_state():
    return JSONResponse(engine.get_state())


@app.post("/api/bot/pause")
async def toggle_pause():
    if engine.paused:
        engine.resume()
        return {"status": "resumed"}
    else:
        engine.pause()
        return {"status": "paused"}


class TradeRequest(BaseModel):
    side:     str   # BUY | SELL
    token:    str   # SOL | JUP | BONK | WIF
    sizePct:  float = 10.0


@app.post("/api/trade")
async def manual_trade(req: TradeRequest):
    result = await engine.manual_trade(req.side, req.token, req.sizePct)
    return JSONResponse(result)


@app.post("/api/airdrop")
async def request_airdrop():
    result = await engine.sol_cli.request_airdrop(1.0)
    bal = await engine.sol_cli.get_devnet_sol()
    return {
        "success":   result.get("success", False),
        "balance":   bal,
        "amount":    result.get("amount", 0),
        "faucetUrl": result.get("faucetUrl", ""),
        "message":   result.get("message", ""),
    }


@app.get("/api/trades")
async def get_trades():
    return JSONResponse({"trades": engine.portfolio.trades})


@app.get("/api/wallet")
async def get_wallet():
    bal = await engine.sol_cli.get_devnet_sol()
    txns = await engine.sol_cli.get_recent_transactions(5)
    return {
        "publicKey":   engine.sol_cli.public_key,
        "devnetSol":   bal,
        "explorerUrl": engine.sol_cli.explorer_url(),
        "transactions": txns,
    }


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    engine.register_ws(ws)
    logger.info(f"WebSocket client connected: {ws.client}")

    # Send immediate state snapshot
    import json
    try:
        await ws.send_text(json.dumps({"type": "connected", **engine.get_state()}))
    except Exception:
        pass

    try:
        while True:
            # Keep connection alive; engine pushes messages directly
            await asyncio.sleep(30)
            await ws.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        engine.deregister_ws(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
