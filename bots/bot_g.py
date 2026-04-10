"""
Bot G — Universal Crypto (Multi-Asset Updown)
Scans all crypto updown markets (ETH, SOL, BNB, etc.)
and applies Binance momentum + Chainlink deviation logic.
Same core edge as Bot A but generalised to all crypto assets.
"""

import asyncio
import logging
import logging.handlers
import time
from datetime import datetime
from config import (
    BOT_G_BANKROLL, BOT_G_DB_PATH, BOT_G_MIN_CONFIDENCE,
    BOT_G_MAX_CONCURRENT_TRADES, BOT_G_MIN_STAKE,
    BOT_G_MIN_ENTRY_ODDS, BOT_G_MAX_ENTRY_ODDS,
    BOT_G_MAX_ENTRY_SECS_INTO_WIN, BOT_G_MIN_SECS_REMAINING,
    NO_ENTRY_LAST_SECS,
)
from bots.base_bot import BaseBot
from signals.signal_g import BotGSignal

logger = logging.getLogger("bot_g")


class BotG(BaseBot):

    BOT_ID            = "G"
    DB_PATH           = BOT_G_DB_PATH
    STARTING_BANKROLL = BOT_G_BANKROLL

    def __init__(self, binance, chainlink, poly, wallet_address=None, polymarket_client=None):
        super().__init__(binance, chainlink, poly, wallet_address=wallet_address, polymarket_client=polymarket_client)
        self._signal = BotGSignal(min_confidence=BOT_G_MIN_CONFIDENCE)
        self.max_concurrent_trades = BOT_G_MAX_CONCURRENT_TRADES
        self._traded_markets = {}  # Cache to enforce strict one-trade-per-market lockout
        self._setup_rejection_logger()

    def _setup_rejection_logger(self):
        import config
        self._rej_log = logging.getLogger("bot_g_rejection")
        self._rej_log.setLevel(logging.INFO)
        # Avoid duplicate handlers if reloaded
        if not self._rej_log.handlers:
            # Always add console stream
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            self._rej_log.addHandler(console)
            
            # Add file handler if enabled
            if getattr(config, "BOT_G_REJECTION_LOGGING", True) and not getattr(config, "BOT_G_REJECTION_ONLY_CONSOLE", False):
                path = getattr(config, "BOT_G_REJECTION_LOG_PATH", "logs/bot_g_rejections.log")
                file_handler = logging.FileHandler(path)
                file_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
                self._rej_log.addHandler(file_handler)

    def _log_skip(self, slug, reason, details=None):
        import config
        if not getattr(config, "BOT_G_REJECTION_LOGGING", True):
            return
        msg = f"[BotG] SKIP | {slug} | Reason: {reason}"
        if details:
            msg += f" | Data: {details}"
        self._rej_log.info(msg)

    async def _loop(self):
        self._log.info("Bot G starting multi-crypto monitor...")

        while self._running:
            try:
                import config
                import importlib
                importlib.reload(config)
                
                # Zero memory leak clean-up of expired market cache
                now = time.time()
                self._traded_markets = {mid: end for mid, end in self._traded_markets.items() if now < end}
                
                # 1. Surgical Strike List Engine (Direct Mathematical Slug Generation)
                await self.poly.fetch_strike_list_markets()
                
                # 2. Strict Isolation: Only evaluate the current active slugs
                target_markets = {}
                now = time.time()
                active_slugs = set()
                assets = getattr(config, "BOT_G_STRIKE_ASSETS", [])
                tfs    = getattr(config, "BOT_G_TIMEFRAMES", {})
                for asset in assets:
                    for tf_name, tf_secs in tfs.items():
                        ts = int(now // tf_secs) * tf_secs
                        active_slugs.add(f"{asset}-updown-{tf_name}-{ts}")

                # Pull strictly from the shared registry ONLY if it matches our active surgical slugs
                for tid, m in self.poly.markets.items():
                    if m.get("slug") in active_slugs:
                        target_markets[tid] = m

                # 2. Write the .txt log (Title | URL) for the user dashboard
                if getattr(config, "WRITE_SCANNED_MARKETS_TXT", False):
                    entries = []
                    for m in target_markets.values():
                        s = m.get("slug", "")
                        es = m.get("event_slug", s)
                        ss = m.get("series_slug")
                        url = f"https://polymarket.com/sports/{ss}/{es}" if ss else f"https://polymarket.com/event/{es}"
                        title = s.replace("-", " ").title()
                        entries.append(f"{title} | {url}")
                    
                    entries = sorted(list(set(entries)))
                    with open("logs/bot_g_markets.txt", "w") as f:
                        f.write("\n".join(entries))

                # 3. Heartbeat log with clinical diagnostic
                best_asset, max_mom = "NONE", 0.0
                for tid, m in target_markets.items():
                    asset = m.get("slug", "").split("-")[0].upper()
                    mom = abs(self.binance.get_momentum(asset, 30))
                    if mom > max_mom: best_asset, max_mom = asset, mom

                self._log.info("[BotG] 🔍 Scanning %d filtered crypto markets | Best: %s (%.4f momentum)", 
                               len(target_markets), best_asset, max_mom)
                
                # 4. Evaluate each market
                for tid, m in list(target_markets.items()):
                    if len(self.executor._positions) >= self.max_concurrent_trades:
                        break
                    await self._evaluate_market(tid, m)

            except Exception as e:
                self._log.error("Bot G loop error: %s", e, exc_info=True)

            await asyncio.sleep(10)

    async def _evaluate_market(self, tid: str, m: dict):
        # Extract market identity first so we can gate on it
        market_id = m.get("condition_id")
        slug = m.get("slug", "")
        ui_slug = m.get("question", slug) # Capture the human readable string to pass to the database
        
        # Parse win_start/win_end from registry, or fall back to slug timestamp
        win_start = m.get("win_start")
        win_end   = m.get("win_end")
        if not win_start or not win_end:
            parts = slug.rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit():
                ts = int(parts[1])
                tf_map = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
                tf = next((k for k in tf_map if f"-{k}-" in slug), None)
                duration = tf_map.get(tf, 300)
                win_start = float(ts)
                win_end   = float(ts + duration)
                m["win_start"] = win_start
                m["win_end"]   = win_end
            else:
                self._log_skip(slug, "no_window_data")
                return

        secs_remaining = win_end - time.time()

        # 1. High-Fidelity Price Discovery
        await self.poly.fetch_book(tid)
        peer_id = m.get("peer_id")
        if peer_id:
            await self.poly.fetch_book(peer_id)
            
        current_price = self._get_fair_value(tid)
        if current_price is None:
            self._log_skip(slug, "price_discovery_failed")
            return

        # 2. Market window safety — STRICT ONE-TRADE-PER-MARKET LOCK
        if market_id in self._traded_markets:
            self._log_skip(slug, "strict_market_lockout", f"market_id={market_id}")
            return

        # 3. Minimum time remaining in window
        if secs_remaining < BOT_G_MIN_SECS_REMAINING:
            self._log_skip(slug, "min_secs_remaining", f"rem={round(secs_remaining,1)}s")
            return

        # 4. Entry timing
        secs_into_window = time.time() - win_start
        if secs_into_window > BOT_G_MAX_ENTRY_SECS_INTO_WIN:
            self._log_skip(slug, "max_secs_into_win", f"into={round(secs_into_window,1)}s")
            return

        # 5. Odds range — sweet spot 0.15–0.85
        if current_price < BOT_G_MIN_ENTRY_ODDS or current_price > BOT_G_MAX_ENTRY_ODDS:
            self._log_skip(slug, "odds_out_of_band", f"price={round(current_price,3)} band={BOT_G_MIN_ENTRY_ODDS}-{BOT_G_MAX_ENTRY_ODDS}")
            return

        # Infer asset from slug
        asset = slug.split("-")[0].upper() if slug else "CRYPTO"
        
        # High-Fidelity Signal Evaluation
        momentum    = self.binance.get_momentum(asset, 30)
        asset_price = self.binance.get_price(asset)
        poly_mid    = current_price

        result = self._signal.evaluate(
            asset=asset,
            momentum=momentum,
            asset_price=asset_price,
            poly_mid=poly_mid,
        )

        if not result.tradeable:
            reason = result.skip_reason or "signal_not_tradeable"
            self._log_skip(slug, reason, f"mom={round(momentum,4)}")
            return

        # ── Entry Price Selection (Fair Value) ──────────────────────────────
        # NOTE: Polymarket 5m binary markets always show asks[0]=0.99 / bids[0]=0.01
        # by structural design. We must add 3 cents (0.03) of explicit positive 
        # slippage allowance to safely cross the Market Maker spread. This blocks 
        # "Order fully filled or killed" 400 rejections while protecting against .99 fills.
        
        SLIPPAGE = 0.03
        if result.direction == "long":
            trade_token_id = tid
            entry_price = round(min(0.98, current_price + SLIPPAGE), 4) # Limit ceiling
            trade_odds = current_price # Retain LTP for tracking logic
        else:
            if peer_id and peer_id in self.poly.markets:
                trade_token_id = peer_id
                target_value = round(1.0 - current_price, 4)
                entry_price = round(min(0.98, target_value + SLIPPAGE), 4) # Limit ceiling
                trade_odds = target_value
            else:
                self._log_skip(slug, "no_peer_token_mapped")
                return

        if not trade_odds:
            self._log_skip(slug, "no_trade_odds")
            return

        passed, reason = self.filters.check(
            db=self.db,
            confidence=result.score,
            odds=trade_odds,
            depth=m.get("depth", 0),
            secs_remaining=secs_remaining,
            market_id=market_id,
        )

        if not passed:
            self._log_skip(slug, "filter_rejection", f"reason={reason}")
            return

        stake = self.sizer.calculate(result.score, trade_odds, self.bankroll.available)
        if stake <= BOT_G_MIN_STAKE:
            self._log_skip(slug, "low_stake", f"stake={round(stake,2)}")
            return

        self._log.info("[BotG] CRYPTO SIGNAL | asset=%s dir=%s score=%.4f odds=%.3f lag=%.3f",
                       asset, result.direction, result.score, trade_odds,
                       result.components.get("poly_lag", 0.0))

        signal_id = self.db.log_signal({
            "ts":                  datetime.utcnow().isoformat(),
            "market_id":           market_id,
            "window_start":        datetime.fromtimestamp(win_start).isoformat() if win_start else None,
            "window_end":          datetime.fromtimestamp(win_end).isoformat() if win_end else None,
            "direction":           result.direction,
            "confidence_score":    result.score,
            "polymarket_odds":     trade_odds,
            # Bot G uses Binance only — Chainlink fields not applicable
            "chainlink_price":     None,
            "chainlink_dev_pct":   None,
            "chainlink_lag_flag":  None,
            "binance_price":       result.components.get("asset_price"),
            "momentum_30s":        momentum,
            "momentum_60s":        None,
            "rsi":                 None,
            "volume_zscore":       None,
            "odds_velocity":       None,
            "skip_reason":         None,
            "features":            {
                **result.components,
                "asset":            asset,
                "poly_lag":         result.components.get("poly_lag"),
                "secs_into_window": round(secs_into_window, 1),
                "secs_remaining":   round(secs_remaining, 1),
            },
        })

        # entry_price = LTP + SLIPPAGE (the FOK limit ceiling sent to Polymarket)
        # trade_odds  = LTP only (used locally for Ratchet TP/SL tracking)
        trade_id = await self.executor.enter(
            direction=result.direction,
            confidence=result.score,
            stake=stake,
            signal_id=signal_id,
            token_id=trade_token_id,
            entry_odds=entry_price,  # ← FOK limit with +0.03 slippage
            market_id=market_id,
            win_start=win_start,
            win_end=win_end,
            condition_id=market_id,
            asset=asset,
            slug=ui_slug,
        )
        
        # Only blacklist once the order actually filled — if FOK rejected, let next tick retry
        if trade_id:
            self._traded_markets[market_id] = win_end

    def _get_fair_value(self, tid: str) -> float | None:
        """
        Implements the Polymarket Pricing Rule:
        - If spread <= 0.10: use Midpoint
        - If spread > 0.10: use Last Trade Price (LTP)
        - Fallback: Peer parity (1.0 - PeerPrice)
        """
        m = self.poly.markets.get(tid)
        if not m: return None
        
        ltp = m.get("ltp")
        
        # 1. Calculate spread from orderbook
        bids, asks = m.get("bids", []), m.get("asks", [])
        if bids and asks:
            best_bid = float(bids[0]["price"])
            best_ask = float(asks[0]["price"])
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2
            
            if spread <= 0.10:
                return mid
            elif ltp:
                return ltp
        
        # 2. Fallback to LTP if orderbook is too wide/missing
        if ltp: return ltp
        
        # 3. Final fallback: Peer token parity
        peer_id = m.get("peer_id")
        if peer_id:
            pm = self.poly.markets.get(peer_id)
            if pm:
                p_bids = pm.get("bids", [])
                p_asks = pm.get("asks", [])
                p_ltp = pm.get("ltp")
                if p_bids and p_asks:
                    p_spread = float(p_asks[0]["price"]) - float(p_bids[0]["price"])
                    p_mid = (float(p_bids[0]["price"]) + float(p_asks[0]["price"])) / 2
                    p_fair = p_mid if p_spread <= 0.10 else (p_ltp or p_mid)
                    return round(1.0 - p_fair, 4)
                elif p_ltp:
                    return round(1.0 - p_ltp, 4)
        
        return m.get("odds")  # Last resort
