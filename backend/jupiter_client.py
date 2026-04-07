"""
Jupiter DEX Aggregator Client — Updated for api.jup.ag/swap/v1 + api.jup.ag/price/v2
With CoinGecko fallback for broader token coverage.
"""
import asyncio
import time
import logging
from typing import Optional
import httpx
from config import (
    TOKENS, JUPITER_QUOTE_API, JUPITER_PRICE_API,
    COINGECKO_API, TRADING_PAIRS,
)

logger = logging.getLogger(__name__)

COINGECKO_IDS = {
    "SOL":  "solana",
    "JUP":  "jupiter-exchange-solana",
    "BONK": "bonk",
    "WIF":  "dogwifcoin",
}


class JupiterClient:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._price_cache: dict = {}
        self._cache_ttl = 4   # seconds

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(12.0),
            headers={"Accept": "application/json", "User-Agent": "AstralPrismBot/1.0"},
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def get_prices(self, symbols: list[str] = None) -> dict[str, float]:
        """
        Fetch USD prices — tries Jupiter Price API v2 first, falls back to CoinGecko.
        """
        symbols = symbols or TRADING_PAIRS
        now = time.time()
        if self._price_cache.get("ts", 0) + self._cache_ttl > now:
            return self._price_cache.get("data", {})

        prices = await self._fetch_jupiter_prices(symbols)
        if not prices:
            prices = await self._fetch_coingecko_prices(symbols)

        if prices:
            self._price_cache = {"ts": now, "data": prices}
        return prices

    async def _fetch_jupiter_prices(self, symbols: list[str]) -> dict[str, float]:
        """Jupiter Price API v2: api.jup.ag/price/v2"""
        mints = ",".join(TOKENS[s]["mint"] for s in symbols if s in TOKENS)
        try:
            resp = await self._client.get(
                f"{JUPITER_PRICE_API}",
                params={"ids": mints},
            )
            resp.raise_for_status()
            raw = resp.json().get("data", {})
            prices: dict[str, float] = {}
            for sym in symbols:
                mint = TOKENS[sym]["mint"]
                if mint in raw and raw[mint]:
                    p = raw[mint].get("price")
                    if p:
                        prices[sym] = float(p)
            if prices:
                logger.debug(f"Jupiter prices: {prices}")
                return prices
        except Exception as e:
            logger.debug(f"Jupiter price API failed: {e}")
        return {}

    async def _fetch_coingecko_prices(self, symbols: list[str]) -> dict[str, float]:
        """CoinGecko fallback: api.coingecko.com/api/v3/simple/price"""
        cg_ids = [COINGECKO_IDS[s] for s in symbols if s in COINGECKO_IDS]
        if not cg_ids:
            return {}
        try:
            resp = await self._client.get(
                f"{COINGECKO_API}/simple/price",
                params={"ids": ",".join(cg_ids), "vs_currencies": "usd"},
            )
            resp.raise_for_status()
            raw = resp.json()
            prices: dict[str, float] = {}
            for sym in symbols:
                cg_id = COINGECKO_IDS.get(sym)
                if cg_id and cg_id in raw:
                    prices[sym] = float(raw[cg_id]["usd"])
            logger.debug(f"CoinGecko prices: {prices}")
            return prices
        except Exception as e:
            logger.debug(f"CoinGecko price API failed: {e}")
        return {}

    async def get_quote(
        self,
        input_symbol: str,
        output_symbol: str,
        input_amount_ui: float,
        slippage_bps: int = 50,
    ) -> Optional[dict]:
        """
        Get best swap quote via Jupiter Swap API v1.
        """
        input_token  = TOKENS.get(input_symbol)
        output_token = TOKENS.get(output_symbol)
        if not input_token or not output_token:
            return None

        decimals   = input_token["decimals"]
        raw_amount = int(input_amount_ui * (10 ** decimals))

        try:
            params = {
                "inputMint":   input_token["mint"],
                "outputMint":  output_token["mint"],
                "amount":      raw_amount,
                "slippageBps": slippage_bps,
            }
            resp = await self._client.get(f"{JUPITER_QUOTE_API}/quote", params=params)
            resp.raise_for_status()
            quote = resp.json()

            out_decimals = output_token["decimals"]
            out_amount   = int(quote.get("outAmount", 0)) / (10 ** out_decimals)
            in_amount    = int(quote.get("inAmount",  0)) / (10 ** decimals)
            price_impact = float(quote.get("priceImpactPct", 0))

            # Extract DEX route labels
            route_plan = quote.get("routePlan", [])
            dexes = []
            for step in route_plan[:3]:
                label = step.get("swapInfo", {}).get("label", "")
                if label and label not in dexes:
                    dexes.append(label)
            route_label = " → ".join(dexes) if dexes else "Jupiter"

            return {
                "inputSymbol":    input_symbol,
                "outputSymbol":   output_symbol,
                "inAmount":       in_amount,
                "outAmount":      out_amount,
                "priceImpact":    price_impact,
                "route":          route_label,
                "executionPrice": out_amount / in_amount if in_amount else 0,
                "rawQuote":       quote,
            }

        except Exception as e:
            logger.debug(f"Quote failed ({input_symbol}→{output_symbol}): {e}")
            return None

    async def get_sol_price(self) -> float:
        prices = await self.get_prices(["SOL"])
        return prices.get("SOL", 0.0)

    async def get_market_metrics(self) -> dict:
        prices = await self.get_prices()
        if not prices:
            return {}

        small_quote = await self.get_quote("SOL", "USDC", 0.1)
        large_quote = await self.get_quote("SOL", "USDC", 10.0)

        depth_score = 1.0
        if small_quote and large_quote and small_quote["executionPrice"] > 0:
            depth_score = round(
                large_quote["executionPrice"] / small_quote["executionPrice"], 6
            )

        return {
            "prices":       prices,
            "solDepthScore": depth_score,
            "smallQuote":   small_quote,
            "largeQuote":   large_quote,
        }
