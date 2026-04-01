# Polymarket Dual Bot

Two independent BTC 5-minute Up/Down trading bots running in parallel.
Paper tested first, then compared, then one goes live.

---

## Architecture

```
main.py  (Orchestrator)
│
├── Shared feeds (one connection each)
│   ├── BinanceFeed     → real-time BTC price, RSI, momentum, volume (WebSocket)
│   ├── ChainlinkFeed   → onchain BTC/USD price + lag detection (Alchemy JSON-RPC)
│   └── PolymarketFeed  → live odds, order book, market discovery, orders
│
├── Bot A — Chainlink lag only
│   ├── signals/signal_a.py   → pure lag score
│   ├── data/bot_a_paper.db   → independent SQLite log
│   └── independent bankroll + circuit breaker
│
└── Bot B — Hybrid
    ├── signals/signal_b.py   → momentum + RSI + volume + odds velocity
    ├── data/bot_b_paper.db   → independent SQLite log
    └── independent bankroll + circuit breaker
```

---

## Strategy summary

### Bot A — Chainlink lag arbitrage
Chainlink's BTC/USD feed only updates onchain when price moves ≥0.5% or
on a ~1 hour heartbeat. When Binance is already 0.45%+ above Chainlink
for 10+ seconds, a Chainlink update is imminent. Polymarket odds haven't
fully priced it in yet — that's the edge.

**This is not prediction. It is information asymmetry.**

### Bot B — Hybrid
Combines four signals: momentum (40%), RSI (24%), volume z-score (18%),
odds velocity (18%). Chainlink lag amplifies (+15%) when it confirms
direction, dampens (×0.70) when it contradicts. Bot B trades without lag.

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Setup folders (only needed once)
python setup_structure.py

# 3. Configure
cp .env.example .env
# Edit .env — paste your ALCHEMY_RPC_URL

# 4. Health check
python test_bot.py

# 5. Run
python main.py
```

---

## Config reference (`config.py`)

| Setting | Paper value | Live value |
|---------|-------------|------------|
| `PAPER_TRADING` | `True` | `False` |
| `CIRCUIT_BREAKER_ENABLED` | `False` | `True` |
| `BOT_A_ENABLED` | `True` | Your choice |
| `BOT_B_ENABLED` | `True` | Your choice |
| `LIVE_CONFLICT_RULE` | n/a | See below |

### Circuit breaker
- `CIRCUIT_BREAKER_ENABLED = False` — paper mode, bot keeps running through loss streaks to gather data
- `CIRCUIT_BREAKER_ENABLED = True` — live mode, halts after `MAX_CONSECUTIVE_LOSSES` or `DAILY_LOSS_LIMIT_PCT`

---

## Turning bots on/off

```python
# config.py
BOT_A_ENABLED = True    # Chainlink lag only
BOT_B_ENABLED = False   # set False to disable
```

---

## Paper testing — what to track

Run for minimum **7 days, 200+ trades per bot**.

Compare results any time:
```bash
python -m analytics.comparison
```

SQL queries on either database:
```sql
-- Overall performance
SELECT outcome, COUNT(*), ROUND(AVG(pnl_usdc),5) AS avg_pnl
FROM trades WHERE resolved=1 GROUP BY outcome;

-- By exit type
SELECT exit_reason, COUNT(*), ROUND(AVG(pnl_usdc),5)
FROM trades WHERE resolved=1 GROUP BY exit_reason;

-- Chainlink lag trades only
SELECT t.outcome, COUNT(*), ROUND(AVG(t.pnl_usdc),5)
FROM trades t JOIN signals s ON t.signal_id=s.id
WHERE s.chainlink_lag_flag=1 AND t.resolved=1
GROUP BY t.outcome;

