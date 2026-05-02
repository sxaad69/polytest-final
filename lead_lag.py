"""
Polymarket Momentum Arbitrage — Full Roadmap Analysis
=======================================================
Covers all 5 phases of the strategy roadmap in a single script.

Phase 1 — Data Baseline
    Simulates 48h of Binance 1s + Polymarket 1m data for BTC, ETH, SOL, XRP, DOGE.
    Drop-in ready: replace simulate_binance_prices() / simulate_polymarket_candles()
    with real data loaders when you have collected data.

Phase 2 — Lead/Lag Proof
    Joins Binance 1s with Polymarket 1m candles.
    Measures exact lag distribution per asset (in seconds).
    Calculates probability jump after significant Binance moves.
    Builds correlation matrix: Binance 30s return bucket -> avg Polymarket prob shift.

Phase 3 — Threshold Tuning
    Tests 8 momentum thresholds per asset (0.05% to 0.50%).
    Filters by chop ratio, sign agreement, and zone.
    Identifies per-asset optimal threshold for >75% win rate.

Phase 4 — Signal Backtesting
    Replays every 5-minute market window across full dataset.
    Applies full signal pipeline: composite momentum -> chop guard ->
    zone guard -> threshold check -> entry logged.
    One signal per market window (first clean signal).

Phase 5 — Profit Ratchet Simulation
    For every triggered signal, simulates the ratchet state machine.
    Tracks entry -> ratchet levels -> exit reason -> P&L.
    Aggregates: win rate, avg profit, avg loss, max drawdown, Sharpe ratio.

Outputs (all in OUTPUT_DIR):
    full_analysis_report.json   -- complete per-asset stats all phases
    trades.csv                  -- every simulated trade with full metadata
    threshold_matrix.csv        -- win rate per asset per threshold
    summary.txt                 -- human-readable executive summary

Usage:
    python lead_lag_analysis.py

To use real data (Phase 2+):
    Replace simulate_binance_prices() with a CCXT fetch.
    Replace simulate_polymarket_candles() with a loader for
    the JSON files produced by polymarket_price_history.py.
"""

import json
import csv
import os
import random
import math
from datetime import datetime, timezone

# ===============================================================
# CONFIG
# ===============================================================

SIMULATION_HOURS      = 48
BINANCE_RES_SEC       = 1
POLYMARKET_RES_SEC    = 60
MARKET_WINDOW_SEC     = 300
LAG_RANGE_SEC         = (10, 30)
OUTPUT_DIR            = "./lead_lag_output"

POSITION_SIZE_USD     = 10.0
DEAD_ZONE_SEC         = 30
DRIFT_ZONE_SEC        = 90
DRIFT_THRESHOLD_MULT  = 2.0

RATCHET_LEVELS = [
    (0.60, 0.52),
    (0.70, 0.62),
    (0.80, 0.74),
    (0.90, 0.85),
]
HARD_STOP   = 0.42
ENTRY_PROB  = 0.50

ASSET_PARAMS = {
    "BTC":  {"price": 65000, "vol_pct": 0.60},
    "ETH":  {"price":  3500, "vol_pct": 0.75},
    "SOL":  {"price":   150, "vol_pct": 1.20},
    "XRP":  {"price":   0.6, "vol_pct": 1.10},
    "DOGE": {"price":  0.15, "vol_pct": 1.40},
}

THRESHOLD_CANDIDATES = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]

RETURN_BUCKETS = [
    ("<-0.3%",      None,   -0.003),
    ("-0.3--0.15%", -0.003, -0.0015),
    ("-0.15-0%",   -0.0015,  0.0),
    ("0-0.15%",     0.0,    0.0015),
    ("0.15-0.3%",   0.0015, 0.003),
    (">0.3%",       0.003,  None),
]


# ===============================================================
# PHASE 1 — DATA SIMULATION
# ===============================================================

