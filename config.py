"""
Polymarket Dual-Bot — Config v4
All settings derived from paper trading data analysis.

Data summary (3000+ trades across v1/v2/v3/v4/v5):
  ✓ v5: Removed 5c Stop Loss — killed 67% of eventual winners.
  ✓ v5: Implemented 120s Momentum Filter — exit if peak gain < 0.10.
  ✓ v5: Target Profit increased to 0.40 — 43% signal accuracy is sufficient.
  ✓ Middle 3 minutes (60-240s elapsed) = 67-68% win rate
  ✓ First 60s = unstable odds, avoid
  ✓ Last 60s = odds decided, avoid
  ✓ Trailing stop = 0% win rate across ALL versions — disabled
  ✓ Hard stop at 30s too late — moved to 60s for better exit price
  ✓ Take profit delta 0.18 too small — increased to 0.22
  ✓ Bot A break-even = 48% (wide margin), Bot B break-even = 64% (tight)
  ✓ Bot A payout ratio better: +$0.71 TP vs -$0.66 HS
  ✓ Bot B needs TAKE_PROFIT_DELTA increase to improve payout ratio
  ✓ Chainlink lag edge at 0.20-0.40% deviation (confirmed)
  ✓ Above 0.40% = crowd already priced in
"""

import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

# ── Mode ───────────────────────────────────────────────────────────────────────
PAPER_TRADING = False     # global flag — False = LIVE trading

# ── Per-bot paper/live mode ────────────────────────────────────────────────────
# Allows running Bot A live while Bot B stays on paper simultaneously
BOT_A_PAPER_TRADING = True
BOT_B_PAPER_TRADING = True
BOT_C_PAPER_TRADING = True   # Bot C PAPER
BOT_D_PAPER_TRADING = True
BOT_E_PAPER_TRADING = True
BOT_F_PAPER_TRADING = True
BOT_G_PAPER_TRADING = True

# ── Bot enable flags ───────────────────────────────────────────────────────────
BOT_A_ENABLED = False        # Retired underperformer (Long drag)
BOT_B_ENABLED = False        # Hybrid (Depreciated/Obsolete)
BOT_C_ENABLED = False        # Retired pair-cost arb (resting dual ask <= 0.985 doesn't occur)
BOT_D_ENABLED = False
BOT_E_ENABLED = False
BOT_F_ENABLED = False
BOT_G_ENABLED = False        # Crypto (Universal)
BOT_SNIPER_ENABLED = True    # Active Terminal Sniper Engine
BOT_SNIPER_PAPER_TRADING = False # LIVE TRADING ACTIVE

# ── Live conflict rule ─────────────────────────────────────────────────────────
LIVE_CONFLICT_RULE = "higher_confidence"

# ── Bankroll ───────────────────────────────────────────────────────────────────
BOT_A_BANKROLL = 50.0        # $50 Latency Arb bankroll
BOT_B_BANKROLL = 10000.0     # DATA VOLCANO simulation
BOT_C_BANKROLL = 50.0        # $50 Paper Pair-Cost Arb bankroll
BOT_D_BANKROLL = 100.0
BOT_E_BANKROLL = 100.0
BOT_F_BANKROLL = 100.0
BOT_G_BANKROLL = 10000.0     # DATA VOLCANO simulation
BOT_SNIPER_BANKROLL = 7.64   # Live Safe Bankroll ($7.64 pUSD)
MAX_BET_PCT    = 0.05
KELLY_FRACTION = 0.25

# ── Shared signal thresholds ───────────────────────────────────────────────────
MIN_ODDS            = 0.001  # PAPER: very wide
MAX_ODDS            = 0.999  # PAPER: very wide
MIN_BOOK_DEPTH      = 0.0    # LIVE: 50.0  # 0 to allow untested tokens to pass depth gate
NO_ENTRY_LAST_SECS  = 0      # LIVE: 180   # don't enter if <180s remaining
NO_ENTRY_FIRST_SECS = 60      # LIVE: 60    # don't enter in first 60s
WINDOW_DURATION     = 300
BOT_C_NO_ENTRY_LAST_SECS = 0  # LIVE: 30    # arbs lock in profit immediately