-- Skip reasons (filter quality)
SELECT reason, COUNT(*) FROM skipped
GROUP BY reason ORDER BY COUNT(*) DESC;
```

Minimum to go live per bot:
- Win rate > 52%
- Positive expectancy after fees
- 200+ trades
- Both long AND short win rates positive

---

## Going live

### Step 1 — Run comparison
```bash
python -m analytics.comparison
```
The report gives an automated verdict and recommends which bot to go live with.

### Step 2 — Set conflict rule (if running both live)
```python
# config.py
LIVE_CONFLICT_RULE = "higher_confidence"
# Options:
# "higher_confidence" → whichever bot has stronger score executes
# "bot_a_priority"    → Bot A always wins when both signal
# "bot_b_priority"    → Bot B always wins when both signal
# "no_trade"          → skip if both want same window (most conservative)
```

### Step 3 — Configure credentials
```python
# config.py
PAPER_TRADING              = False
CIRCUIT_BREAKER_ENABLED    = True
```
```env
# .env
POLYMARKET_PRIVATE_KEY=your_key_without_0x
POLYMARKET_FUNDER_ADDRESS=0x...your_polymarket_profile_address
POLYMARKET_API_KEY=...
POLYMARKET_API_SECRET=...
POLYMARKET_PASSPHRASE=...
```

### Step 4 — Start small
First live week: set `BOT_A_BANKROLL = 20.0` and `BOT_B_BANKROLL = 20.0`.
Scale up only after confirming live performance matches paper.

---

## Circuit Breaker & Profit Protection

The system implements multiple circuit breakers to protect capital:

### 1. Trailing Profit Ratchet (Per Bot)
**Purpose**: Lock in gains after reaching profit threshold with trailing stop protection.

**How it works**:
- **Activation**: When unrealized P&L reaches 10% (`PROFIT_RATCHET_THRESHOLD`)
- **Trailing stop**: 1% drawdown from peak triggers halt (`TRAILING_STOP_PCT`)
- **Example**: 12% peak → halt if drops to 11%. 15% peak → halt if drops to 14%.

**Behavior**:
```
10% reached → Ratchet ACTIVATES, peak = 10%
15% reached → Peak updates to 15%, new stop = 14%
14% reached (drop from 15%) → HALT + LIQUIDATE
```

### 2. Settled Loss Limit (Global)
**Purpose**: Stop trading after cumulative realized losses exceed threshold.

**How it works**:
- Tracks sum of `pnl_usdc` from all closed (`resolved=1`) trades
- **Trigger**: 15% of total bankroll (`DAILY_LOSS_LIMIT_PCT`)
- **Action**: 6-hour trading lock + position liquidation
- **Only counts settled trades** - open positions excluded

### 3. Panic Sell (Global)
**Purpose**: Emergency stop during equity crash.

**How it works**:
- **Trigger**: -25% floating equity (realized + unrealized)
- **Action**: Immediate halt + position liquidation
- **Resets**: Manual restart required

### 4. Consecutive Losses (Per Bot)
**Purpose**: Halt individual bot after loss streak.

**How it works**:
- **Trigger**: 100 consecutive losses (`MAX_CONSECUTIVE_LOSSES`)
- **Action**: Bot halts, other bots continue

---

## Paper vs Live Trading

### P&L Source Switching

| Mode | P&L Source | Data Type | Check Interval |
|------|-----------|-----------|----------------|
| **Paper** | SQLite DB (`trades` table) | Realized only | 10 seconds |
| **Live** | Polymarket API | Realized + Unrealized | 10 seconds |

**Switch**: Set `PAPER_TRADING = False` in `config.py`

### Live Trading API Calls

**Endpoints used**:
- `GET /portfolio/value` - Total value, realized/unrealized P&L
- `GET /positions` - Active positions with unrealized P&L
- `POST /positions/close` - Close position (on circuit breaker)

**Rate limiting**:
- Checks every 10 seconds = 360/hour
- 2 API calls per check = **720 calls/hour**
- Well under Polymarket's 1,000+/min limit
- **Monthly**: ~17,280 API calls

**Error handling**:
- API failures logged to `logs/pnl_errors.log`
- Falls back to last known values on temporary failures
- Circuit breaker still functions with cached data

### Position Liquidation

When circuit breaker triggers, **all positions are closed**:

**Paper mode**:
- Marks DB positions as `resolved=1`
- Simulates market exit at current odds

**Live mode**:
- Calls Polymarket API to close each position
- Waits for transaction confirmation
- Updates DB with actual exit prices

---

## Environment Variables

All circuit breaker settings configurable via environment:

```bash
# Profit Ratchet
PROFIT_RATCHET_THRESHOLD=0.10     # 10% to activate
TRAILING_STOP_PCT=0.01             # 1% drawdown triggers halt
MAX_DAILY_PROFIT_PCT=0.50          # Optional 50% hard cap

