import sys, os
sys.path.insert(0, ".")
from creative_intelligence.config import DB_PATH, DATA_DIR, REPO_ROOT
print(f"CWD: {os.getcwd()}")
print(f"REPO_ROOT: {REPO_ROOT}")
print(f"DATA_DIR: {DATA_DIR}")
print(f"DB_PATH: {DB_PATH}")
print(f"DB exists: {DB_PATH.exists()}")
print(f"DB abs: {DB_PATH.resolve()}")
