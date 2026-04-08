"""
Solana Devnet Client
- Generates a real Solana keypair
- Requests SOL airdrop on devnet
- Simulates demo trade execution (real quotes, simulated on-chain settlement)
  NOTE: Jupiter only runs on mainnet, so we use real mainnet quotes
  but simulate the swap settlement locally with devnet wallet tracking.
"""
import asyncio
import json
import logging
import os
import time
import base58
import httpx
from config import SOLANA_DEVNET_RPC, DEMO_SOL_BALANCE, DEMO_USDC_BALANCE

logger = logging.getLogger(__name__)

WALLET_FILE = os.path.join(os.path.dirname(__file__), ".wallet.json")


class SolanaClient:
    def __init__(self):
        self.keypair: dict = {}        # {"publicKey": str, "secretKey": list[int]}
        self.public_key: str = ""
        self.devnet_sol_balance: float = 0.0  # actual devnet balance
        self._rpc = SOLANA_DEVNET_RPC

    async def setup(self):
        """Load or create a devnet wallet."""
        if os.path.exists(WALLET_FILE):
            with open(WALLET_FILE) as f:
                self.keypair = json.load(f)
            self.public_key = self.keypair["publicKey"]
            logger.info(f"Loaded existing wallet: {self.public_key}")
        else:
            await self._create_wallet()

        await self._refresh_devnet_balance()

    async def _create_wallet(self):
        """Generate a new Ed25519 keypair for Solana."""
        try:
            from solders.keypair import Keypair as SolKeypair
            kp = SolKeypair()
            secret = list(bytes(kp))          # 64 bytes: seed + pubkey
            pubkey = str(kp.pubkey())
        except ImportError:
            # Fallback: use nacl directly
            import nacl.signing
            sk = nacl.signing.SigningKey.generate()
            vk = sk.verify_key
            secret = list(bytes(sk)) + list(bytes(vk))
            pubkey = base58.b58encode(bytes(vk)).decode()

        self.keypair   = {"publicKey": pubkey, "secretKey": secret}
        self.public_key = pubkey

        with open(WALLET_FILE, "w") as f:
            json.dump(self.keypair, f)
        logger.info(f"Created new devnet wallet: {pubkey}")

    async def request_airdrop(self, sol_amount: float = 1.0) -> dict:
        """
        Request SOL airdrop with retry logic.
        Returns dict with success status and faucet fallback URL.
        """
        lamports = int(sol_amount * 1_000_000_000)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "requestAirdrop",
            "params": [self.public_key, lamports],
        }

        # Try up to 3 times with decreasing amounts
        attempts = [
            (sol_amount, lamports),
            (0.5, int(0.5 * 1_000_000_000)),
            (0.1, int(0.1 * 1_000_000_000)),
        ]

        for amt, lamps in attempts:
            payload["params"] = [self.public_key, lamps]
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(self._rpc, json=payload)
                    data = resp.json()
                    if "result" in data:
                        logger.info(f"Airdrop succeeded: {amt} SOL → {self.public_key}")
                        await asyncio.sleep(2)
                        await self._refresh_devnet_balance()
                        return {"success": True, "amount": amt}
                    elif "error" in data:
                        logger.warning(f"Airdrop attempt ({amt} SOL) failed: {data['error']}")
                        await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Airdrop attempt ({amt} SOL) error: {e}")
                await asyncio.sleep(1)

        # All retries failed — return faucet fallback
        faucet_url = f"https://faucet.solana.com/?wallet={self.public_key}"
        logger.warning(f"All airdrop attempts failed. Use web faucet: {faucet_url}")
        return {
            "success": False,
            "faucetUrl": faucet_url,
            "message": "Devnet rate-limited. Use the web faucet instead.",
        }

    async def _refresh_devnet_balance(self):
        """Query actual SOL balance on devnet."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [self.public_key, {"commitment": "confirmed"}],
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._rpc, json=payload)
                data = resp.json()
                lamports = data.get("result", {}).get("value", 0)
                self.devnet_sol_balance = lamports / 1_000_000_000
        except Exception as e:
            logger.warning(f"Balance refresh failed: {e}")

    async def get_devnet_sol(self) -> float:
        await self._refresh_devnet_balance()
        return self.devnet_sol_balance

    async def get_recent_transactions(self, limit: int = 5) -> list:
        """Fetch recent devnet transaction signatures."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [self.public_key, {"limit": limit}],
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._rpc, json=payload)
                data = resp.json()
                sigs = data.get("result", [])
                return [
                    {
                        "signature": s.get("signature", "")[:20] + "...",
                        "slot":      s.get("slot", 0),
                        "timestamp": s.get("blockTime", 0),
                        "err":       s.get("err"),
                    }
                    for s in sigs
                ]
        except Exception:
            return []

    def explorer_url(self) -> str:
        return f"https://explorer.solana.com/address/{self.public_key}?cluster=devnet"


