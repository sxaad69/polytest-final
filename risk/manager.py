import asyncio
"""
Risk Manager
Pre-trade filters, circuit breaker, Kelly sizer.
Each bot passes its own Database so state never mixes.
Circuit breaker respects CIRCUIT_BREAKER_ENABLED from config.
"""

import logging
import requests
import time
from datetime import date
from typing import Optional, Dict, Any
from config import (
    MIN_ODDS, MAX_ODDS, MIN_BOOK_DEPTH,
    NO_ENTRY_LAST_SECS, MAX_CONSECUTIVE_LOSSES,
    DAILY_LOSS_LIMIT_PCT, MAX_BET_PCT, KELLY_FRACTION,
    CIRCUIT_BREAKER_ENABLED,
)

logger = logging.getLogger(__name__)

ratchet_logger = logging.getLogger("ratchet_logger")
ratchet_logger.setLevel(logging.INFO)
if not ratchet_logger.handlers:
    rfh = logging.FileHandler("logs/bot_g_ratchet.log")
    rfh.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    ratchet_logger.addHandler(rfh)
    ratchet_logger.propagate = False  # Prevent double printing to console if you don't want it, though standard logger already prints it.

# Import working Polymarket API client
try:
    from risk.polymarket_api import PolymarketAPIClient
except ImportError:
    PolymarketAPIClient = None
    logger.warning("[RISK] PolymarketAPIClient not available - live trading PnL may not work")


class PreTradeFilters:

    def check(self, db, confidence: float, odds: float,
              depth: float, secs_remaining: float,
              market_id: str = None, stake: float = 0.0,
              global_risk: 'GlobalRiskManager' = None) -> tuple:

        checks = [
            self._confidence(confidence),
            self._odds(odds),
            self._depth(depth),
            self._timing(secs_remaining),
            self._circuit_breaker(db),
            self._global_exposure(global_risk, stake),
        ]
        for check_result in checks:
            try:
                # Defensive check for non-tuple returns or incorrect lengths
                if isinstance(check_result, tuple) and len(check_result) >= 2:
                    passed, reason = check_result[0], check_result[1]
                else:
                    passed, reason = True, "invalid_check_return"
                
                if not passed:
                    db.log_skip(reason, confidence, odds, market_id)
                    return False, reason
            except Exception as e:
                logger.error("Filter check iteration error: %s", e)
                continue
        return True, "all_clear"

    def _confidence(self, score: float) -> tuple:
        if score == 0.0:
            return False, "zero_confidence"
        return True, ""

    def _odds(self, odds: float) -> tuple:
        if odds is None:
            return False, "no_odds_data"
        if odds < MIN_ODDS:
            return False, f"odds_too_low:{odds:.2f}"
        if odds > MAX_ODDS:
            return False, f"odds_too_high:{odds:.2f}"
        return True, ""

    def _depth(self, depth: float) -> tuple:
        if depth < MIN_BOOK_DEPTH:
            return False, f"thin_book:{depth:.1f}"
        return True, ""

    def _timing(self, secs: float) -> tuple:
        if secs < NO_ENTRY_LAST_SECS:
            return False, f"window_closing:{secs:.0f}s"
        return True, ""

    def _circuit_breaker(self, db) -> tuple:
        # If circuit breaker is disabled in config, always pass
        if not CIRCUIT_BREAKER_ENABLED:
            return True, ""

        cb = db.get_cb()
        if cb["last_reset_date"] != date.today().isoformat():
            db.reset_cb()
            return True, ""
        if cb["halted"]:
            return False, f"circuit_breaker:{cb['halted_reason']}"
        return True, ""

    def _global_exposure(self, global_risk, stake: float) -> tuple:
        if not global_risk or stake <= 0:
            return True, ""
        return global_risk.can_enter(stake)


