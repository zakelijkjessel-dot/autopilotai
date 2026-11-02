"""Gedeelde testinstellingen: eigen SQLite-database per testrun, geen echte externe diensten."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="autogarage_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["TWILIO_ACCOUNT_SID"] = ""
os.environ["TWILIO_AUTH_TOKEN"] = ""
os.environ["ENABLE_DEV_ROUTES"] = "false"
os.environ["ENABLE_WEB_CHAT"] = "false"
os.environ["ADMIN_PASSWORD"] = ""

import pytest  # noqa: E402

import models  # noqa: E402,F401
from database import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture()
def db():
    """Schone database per test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