# ── Bot A thresholds (Chainlink lag) ───────────────────────────────────────────
# DATA-BACKED PERFECT BLEND:
# 1. Sustain >= 4s filters 70% of false wicks
# 2. Odds bracket [0.35, 0.70] eliminates 10% win rate lottery traps while maintaining +94% ROI
# 3. Binance spot momentum confirmation prevents fighting the underlying CEX trend
BOT_A_MIN_DEVIATION    = 0.0015 # Meaningful structural lag
BOT_A_MAX_DEVIATION    = 0.60
BOT_A_MIN_SUSTAIN_SECS = 4      # DATA: 4s filter removes transient 1s wicks
BOT_A_MIN_CONFIDENCE   = 0.02
BOT_A_MIN_ODDS         = 0.40   # DATA: sub-0.40 has 18.8% win rate (-7.76 USDC); [0.40-0.49] yields +18.87 USDC
BOT_A_MAX_ODDS         = 0.55   # DATA: odds > 0.55 are net negative (-3.62 USDC combined); [0.40, 0.55] nets +20.27 USDC
BOT_A_REQUIRE_SPOT_MOM = True   # Require Binance 60s momentum confluence

# ── Bot B thresholds (Hybrid) ──────────────────────────────────────────────────
BOT_B_MIN_CONFIDENCE = 0.02     # LIVE: 0.20
BOT_B_SIGNAL_WEIGHTS = {
    "momentum":      0.40,
    "rsi":           0.24,
    "volume":        0.18,
    "odds_velocity": 0.18,
}
BOT_B_LAG_BOOST  = 0.25   # strong reward when lag confirms direction
BOT_B_LAG_DAMPEN = 0.60   # strong penalty when lag contradicts

# ── Bot C thresholds (GLOB Arb) ────────────────────────────────────────────────
# Threshold is sum of YES + NO vwap. < 1.0 is a theoretical arb.
# Entry when (Yes_Ask + No_Ask) <= 0.995 (Guaranteed positive spread / negative risk arb)
ARB_THRESHOLD         = 0.995
BOT_C_MARKET_PATTERNS = ["*"] # Pattern list to scan for arbitrage targets
BOT_C_POLL_INTERVAL   = 3     # Fast 3s scan loop to capture fleeting dislocations
BOT_C_COMPOUND_PCT    = 0.15  # 15% dynamic compounding on available capital
BOT_C_MAX_STAKE       = 50.0  # Max stake cap

# ── Bot D thresholds (Sports Spike) ────────────────────────────────────────────
BOT_D_SPIKE_THRESHOLD   = 0.005  # PAPER: 0.5% move (was 5%) velocity spike to trigger
BOT_D_FADE_ENABLED      = True   # True = fade spikes (mean reversion)
BOT_D_MARKET_PATTERNS   = [      # Sports slug patterns to scan
    "will-*-win-*",
    "*nfl*", "*nba*", "*mlb*", "*nhl*", "*mls*",
    "*soccer*", "*epl*", "*ufc*", "*tennis*",
    "*cs2*", "*dota2*", "*hok*", "*valorant*", "*lol*", "*fc25*",
    "*val-*", "*cs2-*", "*dota2-*", "*lol-*", # short slugs
    "*cbb*", "*ncaa*", # NCAA College Basketball
]

# ── Bot E thresholds (Momentum) ────────────────────────────────────────────────
BOT_E_MIN_VELOCITY = 0.0001# LIVE: 0.015 # Minimum 30s velocity delta to trigger entry
BOT_E_MARKET_PATTERNS = [
    "*president-of-*", "*prime-minister-of-*", "*ceasefire*", "*war-*", "*israel*", "*ukraine*",
    "*will-*-be-*"
]

# ── Bot F thresholds (Copytrade) ────────────────────────────────────────────────
BOT_F_ACCURACY_THRESHOLD = 0.01  # LIVE: 0.65  # Slug must resolve correctly 65%+ of time
BOT_F_MIN_SAMPLES        = 0     # LIVE: 20    # Minimum historical resolutions required
BOT_F_MARKET_PATTERNS    = [
    "*-market-cap-*", "*-fdv-*", "*-one-day-after-*", "*-launch-*",
    "*grammy*", "*oscar*", "*academy-award*", "*awards*", "*next-*-to-*"
]

# ── Bot G thresholds (Crypto) ──────────────────────────────────────────────────
BOT_G_STRIKE_ASSETS = ["btc", "eth", "sol", "bnb", "xrp", "doge"]
BOT_G_TIMEFRAMES = {
    "5m":  300,   # 5-minute markets
    # "15m": 900,   # 15m DISABLED — net negative EV (-8.33 USDC, 38 trades)
}
# Signal momentum band (from 811-trade simulation, March 2026)
BOT_G_MIN_CONFIDENCE          = 0.05   # Full-width data capture for analysis
BOT_G_MOMENTUM_CEILING        = 1.00   # No ceiling for analysis stage

