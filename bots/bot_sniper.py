"""
Bot Sniper — Dual-Window Momentum Sniper
Inherits from Bot G for proven execution and infrastructure.

Strategy:
  Sniper 1 — Early (15s–60s): Buy the dominant side (>=52.5c), TP+15c, SL-8c, 3-min time stop.
  Sniper 2 — Late  (225s+):   Buy the dominant side (>=52.5c), TP+10c, SL-50c, settle on expiry.

DATA-DRIVEN FILTERS (from 149-trade analysis):
  - 5m longs at odds<0.58 = +11.26 USDC, 78.6% win rate (only profitable subset)
  - 15m disabled (net negative EV -8.33 USDC)
  - Shorts disabled (net negative EV -14.59 USDC)
  - SL enabled at -8c to cap losses (was disabled/99.0)

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
        self._sniper2_window_traded: dict = {} # {win_start: win_end} - Strict 1 trade per window cap

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

        # ── DATA-DRIVEN FILTER: 15m disabled (net negative EV -8.33 USDC) ──────
        if timeframe == "15m":
            return

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
        self._sniper2_window_traded = {w: end for w, end in self._sniper2_window_traded.items() if now < end}

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
        s2_start = getattr(cfg, "SNIPER_2_START_SECS", 210)
        s2_end   = getattr(cfg, "SNIPER_2_END_SECS", 255)

        in_s1_window = s1_start <= elapsed_secs <= s1_end
        in_s2_window = s2_start <= elapsed_secs <= s2_end

        if not in_s1_window and not in_s2_window:
            return  # Not in any active window — silent skip

        # ── Sniper 1 — Early Momentum ─────────────────────────────────────────
        if in_s1_window and market_id not in self._sniper1_traded:
            dominance = getattr(cfg, "SNIPER_1_MIN_DOMINANCE", 0.525)
            direction, trade_price, trade_token_id = self._check_dominance(
                tid, m, yes_price, no_price, dominance, slug, confidence=1.0
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
        win_key = int(win_start)
        if in_s2_window and market_id not in self._sniper2_traded and win_key not in self._sniper2_window_traded:
            dominance = getattr(cfg, "SNIPER_2_MIN_DOMINANCE", 0.55)
            direction, trade_price, trade_token_id = self._check_dominance(
                tid, m, yes_price, no_price, dominance, slug, confidence=2.0, win_start=win_start
            )
            if direction:
                trade_id = await self._fire_entry(
                    tid, m, slug, market_id, win_start, win_end,
                    direction, trade_token_id, trade_price,
                    confidence=2.0, sniper_label="S2", timeframe=timeframe
                )
                if trade_id:
                    self._sniper2_traded[market_id] = win_end
                    self._sniper2_window_traded[win_key] = win_end

    def _check_dominance(self, tid, m, yes_price, no_price, min_dominance, slug, confidence=1.0, win_start=None):
        """
        Returns (direction, trade_price, trade_token_id) if one side dominates,
        else (None, None, None).
        Prefers YES side if both exceed threshold (edge case).

        DATA-DRIVEN & QUANT FILTERS:
          - S1: Long-only filter, entry odds < 58c
          - S2: Near-Certain Terminal Strike-Distance filters (BTC >= $120, ETH >= $10, SOL >= $1.0)
        """
        import config as cfg

        asset_symbol = slug.split("-")[0].upper()
        mom_60s = self.binance.get_momentum(asset_symbol, seconds=60) if hasattr(self, "binance") else 0.0

        if confidence == 1.0:
            # ── Sniper 1 early filters ────────────────────────────────────────
            long_only = getattr(cfg, "SNIPER_1_LONG_ONLY", True)
            max_entry_odds = getattr(cfg, "SNIPER_1_MAX_ENTRY_ODDS", 0.58)

            if yes_price >= min_dominance:
                if yes_price <= max_entry_odds:
                    return "long", yes_price, tid
                else:
                    self._log_skip(slug, "odds_too_high", f"yes={yes_price:.3f} > {max_entry_odds}")
                    return None, None, None

            if long_only:
                return None, None, None

            if no_price >= min_dominance:
                peer_id = m.get("peer_id") or self.poly.get_peer_id(tid)
                if peer_id:
                    return "short", no_price, peer_id
                else:
                    self._log_skip(slug, "no_peer_token_mapped")
        else:
            # ── Sniper 2 Late-Window Near-Certain Strike-Distance filters ─────
            max_entry_odds = getattr(cfg, "SNIPER_2_MAX_ENTRY_ODDS", 0.92)
            
            # Strike Distance Check
            current_spot = self.binance.get_price(asset_symbol) if hasattr(self, "binance") else None
            open_strike = self.binance.get_strike_open(asset_symbol, win_start) if (hasattr(self, "binance") and win_start) else None

            # Fallback if open_strike not cached: try fetching from Coinbase candles
            if current_spot and not open_strike and win_start:
                try:
                    import requests
                    start_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(win_start))
                    end_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(win_start + 300))
                    prod = f"{asset_symbol}-USD"
                    resp = requests.get(f"https://api.exchange.coinbase.com/products/{prod}/candles?granularity=300&start={start_iso}&end={end_iso}", timeout=3)
                    if resp.status_code == 200 and resp.json():
                        candle = resp.json()[0]
                        open_strike = float(candle[3])
                        self.binance._strike_open[(prod, int(win_start))] = open_strike
                except Exception:
                    pass

            min_delta_map = getattr(cfg, "SNIPER_MIN_STRIKE_DELTA", {"BTC": 120.0, "ETH": 10.0, "SOL": 1.0})
            required_delta = min_delta_map.get(asset_symbol, 1.0)
            
            spot_delta = (current_spot - open_strike) if (current_spot and open_strike) else 0.0

            # Check YES (Long) side: spot must be significantly ABOVE strike
            if yes_price >= min_dominance:
                if yes_price > max_entry_odds:
                    self._log_skip(slug, "s2_odds_too_high", f"yes={yes_price:.3f} > {max_entry_odds}")
                    return None, None, None
                if open_strike and spot_delta < required_delta:
                    self._log_skip(slug, "s2_strike_cushion_too_small_long", f"spot={current_spot:.2f} open={open_strike:.2f} delta={spot_delta:.2f} < req={required_delta:.2f}")
                    return None, None, None
                if mom_60s <= 0.005:
                    self._log_skip(slug, "s2_insufficient_long_momentum", f"yes={yes_price:.3f} mom={mom_60s:.3f}%<=0.005%")
                    return None, None, None
                return "long", yes_price, tid

            # Check NO (Short) side: spot must be significantly BELOW strike
            if not getattr(cfg, "SNIPER_2_LONG_ONLY", False) and no_price >= min_dominance:
                if no_price > max_entry_odds:
                    self._log_skip(slug, "s2_odds_too_high", f"no={no_price:.3f} > {max_entry_odds}")
                    return None, None, None
                if open_strike and (-spot_delta) < required_delta:
                    self._log_skip(slug, "s2_strike_cushion_too_small_short", f"spot={current_spot:.2f} open={open_strike:.2f} delta={spot_delta:.2f} < req={-required_delta:.2f}")
                    return None, None, None
                if mom_60s >= -0.005:
                    self._log_skip(slug, "s2_insufficient_short_momentum", f"no={no_price:.3f} mom={mom_60s:.3f}%>=-0.005%")
                    return None, None, None
                peer_id = m.get("peer_id") or self.poly.get_peer_id(tid)
                if peer_id:
                    return "short", no_price, peer_id
                else:
                    self._log_skip(slug, "no_peer_token_mapped")
            elif getattr(cfg, "SNIPER_2_LONG_ONLY", False) and no_price >= min_dominance:
                self._log_skip(slug, "s2_long_only_skip_short", f"no={no_price:.3f}")

        return None, None, None

    async def _fire_entry(
        self, tid, m, slug, market_id, win_start, win_end,
        direction, trade_token_id, trade_odds,
        confidence, sniper_label, timeframe="5m"
    ):
        """Execute the buy order via the proven executor pipeline."""
        # Dynamic compounding stake: min $1.00 for micro-bankroll ($2.50)
        base_stake = getattr(config, "SNIPER_STAKE", 1.0)
        current_bankroll = self.executor.bankroll.balance if hasattr(self, "executor") else getattr(config, "BOT_SNIPER_BANKROLL", 2.50)
        stake = round(max(1.0, min(current_bankroll, base_stake)), 2)
        if current_bankroll < 1.0:
            logger.warning("[BotSniper] Bankroll too low to trade: %.2f", current_bankroll)
            return None

        # Apply +3c slippage for FOK order to cross the spread
        SLIPPAGE    = 0.03
        entry_price = round(min(0.98, trade_odds + SLIPPAGE), 4)

        logger.info(
            "[BotSniper][%s] TRIGGER | %s | dir=%s odds=%.3f stake=%.2f (bankroll=%.2f)",
            sniper_label, slug, direction, trade_odds, stake, current_bankroll
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