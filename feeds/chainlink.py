"""
Chainlink Feed + Lag Detector

Uses raw JSON-RPC eth_call via aiohttp — no web3.py threading issues.
Polls every 5 seconds with exponential backoff retry for Alchemy 429s.

Chainlink BTC/USD only updates onchain when:
  (a) price moves ≥ 0.5%  OR  (b) heartbeat timeout (~1 hour)
This creates lag vs Binance spot — which is the edge Bot A exploits.
"""

import asyncio
import logging
import time
import aiohttp
from config import (
    CHAINLINK_RPC_URL, CHAINLINK_BTC_FEED,
    BOT_A_MIN_DEVIATION, BOT_A_MAX_DEVIATION, BOT_A_MIN_SUSTAIN_SECS,
    CHAINLINK_POLL_SECS,
)

logger = logging.getLogger(__name__)

# keccak256("latestRoundData()") first 4 bytes
LATEST_ROUND_SELECTOR = "0xfeaf968c"

FEEDS = {
    "BTC": CHAINLINK_BTC_FEED,
    "ETH": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
    "SOL": "0x4ffC43a60e009B551865A93d232E33Fce9f01507",
    "BNB": "0x14e613AC84a31f709eadbdF89C6CC390fDc9540A",
}


class ChainlinkFeed:

    def __init__(self, binance_feed):
        self.binance              = binance_feed
        
        # Per-asset state dictionaries
        self.prices       = {}
        self.updated_ats  = {}
        self.deviation_pcts = {}
        self.lag_signals  = {}
        self.lag_directions = {}
        self.lag_sustaineds = {}
        
        self._dev_starts  = {}
        self._dev_dirs    = {}
        
        # Initialize default values
        for asset in FEEDS:
            self.prices[asset] = None
            self.updated_ats[asset] = None
            self.deviation_pcts[asset] = 0.0
            self.lag_signals[asset] = 0.0
            self.lag_directions[asset] = None
            self.lag_sustaineds[asset] = 0.0
            self._dev_starts[asset] = None
            self._dev_dirs[asset] = None

        self._running             = False
        self._session             = None
        self._first_fetch_done    = False

        if not CHAINLINK_RPC_URL:
            logger.error(
                "ALCHEMY_RPC_URL not set in .env\n"
                "  → https://dashboard.alchemy.com → Create App → Ethereum Mainnet"
            )

    async def start(self):
        self._running = True
        self._session = aiohttp.ClientSession()
        logger.info("Chainlink feed starting | rpc=%s...", CHAINLINK_RPC_URL[:45])
        try:
            while self._running:
                try:
                    await self._fetch_with_retry()
                    for asset in FEEDS:
                        self._update_lag(asset)
                except Exception as e:
                    logger.warning("Chainlink poll failed: %s", e)
                await asyncio.sleep(CHAINLINK_POLL_SECS)
        finally:
            await self._session.close()

    def stop(self):
        self._running = False

    async def _fetch_with_retry(self):
        """Exponential backoff: 0s, 1s, 2s, 4s — handles Alchemy 429s."""
        delays   = [1, 2, 4]
        last_err = None
        for attempt, delay in enumerate([0] + delays, 1):
            if delay:
                await asyncio.sleep(delay)
            try:
                await self._fetch()
                if attempt > 1:
                    logger.info("Chainlink fetch OK on attempt %d", attempt)
                return
            except Exception as e:
                last_err = e
                logger.debug("Chainlink attempt %d failed: %s", attempt, e)
        raise last_err

    async def _fetch(self):
        """Raw eth_call JSON-RPC — fetching all feeds concurrently."""
        tasks = [self._fetch_single(asset, address) for asset, address in FEEDS.items()]
        await asyncio.gather(*tasks)

    async def _fetch_single(self, asset: str, address: str):
        payload = {
            "jsonrpc": "2.0",
            "method":  "eth_call",
            "params":  [
                {"to": address, "data": LATEST_ROUND_SELECTOR},
                "latest"
            ],
            "id": 1,
        }
        async with self._session.post(
            CHAINLINK_RPC_URL, json=payload,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            data = await resp.json()

        if "error" in data:
            raise RuntimeError(f"RPC error for {asset}: {data['error']}")

        result = data.get("result", "")
        if not result or result == "0x" or len(result) < 130:
            raise RuntimeError(f"Invalid response from {asset} Chainlink contract")

        raw = result[2:]
        price = int(raw[64:128], 16) / 1e8
        updated_at = int(raw[192:256], 16)
        
        self.prices[asset] = price
        self.updated_ats[asset] = updated_at

        if not self._first_fetch_done and asset == "BTC":
            logger.info("Chainlink multi-asset feed working. BTC=$%.2f", price)
            self._first_fetch_done = True

    def _update_lag(self, asset: str):
        cl_price = self.prices.get(asset)
        bn_price = self.binance.get_price(asset)
        
        if not cl_price or not bn_price:
            return
            
        dev = (bn_price - cl_price) / cl_price * 100
        self.deviation_pcts[asset] = dev
        direction = "up" if dev > 0 else "down"
        now = time.time()

        if abs(dev) >= BOT_A_MIN_DEVIATION and abs(dev) <= BOT_A_MAX_DEVIATION:
            if self._dev_dirs[asset] != direction:
                self._dev_starts[asset] = now
                self._dev_dirs[asset] = direction
            self.lag_sustaineds[asset] = now - (self._dev_starts[asset] or now)

            if self.lag_sustaineds[asset] >= BOT_A_MIN_SUSTAIN_SECS:
                magnitude = min(abs(dev) / BOT_A_MIN_DEVIATION * 0.3, 1.0)
                self.lag_signals[asset] = magnitude if direction == "up" else -magnitude
                self.lag_directions[asset] = direction
                # Only spam debug logs for BTC to keep noise down
                if asset == "BTC":
                    logger.debug(
                        "[%s] Lag ACTIVE dev=%.3f%% dir=%s sustained=%.1fs signal=%.2f",
                        asset, dev, direction, self.lag_sustaineds[asset], self.lag_signals[asset]
                    )
            else:
                self.lag_signals[asset] = 0.0
        else:
            self._dev_starts[asset] = None
            self._dev_dirs[asset] = None
            self.lag_sustaineds[asset] = 0.0
            self.lag_signals[asset] = 0.0
            self.lag_directions[asset] = None

    # ── Legacy Properties for Bot A / BaseBot compatibility (BTC ONLY) ────────
    @property
    def price(self) -> float | None:
        return self.prices.get("BTC")
        
    @property
    def deviation_pct(self) -> float:
        return self.deviation_pcts.get("BTC", 0.0)

    @property
    def lag_signal(self) -> float:
        return self.lag_signals.get("BTC", 0.0)
        
    @property
    def lag_sustained(self) -> float:
        return self.lag_sustaineds.get("BTC", 0.0)
        
    @property
    def lag_detected(self) -> bool:
        return abs(self.lag_signal) > 0.01

    @property
    def staleness_secs(self) -> float:
        updated_at = self.updated_ats.get("BTC")
        if not updated_at:
            return 999.0
        return time.time() - updated_at