import re
with open("analysis_queries.sql", "r") as f:
    content = f.read()

blocks = re.split(r'-- ═+.*?\n', content)
queries = []
for block in blocks:
    if not block.strip() or 'POLYMARKET' in block:
        continue
    lines = block.strip().split('\n')
    title = ""
    is_query_15 = False
    for line in lines:
        line = line.strip()
        if line.startswith('-- ') and title == "" and not line.startswith('-- Run this') and not line.startswith('-- Derived'):
            possible_title = line.replace('-- ', '').strip()
            if possible_title and possible_title[0].isdigit():
                title = possible_title
        if title.startswith("15."):
            is_query_15 = True
            
    sql_lines = []
    for line in lines:
        line_s = line.strip()
        if not line_s.startswith('--'):
            if is_query_15:
                if line_s.startswith('/*') or line_s.startswith('*/'):
                    continue
            sql_lines.append(line)
            
    sql_combined = '\n'.join(sql_lines).strip()
    statements = [s.strip() for s in sql_combined.split(';') if s.strip()]
    for idx, sql in enumerate(statements):
        if title and sql:
            queries.append({'title': title, 'sql': sql})

print(len(queries))
for q in queries:
    print(q['title'])
