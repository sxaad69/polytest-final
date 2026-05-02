# Graph Report - .  (2026-05-01)

## Corpus Check
- Corpus is ~42,216 words - fits in a single context window. You may not need a graph.

## Summary
- 575 nodes · 1094 edges · 36 communities detected
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 360 edges (avg confidence: 0.66)
- Token cost: 4,200 input · 800 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Core Bots & Orchestration|Core Bots & Orchestration]]
- [[_COMMUNITY_Multi-Market Bots (Bot C, E, F, G)|Multi-Market Bots (Bot C, E, F, G)]]
- [[_COMMUNITY_Polymarket API & Trading Core|Polymarket API & Trading Core]]
- [[_COMMUNITY_Bot Base Logic & Risk|Bot Base Logic & Risk]]
- [[_COMMUNITY_P&L & Entry Filters|P&L & Entry Filters]]
- [[_COMMUNITY_Price Feeds (Binance & Crypto)|Price Feeds (Binance & Crypto)]]
- [[_COMMUNITY_Orderbook & VWAP Utils|Orderbook & VWAP Utils]]
- [[_COMMUNITY_Bot A (Chainlink Lag Arb)|Bot A (Chainlink Lag Arb)]]
- [[_COMMUNITY_Wallet & Position Management|Wallet & Position Management]]
- [[_COMMUNITY_Bot D (Sports Spikes)|Bot D (Sports Spikes)]]
- [[_COMMUNITY_Health Checks|Health Checks]]
- [[_COMMUNITY_Chainlink Feed|Chainlink Feed]]
- [[_COMMUNITY_Polymarket Feed (LegacyThin)|Polymarket Feed (Legacy/Thin)]]
- [[_COMMUNITY_Analysis & Reporting|Analysis & Reporting]]
- [[_COMMUNITY_Bot B (Hybrid Strategy)|Bot B (Hybrid Strategy)]]
- [[_COMMUNITY_Circuit Breaker Tests|Circuit Breaker Tests]]
- [[_COMMUNITY_Position Liquidation Tool|Position Liquidation Tool]]
- [[_COMMUNITY_Stop Loss Analytics|Stop Loss Analytics]]
- [[_COMMUNITY_Resolved Outcome Fetching|Resolved Outcome Fetching]]
- [[_COMMUNITY_Database Query Utils|Database Query Utils]]
- [[_COMMUNITY_Bot Comparison Analytics|Bot Comparison Analytics]]
- [[_COMMUNITY_Balance Verification Script|Balance Verification Script]]
- [[_COMMUNITY_Bulk Audit & Gamma API|Bulk Audit & Gamma API]]
- [[_COMMUNITY_Price History Audit|Price History Audit]]
- [[_COMMUNITY_Trade Logs Extraction|Trade Logs Extraction]]
- [[_COMMUNITY_Market Resolution Audit|Market Resolution Audit]]
- [[_COMMUNITY_Forensic Audit Tape|Forensic Audit Tape]]
- [[_COMMUNITY_Extraction & Audit Runtime|Extraction & Audit Runtime]]
- [[_COMMUNITY_Documentation - Circuit Breaker|Documentation - Circuit Breaker]]
- [[_COMMUNITY_Documentation - Architecture|Documentation - Architecture]]
- [[_COMMUNITY_Documentation - Setup|Documentation - Setup]]
- [[_COMMUNITY_Legacy BTC Price|Legacy BTC Price]]
- [[_COMMUNITY_Legacy Momentum|Legacy Momentum]]
- [[_COMMUNITY_Legacy Momentum (Secondary)|Legacy Momentum (Secondary)]]
- [[_COMMUNITY_Documentation - Audit Verdict|Documentation - Audit Verdict]]
- [[_COMMUNITY_Documentation - Roadmap|Documentation - Roadmap]]

## God Nodes (most connected - your core abstractions)
1. `info()` - 52 edges
2. `PolymarketAPIClient` - 45 edges
3. `PolymarketFeed` - 44 edges
4. `BaseBot` - 36 edges
5. `Orchestrator` - 22 edges
6. `BinanceFeed` - 20 edges
7. `BotG` - 17 edges
8. `BotA` - 17 edges
9. `BotDSignal` - 16 edges
10. `ChainlinkFeed` - 16 edges

## Surprising Connections (you probably didn't know these)
- `Returns auth headers for CLOB authenticated endpoints.` --uses--> `PolymarketAPIClient`  [INFERRED]
  /Users/user/Documents/Projects/polytest-final/verify_live_api.py → /Users/user/Documents/Projects/polytest-final/risk/polymarket_api.py
- `Fetch all open positions for the wallet.` --uses--> `PolymarketAPIClient`  [INFERRED]
  /Users/user/Documents/Projects/polytest-final/verify_live_api.py → /Users/user/Documents/Projects/polytest-final/risk/polymarket_api.py
