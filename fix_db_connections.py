"""
Quick fix script to replace all get_custom_db_connection references
with the new connection pool functions
"""

import os
import re

# Files to fix based on grep results
files_to_fix = [
    "backend/agents/__init__.py",
    "backend/agents/approval_routing.py",
    "backend/routes/chat.py",
    "backend/routes/agentic.py"
]

for file_path in files_to_fix:
    full_path = f"c:/Users/HP/OneDrive/Desktop/bot/{file_path}"
    
    if not os.path.exists(full_path):
        print(f"Skipping {file_path} (not found)")
        continue
    
    print(f"Processing {file_path}...")
    
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace hybrid_query.get_custom_db_connection() with get_db_connection()
    original = content
    content = content.replace('hybrid_query.get_custom_db_connection()', 'get_db_connection()')
    
    # Replace conn.close() with return_db_connection(conn) - be careful with this
    # Only replace in contexts where we're closing after database operations
    content = re.sub(
        r'(\s+)cursor\.close\(\)\s+conn\.close\(\)',
        r'\1cursor.close()\n\1return_db_connection(conn)',
        content
    )
    
    # Alternative: just conn.close() alone
    # This is trickier, only do it if preceded by cursor operations
    lines = content.split('\n')
    new_lines = []
    for i, line in enumerate(lines):
        if 'conn.close()' in line and 'return_db_connection' not in line:
            # Replace with return_db_connection
            new_line = line.replace('conn.close()', 'return_db_connection(conn)')
            new_lines.append(new_line)
        else:
            new_lines.append(line)
    content = '\n'.join(new_lines)
    
    if content != original:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  ✅ Updated {file_path}")
    else:
        print(f"  ℹ️  No changes needed for {file_path}")

print("\n✅ All files processed!")