# Entry filters (Wide Aperture for Data Gathering)
BOT_G_MIN_ENTRY_ODDS          = 0.35    # Tightened from 0.10
BOT_G_MAX_ENTRY_ODDS          = 0.75    # Tightened from 0.95
BOT_G_MAX_ENTRY_SECS_INTO_WIN = 210     # Expanded from 120 (3.5 mins / 5 mins)
BOT_G_MIN_SECS_REMAINING      = 60      # Don't enter if < 60s left in window

# Position management
BOT_G_MAX_CONCURRENT_TRADES   = 8       # Controlled aggression (was 999 in volcano mode)
BOT_G_MIN_STAKE               = 1.0     # Minimum stake in USDC

# ── Bot Sniper — Dual-Window Strategy ─────────────────────────────────────────
BOT_SNIPER_STRIKE_ASSETS = ["btc", "eth", "sol"]
SNIPER_STAKE             = 1.0       # $1.00 minimum stake per trade for $2.50 bankroll

# Sniper 1 — Early Momentum / Breakout (Proven +$8.64, 100% Win Rate on 5 trades)
SNIPER_1_ENABLED        = True
SNIPER_1_START_SECS     = 20         # Enter after 20s as trend establishes
SNIPER_1_END_SECS       = 120        # Window up to 120s elapsed (first 2 minutes)
SNIPER_1_MIN_DOMINANCE  = 0.54       # Clear directional edge >= 54c
SNIPER_1_MAX_ENTRY_ODDS = 0.68       # Max 0.68 entry (Risk $0.68 to make $0.32 = healthy EV, no blowout risk)
SNIPER_1_LONG_ONLY      = False      # Two-way trading on breakout momentum
SNIPER_1_TP_DELTA       = 0.18       # +18c Take Profit target (e.g. 0.56 -> 0.74 lock-in)
SNIPER_1_SL_DELTA       = 0.14       # -14c Stop Loss: Cuts failed breakouts at -14c loss, preventing 100% wipeouts
SNIPER_1_TIME_STOP_SECS = 240        # Force exit at 4.0 mins if TP not hit

# Sniper 2 — Late High-Odds Sniping (DISABLED — negative EV, asymmetric 9:1 blowout risk)
SNIPER_2_ENABLED        = False
SNIPER_2_START_SECS     = 9999       # Disabled
SNIPER_2_END_SECS       = 9999       # Disabled
SNIPER_2_MIN_DOMINANCE  = 0.60
SNIPER_2_MAX_ENTRY_ODDS = 0.82
SNIPER_2_LONG_ONLY      = False
SNIPER_2_TP_DELTA       = 99.0
SNIPER_2_SL_DELTA       = 99.0
SNIPER_MIN_STRIKE_DELTA = {"BTC": 25.0, "ETH": 2.5, "SOL": 0.35}

# ── Sniper 15m — Scaled for 15-minute markets ──────────────────────────────────
# 15m markets have 3x the duration of 5m, so entry/exit windows scale proportionally.
# Entry window widened to give dominance more time to establish (15m trends develop slower).
# Time stop at 600s (10 min) leaves 5 min for resolution — same 1/3 ratio as 5m's 180s/300s.
SNIPER_15M_1_START_SECS     = 30     # 2x the 5m entry start (dominance needs more time)
SNIPER_15M_1_END_SECS       = 180    # 3x the 5m entry end (wider window for slower trends)
SNIPER_15M_1_MIN_DOMINANCE  = 0.525  # Same dominance threshold as 5m
SNIPER_15M_1_TP_DELTA       = 0.15   # Same +15c Take Profit target
SNIPER_15M_1_SL_DELTA       = 99.0   # SL DISABLED — let trade ride to TP or time exit
SNIPER_15M_1_TIME_STOP_SECS = 600    # Force exit after 10 min (leaves 5 min for resolution)

# ── Global Exclude patterns ────────────────────────────────────────────────────
# Noise Purge: These keywords will trigger a clinical skip for any bot scanning markets.
GLOBAL_EXCLUDE_KEYWORDS = [
    "above", "below", "up-or-down", "updown",
    "bitcoin", "ethereum", "bnb", "solana", "dogecoin", "xrp", "hype",
    "btc", "eth", "sol", "doge", # shorthand common in slugs
    "-up-", "-down-", # catch internal price action markers
]