def simulate_binance_prices(asset, start_ts, duration_sec):
    params     = ASSET_PARAMS[asset]
    price      = params["price"]
    annual_vol = params["vol_pct"] / 100
    dt         = 1 / (6.5 * 3600)
    sigma_step = annual_vol * math.sqrt(dt)

    records         = []
    prev_price      = price
    burst_remaining = 0
    burst_direction = 1

    for i in range(duration_sec):
        shock = random.gauss(0, 1)
        if burst_remaining > 0:
            shock = abs(shock) * burst_direction * random.uniform(1.5, 3.5)
            burst_remaining -= 1
        elif random.random() < 0.006:
            burst_direction = random.choice([-1, 1])
            burst_remaining = random.randint(15, 30)
            shock = abs(shock) * burst_direction * random.uniform(2.0, 5.0)

        price = price * math.exp(sigma_step * shock)
        ret   = (price - prev_price) / prev_price
        records.append({
            "ts":        start_ts + i,
            "price":     round(price, 6),
            "return_1s": round(ret, 8),
        })
        prev_price = price

    return records


def simulate_polymarket_candles(asset, binance_prices, market_windows, lag_sec):
    price_map   = {r["ts"]: r["price"] for r in binance_prices}
    all_candles = []

    for mopen, mclose in market_windows:
        duration     = mclose - mopen
        locked_price = price_map.get(mopen, binance_prices[0]["price"])

        def price_to_prob(bp, t_rem):
            pct_dev   = (bp - locked_price) / locked_price
            steepness = 12 + (1 - t_rem / duration) * 30
            raw       = 1 / (1 + math.exp(-steepness * pct_dev))
            noise     = random.gauss(0, 0.015)
            return max(0.01, min(0.99, raw + noise))

        for minute in range(0, duration, POLYMARKET_RES_SEC):
            candle_ts   = mopen + minute
            lagged_ts   = candle_ts - lag_sec
            t_remaining = duration - minute

            lagged_price = price_map.get(lagged_ts)
            if lagged_price is None:
                nearest = min(price_map.keys(), key=lambda x: abs(x - lagged_ts))
                lagged_price = price_map[nearest]

            prob = price_to_prob(lagged_price, max(1, t_remaining))
            all_candles.append({
                "ts":             candle_ts,
                "asset":          asset,
                "market_open_ts": mopen,
                "locked_price":   round(locked_price, 6),
                "t_remaining":    t_remaining,
                "pm_prob_up":     round(prob, 4),
                "binance_price":  round(lagged_price, 6),
            })

    return all_candles


# ===============================================================
# PHASE 2 — LEAD/LAG PROOF
# ===============================================================

def compute_momentum(price_map, at_ts):
    now_price = price_map.get(at_ts)
    if now_price is None:
        return {}

    def pct(lb):
        p = price_map.get(at_ts - lb)
        return (now_price - p) / p if p else None

    m10, m30, m60 = pct(10), pct(30), pct(60)
    if any(v is None for v in [m10, m30, m60]):
        return {}

    composite   = 0.25 * m10 + 0.50 * m30 + 0.25 * m60
    signs_agree = (m10 > 0) == (m30 > 0) == (m60 > 0)

    window = [price_map[t] for t in range(at_ts - 60, at_ts + 1) if t in price_map]
    if len(window) >= 10:
        rng        = max(window) - min(window)
        net        = abs(window[-1] - window[0])
        chop_ratio = net / rng if rng > 0 else 1.0
        recent     = [price_map[t] for t in range(at_ts - 30, at_ts + 1) if t in price_map]
        flips      = sum(
            1 for i in range(1, len(recent) - 1)
            if (recent[i] - recent[i-1]) * (recent[i+1] - recent[i]) < 0
        )
    else:
        chop_ratio, flips = 1.0, 0

    return {
        "momentum_10s": round(m10,       6),
        "momentum_30s": round(m30,       6),
        "momentum_60s": round(m60,       6),
        "composite":    round(composite, 6),
        "direction":    1 if composite > 0 else -1,
        "signs_agree":  signs_agree,
        "chop_ratio":   round(chop_ratio, 4),
        "flip_count":   flips,
        "is_choppy":    chop_ratio < 0.6 or flips >= 3,
    }


