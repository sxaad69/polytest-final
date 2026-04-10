"""
Execution Layer
Trade entry, position monitor, take profit, hard stop.
Trailing stop disabled — 0% win rate confirmed across all paper test versions.

Changes from data analysis:
  - HARD_STOP_SECONDS: 30 → 60  (earlier exit = better price on losses)
  - TRAILING_STOP: disabled via TRAILING_STOP_ENABLED=False in config
  - peak_gain threshold: 0.05 → 0.10 (kept for when trailing re-enabled)
"""

import asyncio
import logging
import logging.handlers
import os
import time
from datetime import datetime
from config import (
    HARD_STOP_SECONDS, POSITION_POLL_SECS,
    POSITION_HEALTH_GUARD_SECS, POSITION_MANDATORY_REFRESH_SECS, POSITION_LOG_FILE,
)

logger = logging.getLogger(__name__)

# ── Clinical Position Logger ────────────────────────────────────────────────
# Dedicated log for every position heartbeat, guard fire, and price evaluation.
# Written to logs/open_positions.log (auto-created, rotating 5MB x 3 backups).
def _build_position_logger() -> logging.Logger:
    pos_log = logging.getLogger("open_positions")
    if not pos_log.handlers:
        os.makedirs(os.path.dirname(POSITION_LOG_FILE) if os.path.dirname(POSITION_LOG_FILE) else ".", exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            POSITION_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=30
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        pos_log.addHandler(handler)
        pos_log.setLevel(logging.DEBUG)
        pos_log.propagate = False
    return pos_log

pos_logger = _build_position_logger()


class BankrollTracker:

    def __init__(self, balance: float):
        self.balance   = balance
        self._reserved = 0.0

    @property
    def available(self) -> float:
        return self.balance - self._reserved

    def reserve(self, amount: float):
        self._reserved = min(self._reserved + amount, self.balance)

    def settle(self, stake: float, pnl: float):
        self._reserved = max(0.0, self._reserved - stake)
        self.balance   = round(self.balance + pnl, 4)


class ExecutionLayer:

    def __init__(self, bot_id: str, db, poly_feed, circuit_breaker,
                 bankroll: BankrollTracker, starting_bankroll: float,
                 paper_trading: bool = True):
        self.bot_id            = bot_id
        self.db                = db
        self.poly              = poly_feed
        self.cb                = circuit_breaker
        self.bankroll          = bankroll
        self.starting_bankroll = starting_bankroll
        self.paper_trading     = paper_trading
        self._positions: dict  = {}
        self._load_positions()

    def _load_positions(self):
        """Reconstruct in-memory actively managed positions from DB on crash restart."""
        open_trades = self.db.open_trades()
        for t in open_trades:
            tid = t.get("id")
            stake = t.get("stake_usdc", 0.0)
            token = t.get("token_id")
            if not token: # Very old DB entry compat
                token = self.poly.up_token_id if t.get("direction") == "long" else self.poly.down_token_id
            
            entry_odds = t.get("entry_odds", 0.0)
            now = time.time()
            self._positions[tid] = {
                "trade_id":          tid,
                "direction":         t.get("direction"),
                "token_id":          token,
                "market_id":         t.get("market_id"),
                "entry_odds":        entry_odds,
                "peak_odds":         t.get("peak_odds", 0.0),
                "stake_usdc":        stake,
                "size":              round(stake / entry_odds, 6) if entry_odds > 0 else 0.0,
                "window_end":        datetime.fromisoformat(t["window_end"]).timestamp() if t.get("window_end") else None,
                "confidence":        0.0,  # Legacy restored missing confidence
                "asset":             t.get("asset", "CRYPTO"),
                # Health tracking timestamps
                "last_ws_update_ts": now,
                "last_refresh_ts":   now,
            }
            # Initialize with the standard Hard SL. The evaluation loop's profit ratchet 
            # will dynamically take over once the market moves into profit.
            import config
            hard_sl_delta = getattr(config, "HARD_SL_DELTA", 0.15)
            self._positions[tid]["tp_target"] = 0.999
            self._positions[tid]["sl_target"] = round(max(0.001, entry_odds - hard_sl_delta), 4)
            
            self.bankroll.reserve(stake)
        
        if open_trades:
            logger.info("[Bot%s] Reloaded %d active trades from database", self.bot_id, len(open_trades))
            pos_logger.info("[BOOT] Bot %s reloaded %d open trades from DB", self.bot_id, len(open_trades))

    # ── Entry ──────────────────────────────────────────────────────────────────

    async def enter(self, direction: str, confidence: float,
                    stake: float, signal_id: int,
                    token_id: str = None, entry_odds: float = None,
                    market_id: str = None, win_end: float = None,
                    win_start: float = None, condition_id: str = None,
                    asset: str = None, slug: str = None):
        # Backward compatibility for legacy bots (A/B)
        if not token_id:
            if direction == "long":
                token_id   = self.poly.up_token_id
                entry_odds = self.poly.up_odds
                market_id  = self.poly.market_id
                win_end    = self.poly.window_end
                win_start  = self.poly.window_start
            else:
                token_id   = self.poly.down_token_id
                entry_odds = self.poly.down_odds
                market_id  = self.poly.market_id
                win_end    = self.poly.window_end
                win_start  = self.poly.window_start

        # ── One position per market window (all bots) ──────────────────────────
        # Guards against double-entry on same condition regardless of direction.
        # Uses market_id (condition_id) as the dedup key.
        if market_id:
            for pos in self._positions.values():
                if pos.get("market_id") == market_id:
                    logger.debug("[Bot%s] Already in market %s — skipping", self.bot_id, market_id[:12])
                    return None

        # Global risk gate
        if hasattr(self, "global_risk") and self.global_risk:
            passed, reason = self.global_risk.can_enter(stake, token_id, market_id)
            if not passed:
                import logging
                logging.getLogger(f"bot_{self.bot_id.lower()}").warning(
                    "Global Risk Manager skipped trade: %s", reason
                )
                self.db.log_skip(reason, confidence, entry_odds or 0.0, market_id)
                return

        if not entry_odds or not token_id:
            logger.warning("[Bot%s] No odds/token — skipping entry", self.bot_id)
            return None

        import config
        if getattr(config, "USE_MINIMUM_SIZING_TEST", False):
            # True Minimum Sizing logic
            # Polymarket API enforces a hard minimum of 5 shares per order.
            # Use the already-initialized polymarket_client (has credentials) to fetch Ask price.
            ask_price = entry_odds  # safe default
            if hasattr(self, 'global_risk') and self.global_risk and getattr(self.global_risk, 'polymarket_client', None):
                fetched = self.global_risk.polymarket_client.get_current_price(token_id, mode="ask")
                if fetched and fetched > 0:
                    ask_price = fetched

            # Add a 1% slippage buffer so final share count >= 5.0 after exchange division
            min_stake = (5.0 * ask_price) * 1.01

            # Use max(min_stake, config) to respect any per-bot floor
            stake = max(min_stake, getattr(config, f"BOT_{self.bot_id}_MIN_STAKE", 1.0))
            
            MAX_TEST_STAKE = 5.00
            if stake > MAX_TEST_STAKE:
                logger.warning(
                    "[Bot%s] Minimum required stake $%.2f exceeds testing cap of $%.2f. Skipping.", 
                    self.bot_id, stake, MAX_TEST_STAKE
                )
                return None
            logger.info("[Bot%s] TESTING MODE: Using minimum calculated stake $%.2f", self.bot_id, stake)

        order = await self.poly.place_order(
            direction, token_id, stake, entry_odds, self.bot_id,
            paper=self.paper_trading
        )
        if order.get("status") != "filled":
            return None

        filled   = order.get("filled_price", entry_odds)
        order_id = order.get("order_id")
        
        if self.paper_trading and not order_id:
            import uuid
            order_id = f"paper-{uuid.uuid4()}"
            
        trade_id = self.db.log_entry({
            "signal_id":           signal_id,
            "ts_entry":            datetime.utcnow().isoformat(),
            "market_id":           market_id,
            "window_start":        datetime.fromtimestamp(
                                       win_start).isoformat() if win_start else None,
            "window_end":          datetime.fromtimestamp(
                                       win_end).isoformat() if win_end else None,
            "direction":           direction,
            "entry_odds":          filled,
            "stake_usdc":          stake,
            "token_id":            token_id,
            "market_condition_id": condition_id,
            "outcome_index":       0, # Standard for binary crypto tokens
            "clob_order_id":       order_id,
            "taker_fee_bps":       self.poly.taker_fee_bps,
            "chainlink_open":      None,
            "asset":               asset,
            "slug":                slug,
            "confidence":          confidence,
        })

        # Calculate position size in shares (not dollars)
        # Shares = Stake / Price (where price is in 0-1 range)
        position_size = stake / filled if filled > 0 else 0
        
        self._positions[trade_id] = {
            "trade_id":          trade_id,
            "direction":         direction,
            "token_id":          token_id,
            "market_id":         market_id,
            "entry_odds":        filled,
            "peak_odds":         filled,
            "stake_usdc":        stake,
            "size":              position_size,  # SHARES for sell orders
            "window_end":        win_end,
            "asset":             asset,
            "slug":              slug,
            "confidence":        confidence,
            # Health tracking timestamps — initialized to now
            "last_ws_update_ts": time.time(),
            "last_refresh_ts":   time.time(),
        }
        
        # Calculate and store targets (replaced by dynamic Ratchet algorithm)
        pass
        
        pos_logger.info(
            "[ENTRY] [Bot %s] Trade #%s opened | direction=%s | stake=%.2f -> %.1f shares | odds=%.3f",
            self.bot_id, trade_id, direction.upper(), stake, position_size, filled
        )
        
        # CRITICAL: Subscribe this token's WS feed so TP/SL have live prices
        # Without this, _evaluate() can't see real-time price moves for new positions
        await self.poly.subscribe_token(token_id)
        
        self.bankroll.reserve(stake)
        logger.info("[Bot%s][%s] ENTER | id=%s dir=%s odds=%.3f stake=%.2f",
                    self.bot_id,
                    "PAPER" if self.paper_trading else "LIVE",
                    trade_id, direction, filled, stake)
        return trade_id

    # ── Position monitor ───────────────────────────────────────────────────────

    async def start_monitor(self):
        while True:
            if self._positions:
                await self._check_all()
            await asyncio.sleep(POSITION_POLL_SECS)

    async def on_odds_update(self):
        if self._positions:
            await self._check_all()

    async def _check_all(self):
        for tid, pos in list(self._positions.items()):
            await self._evaluate(tid, pos)

    async def _evaluate(self, trade_id: int, pos: dict):
        direction  = pos.get("direction")
        token_id   = pos.get("token_id")
        win_end    = pos.get("window_end")
        asset      = pos.get("asset", "CRYPTO")
        entry_odds = pos.get("entry_odds", 0.0)
        secs_to_end = (win_end - time.time()) if win_end else 999999
        
        if secs_to_end < -30:
            logger.info("[Bot%s] Position %s in resolved market — removing from active monitor",
                        self.bot_id, trade_id)
            pos_logger.info("[REMOVE] [Bot %s] Trade #%s (%s-%s) | Market resolved >30s ago — dropped from monitor",
                            self.bot_id, trade_id, asset, direction)
            if trade_id in self._positions:
                del self._positions[trade_id]
            return

        now = time.time()
        refresh_source = "WS"

        # ── 5s/10s Proactive Refreshes ───────────────────────────────────────
        secs_since_ws = now - pos.get("last_ws_update_ts", 0)
        if secs_since_ws > POSITION_HEALTH_GUARD_SECS:
            try:
                await self.poly.fetch_book(token_id)
                pos["last_ws_update_ts"] = time.time()
                refresh_source = "GUARD-REST"
            except Exception: pass

        secs_since_refresh = now - pos.get("last_refresh_ts", 0)
        if secs_since_refresh > POSITION_MANDATORY_REFRESH_SECS:
            try:
                await self.poly.fetch_book(token_id)
                pos["last_refresh_ts"] = time.time()
                refresh_source = "MANDATORY-REST"
            except Exception: pass

        # ── High-Fidelity Valuation (The "Fair Exit" Rule) ───────────────────
        # For Polymarket 5m binary markets, the orderbook always has bid=0.01
        # and ask=0.99 by structural design (spread = 0.98). Using best_bid
        # as the valuation when spread is wide would give 0.01 for EVERY
        # position, triggering false stop-losses instantly.
        # Rule: tight spread (<=0.10) → use midpoint; wide spread → use LTP.
        market = self.poly.markets.get(token_id)
        if not market: return
        
        bids = market.get("bids", [])
        best_bid = float(bids[0]["price"]) if bids else None
        asks = market.get("asks", [])
        ask_price = float(asks[0]["price"]) if asks else 1.0
        spread = ask_price - (best_bid or 0)
        ltp = market.get("ltp")

        if best_bid and spread <= 0.10:
            # Tight spread: midpoint is reliable
            current_odds = (best_bid + ask_price) / 2
        elif ltp:
            # Wide spread (structural): LTP is the reality source
            current_odds = ltp
        elif best_bid:
            # LTP unavailable: fall back to best_bid
            current_odds = best_bid
        else:
            current_odds = market.get("odds")

        # ── Clinical Heartbeat & Ratchet Target Logic ─────────────────────────
        import config
        current_gain = current_odds - entry_odds if current_odds is not None else 0.0
        peak_gain    = pos.get("peak_odds", entry_odds) - entry_odds

        # Heartbeat String formatting
        is_ratchet_on = False
        hard_sl_target = entry_odds - getattr(config, "HARD_SL_DELTA", 0.15)
        stop_target = hard_sl_target
        
        if peak_gain >= getattr(config, "RATCHET_ACTIVATION_GAIN", 0.10):
            is_ratchet_on = True
            stop_target = max(pos["peak_odds"] - getattr(config, "TRAILING_STOP_DELTA", 0.10), entry_odds + 0.005)
            status_str = f"RATCHET: ON | SL: {stop_target:.3f} | Peak: {pos.get('peak_odds', entry_odds):.3f}"
        else:
            status_str = f"RATCHET: OFF | Hard SL: {hard_sl_target:.3f}"

        slug_str = pos.get("slug", f"{asset}-{direction}")
        conf_str = f"{pos.get('confidence', 0):.4f}"
        pos_logger.info(
            "[HEARTBEAT] [Bot %s] Trade #%s (%s) | Conf: %s | Entry: %.3f | Internal: %s | "
            "%s | Source: %s | WS: %.1fs ago | Secs to end: %.0f",
            self.bot_id, trade_id, slug_str, conf_str, entry_odds,
            f"{current_odds:.3f}" if current_odds is not None else "NO-PRICE",
            status_str,
            refresh_source, secs_since_ws, secs_to_end
        )

        if current_odds is None: return

        # Update peak odds dynamically
        if current_odds > pos.get("peak_odds", entry_odds):
            pos["peak_odds"] = current_odds
            self.db.update_peak(trade_id, current_odds)

        # ── Evaluation ────────────────────────────────────────────────────────
        if getattr(config, "TRAILING_STOP_ENABLED", True):
            # Recalculate gains after peak update just to be 100% accurate on the edge tick
            current_gain = current_odds - entry_odds
            peak_gain    = pos["peak_odds"] - entry_odds
            
            # 1. Hard SL Trapdoor
            if current_gain <= -getattr(config, "HARD_SL_DELTA", 0.15):
                logger.info("[Bot%s] Position %s reached Hard SL (at %.3f)", self.bot_id, trade_id, current_odds)
                pos_logger.info("[EXIT] [Bot %s] Trade #%s | HARD STOP LOSS TRIGGERED | Price: %.3f", self.bot_id, trade_id, current_odds)
                await self._exit(trade_id, pos, current_odds, "hard_sl_hit")
                return

            # 2. Profit Ratchet Evaluation
            if peak_gain >= getattr(config, "RATCHET_ACTIVATION_GAIN", 0.10):
                stop_target = pos["peak_odds"] - getattr(config, "TRAILING_STOP_DELTA", 0.10)
                # STRICT LOCK: Ensure Stop Loss is never worse than Breakeven.
                minimum_safe_exit = entry_odds + 0.005 
                stop_target = max(stop_target, minimum_safe_exit)

                if current_odds <= stop_target:
                    logger.critical("[RATCHET] Trade %s EXITED | Peak: +%.3f | Exit: %.3f", 
                                    trade_id, peak_gain, current_odds)
                    pos_logger.info("[EXIT] [Bot %s] Trade #%s | RATCHET STOP TRIGGERED | Price: %.3f Target: %.3f", 
                                    self.bot_id, trade_id, current_odds, stop_target)
                    await self._exit(trade_id, pos, current_odds, "profit_ratchet_exit")
                    return

        # 3. Hard Stop
        if secs_to_end <= getattr(config, "HARD_STOP_SECONDS", 15):
            await self._exit(trade_id, pos, current_odds, "hard_stop")
            return

    async def _exit(self, trade_id: int, pos: dict,
                    exit_odds: float, reason: str):
        # Check if we've already tried to exit this position too many times
        exit_key = f"exit_attempts_{trade_id}"
        if not hasattr(self, '_exit_attempts'):
            self._exit_attempts = {}
        
        current_attempts = self._exit_attempts.get(trade_key := f"{trade_id}_{reason}", 0)
        
        # Verify balance is available before attempting sell
        # This prevents false "balance: 0" API errors
        try:
            if hasattr(self, 'global_risk') and self.global_risk and self.global_risk.polymarket_client:
                balance = self.global_risk.polymarket_client.get_wallet_balance()
            else:
                balance = 999.0
            if balance < 1.0:  # Less than $1 available
                logger.warning(
                    "[Bot%s] EXIT DELAYED | id=%s reason=%s | Low balance: $%.2f | Retrying in 10s",
                    self.bot_id, trade_id, reason, balance
                )
                # Don't increment attempt counter for API errors
                await asyncio.sleep(10)
                return False
        except Exception as e:
            logger.debug("[Bot%s] Balance check failed: %s", self.bot_id, e)
        # 1. Determine EXACT share amount to sell
        sell_shares = pos["size"]
        if not self.paper_trading and hasattr(self, 'global_risk') and self.global_risk and getattr(self.global_risk, 'polymarket_client', None):
            try:
                # Fetch actual precision ERC1155 balance from the blockchain
                true_balance = self.global_risk.polymarket_client.get_token_balance(pos["token_id"])
                if true_balance > 0:
                    # CRITICAL: Truncate to 6 decimal places (floor) to ensure we NEVER
                    # request even 0.000001 more than we actually own.
                    import math
                    sell_shares = math.floor(true_balance * 1_000_000) / 1_000_000
                    logger.debug("[Bot%s] Overriding expected %f shares with SAFE TRUE balance %f shares", self.bot_id, pos["size"], sell_shares)
                else:
                    # Balance API returned 0 — order may not have filled yet.
                    # Increment attempt counter. After 10 retries, give up and clean up.
                    self._exit_attempts[trade_key] = current_attempts + 1
                    if current_attempts + 1 >= 10:
                        logger.error(
                            "[Bot%s] EXIT ABANDONED | id=%s reason=%s | Balance API returned 0 for 10 consecutive checks. "
                            "Order likely never filled. Removing from monitor. MANUAL CHECK REQUIRED.",
                            self.bot_id, trade_id, reason
                        )
                        if trade_id in self._positions:
                            del self._positions[trade_id]
                    else:
                        logger.warning(
                            "[Bot%s] Live balance for %s is 0 (attempt %d/10) — order may not have filled yet. Waiting.",
                            self.bot_id, pos["token_id"], current_attempts + 1
                        )
                    return False
            except Exception as e:
                logger.error("[Bot%s] Failed to fetch true token balance: %s. Using theoretical size.", self.bot_id, e)

        # 2. Fire the Sell order using exact SHARES (not dollar amount)
        # Apply a dynamic slippage buffer to the limit price to ensure the FOK order matches.
        # As attempts increase, the buffer widens to guarantee the dump.
        if current_attempts == 0:
            slippage = 0.03
        elif current_attempts == 1:
            slippage = 0.05
        elif current_attempts == 2:
            slippage = 0.07
        else:
            # 4+ attempts: Desperation Dump (0.10c slip)
            slippage = 0.10
            
        buffered_exit_price = max(0.01, min(0.99, exit_odds - (0.03 + (current_attempts * 0.02))))
        
        pos_logger.info("[EXIT] [Bot %s] Trade #%s | %s | Current Price: %.3f | Executed Polymarket Limit Fill: %.3f", 
                        self.bot_id, trade_id, reason, exit_odds, buffered_exit_price)
        order = await self.poly.place_order(
            "sell", pos["token_id"],
            sell_shares, buffered_exit_price, self.bot_id,  # Use shares with buffered price
            paper=self.paper_trading
        )
        
        # CRITICAL FIX: Check if order actually succeeded before updating DB
        if order.get("status") != "filled":
            self._exit_attempts[trade_key] = current_attempts + 1
            
            # If we've failed 5+ times, alert but keep trying
            if current_attempts >= 5:
                logger.error(
                    "[Bot%s] EXIT CRITICAL | id=%s reason=%s | Failed %d times | Position still open! MANUAL CLOSE REQUIRED",
                    self.bot_id, trade_id, reason, current_attempts
                )
            else:
                logger.warning(
                    "[Bot%s] EXIT FAILED | id=%s reason=%s | Attempt %d/5 | Order status: %s | Retrying...",
                    self.bot_id, trade_id, reason, current_attempts + 1, order.get("status", "unknown")
                )
            # Do NOT update DB - position is still open
            # The monitor will retry on next poll cycle (3s)
            return False
        
        # Success! Clear attempt counter
        if trade_key in self._exit_attempts:
            del self._exit_attempts[trade_key]
        
        # Use the actual filled price from the exchange
        true_exit_price = order.get("filled_price", exit_odds)
        clob_id = order.get("order_id", "paper_only")
        
        # 2. Log the local exit (resolved=1) - ONLY if order filled
        pnl, outcome = self.db.log_exit(trade_id, {
            "ts_exit":        datetime.utcnow().isoformat(),
            "entry_odds":     pos["entry_odds"],
            "exit_odds":      true_exit_price,
            "peak_odds":      pos["peak_odds"],
            "stake_usdc":     pos["stake_usdc"],
            "exit_reason":    reason,
            "chainlink_close": None,
        })
        
        # 3. Create the TRUTH record in the settlements table
        # For paper trading, we assume 0 slippage for now.
        slippage = int((exit_odds - true_exit_price) * 10000) if exit_odds > true_exit_price else 0
        self.db.log_settlement(
            trade_id=trade_id,
            clob_order_id=clob_id,
            tx_hash=order.get("tx_hash", "paper_tx"),
            usdc_returned=pos["stake_usdc"] + pnl,
            slippage_bps=slippage
        )

        # 4. Finalize Bankroll and risk counters
        self.bankroll.settle(pos["stake_usdc"], pnl)
        self.cb.on_result(self.db, outcome, pnl, self.starting_bankroll)
        
        if trade_id in self._positions:
            del self._positions[trade_id]

        logger.info(
            "[Bot%s] EXIT | id=%s reason=%s odds=%.3f pnl=%+.4f outcome=%s | SETTLED=%s",
            self.bot_id, trade_id, reason, true_exit_price, pnl, outcome, clob_id
        )
        return True