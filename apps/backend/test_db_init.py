import os
import sys

# Mock environment
os.environ["CB_DB_URL"] = "sqlite:///:memory:"

sys.path.insert(0, "/home/shawnji/Documents/projects/CircuitBreaker/apps/backend/src")
from app.db.session import Base, engine

try:
    Base.metadata.create_all(engine)
    print("create_all succeeded")
except Exception:
    import traceback

    traceback.print_exc()