def measure_lead_lag(binance_prices, pm_candles, move_threshold_pct=0.15):
    price_map = {r["ts"]: r["price"] for r in binance_prices}
    prob_map  = {c["ts"]: c["pm_prob_up"] for c in pm_candles}
    prob_ts   = sorted(prob_map.keys())
    thresh    = move_threshold_pct / 100
    lags      = []

    for candle in pm_candles[:-2]:
        ts  = candle["ts"]
        mom = compute_momentum(price_map, ts)
        if not mom or abs(mom["composite"]) < thresh or mom["is_choppy"]:
            continue
        direction  = mom["direction"]
        entry_prob = prob_map.get(ts)
        if entry_prob is None:
            continue
        for fts in prob_ts:
            if fts <= ts:
                continue
            delta = prob_map[fts] - entry_prob
            if (direction == 1 and delta > 0.03) or (direction == -1 and delta < -0.03):
                lags.append(fts - ts)
                break

    if not lags:
        return {"avg_lag_sec": None, "median_lag_sec": None, "samples": 0,
                "distribution": {}}

    lags_s = sorted(lags)
    dist   = {"<30s": 0, "30-60s": 0, "60-90s": 0, ">90s": 0}
    for l in lags:
        if   l < 30: dist["<30s"]   += 1
        elif l < 60: dist["30-60s"] += 1
        elif l < 90: dist["60-90s"] += 1
        else:        dist[">90s"]   += 1

    return {
        "avg_lag_sec":    round(sum(lags) / len(lags), 1),
        "median_lag_sec": lags_s[len(lags_s) // 2],
        "samples":        len(lags),
        "distribution":   dist,
    }


def build_correlation_matrix(binance_prices, pm_candles):
    price_map = {r["ts"]: r["price"] for r in binance_prices}
    prob_list = sorted(pm_candles, key=lambda x: x["ts"])
    rows      = []

    for i, candle in enumerate(prob_list[:-1]):
        ts    = candle["ts"]
        p_now = price_map.get(ts)
        p_30s = price_map.get(ts - 30)
        if not p_now or not p_30s:
            continue
        ret_30s   = (p_now - p_30s) / p_30s
        prob_shift = prob_list[i + 1]["pm_prob_up"] - candle["pm_prob_up"]
        rows.append({"ret_30s": ret_30s, "prob_shift": prob_shift})

    matrix = []
    for label, lo, hi in RETURN_BUCKETS:
        bucket = [
            r for r in rows
            if (lo is None or r["ret_30s"] >= lo)
            and (hi is None or r["ret_30s"] < hi)
        ]
        if bucket:
            avg_shift   = sum(b["prob_shift"] for b in bucket) / len(bucket)
            pct_correct = sum(
                1 for b in bucket
                if (b["ret_30s"] > 0 and b["prob_shift"] > 0) or
                   (b["ret_30s"] < 0 and b["prob_shift"] < 0)
            ) / len(bucket)
        else:
            avg_shift, pct_correct = 0.0, 0.0

        matrix.append({
            "return_bucket":  label,
            "sample_count":   len(bucket),
            "avg_prob_shift": round(avg_shift,   4),
            "pct_correct":    round(pct_correct, 4),
        })

    return matrix


# ===============================================================
# PHASE 3 — THRESHOLD TUNING
# ===============================================================

def get_zone(t_remaining):
    if t_remaining <= DEAD_ZONE_SEC:
        return "dead"
    if t_remaining <= DRIFT_ZONE_SEC:
        return "drift"
    return "normal"


def check_signal(mom, threshold_pct, t_remaining):
    if not mom:
        return False
    zone = get_zone(t_remaining)
    if zone == "dead":
        return False
    if mom["is_choppy"] or not mom["signs_agree"]:
        return False
    effective = threshold_pct / 100
    if zone == "drift":
        effective *= DRIFT_THRESHOLD_MULT
    return abs(mom["composite"]) >= effective


def tune_thresholds(asset, binance_prices, pm_candles):
    price_map = {r["ts"]: r["price"] for r in binance_prices}
    results   = []

    for thresh in THRESHOLD_CANDIDATES:
        wins = losses = 0
        zone_stats   = {"normal": [0, 0], "drift": [0, 0]}
        prob_jumps   = []

        for i, candle in enumerate(pm_candles[:-2]):
            ts          = candle["ts"]
            t_remaining = candle["t_remaining"]
            mom         = compute_momentum(price_map, ts)
            if not check_signal(mom, thresh, t_remaining):
                continue

            direction  = mom["direction"]
            entry_prob = candle["pm_prob_up"]
            exit_prob  = pm_candles[i + 2]["pm_prob_up"]

            correct = (direction == 1 and exit_prob > entry_prob) or \
                      (direction == -1 and exit_prob < entry_prob)

            if correct: wins   += 1
            else:       losses += 1

            zone = get_zone(t_remaining)
            if zone in zone_stats:
                zone_stats[zone][1] += 1
                if correct:
                    zone_stats[zone][0] += 1

            prob_jumps.append(abs(exit_prob - entry_prob))

        total    = wins + losses
        win_rate = wins / total if total > 0 else 0.0
        avg_jump = sum(prob_jumps) / len(prob_jumps) if prob_jumps else 0.0

        def zwr(z):
            w, t = zone_stats[z]
            return round(w / t, 4) if t > 0 else 0.0

        results.append({
            "threshold_pct":  thresh,
            "total_signals":  total,
            "wins":           wins,
            "losses":         losses,
            "win_rate":       round(win_rate, 4),
            "normal_zone_wr": zwr("normal"),
            "drift_zone_wr":  zwr("drift"),
            "avg_prob_jump":  round(avg_jump, 4),
            "meets_75pct":    win_rate >= 0.75,
        })

    return sorted(results, key=lambda x: x["win_rate"], reverse=True)


# ===============================================================
# PHASE 4 — SIGNAL BACKTESTING
# ===============================================================

def backtest_signals(asset, binance_prices, pm_candles, threshold_pct):
    price_map      = {r["ts"]: r["price"] for r in binance_prices}
    candles_by_mkt = {}
    for c in pm_candles:
        candles_by_mkt.setdefault(c["market_open_ts"], []).append(c)

    signals = []
    for mopen, window_candles in sorted(candles_by_mkt.items()):
        window_candles = sorted(window_candles, key=lambda x: x["ts"])
        signal_fired   = False

        for i, candle in enumerate(window_candles[:-2]):
            if signal_fired:
                break
            ts          = candle["ts"]
            t_remaining = candle["t_remaining"]
            mom         = compute_momentum(price_map, ts)
            if not check_signal(mom, threshold_pct, t_remaining):
                continue

            direction    = mom["direction"]
            locked       = candle["locked_price"]
            final_price  = price_map.get(window_candles[-1]["ts"], locked)
            resolved_up  = final_price > locked
            correct      = (direction == 1 and resolved_up) or \
                           (direction == -1 and not resolved_up)

            signals.append({
                "asset":          asset,
                "market_open_ts": mopen,
                "signal_ts":      ts,
                "utc":            datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "zone":           get_zone(t_remaining),
                "t_remaining":    t_remaining,
                "threshold_pct":  threshold_pct,
                "direction":      "UP" if direction == 1 else "DOWN",
                "momentum_10s":   mom["momentum_10s"],
                "momentum_30s":   mom["momentum_30s"],
                "momentum_60s":   mom["momentum_60s"],
                "composite":      mom["composite"],
                "chop_ratio":     mom["chop_ratio"],
                "flip_count":     mom["flip_count"],
                "locked_price":   locked,
                "entry_prob":     candle["pm_prob_up"],
                "final_prob":     round(window_candles[-1]["pm_prob_up"], 4),
                "resolved_up":    resolved_up,
                "correct":        correct,
            })
            signal_fired = True

    return signals


# ===============================================================
# PHASE 5 — PROFIT RATCHET SIMULATION
# ===============================================================

def simulate_ratchet(signal, pm_candles):
    mopen     = signal["market_open_ts"]
    signal_ts = signal["signal_ts"]
    direction = 1 if signal["direction"] == "UP" else -1

    window = sorted(
        [c for c in pm_candles
         if c["market_open_ts"] == mopen and c["ts"] >= signal_ts],
        key=lambda x: x["ts"]
    )
    if not window:
        return _make_trade(signal, "no_data", ENTRY_PROB, ENTRY_PROB, HARD_STOP)

    current_stop = HARD_STOP
    ratchet_idx  = 0
    exit_prob    = None
    exit_reason  = "resolved"

    for candle in window:
        prob       = candle["pm_prob_up"]
        t_rem      = candle["t_remaining"]
        eff_prob   = prob if direction == 1 else (1 - prob)

        # Advance ratchet
        while ratchet_idx < len(RATCHET_LEVELS):
            trigger, new_stop = RATCHET_LEVELS[ratchet_idx]
            if eff_prob >= trigger:
                current_stop = new_stop
                ratchet_idx += 1
            else:
                break

        # Ratchet stop hit (only after first ratchet level reached)
        if eff_prob <= current_stop and current_stop > HARD_STOP:
            exit_prob   = eff_prob
            exit_reason = "ratchet_stop"
            break

        # Hard stop
        if eff_prob <= HARD_STOP:
            exit_prob   = eff_prob
            exit_reason = "hard_stop"
            break

        # Dead zone with profit
        if t_rem <= DEAD_ZONE_SEC and eff_prob > ENTRY_PROB:
            exit_prob   = eff_prob
            exit_reason = "dead_zone_profit_exit"
            break

    if exit_prob is None:
        last_prob = window[-1]["pm_prob_up"]
        exit_prob = last_prob if direction == 1 else (1 - last_prob)

    return _make_trade(signal, exit_reason, ENTRY_PROB, exit_prob, current_stop)


def _make_trade(signal, exit_reason, entry_prob, exit_prob, final_stop):
    pnl_unit = exit_prob - entry_prob
    pnl_usd  = pnl_unit * POSITION_SIZE_USD
    return {
        "asset":          signal["asset"],
        "utc":            signal["utc"],
        "zone":           signal["zone"],
        "direction":      signal["direction"],
        "threshold_pct":  signal["threshold_pct"],
        "composite":      signal["composite"],
        "chop_ratio":     signal["chop_ratio"],
        "entry_prob":     round(entry_prob,  4),
        "exit_prob":      round(exit_prob,   4),
        "final_stop":     round(final_stop,  4),
        "exit_reason":    exit_reason,
        "pnl_per_unit":   round(pnl_unit,   4),
        "pnl_usd":        round(pnl_usd,    4),
        "won":            pnl_usd > 0,
        "correct_signal": signal["correct"],
    }


def aggregate_trades(trades):
    if not trades:
        return {}
    wins    = [t for t in trades if t["won"]]
    losses  = [t for t in trades if not t["won"]]
    pnls    = [t["pnl_usd"] for t in trades]
    total   = sum(pnls)
    avg     = total / len(trades)

    cum, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        cum  += p
        peak  = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    std    = math.sqrt(sum((p - avg) ** 2 for p in pnls) / len(pnls)) if len(pnls) > 1 else 0
    sharpe = avg / std if std > 0 else 0.0

    exit_dist = {}
    for t in trades:
        exit_dist[t["exit_reason"]] = exit_dist.get(t["exit_reason"], 0) + 1

    return {
        "total_trades":  len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(trades), 4),
        "total_pnl_usd": round(total, 2),
        "avg_pnl_usd":   round(avg,   4),
        "avg_win_usd":   round(sum(t["pnl_usd"] for t in wins)   / len(wins),   4) if wins   else 0,
        "avg_loss_usd":  round(sum(t["pnl_usd"] for t in losses) / len(losses), 4) if losses else 0,
        "max_drawdown":  round(max_dd, 4),
        "sharpe_ratio":  round(sharpe, 4),
        "exit_reasons":  exit_dist,
    }


