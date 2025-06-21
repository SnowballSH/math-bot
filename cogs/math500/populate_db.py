import os, json
import sqlite3
from sympy.parsing.latex import parse_latex
import re

DATA_DIR = os.path.dirname(__file__)
DB_PATH  = os.path.join(DATA_DIR, "math500.db")
JSONL    = ["train.jsonl", "test.jsonl"]

def clean_ans(ans: str) -> str:
    cleaned = re.sub(r"\\boxed\s*\{([^}]*)\}", r"\1", ans)
    return cleaned.replace("$$","$")

# Create DB & table
con = sqlite3.connect(DB_PATH)
con.execute("""
CREATE TABLE IF NOT EXISTS problems (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  problem     TEXT,
  solution    TEXT,
  answer_tex  TEXT,
  subject     TEXT,
  level       INTEGER,
  unique_id   TEXT
);
""")

# Load JSONL into DB
for fname in JSONL:
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path): continue
    with open(path) as f:
        for line in f:
            ex = json.loads(line)
            ans = clean_ans(ex.get("answer",""))
            try:
                expr = parse_latex(ans)
                if expr.free_symbols: continue
            except:
                continue
            con.execute(
              "INSERT INTO problems (problem,solution,answer_tex,subject,level,unique_id) VALUES (?,?,?,?,?,?)",
              (ex["problem"], ex["solution"], ans,
               ex.get("subject",""), ex.get("level",0), ex.get("unique_id",""))
            )
con.commit()
con.close()
print("🗄️  Database created at", DB_PATH)
