import sqlite3
import requests
import json
import time
from datetime import datetime, timezone
from collections import defaultdict

DB_PATH = "data/bot_sniper_paper.db"
CACHE_FILE = "logs/slug_truth_cache.txt"

def load_truth_cache():
    cache = {}
    try:
        with open(CACHE_FILE, "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) == 2:
                    cache[parts[0]] = parts[1]
    except FileNotFoundError:
        pass
    return cache

def fetch_binance_klines(symbol, start_ms, end_ms):
    """Fetch 1m klines for a symbol between start_ms and end_ms."""
    print(f"Fetching historical 1m data for {symbol}...")
    url = "https://api.binance.com/api/v3/klines"
    klines = {}
    current_start = start_ms
    
    while current_start < end_ms:
        params = {
            "symbol": symbol.upper() + "USDT",
            "interval": "1m",
            "startTime": current_start,
            "endTime": end_ms,
            "limit": 1000
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if not data or not isinstance(data, list) or len(data) == 0:
                break
                
            for k in data:
                open_time = k[0]
                open_price = float(k[1])
                close_price = float(k[4])
                klines[open_time] = "UP" if close_price > open_price else "DOWN"
            
            # Next batch starts after the last fetched candle
            current_start = data[-1][0] + 60000 
            time.sleep(0.1) # Safe rate limiting
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            break
            
    print(f"  -> Fetched {len(klines)} candles for {symbol}")
    return klines

def main():
    truth_cache = load_truth_cache()
    print(f"Loaded {len(truth_cache)} resolved trades from cache.")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Get all trades with slugs
    cur.execute("SELECT asset, slug FROM trades WHERE slug IS NOT NULL")
    trades = [dict(r) for r in cur.fetchall()]
    conn.close()
    
    if not trades:
        print("No trades found.")
        return
        
    # 1. Determine the exact time range we need
    earliest_epoch = float("inf")
    latest_epoch = 0
    unique_assets = set()
    
    valid_trades = []
    
    for t in trades:
        slug = t["slug"]
        asset = t["asset"].upper()
        if slug not in truth_cache:
            continue
            
        winner = truth_cache[slug]
        if winner not in ("long", "short"):
            continue
            
        try:
            expire_epoch = int(slug.split("-")[-1])
            start_epoch = expire_epoch - 300
        except:
            continue
            
        earliest_epoch = min(earliest_epoch, start_epoch)
        latest_epoch = max(latest_epoch, start_epoch)
        unique_assets.add(asset)
        
        valid_trades.append({
            "asset": asset,
            "start_epoch": start_epoch,
            "pm_outcome": "UP" if winner == "long" else "DOWN"
        })

    print(f"Found {len(valid_trades)} valid trades to analyze.")
    
    # We need candles from 1 minute BEFORE the earliest trade
    start_ms = (earliest_epoch - 3600) * 1000
    end_ms = (latest_epoch + 3600) * 1000
    
    # 2. Bulk download all 1m candles for the needed assets
    all_klines = {}
    for asset in unique_assets:
        all_klines[asset] = fetch_binance_klines(asset, start_ms, end_ms)
        
    # 3. Analyze correlation
    print("\nAnalyzing correlations...")
    matches = 0
    total = 0
    
    # Breakdown by asset
    asset_stats = defaultdict(lambda: {"matches": 0, "total": 0})
    
    for t in valid_trades:
        asset = t["asset"]
        start_epoch = t["start_epoch"]
        pm_outcome = t["pm_outcome"]
        
        # The 1m candle we want OPENED 60 seconds before the 5m window started
        prior_candle_open_ms = (start_epoch - 60) * 1000
        
        candle_trend = all_klines.get(asset, {}).get(prior_candle_open_ms)
        if not candle_trend:
            continue
            
        total += 1
        asset_stats[asset]["total"] += 1
        
        if candle_trend == pm_outcome:
            matches += 1
            asset_stats[asset]["matches"] += 1

    if total == 0:
        print("No intersecting data found.")
        return
        
    overall_win_rate = (matches / total) * 100
    
    print("="*60)
    print("BINANCE 1M PRE-CANDLE CORRELATION (FULL DATABASE AUDIT)")
    print("="*60)
    print(f"Total Trades Analyzed : {total}")
    print(f"Total Matches         : {matches}")
    print(f"Total Misses          : {total - matches}")
    print(f"OVERALL CORRELATION   : {overall_win_rate:.1f}%")
    print("-" * 60)
    print("Breakdown by Asset:")
    
    for asset, stats in sorted(asset_stats.items(), key=lambda x: x[1]["total"], reverse=True):
        t_count = stats["total"]
        if t_count == 0: continue
        m_count = stats["matches"]
        pct = (m_count / t_count) * 100
        print(f"  {asset:<5}: {m_count:>5} / {t_count:<5} ({pct:.1f}%)")
    print("="*60)

if __name__ == "__main__":
    main()