# ── Global Portfolio Risk ──────────────────────────────────────────────────────
# SNIPER MODE: All risk is managed per-trade (momentum filter + 4min safety + binary settlement)
# Portfolio-level halts are disabled to avoid interfering with the 5-minute settlement lifecycle.
GLOBAL_MAX_EXPOSURE_PCT = 1.00   # Disabled — Sniper manages exposure per trade
GLOBAL_DAILY_LOSS_LIMIT = 0.99   # Effectively disabled (99% loss limit)
GLOBAL_HALT_DURATION_MINUTES = 0.0 # No halt duration
GLOBAL_DAILY_PROFIT_TARGET = 99.0  # Effectively disabled
GLOBAL_UNREALIZED_PROFIT_TARGET = 0.0 # DISABLED — do not liquidate on unrealized spikes

# ── Circuit breaker ────────────────────────────────────────────────────────────
CIRCUIT_BREAKER_ENABLED = False   # DISABLED — Sniper manages risk per trade
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "100"))
DAILY_LOSS_LIMIT_PCT    = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.15"))

# ── Enhanced Loss Protection (Tiered Halts) ───────────────────────────────────
# Bot G trades 5m markets — raise thresholds to avoid halting on structural noise
ENHANCED_LOSS_PROTECTION_ENABLED = False
CONSECUTIVE_LOSS_HALT_COUNT = 100     # Halt after this many consecutive losses (was 3; raised from 10 after valuation fix)
CONSECUTIVE_LOSS_HALT_MINUTES = 360  # 6 hours = 360 minutes
TOTAL_DAILY_LOSS_HALT_COUNT = 100     # Halt until tomorrow after this many total daily losses (was 6)

# ── Profit Ratchet (Trailing Stop) ───────────────────────────────────────────
# All values as decimals (0.10 = 10%)
PROFIT_RATCHET_THRESHOLD = float(os.getenv("PROFIT_RATCHET_THRESHOLD", "99.0"))  # DISABLED — set to 9900% to never activate
TRAILING_STOP_PCT = 0.99  # Irrelevant while threshold is disabled
MAX_DAILY_PROFIT_PCT = float(os.getenv("MAX_DAILY_PROFIT_PCT", "0.50"))  # Optional 50% hard cap

# ── P&L Check Frequency ────────────────────────────────────────────────────────
PNL_CHECK_INTERVAL_SEC = int(os.getenv("PNL_CHECK_INTERVAL_SEC", "10"))  # 10 seconds

# ── P&L Error Logging ─────────────────────────────────────────────────────────
PNL_ERROR_LOG_PATH = os.getenv("PNL_ERROR_LOG_PATH", "logs/pnl_errors.log")

# ── Position management ────────────────────────────────────────────────────────
GLOBAL_MIN_TRADE_SIZE = 5.0     # 0 = use pure Kelly, otherwise strict floor
GLOBAL_MAX_TRADE_SIZE = 50.0    # Dynamic compounding cap up to $50 per trade
USE_MINIMUM_SIZING_TEST = True  # True = Trade absolute minimum shares allowed, skip if over $5

# Point-Based Profit Ratchet Configuration
TRAILING_STOP_ENABLED   = False  # Disabled to let the Smash TP work purely
HARD_SL_DELTA           = 1.00  # Effectively disabled to allow volatility recovery
RATCHET_ACTIVATION_GAIN = 0.10  # +10 cents profit to activate trail
TAKE_PROFIT_DELTA       = 0.22
HARD_TP_DELTA           = 0.00  # Disabled: Hold for full binary settlement
TIME_STOP_ENABLED       = True  # Enable absolute kill switch
TIME_STOP_SECONDS       = 120   # 2-Minute Strength Test
TRAILING_STOP_DELTA     = 0.10  # Trails 10 cents behind peak profit
HARD_STOP_SECONDS     = 15      # Last resort only — exit before binary settlement
POSITION_POLL_SECS    = 1
POSITION_HEALTH_GUARD_SECS      = 2    # Emergency REST fetch if no WS update for 2s
POSITION_MANDATORY_REFRESH_SECS = 10   # Forced REST truth-check every 10s regardless
POSITION_LOG_FILE               = "logs/open_positions.log"  # Clinical position log

