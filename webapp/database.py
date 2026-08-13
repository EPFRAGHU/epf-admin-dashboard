import os
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

Base = declarative_base()

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
if DATABASE_URL:
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Could not connect to database: {e}")
        if os.environ.get("RENDER"):
            raise RuntimeError("Running on Render but DB connection failed. Fallback disabled.") from e
        SessionLocal = None
        DATABASE_URL = None
elif os.environ.get("RENDER"):
    raise ValueError("Running on Render but DATABASE_URL is missing. Fallback disabled.")

def get_db():
    if not SessionLocal:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