# ===============================================================
# REPORT
# ===============================================================

def build_summary_text(full_report):
    lines = []
    sep   = "=" * 70

    lines += [
        sep,
        "  POLYMARKET MOMENTUM ARBITRAGE -- FULL ROADMAP ANALYSIS",
        f"  Generated : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"  Simulation: {SIMULATION_HOURS}h | Assets: {list(full_report.keys())}",
        sep,
    ]

    for asset, data in full_report.items():
        lines += [f"\n{'─'*70}", f"  {asset}", f"{'─'*70}"]

        # Phase 2 lag
        lag = data["phase2_lag"]
        lines.append("\n  PHASE 2 -- Lead/Lag Measurement")
        if lag["avg_lag_sec"] is not None:
            lines.append(f"  Avg lag      : {lag['avg_lag_sec']}s")
            lines.append(f"  Median lag   : {lag['median_lag_sec']}s")
            lines.append(f"  Distribution : {lag['distribution']}")
            lines.append(f"  Samples      : {lag['samples']}")
        else:
            lines.append("  Insufficient move events to measure lag.")

        # Phase 2 correlation
        lines.append("\n  Correlation Matrix (Binance 30s return -> PM prob shift)")
        lines.append(f"  {'Bucket':<18} {'Samples':>8} {'Avg dProb':>10} {'Correct%':>10}")
        for row in data["phase2_correlation"]:
            lines.append(
                f"  {row['return_bucket']:<18} "
                f"{row['sample_count']:>8} "
                f"{row['avg_prob_shift']*100:>9.2f}% "
                f"{row['pct_correct']*100:>9.1f}%"
            )

        # Phase 3
        lines.append("\n  PHASE 3 -- Threshold Tuning")
        lines.append(
            f"  {'Threshold':>10} | {'Signals':>8} | {'WinRate':>8} | "
            f"{'Normal':>8} | {'Drift':>8} | {'dProb':>7} | >=75%?"
        )
        lines.append(f"  {'-'*10}+{'-'*10}+{'-'*10}+{'-'*10}+{'-'*10}+{'-'*9}+{'-'*7}")
        for t in data["phase3_tuning"]:
            flag = "  v" if t["meets_75pct"] else ""
            lines.append(
                f"  {t['threshold_pct']:>9}% | "
                f"{t['total_signals']:>8} | "
                f"{t['win_rate']*100:>7.1f}% | "
                f"{t['normal_zone_wr']*100:>7.1f}% | "
                f"{t['drift_zone_wr']*100:>7.1f}% | "
                f"{t['avg_prob_jump']*100:>6.2f}% |{flag}"
            )
        best = next((t for t in data["phase3_tuning"] if t["meets_75pct"]), None)
        top  = data["phase3_tuning"][0] if data["phase3_tuning"] else None
        if best:
            lines.append(
                f"\n  OPTIMAL: {best['threshold_pct']}% -> "
                f"{best['win_rate']*100:.1f}% win rate ({best['total_signals']} signals)"
            )
        elif top:
            lines.append(
                f"\n  No threshold hits 75%. Best: "
                f"{top['threshold_pct']}% -> {top['win_rate']*100:.1f}%"
            )
        else:
            lines.append("\n  No signals detected.")

        # Phase 4
        p4 = data["phase4_backtest"]
        lines.append(f"\n  PHASE 4 -- Signal Backtest ({p4['optimal_threshold']}% threshold)")
        lines.append(f"  Total signals : {p4['total_signals']}")
        lines.append(f"  Signal WR     : {p4['signal_win_rate']*100:.1f}%")
        lines.append(f"  Normal zone   : {p4['normal_zone_signals']} signals | {p4['normal_zone_wr']*100:.1f}% WR")
        lines.append(f"  Drift zone    : {p4['drift_zone_signals']} signals | {p4['drift_zone_wr']*100:.1f}% WR")

        # Phase 5
        p5 = data["phase5_ratchet"]
        lines.append(f"\n  PHASE 5 -- Ratchet P&L (${POSITION_SIZE_USD}/trade)")
        if p5:
            lines.append(f"  Total trades  : {p5['total_trades']}")
            lines.append(f"  Win rate      : {p5['win_rate']*100:.1f}%")
            lines.append(f"  Total P&L     : ${p5['total_pnl_usd']:.2f}")
            lines.append(f"  Avg win       : ${p5['avg_win_usd']:.4f}")
            lines.append(f"  Avg loss      : ${p5['avg_loss_usd']:.4f}")
            lines.append(f"  Max drawdown  : ${p5['max_drawdown']:.4f}")
            lines.append(f"  Sharpe ratio  : {p5['sharpe_ratio']:.4f}")
            lines.append(f"  Exit reasons  : {p5['exit_reasons']}")
        else:
            lines.append("  No trades to report.")

    lines += [
        f"\n{sep}",
        "  RECOMMENDATIONS",
        "  - Use per-asset optimal threshold, not a global value.",
        "  - Normal zone only unless drift WR >= 80%.",
        "  - Lag < 30s = high-confidence entry window.",
        "  - Replace simulation with real data for production thresholds.",
        sep,
    ]
    return "\n".join(lines)


