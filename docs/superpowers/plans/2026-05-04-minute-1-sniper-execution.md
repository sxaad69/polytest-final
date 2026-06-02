# Minute 1 Sniper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the "BotSniper" class inheriting from Bot G, along with its specific configuration and orchestration.

**Architecture:** Use Class Inheritance to reuse Bot G's proven execution layer. Overload the evaluation method with the Minute 1 Sniper Gate.

---

### Task 1: Configuration Setup
**Files:**
- Modify: `/Users/user/Documents/Projects/polytest-final/config.py`

- [ ] **Step 1: Add Sniper Configuration Block**
Add the following variables:
  - `BOT_SNIPER_ENABLED = True`
  - `BOT_SNIPER_BANKROLL = 35.00`
  - `BOT_SNIPER_STRIKE_ASSETS = ["btc", "eth", "sol", "bnb", "xrp", "doge"]`
  - `SNIPER_DIRECTION = "long"`
  - `SNIPER_MIN_MOMENTUM = None`
  - `SNIPER_MIN_ODDS = 0.33`
  - `SNIPER_MAX_ODDS = 0.54`
- [ ] **Step 2: Update Trailing Stop Defaults**
Ensure `RATCHET_ACTIVATION_GAIN = 0.08` and `TRAILING_STOP_DELTA = 0.03` are set for the global execution layer.

---

### Task 2: BotSniper Implementation
**Files:**
- Create: `/Users/user/Documents/Projects/polytest-final/bots/bot_sniper.py`

- [ ] **Step 1: Create BotSniper Class**
Inherit from `BotG`. 
- [ ] **Step 2: Override `_evaluate_market`**
Implement the Minute 1 Sniper Gate:
  - Check `secs_into_window <= 60`.
  - Check `price` in [0.33, 0.54].
  - Check `direction` bias.
- [ ] **Step 3: Integrate `_log_skip`**
Ensure rejections for time/odds are logged via the existing Bot G logger.

---

### Task 3: Orchestration & Launch
**Files:**
- Modify: `/Users/user/Documents/Projects/polytest-final/main.py`

- [ ] **Step 1: Register BotSniper**
Import `BotSniper` and add it to the `registry` in `Orchestrator.run()`.
- [ ] **Step 2: Dry Run (Paper)**
Set `PAPER_TRADING = True` and run the bot. Monitor logs to verify it correctly identifies and "enters" Minute 1 targets.

---

### Task 4: Final Verification
- [ ] **Step 1: Tape Audit**
Run the bot against a 1-hour segment of the May 3rd tape and verify that every entry matches the "Sniper" rules.