class CircuitBreaker:
    """
    Circuit breaker with enhanced loss protection:
    - 3 consecutive losses = 6 hour halt
    - 6 total daily losses = halt until midnight UTC
    """

    def on_result(self, db, outcome: str, pnl: float, starting_bankroll: float):
        # If disabled, still track stats but never halt
        import config
        cb = db.get_cb()
        consecutive = cb["consecutive_losses"]
        daily_loss  = cb["daily_loss_usdc"]
        daily_loss_count = cb.get("daily_loss_count", 0)

        if outcome == "loss":
            consecutive += 1
            daily_loss   = abs(min(0, daily_loss + pnl))
            daily_loss_count += 1
        else:
            consecutive = 0

        halted, reason = False, None
        resume_time_ts = cb.get("resume_time_ts", 0.0)

        # Only actually halt if circuit breaker is enabled
        if CIRCUIT_BREAKER_ENABLED:
            # Enhanced Loss Protection (Tiered Halts)
            if getattr(config, "ENHANCED_LOSS_PROTECTION_ENABLED", False):
                # Tier 1: 3 consecutive losses = 6 hour halt
                consec_limit = getattr(config, "CONSECUTIVE_LOSS_HALT_COUNT", 3)
                consec_minutes = getattr(config, "CONSECUTIVE_LOSS_HALT_MINUTES", 360)
                
                if consecutive >= consec_limit:
                    halted = True
                    reason = f"{consecutive}_consecutive_losses_{consec_minutes}min_halt"
                    resume_time_ts = time.time() + (consec_minutes * 60)
                    logger.critical("🛑 [%s] TIER 1 HALT: %d consecutive losses | HALTING for %d minutes", 
                                  db.bot_id, consecutive, consec_minutes)
                
                # Tier 2: 6 total daily losses = halt until midnight UTC
                total_loss_limit = getattr(config, "TOTAL_DAILY_LOSS_HALT_COUNT", 6)
                if not halted and daily_loss_count >= total_loss_limit:
                    halted = True
                    # Calculate seconds until midnight UTC
                    from datetime import datetime, timedelta
                    now = datetime.utcnow()
                    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    seconds_until_midnight = (midnight - now).total_seconds()
                    resume_time_ts = time.time() + seconds_until_midnight
                    reason = f"{daily_loss_count}_total_losses_until_midnight_utc"
                    logger.critical("🛑 [%s] TIER 2 HALT: %d total daily losses | HALTING until midnight UTC (%.1f hours)", 
                                  db.bot_id, daily_loss_count, seconds_until_midnight / 3600)
            
            # Original circuit breaker logic (fallback)
            if not halted:
                if consecutive >= MAX_CONSECUTIVE_LOSSES:
                    halted = True
                    reason = f"{consecutive}_consecutive_losses"
                    logger.warning("[%s] Circuit breaker: %s consecutive losses — HALTED",
                                   db.bot_id, consecutive)

                if daily_loss / max(starting_bankroll, 1) >= DAILY_LOSS_LIMIT_PCT:
                    halted = True
                    reason = f"daily_loss_{daily_loss/starting_bankroll*100:.1f}pct"
                    logger.warning("[%s] Circuit breaker: daily loss limit hit — HALTED",
                                   db.bot_id)
        else:
            if consecutive >= MAX_CONSECUTIVE_LOSSES:
                logger.warning(
                    "[%s] %s consecutive losses (circuit breaker disabled — continuing)",
                    db.bot_id, consecutive
                )

        db.update_cb(consecutive, daily_loss, halted, reason, 
                     daily_loss_count=daily_loss_count, resume_time_ts=resume_time_ts)


class KellySizer:

    def calculate(self, confidence: float, entry_odds: float,
                  bankroll: float) -> float:
        abs_conf = abs(confidence)
        p = min(0.75, entry_odds + (abs_conf * 0.20))
        q = 1.0 - p
        b = (1.0 - entry_odds) / entry_odds

        if b <= 0:
            return 0.0

        full_k = (p * b - q) / b
        if full_k <= 0:
            return 0.0

        # Calculate pure Kelly stake
        raw_stake = bankroll * (full_k / 2.0) # Half-kelly for safety
        
        # Apply strict bounded rules
        import config
        min_trade = getattr(config, "GLOBAL_MIN_TRADE_SIZE", 0.0)
        max_trade = getattr(config, "GLOBAL_MAX_TRADE_SIZE", 0.0)
        
        final_stake = raw_stake
        
        if min_trade > 0:
            final_stake = max(final_stake, min_trade)
        if max_trade > 0:
            final_stake = min(final_stake, max_trade)
            
        return round(final_stake, 2)