class DemoPortfolio:
    """
    Tracks simulated trading portfolio.
    Uses real Jupiter quotes for execution prices but simulates settlement.
    """
    def __init__(self, start_sol: float = DEMO_SOL_BALANCE, start_usdc: float = DEMO_USDC_BALANCE):
        self.sol:          float = start_sol
        self.usdc:         float = start_usdc
        self.token_bags:   dict  = {}   # token → units held
        self.trades:       list  = []
        self.initial_value: float = 0.0  # set on first price tick
        self._initial_prices: dict = {}

    def set_initial_value(self, prices: dict[str, float]):
        if not self._initial_prices:
            self._initial_prices = dict(prices)
            self.initial_value = (
                self.sol * prices.get("SOL", 0) +
                self.usdc +
                sum(self.token_bags.get(t, 0) * prices.get(t, 0) for t in self.token_bags)
            )

    def current_value(self, prices: dict[str, float]) -> float:
        token_value = sum(
            self.token_bags.get(sym, 0) * prices.get(sym, 0)
            for sym in self.token_bags
        )
        return self.sol * prices.get("SOL", 0) + self.usdc + token_value

    def pnl(self, prices: dict[str, float]) -> float:
        if self.initial_value == 0:
            return 0.0
        return self.current_value(prices) - self.initial_value

    def pnl_pct(self, prices: dict[str, float]) -> float:
        if self.initial_value == 0:
            return 0.0
        return (self.pnl(prices) / self.initial_value) * 100

    def execute_demo_trade(
        self,
        signal: dict,
        quote: dict,
        prices: dict[str, float],
    ) -> dict:
        """
        Simulate executing a trade based on Nemotron signal + Jupiter quote.
        Returns trade record dict.
        """
        token      = signal["token"]
        side       = signal["signal"]   # BUY or SELL
        price      = prices.get(token, 0)
        size_pct   = signal.get("suggestedSizePct", 10) / 100.0
        confidence = signal.get("confidence", 0.5)

        if price == 0 or side == "HOLD":
            return {}

        pnl_usd = 0.0
        fill_qty = 0.0
        fill_cost = 0.0

        if side == "BUY":
            # Spend a portion of USDC to buy token
            spend_usdc = min(self.usdc * size_pct, self.usdc * 0.25)  # cap at 25%
            if token == "SOL":
                fill_qty   = spend_usdc / price
                fill_cost  = spend_usdc
                self.sol  += fill_qty
                self.usdc -= fill_cost
            else:
                fill_qty  = spend_usdc / price
                fill_cost = spend_usdc
                self.token_bags[token] = self.token_bags.get(token, 0) + fill_qty
                self.usdc -= fill_cost

        elif side == "SELL":
            if token == "SOL":
                sell_qty  = self.sol * size_pct
                fill_qty  = sell_qty
                fill_cost = sell_qty * price
                self.sol  -= sell_qty
                self.usdc += fill_cost
            else:
                held = self.token_bags.get(token, 0)
                sell_qty  = held * size_pct
                fill_qty  = sell_qty
                fill_cost = sell_qty * price
                self.token_bags[token] = held - sell_qty
                self.usdc += fill_cost

        trade = {
            "id":          len(self.trades) + 1,
            "timestamp":   time.time(),
            "side":        side,
            "token":       token,
            "size":        round(fill_qty, 6),
            "price":       round(price, 6),
            "cost":        round(fill_cost, 4),
            "confidence":  round(confidence, 3),
            "condition":   signal.get("marketCondition", "NEUTRAL"),
            "risk":        signal.get("riskLevel", "MEDIUM"),
            "pnl":         round(pnl_usd, 4),
            "route":       quote.get("route", "Jupiter") if quote else "Simulated",
            "priceImpact": round(quote.get("priceImpact", 0) * 100, 4) if quote else 0,
            "status":      "FILLED",
        }
        self.trades.append(trade)
        return trade

    def to_dict(self, prices: dict[str, float]) -> dict:
        return {
            "sol":          round(self.sol, 6),
            "usdc":         round(self.usdc, 4),
            "tokens":       {k: round(v, 6) for k, v in self.token_bags.items()},
            "totalValueUSD": round(self.current_value(prices), 4),
            "initialValue": round(self.initial_value, 4),
            "pnl":          round(self.pnl(prices), 4),
            "pnlPct":       round(self.pnl_pct(prices), 4),
            "tradeCount":   len(self.trades),
        }
