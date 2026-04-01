import sqlite3
import pandas as pd
from tabulate import tabulate
import re
import os

DB_A = "data/bot_a_paper.db"
DB_B = "data/bot_b_paper.db"
DB_G = "data/bot_g_paper.db"
SQL_FILE = "analysis_queries.sql"

def get_queries():
    with open(SQL_FILE, "r", encoding='utf-8') as f:
        lines = [line.strip() for line in f.readlines()]
        
    queries = []
    current_title = ""
    is_query_15 = False
    sql_lines = []
    
    for line in lines:
        # Title lines look like: "-- 1. OVERALL SUMMARY"
        if line.startswith('-- ') and len(line) > 3 and line[3].isdigit() and not line.startswith('-- Run this'):
            # Save previous query if exists
            if current_title and sql_lines:
                sql_combined = '\n'.join(sql_lines).strip()
                statements = [s.strip() for s in sql_combined.split(';') if s.strip()]
                for idx, sql in enumerate(statements):
                    if sql:
                        display_title = current_title if len(statements) == 1 else f"{current_title} (Part {idx + 1})"
                        queries.append({'title': display_title, 'sql': sql + ';', 'is_query_15': is_query_15})
                        
            current_title = line.replace('-- ', '').strip()
            is_query_15 = current_title.startswith("15.")
            sql_lines = []
            continue
            
        if current_title:
            if not line.startswith('--'):
                if is_query_15 and (line.startswith('/*') or line.startswith('*/') or line == '*/' or line == '/*'):
                    continue
                sql_lines.append(line)
                
    # Save the last query
    if current_title and sql_lines:
        sql_combined = '\n'.join(sql_lines).strip()
        statements = [s.strip() for s in sql_combined.split(';') if s.strip()]
        for idx, sql in enumerate(statements):
            if sql:
                display_title = current_title if len(statements) == 1 else f"{current_title} (Part {idx + 1})"
                queries.append({'title': display_title, 'sql': sql + ';', 'is_query_15': is_query_15})
                
    return queries

def run_query_on_db(db_path, sql):
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(sql, conn)
        conn.close()
        return df
    except Exception as e:
        print(f"Error running query on {db_path}: {e}")
        return pd.DataFrame()

def run_query_15(base_db, attached_dbs, sql):
    if not os.path.exists(base_db):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(base_db)
        cursor = conn.cursor()
        for alias, path in attached_dbs.items():
            if os.path.exists(path):
                cursor.execute(f"ATTACH DATABASE '{path}' AS {alias};")
        
        df = pd.read_sql_query(sql, conn)
        conn.close()
        return df
    except Exception as e:
        print(f"Error running query 15 on {base_db}: {e}")
        return pd.DataFrame()

def display_side_by_side(dfs, titles, spacing=4):
    """Prints multiple dataframes side-by-side using tabulate"""
    if all(df.empty for df in dfs):
        print("No data available.")
        return
        
    # Convert dataframes to string tables
    str_tables = []
    headers = []
    for i, df in enumerate(dfs):
        if not df.empty:
            str_table = tabulate(df, headers='keys', tablefmt='psql', showindex=False)
            str_tables.append(str_table.split('\n'))
            headers.append(titles[i])
        else:
            str_tables.append(["No Data"])
            headers.append(titles[i])
            
    # Find max lines
    max_lines = max(len(t) for t in str_tables)
    
    # Pad shorter tables with empty strings
    for i in range(len(str_tables)):
        if len(str_tables[i]) < max_lines:
            width = len(str_tables[i][0]) if len(str_tables[i]) > 0 else 10
            str_tables[i].extend([' ' * width] * (max_lines - len(str_tables[i])))
            
    # Combine side by side
    separator = ' ' * spacing
    
    # Print headers side by side
    header_row = ""
    for i in range(len(str_tables)):
        width = len(str_tables[i][0]) if len(str_tables[i]) > 0 else 10
        # Center title over the table width
        header_row += headers[i].center(width) + separator
    print("\n" + header_row)
    
    # Print tables side by side
    for i in range(max_lines):
        row = ""
        for j in range(len(str_tables)):
            table_row = str_tables[j][i]
            # Ensure table row takes up right space
            width = len(str_tables[j][0]) if len(str_tables[j]) > 0 else 10
            row += f"{table_row:<{width}}" + separator
        print(row)
    print("\n")


def main():
    print("Extracting queries...", flush=True)
    queries = get_queries()
    print(f"Parsed {len(queries)} queries.", flush=True)
    
    for q in queries:
        if q['is_query_15']:
            continue
            
        print("="*100, flush=True)
        print(f" {q['title']}", flush=True)
        print("="*100 + "\n", flush=True)
        
        print(f"Running A, B, G for: {q['title']}", flush=True)
        df_a = run_query_on_db(DB_A, q['sql'])
        df_b = run_query_on_db(DB_B, q['sql'])
        df_g = run_query_on_db(DB_G, q['sql'])
        
        display_side_by_side([df_a, df_b, df_g], ["Bot A", "Bot B", "Bot G"])

    # Finally run Query 15
    print("="*100, flush=True)
    print(" 15. COMBINED BOT A vs BOT B vs BOT G COMPARISON", flush=True)
    print("="*100 + "\n", flush=True)
    print("Running query 15...", flush=True)
    sql_15 = """
    SELECT
      'Bot A' AS bot,
      COUNT(*) AS trades,
      ROUND(AVG(CASE WHEN outcome='win' THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate,
      ROUND(SUM(pnl_usdc),4) AS total_pnl,
      ROUND(AVG(pnl_usdc),5) AS expectancy,
      ROUND(100.0+SUM(pnl_usdc),2) AS bankroll
    FROM main.trades WHERE resolved=1
    UNION ALL
    SELECT
      'Bot B',
      COUNT(*),
      ROUND(AVG(CASE WHEN outcome='win' THEN 1.0 ELSE 0.0 END)*100,1),
      ROUND(SUM(pnl_usdc),4),
      ROUND(AVG(pnl_usdc),5),
      ROUND(100.0+SUM(pnl_usdc),2)
    FROM b.trades WHERE resolved=1
    UNION ALL
    SELECT
      'Bot G',
      COUNT(*),
      ROUND(AVG(CASE WHEN outcome='win' THEN 1.0 ELSE 0.0 END)*100,1),
      ROUND(SUM(pnl_usdc),4),
      ROUND(AVG(pnl_usdc),5),
      ROUND(100.0+SUM(pnl_usdc),2)
    FROM g.trades WHERE resolved=1;
    """
    df = run_query_15(DB_A, {'b': DB_B, 'g': DB_G}, sql_15)
    print(tabulate(df, headers='keys', tablefmt='psql', showindex=False))
    print("\n", flush=True)

if __name__ == "__main__":
    main()