class GlobalRiskManager:
    """
    Portfolio-level risk control.
    Supports both paper trading (DB source) and live trading (Polymarket API source).
    """
    def __init__(self, bots_dict: dict):
        self.bots = bots_dict
        import config
        self.max_exposure_pct = config.GLOBAL_MAX_EXPOSURE_PCT
        self.daily_loss_limit = config.GLOBAL_DAILY_LOSS_LIMIT
        self.daily_profit_target = getattr(config, "GLOBAL_DAILY_PROFIT_TARGET", 0.10)
        
        # Paper vs Live trading mode
        self.paper_trading = getattr(config, "PAPER_TRADING", True)
        self.pnl_check_interval = getattr(config, "PNL_CHECK_INTERVAL_SEC", 10)
        
        # Initialize Polymarket API client for live trading
        self.polymarket_client = None
        if not self.paper_trading:
            api_key = getattr(config, "POLYMARKET_API_KEY", None)
            api_secret = getattr(config, "POLYMARKET_API_SECRET", None)
            api_passphrase = getattr(config, "POLYMARKET_PASSPHRASE", None)
            private_key = getattr(config, "POLYMARKET_PRIVATE_KEY", None)
            funder = getattr(config, "POLYMARKET_FUNDER_ADDRESS", None)
            
            if api_key and api_secret and api_passphrase and private_key and funder:
                self.polymarket_client = PolymarketAPIClient(
                    api_key, api_secret, api_passphrase, private_key, funder
                )
                logger.info("[RISK] Live trading mode - Polymarket API client initialized")
            else:
                logger.error("[RISK] Live trading enabled but API credentials missing - falling back to paper mode")
                self.paper_trading = True
        else:
            logger.info("[RISK] Paper trading mode - using DB for P&L")
        
        self.initial_bankrolls = {
            "A": config.BOT_A_BANKROLL, "B": config.BOT_B_BANKROLL, 
            "C": config.BOT_C_BANKROLL, "D": config.BOT_D_BANKROLL,
            "E": config.BOT_E_BANKROLL, "F": config.BOT_F_BANKROLL, 
            "G": config.BOT_G_BANKROLL, "SNIPER": getattr(config, "BOT_SNIPER_BANKROLL", 10000.0)
        }
        
        # In live mode, the True starting bankroll is the LIVE wallet balance!
        # Do not use config.py defaults because they will cause massive
        # false percentage crashes if the real wallet has less money.
        if not self.paper_trading and self.polymarket_client:
            try:
                live_balance = self.polymarket_client.get_wallet_balance()
                if live_balance > 0:
                    logger.critical("[RISK] Overriding config bankrolls! Using live wallet balance $%.2f as baseline.", live_balance)
                    # We override all active bots to share this true base
                    # (since they all trade from the exact same Polymarket wallet)
                    for k in self.initial_bankrolls:
                        self.initial_bankrolls[k] = live_balance
            except Exception as e:
                logger.error("[RISK] Failed to fetch live wallet balance on startup: %s. Using config defaults.", e)
                
        # Only sum bankrolls for BOTS THAT ARE ACTUALLY ACTIVE
        active_ids = {bot.db.bot_id if hasattr(bot, 'db') else k for k, bot in bots_dict.items()}
        # If we are using live wallet, the total bankroll IS the wallet balance. 
        # Don't double count it for each active bot if they share one wallet!
        if not self.paper_trading and self.polymarket_client:
            self._total_bankroll = self.initial_bankrolls.get("G", 100.0)
        else:
            self._total_bankroll = sum(v for k, v in self.initial_bankrolls.items() if k in active_ids)
        self._started_at = time.time()

    def can_enter(self, stake: float, token_id: str = None, market_id: str = None) -> tuple:
        """Checks if a new trade would exceed global limits or create a token conflict."""
        current_exposure = 0.0
        for bot in self.bots.values():
            if hasattr(bot, "executor") and bot.executor:
                for pos in bot.executor._positions.values():
                    # Cross-bot token conflict — same token = same direction, no value in doubling
                    if token_id and pos.get("token_id") == token_id:
                        return False, f"cross_bot_conflict:token:{token_id[:12]}"
                    current_exposure += pos.get("stake_usdc", 0.0)
        
        limit = self._total_bankroll * self.max_exposure_pct
        if (current_exposure + stake) > limit:
            return False, f"global_exposure_limit:{current_exposure+stake:.1f}/{limit:.1f}"
        
        return True, ""

    def _get_bot_pnl(self, bid: str, bot, bot_initial: float, since_ts: float = None) -> tuple:
        """
        Get bot PnL based on trading mode:
        - Paper: Query DB trades table (realized P&L only)
        - Live: Call Polymarket API (realized + unrealized P&L)
        
        Args:
            since_ts: Unix timestamp — if set, realized PnL only counts trades after this time
                      Pass self._started_at for session-only P&L (Profit Ratchet)
                      Leave None for 24h daily window (Daily Loss Limit)
        
        Returns: (total_pnl, total_pnl_pct, source)
        """
        total_pnl = 0.0
        source = "unknown"
        
        if self.paper_trading:
            # Paper trading: Use database settled trades
            try:
                with bot.db._conn() as conn:
                    row = conn.execute(
                        "SELECT SUM(pnl_usdc) FROM trades WHERE resolved=1"
                    ).fetchone()
                    if row and row[0]:
                        total_pnl = float(row[0])
                        source = "db_paper"
            except Exception as e:
                logger.error("[CB-PAPER] Error reading PnL from DB for %s: %s", bid, e)
                source = "db_error"
        else:
            # Live trading: Use Polymarket API
            if self.polymarket_client:
                try:
                    # Get wallet address from bot if available
                    wallet_address = getattr(bot, 'wallet_address', None)
                    if wallet_address:
                        result = self.polymarket_client.get_pnl_summary(
                            wallet_address, bot_initial, since_ts=since_ts
                        )
                        if result.get('success'):
                            total_pnl = result['total_pnl']
                            source = "polymarket_api" if since_ts is None else "polymarket_api_session"
                            logger.info(
                                "[CB-LIVE] %s: value=$%.2f, realized=$%.2f, unrealized=$%.2f",
                                bid,
                                result.get('total_value', 0),
                                result.get('realized_pnl', 0),
                                result.get('unrealized_pnl', 0)
                            )
                        else:
                            logger.error(
                                "[CB-LIVE] API call failed for %s: %s",
                                bid, result.get('error')
                            )
                            source = "api_error"
                    else:
                        logger.error("[CB-LIVE] No wallet address for bot %s", bid)
                        source = "no_wallet"
                except Exception as e:
                    logger.error("[CB-LIVE] Exception calling Polymarket API for %s: %s", bid, e)
                    source = "api_exception"
            else:
                logger.error("[CB-LIVE] Polymarket client not initialized for bot %s", bid)
                source = "no_client"
        
        total_pnl_pct = total_pnl / max(bot_initial, 1.0)
        return total_pnl, total_pnl_pct, source

    async def liquidate_all_positions(self, reason: str = "circuit_breaker") -> Dict[str, Any]:
        """
        Emergency liquidation - close all positions for all bots.
        For paper trading: marks DB positions as resolved.
        For live trading: calls bot executor to close positions on Polymarket.
        """
        results = {"paper": {}, "live": {}, "timestamp": time.time()}
        
        for bid, bot in self.bots.items():
            wallet_address = getattr(bot, 'wallet_address', None)
            
            if self.paper_trading:
                # Paper trading: Mark all open positions as resolved in DB
                try:
                    with bot.db._conn() as conn:
                        # Get all unresolved positions
                        positions = conn.execute(
                            "SELECT id, token_id, stake_usdc, entry_odds FROM trades WHERE resolved=0"
                        ).fetchall()
                        
                        closed_count = 0
                        for pos in positions:
                            pos_id, token_id, stake, entry_odds = pos
                            # Mark as resolved with current market price (simplified)
                            conn.execute(
                                "UPDATE trades SET resolved=1, exit_odds=?, pnl_usdc=0 WHERE id=?",
                                (entry_odds, pos_id)  # Assume flat exit for paper mode
                            )
                            closed_count += 1
                        
                        conn.commit()
                        results["paper"][bid] = {
                            "success": True,
                            "closed_count": closed_count,
                            "message": f"Paper positions marked resolved"
                        }
                        logger.critical("[LIQUIDATE] Bot %s: Closed %d paper positions | Reason: %s", 
                                      bid, closed_count, reason)
                except Exception as e:
                    logger.error("[LIQUIDATE] Failed to close paper positions for %s: %s", bid, e)
                    results["paper"][bid] = {"success": False, "error": str(e)}
            else:
                # Live trading: Use bot's executor to close positions
                if hasattr(bot, 'executor') and bot.executor:
                    try:
                        closed_count = 0
                        failed_count = 0
                        
                        # Get all in-memory positions
                        positions_copy = list(bot.executor._positions.items())
                        
                        for trade_id, pos in positions_copy:
                            try:
                                # Get current odds for exit
                                market = bot.poly.markets.get(pos.get("token_id")) if hasattr(bot, 'poly') else None
                                current_odds = market.get("odds") if market else pos.get("entry_odds", 0.5)
                                
                                # Call _exit to close on Polymarket (this now checks order status)
                                success = await bot.executor._exit(
                                    trade_id, pos, current_odds, 
                                    f"emergency_liquidation_{reason}"
                                )
                                if success:
                                    closed_count += 1
                                else:
                                    failed_count += 1
                                
                            except Exception as e:
                                logger.error("[LIQUIDATE] Failed to close position %s for bot %s: %s", 
                                           trade_id, bid, e)
                                failed_count += 1
                        
                        results["live"][bid] = {
                            "success": failed_count == 0,
                            "closed_count": closed_count,
                            "failed_count": failed_count,
                            "message": f"Closed {closed_count} positions, {failed_count} failed"
                        }
                        
                        if failed_count == 0:
                            logger.critical("[LIQUIDATE] Bot %s: Closed %d live positions | Reason: %s",
                                          bid, closed_count, reason)
                        else:
                            logger.error("[LIQUIDATE] Bot %s: Only closed %d/%d positions | Reason: %s",
                                       bid, closed_count, closed_count + failed_count, reason)
                            
                    except Exception as e:
                        logger.error("[LIQUIDATE] Exception closing live positions for %s: %s", bid, e)
                        results["live"][bid] = {"success": False, "error": str(e)}
                else:
                    logger.error("[LIQUIDATE] Bot %s: No executor available", bid)
                    results["live"][bid] = {"success": False, "error": "No executor available"}
        
        return results

    async def check_health(self) -> bool:
        """Aggregates and enforces global circuit breakers."""
        import time
        import config
        
        # 1. Pre-check: Are we currently inside a 6-hour penalty box?
        for bid, bot in self.bots.items():
            cb = bot.db.get_cb()
            resume_ts = cb.get("resume_time_ts", 0.0)
            if resume_ts > time.time():
                minutes_left = (resume_ts - time.time()) / 60.0
                logger.warning("GLOBAL CIRCUIT BREAKER ACTIVE: Sleeping for %.1f more minutes.", minutes_left)
                return False

        # 1b. Reset peak profit tracking when resuming from halt
        for bot in self.bots.values():
            b_cb = bot.db.get_cb()
            if b_cb.get('halted', 0):
                bot.db.update_cb(
                    b_cb.get('consecutive_losses', 0),
                    b_cb.get('daily_loss_usdc', 0.0),
                    halted=False,
                    peak_profit_pct=0.0  # Reset for new trading session
                )
                logger.info("[CB-RESUME] Peak profit reset to 0%% for new trading session")

        # 2. Portfolio Valuation
        total_daily_loss = 0.0
        current_total_bankroll = 0.0
        open_positions_value = 0.0
        self.needs_liquidation = False
        self.liquidation_reason = ""
        
        for bid, bot in self.bots.items():
            # a) Daily Loss - Use Polymarket API in live mode, DB in paper mode
            if not self.paper_trading and self.polymarket_client and hasattr(bot, 'wallet_address') and bot.wallet_address:
                try:
                    bot_initial = self.initial_bankrolls.get(bid, 50.0)
                    result = await asyncio.to_thread(self.polymarket_client.get_pnl_summary, bot.wallet_address, bot_initial)
                    if result.get("success"):
                        realized_pnl = result.get("realized_pnl", 0)
                        # Only count losses (negative PnL) toward daily loss limit
                        daily_loss = abs(min(0, realized_pnl))
                        total_daily_loss += daily_loss
                        logger.debug("[CB-LIVE] %s: Daily loss from API: $%.2f (realized_pnl: $%.2f)", 
                                     bid, daily_loss, realized_pnl)
                    else:
                        # Fallback to DB if API fails
                        cb_data = bot.db.get_cb()
                        total_daily_loss += cb_data.get('daily_loss_usdc', 0.0)
                        logger.warning("[CB-LIVE] %s: API failed, using DB daily loss", bid)
                except Exception as e:
                    # Fallback to DB on exception
                    cb_data = bot.db.get_cb()
                    total_daily_loss += cb_data.get('daily_loss_usdc', 0.0)
                    logger.error("[CB-LIVE] %s: Exception fetching daily loss: %s", bid, e)
            else:
                # Paper mode: Use DB settled losses
                cb_data = bot.db.get_cb()
                total_daily_loss += cb_data.get('daily_loss_usdc', 0.0)
            
            # b) Balance Check - Use Polymarket API in live mode, local bankroll in paper
            bot_initial = self.initial_bankrolls.get(bid, 50.0)
            if not self.paper_trading and self.polymarket_client and hasattr(bot, 'wallet_address') and bot.wallet_address:
                # Live mode: Fetch actual wallet balance from Polymarket API
                try:
                    result = await asyncio.to_thread(self.polymarket_client.get_pnl_summary, bot.wallet_address, bot_initial)
                    if result.get("success"):
                        actual_balance = result.get("cash_balance", 0)
                        current_total_bankroll += actual_balance
                        logger.debug("[CB-LIVE] %s: Bankroll from API: $%.2f", bid, actual_balance)
                    else:
                        # Fallback to local bankroll if API fails
                        if hasattr(bot, "bankroll") and bot.bankroll:
                            current_total_bankroll += getattr(bot.bankroll, "balance", 0.0)
                        logger.warning("[CB-LIVE] %s: API failed, using local bankroll: $%.2f", 
                                     bid, getattr(bot.bankroll, "balance", 0.0) if hasattr(bot, "bankroll") else 0)
                except Exception as e:
                    # Fallback to local bankroll on exception
                    if hasattr(bot, "bankroll") and bot.bankroll:
                        current_total_bankroll += getattr(bot.bankroll, "balance", 0.0)
                    logger.error("[CB-LIVE] %s: Exception fetching bankroll: %s", bid, e)
            else:
                # Paper mode: Use local bankroll tracker
                if hasattr(bot, "bankroll") and bot.bankroll:
                    current_total_bankroll += getattr(bot.bankroll, "balance", 0.0)
                
            # c) Floating PnL of persistent positions (Mark-to-Market using BID odds)
            if hasattr(bot, "executor") and bot.executor:
                for tid, pos in bot.executor._positions.items():
                    cost = pos.get("stake_usdc", 0.0)
                    m = bot.poly.markets.get(pos.get("token_id")) if hasattr(bot, "poly") else None
                    
                    # SAFETY CHECK: If we have no price data yet (Startup Phase),
                    # value the position at COST to prevent a false Panic Sell.
                    if not m or not m.get("odds") or pos.get("entry_odds", 0) <= 0:
                        open_positions_value += cost # Valued fully at cost
                        continue

                    # Use BID odds for conservative "What can I sell for NOW" value.
                    current_bid = m.get("bid") or m.get("odds") or 0.0
                    if current_bid <= 0:
                        open_positions_value += cost  # No usable price yet — value at cost
                        continue
                    shares = cost / pos["entry_odds"]
                    
                    # Apply 0.5% buffer for slippage + 2% Taker Fee
                    current_val = (shares * current_bid) * 0.975
                    open_positions_value += current_val

        loss_pct = total_daily_loss / max(self._total_bankroll, 1)
        
        # True Floating Equity (Cash Balance + Value of Open Positions)
        total_equity = current_total_bankroll + open_positions_value
        equity_pct = (total_equity - self._total_bankroll) / max(self._total_bankroll, 1)
        
        # 3. Maximum Loss Trigger (The 6-Hour Rule)
        if loss_pct >= self.daily_loss_limit:
            lock_minutes = getattr(config, "GLOBAL_HALT_DURATION_MINUTES", 6.0)
            resume_ts = time.time() + (lock_minutes * 60)
            
            logger.critical("🚨 GLOBAL CIRCUIT BREAKER: Settled loss %.1f%% | INITIATING %.1f-MINUTE DATABASE LOCK", 
                          loss_pct*100, lock_minutes)
                          
            for bot in self.bots.values():
                b_cb = bot.db.get_cb()
                bot.db.update_cb(b_cb.get('consecutive_losses', 0), 
                                 b_cb.get('daily_loss_usdc', 0),
                                 halted=True, reason=f"settled_loss_limit_{lock_minutes}h_lock",
                                 resume_time_ts=resume_ts)
            # LIQUIDATE ALL POSITIONS
            await self.liquidate_all_positions(reason=f"settled_loss_{loss_pct*100:.1f}pct")
            return False
            
        # 4. Profit Ratchet (Floating Equity Spike +20%) -> capture gains
        # Guarded by the same startup grace period as Panic Sell —
        # a false +20% spike from unseeded odds must not trigger premature liquidation.
        STARTUP_GRACE_SECS = 60
        unreal_target = getattr(config, "GLOBAL_UNREALIZED_PROFIT_TARGET", 0.20)
        if unreal_target > 0 and equity_pct >= unreal_target:
            if time.time() - getattr(self, '_started_at', 0) < STARTUP_GRACE_SECS:
                pass  # skip ratchet during startup grace period
            else:
                self.needs_liquidation = True
                self.liquidation_reason = f"profit_ratchet_{equity_pct*100:.1f}pct"
                logger.critical("🚀 PROFIT RATCHET TRIGGERED: +%.1f%% Floating Equity | SECURING ALL BAGS",
                              equity_pct*100)
                await self.liquidate_all_positions(reason=f"profit_ratchet_{equity_pct*100:.1f}pct")
                return False

        # 5. Panic Sell (Floating Equity Crash equivalent to config Limit) -> stop systemic bleed
        panic_floor = -getattr(config, "GLOBAL_DAILY_LOSS_LIMIT", 0.25)
        STARTUP_GRACE_SECS = 60
        if time.time() - getattr(self, '_started_at', 0) < STARTUP_GRACE_SECS:
            pass # skip panic checks during startup
        elif equity_pct <= panic_floor:
            self.needs_liquidation = True
            self.liquidation_reason = f"panic_exit_{equity_pct*100:.1f}pct"
            logger.critical("⚠️ PANIC SELL TRIGGERED: %.1f%% Floating Equity Crash | LIQUIDATING PORTFOLIO", 
                          equity_pct*100)
            # LIQUIDATE ALL POSITIONS
            await self.liquidate_all_positions(reason=f"panic_exit_{equity_pct*100:.1f}pct")
            return False
            
        # 6. Trailing Profit Ratchet (Locks in gains with 1% trailing stop)
        TRAILING_STOP_PCT = 0.01  # 1% drop from peak triggers halt
        PROFIT_THRESHOLD = getattr(config, "PROFIT_RATCHET_THRESHOLD", 0.10)
        
        logger.info("[CB-RATCHET] Checking %d bots: %s", len(self.bots), list(self.bots.keys()))
        
        for bid, bot in self.bots.items():
            has_bankroll = hasattr(bot, "bankroll")
            bankroll_is_none = bot.bankroll is None if has_bankroll else True
            logger.info("[CB-RATCHET] Bot %s: has_bankroll=%s, bankroll_is_none=%s", bid, has_bankroll, bankroll_is_none)
            
            if has_bankroll and not bankroll_is_none:
                bot_initial = self.initial_bankrolls.get(bid, 50.0)
                
                # RATCHET uses session-only PnL (pass startup timestamp)
                # so previous trades from earlier today don't pre-trigger the ratchet
                total_pnl, bot_profit_pct, source = await asyncio.to_thread(self._get_bot_pnl, bid, bot, bot_initial, since_ts=self._started_at)
                
                b_cb = bot.db.get_cb()
                peak_profit = float(b_cb.get('peak_profit_pct', 0.0) or 0.0)
                
                logger.info("[CB-RATCHET] %s: profit=%.1f%% (%.2f/%s), peak=%.1f%%, threshold=%.1f%%, source=%s", 
                           bid, bot_profit_pct*100, total_pnl, bot_initial, peak_profit*100, PROFIT_THRESHOLD*100, source)
                ratchet_logger.info("[CB-RATCHET] %s: profit=%.1f%% (%.2f/%s), peak=%.1f%%, threshold=%.1f%%, source=%s", 
                           bid, bot_profit_pct*100, total_pnl, bot_initial, peak_profit*100, PROFIT_THRESHOLD*100, source)
                
                # ALWAYS update peak if current profit is higher (even below threshold)
                if bot_profit_pct > peak_profit:
                    old_peak = peak_profit
                    peak_profit = bot_profit_pct
                    try:
                        bot.db.update_cb(
                            b_cb.get('consecutive_losses', 0),
                            b_cb.get('daily_loss_usdc', 0.0),
                            peak_profit_pct=peak_profit
                        )
                        logger.info("[CB-RATCHET] %s: PEAK UPDATED %.1f%% -> %.1f%%", bid, old_peak*100, peak_profit*100)
                    except Exception as e:
                        logger.error("[CB-RATCHET] Failed to update peak for %s: %s", bid, e)
                
                # Trailing profit ratchet (1% trailing stop after 10% threshold)
                if peak_profit >= PROFIT_THRESHOLD:
                    drawdown_from_peak = (peak_profit - bot_profit_pct) / peak_profit if peak_profit > 0 else 0
                    logger.info("[CB-RATCHET] %s: peak=%.1f%% current=%.1f%% drawdown=%.1f%%", 
                               bid, peak_profit*100, bot_profit_pct*100, drawdown_from_peak*100)
                    if drawdown_from_peak >= TRAILING_STOP_PCT:
                        logger.critical("🎯 PROFIT RATCHET TRIGGERED: Bot %s peak=%.1f%% current=%.1f%% (drawdown %.1f%%) | HALTING TO LOCK GAINS", 
                                      bid, peak_profit*100, bot_profit_pct*100, drawdown_from_peak*100)
                        bot.db.update_cb(
                            b_cb.get('consecutive_losses', 0),
                            b_cb.get('daily_loss_usdc', 0.0),
                            halted=True, 
                            reason=f"profit_ratchet_peak{peak_profit*100:.1f}pct_drop{drawdown_from_peak*100:.1f}pct"
                        )
                        # LIQUIDATE THIS BOT'S POSITIONS
                        await self.liquidate_all_positions(reason=f"bot_{bid}_profit_ratchet")
                        return False
        
        return True