- `Get current mid price for a token from CLOB.` --uses--> `PolymarketAPIClient`  [INFERRED]
  /Users/user/Documents/Projects/polytest-final/verify_live_api.py → /Users/user/Documents/Projects/polytest-final/risk/polymarket_api.py
- `Fetch all filled trades from data API for realized PnL.` --uses--> `PolymarketAPIClient`  [INFERRED]
  /Users/user/Documents/Projects/polytest-final/verify_live_api.py → /Users/user/Documents/Projects/polytest-final/risk/polymarket_api.py
- `Calculate unrealized PnL from open positions.` --uses--> `PolymarketAPIClient`  [INFERRED]
  /Users/user/Documents/Projects/polytest-final/verify_live_api.py → /Users/user/Documents/Projects/polytest-final/risk/polymarket_api.py

## Communities

### Community 0 - "Core Bots & Orchestration"
Cohesion: 0.05
Nodes (42): BaseBot, BotB, BotC, BotD, Bot D — Sports Spike Monitors live sports markets (NFL, NBA, soccer, UFC, etc.), BotG, Polymarket Multi-Bot — Main Orchestrator Launches up to 7 bots as independent pa, Monitors global circuit breaker across all bots. (+34 more)

### Community 1 - "Multi-Market Bots (Bot C, E, F, G)"
Cohesion: 0.05
Nodes (38): Bot C — GLOB Arbitrage Monitors all discovered markets for YES + NO < 0.985 oppo, BotE, Bot E — Adaptive Momentum Monitors momentum across all discovered markets. Trade, Custom loop for Bot E to monitor multiple markets., BotF, Bot F — Copytrade (Market Slug Mirroring) Monitors historically accurate market, Bot G — Universal Crypto (Multi-Asset Updown) Scans all crypto updown markets (E, # NOTE: Polymarket 5m binary markets always show asks[0]=0.99 / bids[0]=0.01 (+30 more)

### Community 2 - "Polymarket API & Trading Core"
Cohesion: 0.06
Nodes (31): Polymarket Dual-Bot — Config v4 All settings derived from paper trading data ana, validate(), close_single_trade(), get_best_bid(), liquidate_bot(), main(), now_iso(), Attempts to fully close a single open trade.      Returns one of: 'closed', 'par (+23 more)

### Community 3 - "Bot Base Logic & Risk"
Cohesion: 0.06
Nodes (17): BaseBot, Base Bot — shared loop logic. Both Bot A and Bot B inherit from this. Subclasses, Print bot state every 60s so you always know what's happening., Custom loop for Bot C to monitor multiple markets., Custom loop: scan all sports markets every 5s for spikes., CircuitBreaker, KellySizer, PreTradeFilters (+9 more)

### Community 4 - "P&L & Entry Filters"
Cohesion: 0.12
Nodes (29): bot_a_filter(), calc_drawdown(), calc_pnl(), calc_sharpe(), divider(), early_entry_filter(), _entry_odds(), fail() (+21 more)

### Community 5 - "Price Feeds (Binance & Crypto)"
Cohesion: 0.1
Nodes (8): BinanceFeed, momentum_30s(), momentum_60s(), price(), BTC Price Feed Primary:  Coinbase Advanced Trade WebSocket — works on all AWS re, Universal Crypto Price Feed using Coinbase as primary, Binance as fallback., Implements the Polymarket Pricing Rule:         - If spread <= 0.10: use Midpoin, No-op legacy shim. Discovery is now handled by start_discovery background task.

### Community 6 - "Orderbook & VWAP Utils"
Cohesion: 0.12
Nodes (14): calculate_hedge_price(), calculate_vwap(), Calculates the Volume Weighted Average Price (VWAP) for a given USDC depth., Returns the complementary price such that price_a + price_b = 0.98.     0.98 is, Processes incoming WebSocket messages with LTP + Spread awareness., REST polling fallback. get_held_tids is an optional callable returning the, feed(), test_handle_book_event() (+6 more)

### Community 7 - "Bot A (Chainlink Lag Arb)"
Cohesion: 0.17
Nodes (11): BotA, Bot A — Pure Chainlink Lag Arbitrage, BotAResult, BotASignal, Bot A Signal — Pure Chainlink Lag Arbitrage Only trades when Binance has a susta, MockBinance, MockBotASignal, MockChainlink (+3 more)

### Community 8 - "Wallet & Position Management"
Cohesion: 0.16
Nodes (18): calc_realized_pnl(), calc_unrealized_pnl(), clob_headers(), get_blockchain_usdc_balance(), get_current_price(), get_filled_trades(), get_open_positions(), get_wallet_balance() (+10 more)

### Community 9 - "Bot D (Sports Spikes)"
Cohesion: 0.18
Nodes (13): BotDResult, BotDSignal, Bot D Signal — Sports Spike Detector Fires when a sports market experiences a su, A sharp downward spike should trigger a LONG (fade) entry., In ride mode, spike up → LONG, spike down → SHORT., A spike below threshold should not trigger., Odds out of the allowed range should skip., A sharp upward spike should trigger a SHORT (fade) entry. (+5 more)

### Community 10 - "Health Checks"
Cohesion: 0.29
Nodes (11): fail(), ok(), Bot Health Check — run before starting the bot.      python test_bot.py  Tests:, record(), test_binance(), test_chainlink(), test_clob(), test_gamma() (+3 more)

### Community 11 - "Chainlink Feed"
Cohesion: 0.19
Nodes (4): ChainlinkFeed, Chainlink Feed + Lag Detector  Uses raw JSON-RPC eth_call via aiohttp — no web3., Exponential backoff: 0s, 1s, 2s, 4s — handles Alchemy 429s., Raw eth_call JSON-RPC — returns BTC/USD price in 8 decimals.

### Community 12 - "Polymarket Feed (Legacy/Thin)"
Cohesion: 0.15
Nodes (1): Polymarket Feed Live odds via WebSocket (with REST polling fallback), order book

### Community 13 - "Analysis & Reporting"
Cohesion: 0.27
Nodes (10): run_analysis(), generate_performance_table(), generate_signals_table(), get_recent_signals(), get_stats(), main(), mk_layout(), _one() (+2 more)

### Community 14 - "Bot B (Hybrid Strategy)"
Cohesion: 0.25
Nodes (4): Bot B — Hybrid Strategy, BotBResult, BotBSignal, Bot B Signal — Hybrid Strategy Momentum + RSI + volume + odds velocity. Chainlin

### Community 15 - "Circuit Breaker Tests"
Cohesion: 0.27
Nodes (9): Mock test for Legacy Circuit Breaker Tests profit ratchet and loss circuit break, Test: Bot hits 7 consecutive losses (should NOT halt, limit=100)     Expected: S, Create fresh test database, Test: Bot makes 259% profit (like Legacy A)     Expected: Should halt at 10% pro, Test: Bot loses 25% (exceeds 20% daily loss limit)     Expected: Should halt at, setup_test_db(), test_consecutive_losses(), test_loss_circuit_breaker() (+1 more)

### Community 16 - "Position Liquidation Tool"
Cohesion: 0.33
Nodes (9): calc_pnl(), close_db(), fail(), get_current_odds(), main(), ok(), close_positions.py — Close all open paper positions before going live  Run: pyth, Fetch current midpoint odds for a token. (+1 more)

### Community 17 - "Stop Loss Analytics"
Cohesion: 0.54
Nodes (7): analyze_sl(), api_get(), fetch_condition_id(), fetch_price_after_sl(), fetch_resolved_outcome(), main(), ts_to_unix()

### Community 18 - "Resolved Outcome Fetching"
Cohesion: 0.54
Nodes (7): analyze_sl(), api_get(), fetch_condition_id(), fetch_price_after_sl(), fetch_resolved_outcome(), main(), ts_to_unix()

### Community 19 - "Database Query Utils"
Cohesion: 0.48
Nodes (6): display_side_by_side(), get_queries(), main(), Prints multiple dataframes side-by-side using tabulate, run_query_15(), run_query_on_db()

### Community 20 - "Bot Comparison Analytics"
Cohesion: 0.29
Nodes (3): print_comparison(), Comparison Analytics Side-by-side report for Bot A vs Bot B. Run any time: pytho, Prints a comparison table for all bots in the given dict {name: balance}.

### Community 21 - "Balance Verification Script"
Cohesion: 0.53
Nodes (5): fail(), main(), ok(), check_balance.py — Verify wallet and account before going live  Run: python scri, warn()

### Community 22 - "Bulk Audit & Gamma API"
Cohesion: 0.47
Nodes (5): bulk_audit(), fetch_page(), get_winner_index(), Fetch a page of 500 closed markets from Gamma API., Identifies the winning index based on outcomePrices.

### Community 23 - "Price History Audit"
Cohesion: 0.6
Nodes (5): fetch_price_history(), fetch_token_id(), process_row(), run_audit(), ts_to_unix()

### Community 24 - "Trade Logs Extraction"
Cohesion: 0.6
Nodes (5): audit_single(), extract_logs_for_trade(), fetch_tape(), fetch_token_id(), main()

### Community 25 - "Market Resolution Audit"
Cohesion: 0.47
Nodes (5): audit_db(), fetch_resolution(), get_winner_index(), Fetch market resolution data from Gamma API using standard urllib., Extracts the winning outcome index from outcomePrices.     outcomePrices = ["1",

### Community 26 - "Forensic Audit Tape"
Cohesion: 0.7
Nodes (4): extract_logs_for_trade(), fetch_tape(), fetch_token_id(), main()

### Community 27 - "Extraction & Audit Runtime"
Cohesion: 0.7
Nodes (4): extract_logs(), fetch_tape(), fetch_token_id(), run_audit()

### Community 28 - "Documentation - Circuit Breaker"
Cohesion: 0.4
Nodes (5): Circuit Breaker System, Consecutive Losses (Per Bot), Panic Sell (Global), Settled Loss Limit, Trailing Profit Ratchet

### Community 30 - "Documentation - Architecture"
Cohesion: 0.67
Nodes (3): Polymarket Dual Bot Architecture, Bot A (Chainlink Lag), Bot B (Hybrid Momentum)

### Community 32 - "Documentation - Setup"
Cohesion: 1.0
Nodes (1): Run once from your project root to create the correct folder structure.     pyth

### Community 36 - "Legacy BTC Price"
Cohesion: 1.0
Nodes (1): Legacy BTC price property for Bot A/B.

### Community 37 - "Legacy Momentum"
Cohesion: 1.0
Nodes (1): Legacy BTC momentum property.

### Community 38 - "Legacy Momentum (Secondary)"
Cohesion: 1.0
Nodes (1): Legacy BTC momentum property.

### Community 43 - "Documentation - Audit Verdict"
Cohesion: 1.0
Nodes (1): Audit Final Verdict

### Community 44 - "Documentation - Roadmap"
Cohesion: 1.0
Nodes (1): Development Roadmap

## Knowledge Gaps
- **85 isolated node(s):** `Run once from your project root to create the correct folder structure.     pyth`, `Prints multiple dataframes side-by-side using tabulate`, `Polymarket Dual-Bot — Config v4 All settings derived from paper trading data ana`, `Mock test for Legacy Circuit Breaker Tests profit ratchet and loss circuit break`, `Create fresh test database` (+80 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Polymarket Feed (Legacy/Thin)`** (13 nodes): `polymarket.py`, `book_depth()`, `down_odds()`, `down_token_id()`, `market_id()`, `odds_velocity()`, `Polymarket Feed Live odds via WebSocket (with REST polling fallback), order book`, `seconds_elapsed()`, `seconds_remaining()`, `up_odds()`, `up_token_id()`, `window_end()`, `window_start()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Documentation - Setup`** (2 nodes): `setup_structure.py`, `Run once from your project root to create the correct folder structure.     pyth`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Legacy BTC Price`** (1 nodes): `Legacy BTC price property for Bot A/B.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Legacy Momentum`** (1 nodes): `Legacy BTC momentum property.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Legacy Momentum (Secondary)`** (1 nodes): `Legacy BTC momentum property.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Documentation - Audit Verdict`** (1 nodes): `Audit Final Verdict`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Documentation - Roadmap`** (1 nodes): `Development Roadmap`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `info()` connect `Polymarket API & Trading Core` to `Core Bots & Orchestration`, `Multi-Market Bots (Bot C, E, F, G)`, `Bot Base Logic & Risk`, `P&L & Entry Filters`, `Price Feeds (Binance & Crypto)`, `Chainlink Feed`, `Bulk Audit & Gamma API`, `Price History Audit`, `Market Resolution Audit`?**
  _High betweenness centrality (0.193) - this node is a cross-community bridge._
- **Why does `PolymarketFeed` connect `Polymarket API & Trading Core` to `Core Bots & Orchestration`, `Bot Base Logic & Risk`, `Price Feeds (Binance & Crypto)`, `Orderbook & VWAP Utils`, `Polymarket Feed (Legacy/Thin)`, `Position Liquidation Tool`?**
  _High betweenness centrality (0.171) - this node is a cross-community bridge._
- **Why does `PolymarketAPIClient` connect `Core Bots & Orchestration` to `Wallet & Position Management`, `Polymarket API & Trading Core`, `Bot Base Logic & Risk`?**
  _High betweenness centrality (0.142) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `info()` (e.g. with `.__init__()` and `.run()`) actually correct?**
  _`info()` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `PolymarketAPIClient` (e.g. with `test_live_order.py — Comprehensive end-to-end API validation.  Validates:   1. S` and `Find the current active BTC 5m market and return token IDs.`) actually correct?**
  _`PolymarketAPIClient` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `PolymarketFeed` (e.g. with `Calculate number of shares held from a trade record.     shares = stake_usdc / e` and `Fetch the current best bid price for a token from the order book.     We sell at`) actually correct?**
  _`PolymarketFeed` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `BaseBot` (e.g. with `PolymarketFeed` and `BinanceFeed`) actually correct?**
  _`BaseBot` has 26 INFERRED edges - model-reasoned connections that need verification._