# ===============================================================
# MAIN
# ===============================================================

def main():
    random.seed(42)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    now_ts   = int(datetime.now(timezone.utc).timestamp())
    start_ts = now_ts - SIMULATION_HOURS * 3600
    duration = SIMULATION_HOURS * 3600

    market_windows = [
        (start_ts + i * MARKET_WINDOW_SEC,
         start_ts + (i + 1) * MARKET_WINDOW_SEC)
        for i in range(duration // MARKET_WINDOW_SEC)
    ]

    print("=" * 70)
    print("  Polymarket Momentum Arbitrage -- Full Roadmap Analysis")
    print(f"  Simulation : {SIMULATION_HOURS}h | "
          f"{len(market_windows)} market windows per asset")
    print(f"  Assets     : {list(ASSET_PARAMS.keys())}")
    print("=" * 70)

    full_report = {}
    all_trades  = []
    all_signals = []
    all_tuning  = {}

    for asset in ASSET_PARAMS:
        print(f"\n[{asset}]")

        # Phase 1
        print(f"  Phase 1 -- Generating {SIMULATION_HOURS}h data...")
        binance_prices = simulate_binance_prices(asset, start_ts, duration)
        lag_sec        = random.randint(*LAG_RANGE_SEC)
        pm_candles     = simulate_polymarket_candles(
            asset, binance_prices, market_windows, lag_sec
        )
        print(f"           {len(binance_prices):,} Binance ticks | "
              f"{len(pm_candles)} PM candles | lag={lag_sec}s")

        # Phase 2
        print("  Phase 2 -- Lead/lag + correlation matrix...")
        lag_stats   = measure_lead_lag(binance_prices, pm_candles)
        corr_matrix = build_correlation_matrix(binance_prices, pm_candles)
        print(f"           Avg lag={lag_stats.get('avg_lag_sec')}s | "
              f"Samples={lag_stats.get('samples')}")

        # Phase 3
        print("  Phase 3 -- Threshold tuning...")
        tuning = tune_thresholds(asset, binance_prices, pm_candles)
        all_tuning[asset] = tuning
        optimal = next(
            (t["threshold_pct"] for t in tuning if t["meets_75pct"]),
            tuning[0]["threshold_pct"] if tuning else 0.20
        )
        best_wr = tuning[0]["win_rate"] * 100 if tuning else 0
        print(f"           Optimal={optimal}% | Best WR={best_wr:.1f}%")

        # Phase 4
        print(f"  Phase 4 -- Signal backtest at {optimal}%...")
        signals = backtest_signals(asset, binance_prices, pm_candles, optimal)
        all_signals.extend(signals)
        total_s   = len(signals)
        correct_s = sum(1 for s in signals if s["correct"])
        sig_wr    = correct_s / total_s if total_s > 0 else 0
        normal_s  = [s for s in signals if s["zone"] == "normal"]
        drift_s   = [s for s in signals if s["zone"] == "drift"]
        nwr = sum(1 for s in normal_s if s["correct"]) / len(normal_s) if normal_s else 0
        dwr = sum(1 for s in drift_s  if s["correct"]) / len(drift_s)  if drift_s  else 0
        print(f"           {total_s} signals | WR={sig_wr*100:.1f}% | "
              f"Normal={nwr*100:.1f}% | Drift={dwr*100:.1f}%")

        # Phase 5
        print("  Phase 5 -- Ratchet P&L simulation...")
        trades = [simulate_ratchet(sig, pm_candles) for sig in signals]
        all_trades.extend(trades)
        agg = aggregate_trades(trades)
        print(f"           {agg.get('total_trades', 0)} trades | "
              f"WR={agg.get('win_rate', 0)*100:.1f}% | "
              f"P&L=${agg.get('total_pnl_usd', 0):.2f} | "
              f"Sharpe={agg.get('sharpe_ratio', 0):.4f}")

        full_report[asset] = {
            "simulated_lag_sec":  lag_sec,
            "phase2_lag":         lag_stats,
            "phase2_correlation": corr_matrix,
            "phase3_tuning":      tuning,
            "phase4_backtest": {
                "optimal_threshold":   optimal,
                "total_signals":       total_s,
                "signal_win_rate":     round(sig_wr, 4),
                "normal_zone_signals": len(normal_s),
                "normal_zone_wr":      round(nwr, 4),
                "drift_zone_signals":  len(drift_s),
                "drift_zone_wr":       round(dwr, 4),
            },
            "phase5_ratchet": agg,
        }

    # Save outputs
    print(f"\n{'='*70}")
    print("  Saving outputs...")

    rpt_path = os.path.join(OUTPUT_DIR, "full_analysis_report.json")
    with open(rpt_path, "w") as f:
        json.dump(full_report, f, indent=2)
    print(f"  Saved -> {rpt_path}")

    trades_path = os.path.join(OUTPUT_DIR, "trades.csv")
    if all_trades:
        with open(trades_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_trades[0].keys())
            writer.writeheader()
            writer.writerows(all_trades)
    print(f"  Saved -> {trades_path}")

    matrix_path = os.path.join(OUTPUT_DIR, "threshold_matrix.csv")
    matrix_rows = []
    for asset, tuning in all_tuning.items():
        for t in tuning:
            matrix_rows.append({"asset": asset, **t})
    if matrix_rows:
        with open(matrix_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=matrix_rows[0].keys())
            writer.writeheader()
            writer.writerows(matrix_rows)
    print(f"  Saved -> {matrix_path}")

    summary      = build_summary_text(full_report)
    summary_path = os.path.join(OUTPUT_DIR, "summary.txt")
    with open(summary_path, "w") as f:
        f.write(summary)
    print(f"  Saved -> {summary_path}")

    print()
    print(summary)


if __name__ == "__main__":
    main()

