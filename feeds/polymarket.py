"""
Polymarket Feed
Live odds via WebSocket (with REST polling fallback),
order book depth, market discovery, and order placement.
One shared instance — both bots read from it.

Key fix: Gamma API returns startDateIso/endDateIso as plain dates (not datetimes).
Window start/end are extracted directly from the slug timestamp instead:
  slug = btc-updown-5m-1773543000
  window_start = 1773543000
  window_end   = 1773543000 + 300

Token IDs (needed for WS subscription and orders) are fetched separately
from the CLOB API using the market's conditionId.
"""

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
import aiohttp
import websockets
from config import POLYMARKET_CLOB_URL, POLYMARKET_GAMMA_URL, PAPER_TRADING

logger = logging.getLogger(__name__)

POLY_WS_URL    = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WINDOW_SECONDS = 300   # 5-minute windows


import fnmatch
from utils.pm_math import calculate_vwap, calculate_hedge_price

class PolymarketFeed:

    def __init__(self):
        # Multi-market state: token_id -> market_data
        self.markets = {}
        
        # Compatibility trackers for legacy Bots A and B (BTC-UPDOWN)
        self._default_up_id = None
        self._default_down_id = None
        self._default_window = {"start": None, "end": None}
        
        self.taker_fee_bps = 0
        self.maker_fee_bps = 0
        self._running      = False
        self._session      = None
        self._ws           = None
        self._last_subscribed_ids = set()
        self._ws           = None
        self._debug_count  = 0  # Counter for Wide Debug prints
        # Shared reference to executor._positions so _handle() can update
        # last_ws_update_ts on position objects when a live price arrives.
        # Populated via register_executor() at bot startup.
        self._exec_positions = {}

    # ── Compatibility Layer (to avoid breaking Bot A & B) ──────────────────────

    def register_executor(self, executor):
        """Wire up the shared positions reference so _handle() can update
        last_ws_update_ts on position objects when live WS prices arrive."""
        self._exec_positions = executor._positions

    @property
    def up_token_id(self): return self._default_up_id
    
    @property
    def down_token_id(self): return self._default_down_id

    @property
    def up_odds(self): 
        return self.markets.get(self._default_up_id, {}).get("odds")

    @property
    def down_odds(self):
        return self.markets.get(self._default_down_id, {}).get("odds")

    @property
    def window_start(self): return self._default_window["start"]

    @property
    def window_end(self): return self._default_window["end"]

    @property
    def book_depth(self):
        return self.markets.get(self._default_up_id, {}).get("depth", 0.0)

    @property
    def odds_velocity(self):
        return self.markets.get(self._default_up_id, {}).get("velocity", 0.0)
        
    @property
    def market_id(self):
        return self.markets.get(self._default_up_id, {}).get("condition_id")

    async def start_discovery(self, interval: int = 60):
        """Background loop to discover all active markets efficiently."""
        logger.info("Polymarket discovery service starting | interval=%ds", interval)
        while True:
            try:
                # 1. Surgical Strike List Engine (Direct Mathematical Slug Generation)
                # This replaces the need for bots to call fetch_strike_list_markets() synchronously.
                import config
                assets     = getattr(config, "BOT_G_STRIKE_ASSETS", ["btc", "eth", "sol", "bnb", "xrp", "doge"])
                timeframes = getattr(config, "BOT_G_TIMEFRAMES", {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400})
                
                now = time.time()
                fetches = []
                for asset in assets:
                    for tf_name, tf_secs in timeframes.items():
                        ts = int(now // tf_secs) * tf_secs
                        slug = f"{asset}-updown-{tf_name}-{ts}"
                        fetches.append(self._fetch_and_register(slug, ts, tf_secs))
                
                if fetches:
                    # Limit concurrency for discovery to avoid rate limits
                    logger.debug("Discovery: Fetching %d surgical slugs", len(fetches))
                    for i in range(0, len(fetches), 10):
                        chunk = fetches[i:i+10]
                        await asyncio.gather(*chunk, return_exceptions=True)

                # 2. General discovery for legacy Bot A/B patterns
                ts_window = int(now // 300) * 300
                surgical_pattern = f"*-updown-*-{ts_window}"
                await self.refresh_all_markets(pattern=surgical_pattern)
                
            except Exception as e:
                logger.error("Discovery loop error: %s", e)
            await asyncio.sleep(interval)

    async def _fetch_params(self, p: dict):
        """Helper to fetch from Gamma API with standard active/closed filters."""
        try:
            async with self._session.get(
                f"{POLYMARKET_GAMMA_URL}/markets",
                params={**{"active": "true", "closed": "false"}, **p},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return []
                res = await resp.json()
                if not res: return []
                return res if isinstance(res, list) else res.get("markets", [])
        except Exception as e:
            logger.debug("Fetch params error: %s", e)
            return []

    async def refresh_all_markets(self, pattern: str = None) -> bool:
        """
        Fetches actively expiring markets from Gamma.
        If pattern is provided (Surgical Mode), it only registers markets matching that pattern.
        """
        try:
            now = time.time()
            from datetime import datetime, timedelta, timezone

            cutoff_limit = datetime.now(timezone.utc) + timedelta(days=2) # Max 48 hours from now

            # Fetch both High Volume and Very Newest Active Markets
            results = await asyncio.gather(
                self._fetch_params({"order": "volumeNum", "ascending": "false", "limit": "200"}),
                self._fetch_params({"order": "startDate", "ascending": "false", "limit": "300"}),
            )

            all_markets = []
            seen_ids = set()
            for batch in results:
                for m in batch:
                    mid = m.get("conditionId") or m.get("condition_id")
                    if mid not in seen_ids:
                        all_markets.append(m)
                        seen_ids.add(mid)

            count = 0
            for m in all_markets:
                slug = m.get("slug", "")
                if not slug: continue
                
                # Surgical Filter: If pattern is provided, skip everything that doesn't match
                if pattern and not fnmatch.fnmatch(slug, pattern):
                    continue
                if not slug: continue
                
                # Check Expiration (Skip markets expiring after 48 hours to remove 2028 elections, etc)
                end_str = m.get("endDate", "")
                if end_str:
                    try:
                        # e.g., "2028-11-08T00:00:00Z"
                        dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                        if dt > cutoff_limit:
                            continue # Skip long-term wandering macro markets
                    except Exception:
                        pass
                        
                tid_up, tid_down = self._parse_clob_ids(m)
                if not tid_up or not tid_down: continue
                
                win_ts    = self._extract_ts_from_slug(slug)
                win_start = float(win_ts) if win_ts else now
                win_end   = win_start + WINDOW_SECONDS
                
                # Register metadata
                for tid, peer in [(tid_up, tid_down), (tid_down, tid_up)]:
                    if tid not in self.markets:
                        # Extract event details for high-fidelity URL construction
                        events = m.get("events") or []
                        e_obj = events[0] if events else {}
                        event_slug = e_obj.get("slug") or m.get("slug")
                        series = e_obj.get("series") or []
                        series_slug = series[0].get("slug") if series else None

                        self.markets[tid] = {
                            "odds": None,
                            "ltp": None,    # Last Trade Price (High-fidelity source)
                            "history": deque(maxlen=60),
                            "velocity": 0.0,
                            "bids": [], "asks": [], "depth": 0.0,
                            "win_start": win_start,
                            "win_end": win_end,
                            "slug": slug,
                            "event_slug": event_slug,   # For /event/ URLs
                            "series_slug": series_slug, # For /sports/ URLs
                            "peer_id": peer,
                            "condition_id": self._extract_condition_id(m)
                        }
                    else:
                        self.markets[tid]["win_start"] = win_start
                        self.markets[tid]["win_end"] = win_end
                
                # Legacy BTC-UPDOWN
                if "btc-updown-5m-" in slug and win_start <= now < win_end:
                    self._default_up_id = tid_up
                    self._default_down_id = tid_down
                    self._default_window = {"start": win_start, "end": win_end}
                    self.taker_fee_bps = int(m.get("takerBaseFee", 0)) // 100
                count += 1
            
            await self.resubscribe()
            return True
        except Exception as e:
            logger.error("refresh_all_markets error: %s", e)
            return False

    async def fetch_markets_by_pattern(self, pattern: str) -> bool:
        """Reads from already-populated shared registry."""
        matches = [tid for tid, m in self.markets.items() 
                   if fnmatch.fnmatch(m.get("slug", ""), pattern)]
        return len(matches) > 0

    async def fetch_market(self) -> bool:
        """
        Legacy compat: strictly computes and loads the current rolling BTC 5m market.
        Directly grabs the exact slug via the REST API to bypass pagination limits.
        """
        now = time.time()
        window_ts = int(now // WINDOW_SECONDS) * WINDOW_SECONDS
        
        found = False
        for ts in [window_ts, window_ts - WINDOW_SECONDS, window_ts + WINDOW_SECONDS]:
            slug = f"btc-updown-5m-{ts}"
            m = await self._fetch_by_slug(slug)
            if not m:
                continue

            win_start = float(ts)
            win_end = win_start + WINDOW_SECONDS
            
            if win_start <= now < win_end:
                tid_up, tid_down = self._parse_clob_ids(m)
                if tid_up and tid_down:
                    self._default_up_id = tid_up
                    self._default_down_id = tid_down
                    self._default_window = {"start": win_start, "end": win_end}
                    self.taker_fee_bps = int(m.get("takerBaseFee", 0)) // 100
                    
                    # Also register it dynamically globally into the fleet
                    for tid, peer in [(tid_up, tid_down), (tid_down, tid_up)]:
                        if tid not in self.markets:
                            self.markets[tid] = {
                                "odds": None,
                                "history": deque(maxlen=60),
                                "velocity": 0.0,
                                "bids": [], "asks": [], "depth": 0.0,
                                "win_start": win_start,
                                "win_end": win_end,
                                "slug": slug,
                                "peer_id": peer,
                                "condition_id": self._extract_condition_id(m)
                            }
                    
                    logger.info("New market loaded: %s | window: %s to %s", slug, win_start, win_end)
                    found = True
                    break
        
        
        if found:
            await self.resubscribe()
        return found

    async def fetch_strike_list_markets(self) -> bool:
        """
        No-op legacy shim. Discovery is now handled by start_discovery background task.
        Bots now simply read from the up-to-date self.markets registry.
        """
        return True

    async def _fetch_and_register(self, slug: str, ts: int, duration: int):
        m = await self._fetch_by_slug(slug)
        if not m:
            # Clinical Trace: Slug calculation correct but Polymarket returns 404
            with open("logs/errors.log", "a") as f:
                ts_readable = datetime.fromtimestamp(ts).strftime('%H:%M:%S')
                f.write(f"[{ts_readable}] [404] Slug not found: {slug}\n")
            return
        
        win_start, win_end = float(ts), float(ts + duration)
        tid_up, tid_down = self._parse_clob_ids(m)
        if not tid_up or not tid_down: return
        
        condition_id = self._extract_condition_id(m)
        for tid, peer in [(tid_up, tid_down), (tid_down, tid_up)]:
            if tid not in self.markets:
                self.markets[tid] = {
                    "odds": None, "history": deque(maxlen=60), "velocity": 0.0,
                    "slug": slug, "peer_id": peer, "condition_id": condition_id
                }
            # Always refresh window metadata and condition link
            self.markets[tid]["win_start"] = win_start
            self.markets[tid]["win_end"]   = win_end
            self.markets[tid]["condition_id"] = condition_id
        return True

    def _extract_condition_id(self, m: dict) -> str | None:
        return m.get("conditionId") or m.get("condition_id")

    def _parse_clob_ids(self, market_data: dict) -> tuple:
        clob_ids = market_data.get("clobTokenIds", [])
        if isinstance(clob_ids, str):
            try: clob_ids = json.loads(clob_ids)
            except: clob_ids = []
        
        outcomes = market_data.get("outcomes", [])
        up_id = down_id = None
        
        if clob_ids and len(clob_ids) >= 2:
            for i, o in enumerate(outcomes):
                name = o.lower()
                if name in ("up", "yes") and i < len(clob_ids):
                    up_id = clob_ids[i]
                elif name in ("down", "no") and i < len(clob_ids):
                    down_id = clob_ids[i]
            
            if not up_id: # fallback
                up_id, down_id = clob_ids[0], clob_ids[1]
                
        return up_id, down_id

    def _extract_ts_from_slug(self, slug: str) -> int | None:
        try:
            return int(slug.split("-")[-1])
        except: return None

    async def _fetch_by_slug(self, slug: str) -> dict | None:
        """Fetch a single market from Gamma API by slug."""
        try:
            async with self._session.get(
                f"{POLYMARKET_GAMMA_URL}/markets",
                params={"slug": slug},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
            markets = data if isinstance(data, list) else data.get("markets", [])
            return markets[0] if markets else None
        except Exception as e:
            logger.debug("_fetch_by_slug(%s) error: %s", slug, e)
            return None

    # ── Order book ─────────────────────────────────────────────────────────────

    async def fetch_book(self, token_id: str):
        """Fetches Orderbook snapshot from CLOB REST API."""
        try:
            async with self._session.get(
                f"{POLYMARKET_CLOB_URL}/book",
                params={"token_id": token_id},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                book = await resp.json()
            
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            
            if token_id in self.markets:
                self.markets[token_id]["bids"] = bids
                self.markets[token_id]["asks"] = asks
                
                # Update Midpoint Odds (Critical for Hard Stop Accuracy)
                if bids and asks:
                    best_bid = float(bids[0].get("price", 0))
                    best_ask = float(asks[0].get("price", 0))
                    if best_bid > 0 and best_ask > 0:
                        spread = best_ask - best_bid
                        self.markets[token_id]["odds"] = (best_bid + best_ask) / 2
                        
                        # Rule: If spread > 0.10, the midpoint is often unreliable.
                        # We will supplement it with LTP below.
                        
                        # FIX: Also update the peer (mirror) token price via hedge math
                        peer_id = self.markets[token_id].get("peer_id")
                        if peer_id and peer_id in self.markets:
                            self.markets[peer_id]["odds"] = calculate_hedge_price(
                                self.markets[token_id]["odds"]
                            )

                # ── FETCH LAST TRADE PRICE (The Reality Source) ──
                try:
                    async with self._session.get(
                        f"{POLYMARKET_CLOB_URL}/last-trade-price",
                        params={"token_id": token_id},
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        if resp.status == 200:
                            ltp_data = await resp.json()
                            ltp = float(ltp_data.get("price", 0)) if ltp_data.get("price") else None
                            if ltp:
                                self.markets[token_id]["ltp"] = ltp
                                
                                # If spread is wide, LTP IS the "odds" for valuation
                                bid = float(bids[0].get("price", 0)) if bids else 0
                                ask = float(asks[0].get("price", 0)) if asks else 0
                                if bid and ask and (ask - bid) > 0.10:
                                    self.markets[token_id]["odds"] = ltp
                except Exception as e:
                    logger.debug("LTP fetch error for %s: %s", token_id[:12], e)
                
                # Always update depth for any token (not just default)
                self.markets[token_id]["depth"] = sum(
                    float(b["price"]) * float(b["size"]) for b in bids[:5]
                )
        except Exception as e:
            logger.debug("fetch_book error: %s", e)

    # ── WebSocket odds stream ──────────────────────────────────────────────────

    async def start_odds_stream(self):
        """Unified WebSocket stability loop with diagnostic prints."""
        print(">>> FEED DEBUG: start_odds_stream entered")
        self._running = True
        self._last_heartbeat = time.time()
        self._msg_count = 0
        
        while self._running:
            try:
                now = time.time()
                
                # Diagnostic Pulse every 60s
                if now - self._last_heartbeat >= 60:
                    logger.info("Polymarket Feed Heartbeat | msgs_received=%d", self._msg_count)
                    print(f">>> FEED PULSE: msgs_received={self._msg_count}")
                    self._msg_count = 0
                    self._last_heartbeat = now

                if not self._ws:
                    print(">>> FEED DEBUG: Calling _ws_connect()")
                    await self._ws_connect()
                else:
                    await self.resubscribe()
            except Exception as e:
                print(f">>> FEED CRASH: {e}")
                logger.error("WebSocket main loop error: %s", e)
            
            await asyncio.sleep(2)

    async def _ws_connect(self):
        """Dedicated connection logic with diagnostic prints."""
        self._ws = None
        self._subscribed_tids = set() 
        
        try:
            print(f">>> FEED DEBUG: Attempting WS connect to {POLY_WS_URL}")
            logger.info("Polymarket WS: Attempting to connect to %s...", POLY_WS_URL)
            async with websockets.connect(POLY_WS_URL, 
                                         ping_interval=20, 
                                         ping_timeout=20,
                                         open_timeout=15) as ws:
                self._ws = ws
                print(">>> FEED DEBUG: WS CONNECTED ✓")
                logger.info("Polymarket WS connected ✓")
                
                if self.markets:
                    await self._subscribe(ws)
                    
                async for raw in ws:
                    if not self._running: break
                    self._handle(raw)
        except asyncio.TimeoutError:
            print(">>> FEED DEBUG: WS Handshake Timeout (15s)")
            logger.error("Polymarket WS: Connection handshake timed out")
        except Exception as e:
            print(f">>> FEED DEBUG: WS connection failed: {e}")
            logger.error("Polymarket WS: Connection loop failed: %s", e)
        finally:
            self._ws = None
            print(">>> FEED DEBUG: WS Connection closed")

    async def _subscribe(self, ws):
        """Subscribe to price and book updates for newly registered markets."""
        if not hasattr(self, '_subscribed_tids'):
            self._subscribed_tids = set()
            
        new_tids = [tid for tid in self.markets.keys() if tid not in self._subscribed_tids]
        if not new_tids: 
            return
        
        await ws.send(json.dumps({
            "assets_ids": new_tids,
            "type":       "market",
        }))
        logger.info("WS subscribed | +%d new tokens", len(new_tids))
        
        for t in new_tids:
            self._subscribed_tids.add(t)
            
        # FIX: Use high-fidelity book seeding instead of unreliable /midpoint
        await self._seed_from_book(new_tids)

    async def subscribe_token(self, token_id: str):
        """Dynamically subscribe a single token to the live WebSocket.
        
        Called after a new position is opened so TP/SL can track real prices.
        Safe to call at any time — idempotent, won't double-subscribe.
        """
        if not hasattr(self, '_subscribed_tids'):
            self._subscribed_tids = set()

        # Already subscribed — nothing to do
        if token_id in self._subscribed_tids:
            return

        # Ensure the token exists in self.markets with at least a minimal entry
        # so WS _handle() will accept and store price updates for it
        if token_id not in self.markets:
            from collections import deque
            # FIX: Attempt to resolve peer_id from existing registry before creating
            # an empty slot with peer_id=None which permanently breaks Hedge Logic.
            resolved_peer = next(
                (m.get("peer_id") for tid, m in self.markets.items()
                 if m.get("peer_id") == token_id or
                 (m.get("condition_id") and self.markets.get(m.get("peer_id"), {}).get("condition_id") == m.get("condition_id"))),
                None
            )
            # Also check if any existing token claims this token as its peer
            if not resolved_peer:
                resolved_peer = next(
                    (tid for tid, m in self.markets.items() if m.get("peer_id") == token_id),
                    None
                )
            self.markets[token_id] = {
                "odds": None, "ltp": None, "history": deque(maxlen=60),
                "velocity": 0.0, "bids": [], "asks": [], "depth": 0.0,
                "win_start": None, "win_end": None,
                "slug": "", "peer_id": resolved_peer, "condition_id": None,
            }
            if resolved_peer:
                logger.info("[FEED] subscribe_token: Resolved peer_id %s...→%s...", token_id[:12], resolved_peer[:12])
            else:
                logger.warning("[FEED] subscribe_token: Could not resolve peer_id for %s... — Hedge Logic may be degraded", token_id[:12])

        # If WS is connected, subscribe now
        if self._ws:
            try:
                await self._ws.send(json.dumps({
                    "assets_ids": [token_id],
                    "type": "market",
                }))
                self._subscribed_tids.add(token_id)
                logger.info("[FEED] Dynamically subscribed to token %s", token_id[:20])
                # Seed initial odds via REST so _evaluate() has a starting price
                await self._seed_from_book([token_id])
            except Exception as e:
                logger.warning("[FEED] Dynamic WS subscribe failed for %s: %s", token_id[:20], e)
        else:
            # WS not connected — mark it so it gets picked up on next reconnect
            logger.debug("[FEED] WS not connected — %s will subscribe on next reconnect", token_id[:20])

    async def _seed_from_book(self, tids: list):
        """
        High-fidelity initialization: Uses Orderbook + Last Trade Price + Parity.
        Replaces legacy /midpoint seeding which is inaccurate for 5m markets.
        """
        if not tids: return
        try:
            for tid in tids:
                # 1. Primary side fetch
                await self.fetch_book(tid)
                
                # 2. Check for mirrored parity if the current side is thin
                m = self.markets.get(tid)
                if not m: continue
                
                has_book = m.get("bids") and m.get("asks")
                if not has_book and m.get("peer_id"):
                    # This side is blank, try to seed from peer parity
                    peer_id = m["peer_id"]
                    await self.fetch_book(peer_id)
                    pm = self.markets.get(peer_id)
                    if pm and pm.get("odds"):
                        m["odds"] = round(1.0 - pm["odds"], 4)
                        logger.debug("Seeding %s via peer parity: %.3f", tid[:12], m["odds"])

            logger.info("Sight Restored: Seeded %d markets via Orderbook/LTP", len(tids))
        except Exception as e:
            logger.debug("Seed error: %s", e)

    async def resubscribe(self):
        """
        Throttled resubscribe — only fires when new token IDs are added.
        30s cooldown prevents 1011 WS errors from rapid consecutive calls.
        """
        if not self._ws: return

        # 30s cooldown — prevents server-side keepalive timeout (1011)
        last_t = getattr(self, "_last_sub_time", 0)
        if time.time() - last_t < 30:
            return

        current_ids = set(self.markets.keys())
        if current_ids == self._last_subscribed_ids:
            return

        try:
            await self._subscribe(self._ws)
            self._last_subscribed_ids = current_ids
            self._last_sub_time = time.time()
        except Exception as e:
            # Normal retry — not an error. WS reconnect loop will handle reconnection.
            logger.debug("Resubscribe skipped: %s", e)

    def _handle(self, raw: str):
        """Processes incoming WebSocket messages with LTP + Spread awareness."""
        try:
            msg = json.loads(raw)
            self._msg_count = getattr(self, "_msg_count", 0) + 1

            # Polymarket CLOB often sends batches as a list
            events = msg if isinstance(msg, list) else [msg]

            for event in events:
                if not isinstance(event, dict): continue

                # Unwrap nested data (standard CLOB pattern)
                data = event.get("data") if "data" in event else event
                if not isinstance(data, dict): continue

                tid = data.get("token_id") or data.get("asset_id") or data.get("market_id")
                if not tid or tid not in self.markets: continue

                m_type = event.get("event_type") or event.get("type")

                # ── 1. Update Price (Midpoint/Market) ──
                price = data.get("price")

                if price is not None:
                    price = float(price)
                    now_ts = time.time()

                    # ── 2. Update Trade (Reality Source) ──
                    if m_type == "trade":
                        self.markets[tid]["ltp"] = price
                        # Rule: If spread is wide, LTP wins for valuation
                        bid = self.markets[tid].get("bid", 0)
                        ask = self.markets[tid].get("ask", 0)
                        if bid and ask and (ask - bid) > 0.10:
                            self.markets[tid]["odds"] = price
                    else:
                        # Standard market midpoint update
                        self.markets[tid]["odds"] = price

                    self.markets[tid]["history"].append((now_ts, price))
                    self._update_velocity(tid)

                    # Proof of Vision Log
                    print(f">>> EYES OPEN: {tid[:12]} moved to {price} ({m_type})")

                    # ── 3. Health Guard Update ──
                    if self._exec_positions:
                        for pos in self._exec_positions.values():
                            if pos.get("token_id") == tid:
                                pos["last_ws_update_ts"] = now_ts

                    # Auto-hedge logic for binary pairs
                    peer_id = self.markets[tid].get("peer_id")
                    if peer_id and peer_id in self.markets:
                        self.markets[peer_id]["odds"] = calculate_hedge_price(price)
                        if self._exec_positions:
                            for pos in self._exec_positions.values():
                                if pos.get("token_id") == peer_id:
                                    pos["last_ws_update_ts"] = now_ts

                # ── L2 Book Update ──
                book = data.get("book")
                if book:
                    bids = book.get("bids", [])
                    asks = book.get("asks", [])
                    self.markets[tid]["bids"] = bids
                    self.markets[tid]["asks"] = asks

                    # Recalculate best bid/ask for valuation logic
                    if bids: self.markets[tid]["bid"] = float(bids[0].get("price", 0.0))
                    if asks: self.markets[tid]["ask"] = float(asks[0].get("price", 1.0))

        except Exception as e:
            logger.debug("WS parse error: %s", e)

    def _update_velocity(self, tid: str):
        m = self.markets.get(tid)
        if not m: return
        cutoff = time.time() - 30
        history = list(m["history"])
        history = [(t, p) for t, p in history if t >= cutoff]
        m["velocity"] = round(
            history[-1][1] - history[0][1], 4
        ) if len(history) >= 2 else 0.0

    async def _poll_fallback(self, get_held_tids=None):
        """REST polling fallback. get_held_tids is an optional callable returning the
        set of token_ids currently held in open positions. Those are ALWAYS polled
        regardless of whether their market window has expired."""
        while self._running:
            try:
                now = time.time()
                # FIX: Always include tokens held in open positions, even if their
                # market window has expired (the exact failure mode that caused BTC/ETH
                # positions to be abandoned). Previously only win_start<=now<=win_end
                # tokens were polled — positions past win_end were silently skipped.
                held_tids = get_held_tids() if callable(get_held_tids) else set()
                active_tids = [
                    tid for tid, m in self.markets.items()
                    if tid in held_tids or m.get("win_start", 0) <= now <= m.get("win_end", 0)
                ]
                
                polled = set()
                for tid in active_tids:
                    if tid in polled: continue
                    
                    m = self.markets[tid]
                    async with self._session.get(
                        f"{POLYMARKET_CLOB_URL}/midpoint",
                        params={"token_id": tid},
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        d = await resp.json()
                        mid = float(d.get("mid", 0.5))
                        
                    self.markets[tid]["odds"] = mid
                    self.markets[tid]["bid"]  = mid - 0.005 # Fallback seed
                    self.markets[tid]["ask"]  = mid + 0.005
                    self.markets[tid]["history"].append((now, mid))
                    self._update_velocity(tid)
                    
                    # Also try to get orderbook snapshot for true bid
                    async with self._session.get(
                        f"{POLYMARKET_CLOB_URL}/book",
                        params={"token_id": tid},
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        book = await resp.json()
                        if book and book.get("bids"):
                            self.markets[tid]["bid"] = float(book["bids"][0].get("price", mid))
                        if book and book.get("asks"):
                            self.markets[tid]["ask"] = float(book["asks"][0].get("price", mid))

                    peer_id = m.get("peer_id")
                    if peer_id and peer_id in self.markets:
                        self.markets[peer_id]["odds"] = calculate_hedge_price(mid)
                        self.markets[peer_id]["bid"]  = calculate_hedge_price(self.markets[tid]["ask"])
                        self.markets[peer_id]["ask"]  = calculate_hedge_price(self.markets[tid]["bid"])
                        polled.add(peer_id)
                        
                    polled.add(tid)
                    
            except Exception as e:
                logger.debug("Poll fallback error: %s", e)
            await asyncio.sleep(3)

    # ── Order placement ────────────────────────────────────────────────────────

    async def place_order(self, direction: str, token_id: str,
                          size: float, price: float, bot_id: str,
                          paper: bool = True) -> dict:
        if paper:
            logger.info("[PAPER Bot%s] %s size=%.2f price=%.3f",
                        bot_id, direction.upper(), size, price)
            return {"status": "filled", "filled_price": price, "paper": True}

        # ── Live order via py-clob-client ──────────────────────────────────
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
            from py_clob_client.constants import POLYGON
            from config import (
                POLYMARKET_PRIVATE_KEY, POLYMARKET_FUNDER_ADDRESS,
                POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE,
            )

            if getattr(self, "_clob_client", None) is None:
                creds = ApiCreds(
                    api_key        = POLYMARKET_API_KEY,
                    api_secret     = POLYMARKET_API_SECRET,
                    api_passphrase = POLYMARKET_PASSPHRASE,
                )
                self._clob_client = ClobClient(
                    host           = POLYMARKET_CLOB_URL,
                    key            = POLYMARKET_PRIVATE_KEY,
                    chain_id       = POLYGON,
                    creds          = creds,
                    funder         = POLYMARKET_FUNDER_ADDRESS,
                    signature_type = 1,   # EOA — required for Magic/Gmail wallet
                )
            client = self._clob_client

            # Round price to valid tick (0.01 increments)
            rounded_price = round(round(price / 0.01) * 0.01, 4)

            import math

            if direction == "sell":
                # SELL: GTC limit order with floored shares to never oversell
                shares = math.floor(size * 100_000) / 100_000
                order_args = OrderArgs(
                    token_id = token_id,
                    price    = rounded_price,
                    size     = shares,
                    side     = "SELL",
                )
                signed_order = client.create_order(order_args)
                resp = client.post_order(signed_order, OrderType.GTC)
            else:
                # BUY: FOK market order using create_market_order (correct Polymarket API)
                # amount = USDC to spend (maker). Builder handles shares/precision internally.
                from py_clob_client.clob_types import MarketOrderArgs
                usdc_amount = round(size, 2)
                market_args = MarketOrderArgs(
                    token_id = token_id,
                    amount   = usdc_amount,
                    side     = "BUY",
                    price    = rounded_price,
                )
                signed_order = client.create_market_order(market_args)
                resp = client.post_order(signed_order, OrderType.FOK)

            if resp and resp.get("success"):
                filled_price = float(resp.get("price", rounded_price))
                filled_size  = float(resp.get("size", size))
                logger.info(
                    "[LIVE Bot%s] %s FILLED | size=%.2f price=%.3f order_id=%s",
                    bot_id, direction.upper(), filled_size, filled_price,
                    resp.get("orderID", "?")
                )
                return {
                    "status":       "filled",
                    "filled_price": filled_price,
                    "filled_size":  filled_size,
                    "order_id":     resp.get("orderID"),
                    "paper":        False,
                }
            else:
                logger.error("[LIVE Bot%s] Order rejected: %s", bot_id, resp)
                return {"status": "failed", "reason": str(resp)}

        except ImportError:
            logger.error("py-clob-client not installed — pip install py-clob-client")
            return {"status": "failed", "reason": "missing_dependency"}
        except Exception as e:
            logger.error("[LIVE Bot%s] Order error: %s", bot_id, e)
            return {"status": "failed", "reason": str(e)}

    # ── Timing ─────────────────────────────────────────────────────────────────

    @property
    def seconds_remaining(self) -> float:
        return max(0.0, (self.window_end or 0) - time.time())

    @property
    def seconds_elapsed(self) -> float:
        return max(0.0, time.time() - (self.window_start or time.time()))

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_):
        self._running = False
        if self._session:
            await self._session.close()