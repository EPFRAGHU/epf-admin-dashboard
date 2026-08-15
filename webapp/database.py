import os
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    serial_no = Column(Integer, nullable=True)  # Consultant display number (e.g. 1, 2, 3)
    name = Column(String(255), nullable=False)
    mobile = Column(String(50), nullable=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="consultant")  # 'superadmin' or 'consultant'
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    establishments = relationship("Establishment", back_populates="user", cascade="all, delete-orphan")


class Establishment(Base):
    __tablename__ = "establishments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    address = Column(Text, nullable=True)
    coverage_date = Column(String(50), nullable=True)
    data = Column(Text, nullable=False, default="{}")  # Serialized Project JSON
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="establishments")
    payments = relationship("Payment", back_populates="establishment", cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    establishment_id = Column(Integer, ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False, index=True)
    financial_year = Column(String(50), nullable=False, index=True)  # e.g. "2026-27"
    month = Column(String(20), nullable=False)  # "Mar", "Apr", ... "Feb"
    is_paid = Column(Boolean, default=False, nullable=False)
    amount = Column(Float, nullable=True)
    paid_date = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    establishment = relationship("Establishment", back_populates="payments")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    establishment_id = Column(Integer, ForeignKey("establishments.id", ondelete="SET NULL"), nullable=True, index=True)
    action_type = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=False)
    extra_data = Column(Text, nullable=True, default="{}")  # Serialized JSON

    user = relationship("User")
    establishment = relationship("Establishment")


# Legacy tables for migration
class ProjectData(Base):
    __tablename__ = "projects"
    filename = Column(String, primary_key=True)
    data = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String)


SessionLocal = None
engine = None

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./epf_app.db"

try:
    if DATABASE_URL.startswith("sqlite"):
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Could not connect to database: {e}")
    if os.environ.get("RENDER"):
        raise RuntimeError("Running on Render but DB connection failed.") from e
    # Fallback to local SQLite
    DATABASE_URL = "sqlite:///./epf_app.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)


def get_db():
    if not SessionLocal:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
