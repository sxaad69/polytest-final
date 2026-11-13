"""
Bot C — GLOB Arbitrage
Monitors all discovered markets for YES + NO < 0.985 opportunities.
Executes simultaneous buy-both orders and holds until settlement.
"""

import asyncio
import logging
import math
import time
from datetime import datetime
from config import (
    BOT_C_BANKROLL, BOT_C_DB_PATH, 
    MAX_BET_PCT, MIN_ODDS, MAX_ODDS, ARB_THRESHOLD,
    NO_ENTRY_LAST_SECS, BOT_C_NO_ENTRY_LAST_SECS
)
import config
from bots.base_bot import BaseBot
from signals.signal_c import BotCSignal
from utils.pm_math import calculate_vwap

logger = logging.getLogger("bot_c")

class BotC(BaseBot):

    BOT_ID            = "C"
    DB_PATH           = BOT_C_DB_PATH
    STARTING_BANKROLL = BOT_C_BANKROLL

    def __init__(self, binance, chainlink, poly, wallet_address=None, polymarket_client=None):
        super().__init__(binance, chainlink, poly, wallet_address=wallet_address, polymarket_client=polymarket_client)
        self._signal = BotCSignal(arb_threshold=ARB_THRESHOLD)
        self.max_concurrent_trades = 2 if not self.executor.paper_trading else 12
        self.processed_markets = {} # condition_id -> win_end

    async def _loop(self):
        """Custom loop for Bot C to monitor multiple markets."""
        self._log.info("Bot C starting multi-market monitor...")
        
        while self._running:
            try:
                import config
                import importlib
                importlib.reload(config)
                import fnmatch
                
                # 1. Define target markets (Focus on liquid 5m crypto and exclude sports)
                target_markets = {}
                for tid, m in self.poly.markets.items():
                    slug = m.get("slug", "").lower()
                    
                    # A) Bot C Specific: EXCLUDE Sports
                    if any(fnmatch.fnmatch(slug, p) for p in getattr(config, "BOT_D_MARKET_PATTERNS", [])):
                        continue
                    
                    # B) Bot C Specific: Match crypto 5m markets or general patterns
                    is_match = False
                    for p in getattr(config, "BOT_C_MARKET_PATTERNS", ["*-updown-*", "*"]):
                        if fnmatch.fnmatch(slug, p):
                            is_match = True
                            break
                    if is_match:
                        target_markets[tid] = m

                # 2. Write the .txt log (Title | URL) for the user clinical dashboard
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
                    with open("logs/bot_c_markets.txt", "w") as f:
                        f.write("\n".join(entries))

                # 3. Cleanup and iterate evaluation
                now = time.time()
                self.processed_markets = {cid: end for cid, end in self.processed_markets.items() if end > now}

                for tid, m in list(target_markets.items()):
                    if len(self.executor._positions) >= self.max_concurrent_trades:
                        break
                    
                    peer_id = m.get("peer_id")
                    if not peer_id or tid > peer_id: continue
                    if m.get("condition_id") in self.processed_markets: continue

                    await self._evaluate_market(tid, peer_id, m)
                
                self._log.info("[BotC] 🔍 Scanning %d clinical markets (No Sports/Noise)...", len(target_markets))
            except Exception as e:
                self._log.error("Bot C loop error: %s", e, exc_info=True)
            
            await asyncio.sleep(getattr(config, "BOT_C_POLL_INTERVAL", 3)) # Fast 3s poll for Arb discovery

    async def _evaluate_market(self, tid_yes: str, tid_no: str, m_yes: dict):
        m_no = self.poly.markets.get(tid_no)
        if not m_no: return

        # Timing check - use Bot C specific timing for arbs
        secs_remaining = m_yes.get("win_end", 0) - time.time()
        if secs_remaining < BOT_C_NO_ENTRY_LAST_SECS:
            return

        # 1. Canonical Pricing Engine quotes for both legs
        quote_yes = self.poly.get_fair_price(tid_yes)
        quote_no  = self.poly.get_fair_price(tid_no)
        yes_price = quote_yes.get("fair_price")
        no_price  = quote_no.get("fair_price")

        if yes_price is None or no_price is None or yes_price <= 0 or no_price <= 0:
            return

        # 1b. LIQUID ODDS GATE: Strictly restrict to liquid band [0.20, 0.80]
        # Rejects illiquid tail/penny traps (e.g. 0.01 / 0.88) where books are ghost quotes
        if not (0.20 <= yes_price <= 0.80 and 0.20 <= no_price <= 0.80):
            return

        # 2. Dynamic Compounding Stake (15% of bankroll, minimum $2.0 [$1/leg] for live micro-bankrolls, capped at $50.0)
        compound_pct = getattr(config, "BOT_C_COMPOUND_PCT", 0.15)
        max_stake    = getattr(config, "BOT_C_MAX_STAKE", 50.0)
        min_stake    = 2.0 if (self.bankroll.available < 10.0 or not self.executor.paper_trading) else 5.0
        stake        = round(max(min_stake, min(self.bankroll.available * compound_pct, max_stake)), 2)
        if self.bankroll.available < stake:
            if self.bankroll.available >= 2.0:
                stake = 2.0
            else:
                return

        # 3. Evaluate Signal
        market_id = m_yes.get("condition_id")
        result = self._signal.evaluate(
            market_id=market_id,
            token_yes=tid_yes,
            token_no=tid_no,
            yes_vwap=yes_price,
            no_vwap=no_price
        )

        # 5. Check Global Filters
        passed, reason = self.filters.check(
            db=self.db,
            confidence=result.score,
            odds=result.sum_price / 2,
            depth=m_yes.get("depth", 0) + m_no.get("depth", 0),
            secs_remaining=secs_remaining,
            market_id=market_id
        )

        if not passed or not result.tradeable:
            return

        # 5b. PRE-TRADE ORDERBOOK DEPTH GATE:
        # Polymarket enforces min $1.00 per order leg. Calculate integer shares required.
        stake_per_leg = stake / 2
        shares_yes = math.ceil(max(1.0 / yes_price, stake_per_leg / yes_price))
        shares_no  = math.ceil(max(1.0 / no_price, stake_per_leg / no_price))
        req_shares = max(shares_yes, shares_no)

        # In live mode (or when checking liquidity), verify real resting asks on both orderbooks
        has_depth = await self.poly.verify_arb_liquidity(tid_yes, tid_no, yes_price, no_price, float(req_shares))
        if not has_depth:
            self._log.debug("[BotC] Arb skipped by Depth Gate: insufficient resting ask liquidity for %s (req: %d shares)",
                            m_yes.get("slug", market_id)[:25], req_shares)
            return

        # 6. Execute Arb
        self._log.info("[BotC] ARB CONFIRMED WITH DEPTH | market=%s yes=%.3f no=%.3f sum=%.3f stake=%.2f (shares=%d)",
                       market_id[:10], yes_price, no_price, result.sum_price, stake, req_shares)
        
        await self._enter_arb(tid_yes, tid_no, stake/2, yes_price, no_price, result, m_yes)
        self.processed_markets[market_id] = m_yes.get("win_end", 0)

    async def _enter_arb(self, tid_yes, tid_no, stake_per_leg, price_yes, price_no, result, m_yes):
        # Concurrently fire both orders to guarantee simultaneous submission
        task_yes = self.poly.place_order("long", tid_yes, stake_per_leg, price_yes, "C", paper=self.executor.paper_trading)
        task_no  = self.poly.place_order("long", tid_no, stake_per_leg, price_no, "C", paper=self.executor.paper_trading)
        res_yes, res_no = await asyncio.gather(task_yes, task_no, return_exceptions=True)

        if isinstance(res_yes, Exception):
            self._log.error("[BotC] Order YES threw exception: %s", res_yes)
            res_yes = {"status": "failed", "error": str(res_yes)}
        if isinstance(res_no, Exception):
            self._log.error("[BotC] Order NO threw exception: %s", res_no)
            res_no = {"status": "failed", "error": str(res_no)}

        yes_filled = isinstance(res_yes, dict) and res_yes.get("status") == "filled"
        no_filled  = isinstance(res_no, dict) and res_no.get("status") == "filled"

        if yes_filled and no_filled:
            # Log as a single "arb" trade
            self.db.log_entry({
                "signal_id": 0,
                "ts_entry": datetime.utcnow().isoformat(),
                "market_id": result.market_id,
                "direction": "arb",
                "entry_odds": result.sum_price,
                "stake_usdc": stake_per_leg * 2,
                "confidence_score": result.score,
                "slug": m_yes.get("slug", result.market_id),
                "asset": "ARB",
            })
            self.bankroll.reserve(stake_per_leg * 2)
            self._log.info("[BotC] ARB EXECUTED | Locked in %.2f%% profit | Total Stake: $%.2f",
                           (1.0 - result.sum_price)*100, stake_per_leg * 2)
        else:
            # ATOMIC ROLLBACK / EMERGENCY UNWIND:
            # If one leg filled but the other failed FOK, IMMEDIATELY dump the filled leg at best bid
            if yes_filled and not no_filled:
                price_yes_safe = price_yes if price_yes > 0 else 0.50
                shares = res_yes.get("filled_size", res_yes.get("shares", stake_per_leg / price_yes_safe))
                self._log.critical("[BotC] ATOMIC ROLLBACK: YES filled (%.2f shares) but NO failed! Dumping YES immediately...", shares)
                unwind_res = await self.poly.place_order("sell", tid_yes, shares, max(0.01, price_yes - 0.02), "C", paper=self.executor.paper_trading)
                self._log.warning("[BotC] ROLLBACK COMPLETE: YES unwind status: %s", unwind_res.get("status"))

            elif no_filled and not yes_filled:
                price_no_safe = price_no if price_no > 0 else 0.50
                shares = res_no.get("filled_size", res_no.get("shares", stake_per_leg / price_no_safe))
                self._log.critical("[BotC] ATOMIC ROLLBACK: NO filled (%.2f shares) but YES failed! Dumping NO immediately...", shares)
                unwind_res = await self.poly.place_order("sell", tid_no, shares, max(0.01, price_no - 0.02), "C", paper=self.executor.paper_trading)
                self._log.warning("[BotC] ROLLBACK COMPLETE: NO unwind status: %s", unwind_res.get("status"))
            else:
                self._log.info("[BotC] Both FOK orders cancelled cleanly — 0 capital exposed")

    def evaluate_signal(self):
        # Not used by custom loop but needed for BaseBot abstract parity
        return None
