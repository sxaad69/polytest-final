"""
Bot Sniper — Dual-Window Momentum Sniper
Inherits from Bot G for proven execution and infrastructure.

Strategy:
  Sniper 1 — Early (15s–60s): Buy the dominant side (>=52.5c), TP+10c, SL-8c, 2-min time stop.
  Sniper 2 — Late  (225s+):   Buy the dominant side (>=52.5c), TP+10c, SL-50c, settle on expiry.

Both can fire on the same market — Sniper 2 requires Sniper 1 to have already exited first.
Sniper mode is identified in trader.py via confidence: 1.0=S1, 2.0=S2.
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
        self.strike_assets = config.BOT_SNIPER_STRIKE_ASSETS

        # Per-sniper lockout dicts: {market_id: win_end}
        # Separate so Sniper 2 can still fire after Sniper 1 exits
        self._sniper1_traded: dict = {}
        self._sniper2_traded: dict = {}

        self._setup_rejection_logger()

    def _setup_rejection_logger(self):
        self._rej_log = logging.getLogger("bot_sniper_rejection")
        self._rej_log.setLevel(logging.INFO)
        if not self._rej_log.handlers:
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            self._rej_log.addHandler(console)

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
        slug      = m.get("slug", "")
        market_id = m.get("condition_id")

        # ── Detect timeframe from slug ────────────────────────────────────────
        # Slug format: {asset}-updown-{timeframe}-{ts} (e.g. btc-updown-5m-123456)
        timeframe = "5m"   # default
        if "-15m-" in slug:
            timeframe = "15m"
        tf_duration = 300 if timeframe == "5m" else 900

        # ── Parse window timestamps ───────────────────────────────────────────
        win_start = m.get("win_start")
        win_end   = m.get("win_end")
        if not win_start or not win_end:
            parts = slug.rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit():
                ts        = int(parts[1])
                win_start = float(ts)
                win_end   = float(ts + tf_duration)
            else:
                return

        now          = time.time()
        elapsed_secs = now - win_start

        # Skip if market window has effectively ended
        if elapsed_secs < 0 or (win_end - now) < 5:
            return

        # ── Purge expired entries from lockout dicts ──────────────────────────
        self._sniper1_traded = {mid: end for mid, end in self._sniper1_traded.items() if now < end}
        self._sniper2_traded = {mid: end for mid, end in self._sniper2_traded.items() if now < end}

        # ── Price discovery ───────────────────────────────────────────────────
        current_price = self._get_fair_value(tid)
        if current_price is None:
            self._log_skip(slug, "price_discovery_failed")
            return

        yes_price = round(current_price, 4)
        no_price  = round(1.0 - current_price, 4)

        # ── Route to the appropriate sniper window ────────────────────────────
        import config as cfg
        if timeframe == "15m":
            s1_start = getattr(cfg, "SNIPER_15M_1_START_SECS", 30)
            s1_end   = getattr(cfg, "SNIPER_15M_1_END_SECS", 180)
        else:
            s1_start = getattr(cfg, "SNIPER_1_START_SECS", 15)
            s1_end   = getattr(cfg, "SNIPER_1_END_SECS", 60)
        s2_start = getattr(cfg, "SNIPER_2_START_SECS", 225)

        in_s1_window = s1_start <= elapsed_secs <= s1_end
        in_s2_window = elapsed_secs >= s2_start

        if not in_s1_window and not in_s2_window:
            return  # Not in any active window — silent skip

        # ── Sniper 1 — Early Momentum ─────────────────────────────────────────
        if in_s1_window and market_id not in self._sniper1_traded:
            dominance = getattr(cfg, "SNIPER_1_MIN_DOMINANCE", 0.525)
            direction, trade_price, trade_token_id = self._check_dominance(
                tid, m, yes_price, no_price, dominance, slug
            )
            if direction:
                trade_id = await self._fire_entry(
                    tid, m, slug, market_id, win_start, win_end,
                    direction, trade_token_id, trade_price,
                    confidence=1.0, sniper_label="S1", timeframe=timeframe
                )
                if trade_id:
                    self._sniper1_traded[market_id] = win_end
            return  # Don't fall through to S2 in same tick

        # ── Sniper 2 — Late Entry ─────────────────────────────────────────────
        if in_s2_window and market_id not in self._sniper2_traded:
            dominance = getattr(cfg, "SNIPER_2_MIN_DOMINANCE", 0.525)
            direction, trade_price, trade_token_id = self._check_dominance(
                tid, m, yes_price, no_price, dominance, slug
            )
            if direction:
                trade_id = await self._fire_entry(
                    tid, m, slug, market_id, win_start, win_end,
                    direction, trade_token_id, trade_price,
                    confidence=2.0, sniper_label="S2", timeframe=timeframe
                )
                if trade_id:
                    self._sniper2_traded[market_id] = win_end

    def _check_dominance(self, tid, m, yes_price, no_price, min_dominance, slug):
        """
        Returns (direction, trade_price, trade_token_id) if one side dominates,
        else (None, None, None).
        Prefers YES side if both exceed threshold (edge case).
        """
        if yes_price >= min_dominance:
            return "long", yes_price, tid

        if no_price >= min_dominance:
            peer_id = m.get("peer_id") or self.poly.get_peer_id(tid)
            if peer_id:
                return "short", no_price, peer_id
            else:
                self._log_skip(slug, "no_peer_token_mapped")

        return None, None, None

    async def _fire_entry(
        self, tid, m, slug, market_id, win_start, win_end,
        direction, trade_token_id, trade_odds,
        confidence, sniper_label, timeframe="5m"
    ):
        """Execute the buy order via the proven executor pipeline."""
        stake = config.SNIPER_STAKE

        # Apply +3c slippage for FOK order to cross the spread
        SLIPPAGE    = 0.03
        entry_price = round(min(0.98, trade_odds + SLIPPAGE), 4)

        logger.info(
            "[BotSniper][%s] TRIGGER | %s | dir=%s odds=%.3f",
            sniper_label, slug, direction, trade_odds
        )

        # Lock immediately to prevent race condition on concurrent tasks
        if confidence == 1.0:
            self._sniper1_traded[market_id] = win_end
        else:
            self._sniper2_traded[market_id] = win_end

        # Gather background metrics for DB entry
        asset_symbol = slug.split("-")[0].upper()
        bn_price = self.binance.get_price(asset_symbol) or 0.0
        
        cl_price = self.chainlink.prices.get(asset_symbol) if hasattr(self.chainlink, 'prices') else None
        cl_lag = self.chainlink.lag_signals.get(asset_symbol) if hasattr(self.chainlink, 'lag_signals') else None

        trade_id = await self.executor.enter(
            direction=direction,
            confidence=confidence,
            stake=stake,
            signal_id=0,
            token_id=trade_token_id,
            entry_odds=entry_price,
            market_id=market_id,
            win_start=win_start,
            win_end=win_end,
            condition_id=market_id,
            asset=asset_symbol,
            slug=slug,
            binance_price=bn_price,
            chainlink_price_entry=cl_price,
            chainlink_lag=cl_lag,
            timeframe=timeframe,
        )

        if not trade_id:
            # Revert lock if order was rejected/not filled
            if confidence == 1.0:
                self._sniper1_traded.pop(market_id, None)
            else:
                self._sniper2_traded.pop(market_id, None)

        return trade_id
