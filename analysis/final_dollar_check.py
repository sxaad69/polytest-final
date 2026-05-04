import pandas as pd
import numpy as np

df = pd.read_csv('../logs/market_tape_2026-05-03.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])
df['window_start_ts'] = df['market_slug'].str.extract(r'(\d+)$').astype(float)
df['window_start_dt'] = pd.to_datetime(df['window_start_ts'], unit='s')
df['window_end_dt'] = df['window_start_dt'] + pd.Timedelta(minutes=5)
df['rem'] = (df['window_end_dt'] - df['timestamp']).dt.total_seconds()

# Partial Day (up to 16:36 UTC)
partial_df = df[df['timestamp'] <= '2026-05-03 16:36:12']
# Full Day
full_df = df

def get_pnl(data):
    picker = data[(data['rem'] >= 240) & (data['rem'] <= 300) & (data['poly_mid'] >= 0.33) & (data['poly_mid'] <= 0.54)]
    entries = picker.sort_values('timestamp').groupby('market_slug').first()
    outcomes = data.groupby('market_slug')['poly_mid'].last()
    grouped = data.groupby('market_slug')
    
    inv = 3.00; sl = 0.05; tp = 0.32
    total_pnl = 0
    for slug, entry in entries.iterrows():
        ep = entry['poly_mid']; et = entry['timestamp']; sh = inv/ep; sl_p = ep-sl; tp_p = ep+tp
        m_data = grouped.get_group(slug)
        m_future = m_data[m_data['timestamp'] > et].sort_values('timestamp')
        
        pnl = 0; met = False
        for _, t in m_future.iterrows():
            if t['poly_mid'] <= sl_p: pnl = (sh * sl_p) - inv; met = True; break
            if t['poly_mid'] >= tp_p: pnl = (sh * tp_p) - inv; met = True; break
        if not met: pnl = (sh * 1.0 - inv) if outcomes.get(slug, 0) > 0.5 else -inv
        total_pnl += pnl
    return len(entries), total_pnl

p_count, p_pnl = get_pnl(partial_df)
f_count, f_pnl = get_pnl(full_df)

print(f"PARTIAL DAY (00:00-16:36): Trades: {p_count} | Profit: ${p_pnl:.2f} | ROI: {(p_pnl/(p_count*3))*100:.2f}%")
print(f"FULL DAY (00:00-23:59):    Trades: {f_count} | Profit: ${f_pnl:.2f} | ROI: {(f_pnl/(f_count*3))*100:.2f}%")
print(f"EVENING SESSION GROWTH:    Trades: {f_count - p_count} | Profit: ${f_pnl - p_pnl:.2f}")
