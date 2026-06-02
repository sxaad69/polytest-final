"""
4-Minute Price Audit — From Bot Position Logs
===============================================
Reads the open_positions.log to extract minute-by-minute price
snapshots for each confirmed LOSS trade (resolved SHORT).
No external API needed — uses the bot's own heartbeat data.
"""
import sqlite3
import re
import os
from datetime import datetime, timezone

DB_PATH  = "data/bot_sniper_paper.db"
LOG_FILE = "logs/open_positions.log"
OUTPUT   = "logs/4min_audit.txt"

# Parse: [HEARTBEAT] ... Trade #ID ... | Current: PRICE | ... | Secs to end: SECS
HB_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[HEARTBEAT\].*?Trade #(\d+).*?"
    r"Entry: ([\d.]+).*?Current: ([\d.]+).*?Secs to end: ([\d.]+)"
)

def load_heartbeats():
    """Return dict: trade_id -> list of {ts, entry, current, secs_to_end}"""
    data = {}
    if not os.path.exists(LOG_FILE):
        print(f"Log file not found: {LOG_FILE}")
        return data
    with open(LOG_FILE, "r") as f:
        for line in f:
            m = HB_PATTERN.search(line)
            if not m:
                continue
            ts_str      = m.group(1)
            trade_id    = int(m.group(2))
            entry       = float(m.group(3))
            current     = float(m.group(4))
            secs_to_end = float(m.group(5))
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            data.setdefault(trade_id, []).append({
                "ts":          ts,
                "entry":       entry,
                "current":     current,
                "secs_to_end": secs_to_end,
            })
    return data

def price_at_secs_remaining(heartbeats, target_secs, tolerance=35):
    """Find the heartbeat closest to a given 'secs_to_end' value."""
    best = None
    min_diff = float("inf")
    for hb in heartbeats:
        diff = abs(hb["secs_to_end"] - target_secs)
        if diff < min_diff:
            min_diff = diff
            best = hb
    if best and min_diff <= tolerance:
        return best["current"]
    return None

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Confirmed losses: truth_settled at 0.0 (resolved SHORT, held as LONG)
    cur.execute("""
        SELECT id, asset, direction, entry_odds, stake_usdc, slug
        FROM trades
        WHERE ts_entry >= '2026-05-09T15:22:00'
        AND   exit_reason = 'truth_settled'
        AND   exit_odds   = 0.0
        AND   direction   = 'long'
        ORDER BY id
    """)
    losses = cur.fetchall()
    conn.close()

    if not losses:
        print("No confirmed loss trades found.")
        return

    print(f"Loading heartbeats from {LOG_FILE}...")
    hb_data = load_heartbeats()
    print(f"Loaded heartbeats for {len(hb_data)} trades.\n")

    lines = [
        "4-MINUTE PRICE AUDIT (from Bot Logs) — Confirmed SHORT Resolutions",
        "="*110,
        f"{'ID':<6} {'Asset':<5} {'Entry':<7} | {'@4m':>6} {'@3m':>6} {'@2m':>6} {'@1m':>6} {'@0m':>6} | {'4m vs Entry':>12} | {'M4<Entry?':>10} | Slug",
        "-"*110,
    ]

    would_save        = 0
    total_analysed    = 0
    potential_savings = 0.0
    no_data_count     = 0

    # Window = 300s. Secs to end: 240=@1min, 180=@2min, 120=@3min, 60=@4min, 0=@5min
    # Minutes into window:  1min=secs_to_end~240, 2min~180, 3min~120, 4min~60, final~0
    for t in losses:
        tid = t["id"]
        hbs = hb_data.get(tid)

        if not hbs:
            lines.append(f"{tid:<6} {t['asset']:<5} {t['entry_odds']:<7.3f} | {'NO LOG DATA — trade not tracked in heartbeat log':}")
            no_data_count += 1
            continue

        entry = t["entry_odds"]
        stake = t["stake_usdc"]
        shares = stake / entry

        p_at_4m = price_at_secs_remaining(hbs, 60)   # 4 min into = 60s left
        p_at_3m = price_at_secs_remaining(hbs, 120)  # 3 min into = 120s left
        p_at_2m = price_at_secs_remaining(hbs, 180)  # 2 min into = 180s left
        p_at_1m = price_at_secs_remaining(hbs, 240)  # 1 min into = 240s left
        p_at_0m = price_at_secs_remaining(hbs, 10)   # final ~0s left

        total_analysed += 1

        m4_vs_entry = (p_at_4m - entry) if p_at_4m is not None else None

        if p_at_4m is not None and p_at_4m < entry:
            m4_flag = "YES ✅"
            would_save += 1
            # Money saved vs full wipeout at 0.0
            exit_val_at_m4 = p_at_4m * shares
            loss_at_m4     = exit_val_at_m4 - stake
            loss_at_zero   = -stake
            saved = loss_at_m4 - loss_at_zero
            potential_savings += saved
        elif p_at_4m is None:
            m4_flag = "NO DATA"
        else:
            m4_flag = "NO ❌ (above entry)"

        def fmt(v):
            return f"{v:.3f}" if v is not None else " N/A "

        m4_str = f"{m4_vs_entry:+.3f}" if m4_vs_entry is not None else "  N/A"
        lines.append(
            f"{tid:<6} {t['asset']:<5} {entry:<7.3f} | "
            f"{fmt(p_at_4m):>6} {fmt(p_at_3m):>6} {fmt(p_at_2m):>6} {fmt(p_at_1m):>6} {fmt(p_at_0m):>6} | "
            f"{m4_str:>12} | {m4_flag:<10} | {t['slug']}"
        )

    lines += [
        "="*110,
        f"Trades analysed        : {total_analysed}",
        f"No log data            : {no_data_count}",
        f"M4 below entry (save?) : {would_save} / {total_analysed}",
        f"Potential $ saved      : +${potential_savings:.2f} (vs full -$stake wipeout)",
    ]

    report = "\n".join(lines)
    print(report)

    os.makedirs("logs", exist_ok=True)
    with open(OUTPUT, "w") as f:
        f.write(report)
    print(f"\nSaved to {OUTPUT}")

if __name__ == "__main__":
    main()
