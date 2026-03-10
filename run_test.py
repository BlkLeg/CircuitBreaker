import os
# Local/test DB URL only; do not use in production.
os.environ["CB_TEST_DB_URL"] = "postgresql://breaker:breaker@localhost:5432/circuitbreaker_test"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal

if __name__ == "__main__":
    pass