# Loss Protection
MAX_CONSECUTIVE_LOSSES=100         # Bot halt after N losses
DAILY_LOSS_LIMIT_PCT=0.15          # 15% settled loss limit
GLOBAL_HALT_DURATION_MINUTES=6.0   # Lock duration after loss limit

# P&L Monitoring
PNL_CHECK_INTERVAL_SEC=10          # Check every 10 seconds
PNL_ERROR_LOG_PATH=logs/pnl_errors.log

# Live Trading API
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
```

**Override in `config.py`**:
```python
import os
PROFIT_RATCHET_THRESHOLD = float(os.getenv("PROFIT_RATCHET_THRESHOLD", "0.10"))
```

---

## Monitoring Circuit Breaker Status

**Check bot status**:
```sql
-- View all bots
SELECT bot_id, halted, halted_reason, peak_profit_pct, 
       daily_loss_usdc, consecutive_losses 
FROM circuit_breaker;

-- Specific bot
SELECT * FROM circuit_breaker WHERE bot_id='A';
```

**View logs**:
```bash
# Circuit breaker triggers
grep -E "PROFIT RATCHET|CIRCUIT BREAKER|PANIC SELL|LIQUIDAT" logs/bot.log

# P&L calculations
grep "CB-RATCHET" logs/bot.log

# API errors
tail -f logs/pnl_errors.log
```

---

## AWS deployment

### First time
```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
git clone https://github.com/YOUR_USERNAME/polymarket-bot.git polymarket
cd polymarket
bash setup_aws.sh
```

### Every future update
```bash
ssh ubuntu@your-ec2-ip
cd polymarket
./deploy.sh
```

### Monitoring
```bash
sudo journalctl -u polymarket-bot -f                    # live logs
sudo journalctl -u polymarket-bot --since today          # today only
sudo journalctl -u polymarket-bot -f | grep -E "ACTIVE|Waiting|ENTER|EXIT|HALTED"
sudo systemctl status polymarket-bot                     # running?
```

---

## API keys

| Key | Where | Required for |
|-----|-------|--------------|
| **Alchemy RPC URL** | dashboard.alchemy.com → Create App → Ethereum Mainnet | Paper + live |
| **Polymarket private key** | reveal.magic.link/polymarket | Live only |
| **Polymarket funder address** | Your Polymarket profile page | Live only |
| **Polymarket API key/secret/passphrase** | polymarket.com → Profile → API Keys | Live only |

---

## File structure

```
├── main.py                    Orchestrator
├── config.py                  All parameters + CIRCUIT_BREAKER_ENABLED flag
├── test_bot.py                Health check — run before main.py
├── setup_structure.py         One-time folder setup
├── requirements.txt
├── .env.example               Copy to .env and fill in
├── .gitignore
├── polymarket-bot.service     Systemd unit file for AWS
├── setup_aws.sh               First-time AWS setup script
├── deploy.sh                  Pull latest + restart on AWS
├── data/                      SQLite databases (auto-created, git-ignored)
│   ├── bot_a_paper.db
│   └── bot_b_paper.db
├── bots/
│   ├── base_bot.py            Shared loop + heartbeat logging
│   ├── bot_a.py               Bot A entry point
│   └── bot_b.py               Bot B entry point
├── signals/
│   ├── signal_a.py            Chainlink lag signal
│   └── signal_b.py            Hybrid signal
├── feeds/
│   ├── binance_ws.py          Price + RSI + momentum + volume
│   ├── chainlink.py           Onchain price + lag detection (raw JSON-RPC)
│   └── polymarket.py          Odds + order book + market discovery + orders
├── risk/
│   └── manager.py             Filters + circuit breaker + Kelly sizing
├── execution/
│   └── trader.py              Entry + trailing stop + TP + hard stop
├── analytics/
│   └── comparison.py          7-day side-by-side report + go-live verdict
└── database/
    └── db.py                  SQLite schema + all read/write operations
```
