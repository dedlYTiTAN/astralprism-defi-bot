"""
AstralPrism DeFi Bot — Configuration & Token Registry
Uses Nemotron 3 Super (nvidia/nemotron-3-super-120b-a12b) via NVIDIA NIM
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Token Registry ───────────────────────────────────────────────────────────
TOKENS = {
    "SOL": {
        "mint": "So11111111111111111111111111111111111111112",
        "symbol": "SOL",
        "name": "Solana",
        "decimals": 9,
        "color": "#9945FF",
    },
    "USDC": {
        "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "symbol": "USDC",
        "name": "USD Coin",
        "decimals": 6,
        "color": "#2775CA",
    },
    "JUP": {
        "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "symbol": "JUP",
        "name": "Jupiter",
        "decimals": 6,
        "color": "#C7F284",
    },
    "BONK": {
        "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "symbol": "BONK",
        "name": "Bonk",
        "decimals": 5,
        "color": "#F7931A",
    },
    "WIF": {
        "mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "symbol": "WIF",
        "name": "dogwifhat",
        "decimals": 6,
        "color": "#FF6B6B",
    },
}

# Monitored pairs — all quoted in USDC
TRADING_PAIRS = ["SOL", "JUP", "BONK", "WIF"]

# ─── API Endpoints ─────────────────────────────────────────────────────────────
NVIDIA_API_KEY       = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL      = "https://integrate.api.nvidia.com/v1"
NEMOTRON_MODEL       = "nvidia/nemotron-3-super-120b-a12b"   # 120B reasoning model

JUPITER_QUOTE_API    = "https://api.jup.ag/swap/v1"   # New Jupiter Swap API v1
JUPITER_PRICE_API    = "https://api.jup.ag/price/v2"  # New Jupiter Price API v2
COINGECKO_API        = "https://api.coingecko.com/api/v3"  # Fallback prices

SOLANA_DEVNET_RPC    = "https://api.devnet.solana.com"
SOLANA_MAINNET_RPC   = "https://api.mainnet-beta.solana.com"

# ─── Bot Parameters ────────────────────────────────────────────────────────────
ANALYSIS_INTERVAL_SEC = 20          # AI runs every 20 seconds
PRICE_POLL_INTERVAL   = 5           # Price refresh every 5 seconds
PRICE_HISTORY_MAX     = 120         # Keep 120 price ticks per token
DEMO_TRADE_SOL        = 0.05        # 0.05 SOL per demo trade
DEMO_USDC_BALANCE     = 100.0       # Starting simulated USDC
DEMO_SOL_BALANCE      = 2.0         # Starting simulated SOL (devnet)
MAX_SLIPPAGE_BPS      = 50          # 0.5% slippage tolerance
AIRDROP_SOL           = 1           # SOL to request from devnet airdrop

# ─── Live Trading (mainnet) ────────────────────────────────────────────────────
# LIVE_MODE=true executes real swaps on Solana mainnet via Jupiter
# Set WALLET_PRIVATE_KEY to a DEDICATED BURNER WALLET — never your main wallet
LIVE_MODE            = os.getenv("LIVE_MODE", "false").lower() == "true"
WALLET_PRIVATE_KEY   = os.getenv("WALLET_PRIVATE_KEY", "")   # base58 Phantom private key
MAX_LOSS_USD         = float(os.getenv("MAX_LOSS_USD", "10")) # Hard kill at $10 loss
MIN_CONFIDENCE_LIVE  = 0.65         # Only trade if AI confidence >= 65%
MAX_TRADE_PCT        = 0.20         # Max 20% of portfolio per trade
MAX_TRADES_PER_MIN   = 2            # Throttle: max 2 trades per minute
MIN_SOL_FOR_FEES     = 0.005        # Keep this much SOL for gas fees
SWAP_PRIORITY_FEE    = 100_000      # microlamports priority fee
