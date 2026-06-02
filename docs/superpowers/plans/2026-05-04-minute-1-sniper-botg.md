# Minute 1 Sniper (Bot G Integration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Bot G into a specialized "Minute 1 Sniper" using the validated 0.33–0.54 price band and 8c/3c trailing take profit logic.

**Architecture:** We will keep Bot G's existing multi-asset scanning loop but inject a "Sniper Gate" into its evaluation method. This gate will strictly enforce the Minute 1 timing, the YES-only side bias, and the specific entry odds band. Risk parameters will be controlled via global config.

**Tech Stack:** Python, Asyncio, Polymarket CLOB API, Binance WebSocket.

---

### Task 1: Global Risk & Configuration Update
**Files:**
- Modify: `/Users/user/Documents/Projects/polytest-final/config.py`

- [ ] **Step 1: Update Global Exclude Keywords**
Remove "updown", "btc", "eth", etc., from `GLOBAL_EXCLUDE_KEYWORDS` so the bot can see the crypto markets.
- [ ] **Step 2: Set Sniper Risk Parameters**
Update `RATCHET_ACTIVATION_GAIN` to 0.08, `TRAILING_STOP_DELTA` to 0.03, and `HARD_SL_DELTA` to 0.05.
- [ ] **Step 3: Enable Bot G & Disable Others**
Set `BOT_G_ENABLED = True` and all other bot flags to `False`.

---

### Task 2: Injecting the Sniper Gate into Bot G
**Files:**
- Modify: `/Users/user/Documents/Projects/polytest-final/bots/bot_g.py`

- [ ] **Step 1: Implement Time & Odds Gate**
Modify `_evaluate_market` to return early if:
  - `secs_into_window > 60` (Not Minute 1)
  - `current_price < 0.33` or `current_price > 0.54` (Outside Power Band)
- [ ] **Step 2: Implement Side Bias**
Modify the direction logic to only proceed if `result.direction == "long"` (YES side). Reject all "short" signals.

---

### Task 3: Verification & Live Audit
**Files:**
- Create: `/Users/user/Documents/Projects/polytest-final/scratch/verify_sniper_setup.py`

- [ ] **Step 1: Write Verification Script**
Create a script that instantiates Bot G and runs it against a single known "Minute 1" market from the tape to verify the gates fire correctly.
- [ ] **Step 2: Dry Run**
Run the bot in `PAPER_TRADING = True` mode and monitor `logs/bot_g_rejections.log` to confirm it is correctly ignoring non-Minute 1 and non-Power Band markets.

---

### Task 4: Deployment
- [ ] **Step 1: Start Bot**
Execute `python3 main.py` and monitor the console for "Bot G Sniper Active" heartbeats.