# ── RPC Endpoints ──────────────────────────────────────────────────────────────
CHAINLINK_RPC_URL  = os.getenv("ALCHEMY_RPC_URL", "")  # Ethereum Mainnet
POLYGON_RPC_URL    = os.getenv("POLYGON_RPC_URL", "")
CHAINLINK_BTC_FEED = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"
CHAINLINK_POLL_SECS = 5

# ── Binance / Coinbase ─────────────────────────────────────────────────────────
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@trade"

# ── Polymarket ─────────────────────────────────────────────────────────────────
POLYMARKET_CLOB_URL  = "https://clob.polymarket.com"
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"

# Live trading credentials (empty during paper testing)
POLYMARKET_PRIVATE_KEY    = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")
POLYMARKET_API_KEY        = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET     = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_PASSPHRASE     = os.getenv("POLYMARKET_PASSPHRASE", "")

# ── Database ───────────────────────────────────────────────────────────────────
_DATA_DIR = pathlib.Path(__file__).parent / "data"
_DATA_DIR.mkdir(exist_ok=True)

BOT_A_DB_PATH = str(_DATA_DIR / "bot_a_paper.db")
BOT_B_DB_PATH = str(_DATA_DIR / "bot_b_paper.db")
BOT_C_DB_PATH = str(_DATA_DIR / "bot_c_live.db") if not BOT_C_PAPER_TRADING else str(_DATA_DIR / "bot_c_paper.db")
BOT_D_DB_PATH = str(_DATA_DIR / "bot_d_paper.db")
BOT_E_DB_PATH = str(_DATA_DIR / "bot_e_paper.db")
BOT_F_DB_PATH = str(_DATA_DIR / "bot_f_paper.db")
BOT_G_DB_PATH = str(_DATA_DIR / "bot_g_paper.db")
BOT_SNIPER_DB_PATH = str(_DATA_DIR / "bot_sniper_paper.db")

# ── Logging & Monitoring ───────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
WRITE_SCANNED_MARKETS_TXT = True   # Overwrites logs/bot_X_markets.txt with actively monitored slugs

# High-Precision Signal Trace for Bot G
BOT_G_REJECTION_LOGGING      = True   # Set to False to disable all skip logs
BOT_G_REJECTION_ONLY_CONSOLE = False  # Set to True to skip writing to log file
BOT_G_REJECTION_LOG_PATH     = "logs/bot_g_rejections.log"

# ── Market Tape Logger ─────────────────────────────────────────────────────────
# Records every WebSocket price tick for all 12 markets to a daily CSV file.
# Zero extra API calls — reads only from the existing live WebSocket stream.
# Use for backtesting, lag analysis, and confidence threshold research.
MARKET_TAPE_ENABLED        = False  # Set False to disable all tick logging
MARKET_TAPE_RETENTION_DAYS = 7      # Auto-delete tape files older than N days


# ── Startup validation ─────────────────────────────────────────────────────────
def validate():
    errors = []
    if not CHAINLINK_RPC_URL:
        errors.append(
            "ALCHEMY_RPC_URL is not set in .env\n"
            "  → https://dashboard.alchemy.com → Create App → Ethereum Mainnet"
        )
    # Check live credentials if any bot is going live
    live_bots = [BOT_A_PAPER_TRADING, BOT_B_PAPER_TRADING, BOT_C_PAPER_TRADING, BOT_D_PAPER_TRADING, BOT_E_PAPER_TRADING, BOT_F_PAPER_TRADING, BOT_G_PAPER_TRADING]
    if any(not paper for paper in live_bots):
        if not POLYGON_RPC_URL:
            errors.append("POLYGON_RPC_URL is not set in .env (required for redemptions)")
        for name, val in [
            ("POLYMARKET_PRIVATE_KEY",    POLYMARKET_PRIVATE_KEY),
            ("POLYMARKET_FUNDER_ADDRESS", POLYMARKET_FUNDER_ADDRESS),
            ("POLYMARKET_API_KEY",        POLYMARKET_API_KEY),
            ("POLYMARKET_API_SECRET",     POLYMARKET_API_SECRET),
            ("POLYMARKET_PASSPHRASE",     POLYMARKET_PASSPHRASE),
        ]:
            if not val:
                errors.append(
                    f"{name} is not set in .env (required for live trading)"
                )
    if errors:
        print("\n❌ Config errors:\n")
        for e in errors:
            print(f"  • {e}")
        print()
        raise SystemExit(1)