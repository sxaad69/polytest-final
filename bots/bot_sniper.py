"""
Bot Sniper — The Minute 1 "Picker" Specialist
Inherits from Bot G for proven execution and infrastructure.
Applies strict Minute 1 and 0.33-0.54 Power Band filters.
"""

import logging
import time
import asyncio
from bots.bot_g import BotG
import config

logger = logging.getLogger("bot_sniper")

class BotSniper(BotG):
    BOT_ID            = "SNIPER"
    DB_PATH           = config.BOT_SNIPER_DB_PATH
    STARTING_BANKROLL = config.BOT_SNIPER_BANKROLL

    def __init__(self, binance, chainlink, poly, wallet_address=None, polymarket_client=None):
        super().__init__(binance, chainlink, poly, wallet_address=wallet_address, polymarket_client=polymarket_client)
        # Use sniper-specific assets
        self.strike_assets = config.BOT_SNIPER_STRIKE_ASSETS
        self._setup_rejection_logger()

    def _setup_rejection_logger(self):
        self._rej_log = logging.getLogger("bot_sniper_rejection")
        self._rej_log.setLevel(logging.INFO)
        if not self._rej_log.handlers:
            # Console handler
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            self._rej_log.addHandler(console)
            
            # File handler
            path = "logs/bot_sniper_rejections.log"
            file_handler = logging.FileHandler(path)
            file_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            self._rej_log.addHandler(file_handler)

    def _log_skip(self, slug, reason, details=None):
        msg = f"[BotSniper] SKIP | {slug} | Reason: {reason}"
        if details:
            msg += f" | Data: {details}"
        self._rej_log.info(msg)

    async def _evaluate_market(self, tid: str, m: dict):
        slug = m.get("slug", "")
        market_id = m.get("condition_id")
        
        # 1. Standard Bot G Safety Checks (Market Lockout, etc.)
        if market_id in self._traded_markets:
            return

        # Parse window data
        win_start = m.get("win_start")
        win_end   = m.get("win_end")
        if not win_start or not win_end:
            # Fallback for slug timestamp
            parts = slug.rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit():
                ts = int(parts[1])
                win_start = float(ts)
                win_end   = float(ts + 300)
            else:
                return

        now = time.time()
        elapsed_secs = now - win_start

        # ── GATE 1: TIME (Minute 1 Sniper) ──────────────────────────────────
        if elapsed_secs > 60:
            self._log_skip(slug, "not_minute_1", f"elapsed={round(elapsed_secs, 1)}s")
            return
        if elapsed_secs < 0:
            return

        # ── GATE 2: PRICE DISCOVERY ──────────────────────────────────────────
        current_price = self._get_fair_value(tid)
        if current_price is None:
            return

        # ── GATE 3: DIRECTIONAL PRICE BAND (PURE PRICE PICKER) ──────────────
        direction = None
        trade_token_id = None
        trade_odds = 0.0

        # YES Check
        if config.SNIPER_MIN_ODDS <= current_price <= config.SNIPER_MAX_ODDS:
            if config.SNIPER_DIRECTION in ["long", None]:
                direction = "long"
                trade_token_id = tid
                trade_odds = current_price
        
        # NO Check (only if YES didn't trigger)
        if not direction and config.SNIPER_DIRECTION in ["short", None]:
            no_price = round(1.0 - current_price, 4)
            if config.SNIPER_MIN_ODDS <= no_price <= config.SNIPER_MAX_ODDS:
                peer_id = m.get("peer_id") or self.poly.get_peer_id(tid)
                if peer_id:
                    direction = "short"
                    trade_token_id = peer_id
                    trade_odds = no_price
                else:
                    self._log_skip(slug, "no_peer_token_mapped")
                    return

        if not direction:
            self._log_skip(slug, "odds_out_of_band", f"price={round(current_price, 3)}")
            return

        # ── EXECUTION ──────────────────────────────────────────────────────
        # Use Bot G's proven execution flow
        stake = config.SNIPER_STAKE
        
        # Apply standard slippage buffer for FOK orders
        SLIPPAGE = 0.03
        entry_price = round(min(0.98, trade_odds + SLIPPAGE), 4)

        logger.info(f"[BotSniper] TRIGGER | {slug} | dir={direction} odds={trade_odds:.3f}")
        
        trade_id = await self.executor.enter(
            direction=direction,
            confidence=1.0,
            stake=stake,
            signal_id=0,
            token_id=trade_token_id,
            entry_odds=entry_price,
            market_id=market_id,
            win_start=win_start,
            win_end=win_end,
            condition_id=market_id,
            asset=slug.split("-")[0].upper(),
            slug=slug,
        )

        if trade_id:
            self._traded_markets[market_id] = win_end
