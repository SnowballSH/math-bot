# migrate_leaderboard.py
import os
import json
import sqlite3

# adjust paths as needed
data_dir = os.path.join(os.path.dirname(__file__))
json_bak = os.path.join(data_dir, "leaderboard.json")
db_path = os.path.join(data_dir, "math500.db")

# Load old JSON backup
try:
    with open(json_bak, "r", encoding="utf-8") as f:
        old_lb = json.load(f)
except (OSError, json.JSONDecodeError) as e:
    print(f"Failed to load leaderboard backup: {e}")
    exit(1)

# Connect to SQLite database
try:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
except sqlite3.Error as e:
    print(f"Database connection failed: {e}")
    exit(1)

# Ensure the new leaderboard table exists
try:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leaderboard (
            user_id   INTEGER PRIMARY KEY,
            solved    INTEGER DEFAULT 0,
            attempted INTEGER DEFAULT 0
        );
        """
    )
    con.commit()
except sqlite3.Error as e:
    print(f"Failed to ensure leaderboard table exists: {e}")
    con.close()
    exit(1)

# Migrate each user's stats into the new leaderboard schema
migrated = 0
for uid_str, stats in old_lb.items():
    try:
        uid = int(uid_str)
    except ValueError:
        continue
    solved = int(stats.get("solved", 0))
    attempted = int(stats.get("attempted", 0))
    try:
        cur.execute(
            """
            INSERT INTO leaderboard(user_id, solved, attempted)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                solved    = excluded.solved,
                attempted = excluded.attempted
            """,
            (uid, solved, attempted),
        )
        migrated += 1
    except sqlite3.Error as e:
        print(f"Failed to insert stats for user {uid}: {e}")

# Commit and cleanup
try:
    con.commit()
    print(f"Migrated {migrated} users into {db_path}")
finally:
    con.close()
