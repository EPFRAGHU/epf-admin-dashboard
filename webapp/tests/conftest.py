import os
import sys
from pathlib import Path

# MUST set test DATABASE_URL before importing webapp modules
TEST_DB_PATH = Path(__file__).resolve().parent.parent.parent / "test_epf.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient
from webapp.database import Base, engine, SessionLocal, User, Establishment, Payment, ActivityLog
from webapp.auth import hash_password
from webapp.app import app


class AuthClient:
    """Authenticated client wrapper around TestClient with default JWT Authorization headers."""
    def __init__(self, test_client: TestClient, token: str, user_dict: dict):
        self.client = test_client
        self.token = token
        self.user = user_dict
        self.headers = {"Authorization": f"Bearer {token}"}
        self.active_establishment_id = None

    def set_establishment(self, est_id: int):
        self.active_establishment_id = est_id
        self.headers["X-Establishment-Id"] = str(est_id)

    def get(self, url: str, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return self.client.get(url, headers=headers, **kwargs)

    def post(self, url: str, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return self.client.post(url, headers=headers, **kwargs)

    def put(self, url: str, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return self.client.put(url, headers=headers, **kwargs)

    def delete(self, url: str, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return self.client.delete(url, headers=headers, **kwargs)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create test database schema before tests and remove SQLite file after all tests."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink()
        except Exception:
            pass


@pytest.fixture
def test_db():
    """Provide a clean transactional database session per test function."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    """Unauthenticated FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture
def superadmin_session(client, test_db) -> AuthClient:
    """Create a superadmin user in the database and return an authenticated TestClient."""
    email = "superadmin.test@epfdashboard.com"
    password = "SuperadminPass@123"

    user = test_db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            name="Test Superadmin",
            email=email,
            mobile="9999900000",
            password_hash=hash_password(password),
            role="superadmin",
            is_active=True
        )
        test_db.add(user)
        test_db.commit()
        test_db.refresh(user)

    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Superadmin login failed: {res.text}"
    token = res.json()["token"]
    user_dict = res.json()["user"]

    return AuthClient(client, token, user_dict)


@pytest.fixture
def consultant_a(client, test_db) -> AuthClient:
    """Create Consultant A in the database and return an authenticated TestClient."""
    email = "consultant_a@testepf.com"
    password = "PasswordA@123"

    user = test_db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            serial_no=101,
            name="Consultant Alpha",
            email=email,
            mobile="9876500001",
            password_hash=hash_password(password),
            role="consultant",
            is_active=True
        )
        test_db.add(user)
        test_db.commit()
        test_db.refresh(user)

    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Consultant A login failed: {res.text}"
    token = res.json()["token"]
    user_dict = res.json()["user"]

    return AuthClient(client, token, user_dict)


@pytest.fixture
def consultant_b(client, test_db) -> AuthClient:
    """Create Consultant B in the database and return an authenticated TestClient."""
    email = "consultant_b@testepf.com"
    password = "PasswordB@123"

    user = test_db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            serial_no=102,
            name="Consultant Beta",
            email=email,
            mobile="9876500002",
            password_hash=hash_password(password),
            role="consultant",
            is_active=True
        )
        test_db.add(user)
        test_db.commit()
        test_db.refresh(user)

    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Consultant B login failed: {res.text}"
    token = res.json()["token"]
    user_dict = res.json()["user"]

    return AuthClient(client, token, user_dict)
