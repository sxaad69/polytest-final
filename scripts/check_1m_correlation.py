import sqlite3
import requests
import json
from datetime import datetime, timezone

DB_PATH = "data/bot_sniper_paper.db"
CACHE_FILE = "logs/slug_truth_cache.txt"

def load_cache():
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

def get_binance_1m_candle(symbol, end_time_ms):
    """Fetch the 1m candle exactly BEFORE the given timestamp."""
    try:
        url = "https://api.binance.com/api/v3/klines"
        # We want the 1m candle that closed exactly at `end_time_ms`.
        # So we ask for 2 candles ending at end_time_ms.
        params = {
            "symbol": symbol.upper() + "USDT",
            "interval": "1m",
            "endTime": end_time_ms,
            "limit": 2
        }
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()
        if not data or len(data) == 0:
            return None
        
        # The last candle in the result is the one that ends at or just before end_time_ms
        # Binance kline format: [Open time, Open, High, Low, Close, Volume, Close time, ...]
        target_candle = data[-1]
        
        # If the target candle's open time is exactly at the window start, 
        # we actually want the candle BEFORE it.
        if target_candle[0] == end_time_ms:
            if len(data) > 1:
                target_candle = data[-2]
            else:
                return None
                
        open_price = float(target_candle[1])
        close_price = float(target_candle[4])
        close_time = target_candle[6]
        
        trend = "UP" if close_price > open_price else "DOWN"
        return {
            "open": open_price,
            "close": close_price,
            "trend": trend,
            "close_time": datetime.fromtimestamp(close_time/1000, tz=timezone.utc)
        }
    except Exception as e:
        print(f"Binance error for {symbol}: {e}")
        return None

def main():
    cache = load_cache()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Get the 5 most recent trades that have a resolved truth in our cache
    cur.execute("""
        SELECT id, asset, direction, slug, ts_entry 
        FROM trades 
        ORDER BY ts_entry DESC 
        LIMIT 50
    """)
    recent_trades = cur.fetchall()
    conn.close()
    
    found = 0
    print("="*70)
    print("1-MINUTE PRE-WINDOW CORRELATION AUDIT (LAST 5 TRADES)")
    print("="*70)
    
    for t in recent_trades:
        slug = t["slug"]
        if not slug or slug not in cache:
            continue
            
        winner = cache[slug]
        if winner not in ("long", "short"):
            continue
            
        # Figure out the exact 5-minute window start time.
        # Polymarket 5m slugs usually end with the expiration epoch.
        # e.g. btc-updown-5m-1780272000
        try:
            expire_epoch = int(slug.split("-")[-1])
            start_epoch = expire_epoch - 300  # 5 minutes before expiration
        except Exception:
            continue
            
        start_time_ms = start_epoch * 1000
        start_dt = datetime.fromtimestamp(start_epoch, tz=timezone.utc)
        
        candle = get_binance_1m_candle(t["asset"], start_time_ms)
        if not candle:
            continue
            
        pm_outcome = "UP" if winner == "long" else "DOWN"
        matched = "✅ MATCH" if candle["trend"] == pm_outcome else "❌ NO MATCH"
        
        print(f"Trade Asset: {t['asset'].upper()}")
        print(f"5m Window  : {start_dt.strftime('%H:%M:%S UTC')} to {datetime.fromtimestamp(expire_epoch, tz=timezone.utc).strftime('%H:%M:%S UTC')}")
        print(f"1m Candle  : Closed at {candle['close_time'].strftime('%H:%M:%S UTC')} | Open: {candle['open']} -> Close: {candle['close']}")
        print(f"1m Trend   : {candle['trend']}")
        print(f"5m Outcome : {pm_outcome} (Polymarket Truth)")
        print(f"Correlation: {matched}")
        print("-" * 70)
        
        found += 1
        if found >= 5:
            break

if __name__ == "__main__":
    main()
