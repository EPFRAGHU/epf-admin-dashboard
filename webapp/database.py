import os
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, Float, DateTime, Date, ForeignKey, UniqueConstraint
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
    password_hash = Column(String(255), nullable=True)  # null for Google-only accounts (no local password)
    google_id = Column(String(255), nullable=True, unique=True, index=True)  # Google "sub" claim, once linked
    role = Column(String(50), nullable=False, default="consultant")  # 'superadmin', 'consultant', or 'employer'
    max_establishments = Column(Integer, nullable=True)  # Employer establishment cap; null = unlimited (always null for consultant/superadmin)
    custom_rate_per_employee = Column(Float, nullable=True)  # Nullable rate override (₹/emp)
    default_billing_mode = Column(String(20), nullable=True)  # 'per_employee' | 'flat_fee' | null (no consultant-level default). Consultant role only; superadmin-set only.
    default_flat_fee_per_establishment = Column(Float, nullable=True)  # ₹/month, only meaningful when default_billing_mode='flat_fee'
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
    custom_rate_per_employee = Column(Float, nullable=True)  # Nullable rate override (₹/emp)
    advance_credit_balance = Column(Float, nullable=False, default=0.0)  # Prepaid subscription credit (₹), auto-applied to future months
    trial_ends_on = Column(Date, nullable=True)  # Null = no trial (normal enforcement). Superadmin-set only.
    billing_mode = Column(String(20), nullable=True)  # 'per_employee' | 'flat_fee' | null. Null means "inherit consultant's default_billing_mode, or global default if consultant has none set." Superadmin-set only. See resolve_billing_mode().
    flat_fee_amount = Column(Float, nullable=True)  # ₹/month, only meaningful when billing_mode='flat_fee'. Null when inheriting.
    data = Column(Text, nullable=False, default="{}")  # Serialized Project JSON
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="establishments")
    payments = relationship("Payment", back_populates="establishment", cascade="all, delete-orphan")
    subscription_fees = relationship("SubscriptionFee", back_populates="establishment", cascade="all, delete-orphan")


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


class SubscriptionFee(Base):
    __tablename__ = "subscription_fees"
    # payment_status: 'unpaid' | 'pending_verification' | 'paid'
    # submitted_utr / submitted_by / submitted_at — set on POST submit-utr
    # verified_by / verified_at — set on approve
    # rejection_reason — set on reject, cleared on resubmit

    id = Column(Integer, primary_key=True, autoincrement=True)
    establishment_id = Column(Integer, ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False, index=True)
    financial_year = Column(String(50), nullable=False, index=True)  # e.g. "2026-27"
    month = Column(String(20), nullable=False)  # "Mar", "Apr", ... "Feb"
    employee_count = Column(Integer, default=0, nullable=False)
    rate_applied = Column(Float, default=10.0, nullable=True)  # Null for flat_fee rows -- there's no per-employee rate to show
    amount_due = Column(Float, default=0.0, nullable=False)
    billing_mode = Column(String(20), nullable=False, default="per_employee")  # Mode this specific row was billed under -- frozen once paid, so a later mode switch never rewrites history
    is_paid = Column(Boolean, default=False, nullable=False)
    paid_date = Column(String(50), nullable=True)
    payment_reference = Column(String(255), nullable=True)  # UPI / Bank reference / Cashfree payment id
    notes = Column(Text, nullable=True)
    cashfree_order_id = Column(String(120), nullable=True, index=True)  # Cashfree Payment Link's link_id ("sub_..."), while a link is outstanding
    cashfree_payment_link_url = Column(Text, nullable=True)
    payment_status = Column(String(30), nullable=False, default="unpaid")  # 'unpaid' | 'pending_verification' | 'paid'
    submitted_utr = Column(String(255), nullable=True)   # UTR entered by the consultant/employer
    submitted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    verified_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    establishment = relationship("Establishment", back_populates="subscription_fees")


class AdvanceCreditLedger(Base):
    __tablename__ = "advance_credit_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    establishment_id = Column(Integer, ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type = Column(String(20), nullable=False)  # 'topup' | 'applied'
    amount = Column(Float, nullable=False)
    cashfree_order_id = Column(String(120), nullable=True, index=True)  # link_id ("adv_..."), only for Cashfree-initiated topups
    cashfree_payment_link_url = Column(Text, nullable=True)
    payment_reference = Column(String(255), nullable=True)  # manual UPI ref, or Cashfree payment id once confirmed
    notes = Column(Text, nullable=True)
    applied_to_fee_id = Column(Integer, ForeignKey("subscription_fees.id", ondelete="SET NULL"), nullable=True)  # only on 'applied' entries
    status = Column(String(20), nullable=False, default="manual")  # 'pending' | 'confirmed' | 'manual' | 'pending_verification' | 'rejected'
    submitted_utr = Column(String(255), nullable=True)   # UTR entered by the consultant/employer via the manual UPI/QR path
    submitted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    verified_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    establishment = relationship("Establishment")
    applied_to_fee = relationship("SubscriptionFee")


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


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    key = Column(String(100), primary_key=True)
    value = Column(Boolean, nullable=False, default=True)
    description = Column(String(255), nullable=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(String(50), nullable=False, index=True)  # 'consultant' or 'employer'
    action = Column(String(100), nullable=False, index=True)
    allowed = Column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint('role', 'action', name='uq_role_permissions_role_action'),)


class UserPermissionOverride(Base):
    __tablename__ = "user_permission_overrides"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    allowed = Column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint('user_id', 'action', name='uq_user_permission_overrides_user_action'),)

    user = relationship("User")


class SignupRequest(Base):
    __tablename__ = "signup_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(String(50), nullable=False)  # 'employer' or 'consultant'
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    mobile = Column(String(50), nullable=True)
    password_hash = Column(String(255), nullable=True)  # hashed immediately on submission -- plaintext never stored; null if email_verified_via_google
    google_id = Column(String(255), nullable=True)  # Google "sub" claim, if this request came from Google sign-in
    email_verified_via_google = Column(Boolean, nullable=False, default=False)
    establishment_code = Column(String(100), nullable=True)  # employer only
    establishment_name = Column(String(255), nullable=True)
    establishment_address = Column(Text, nullable=True)
    coverage_date = Column(String(50), nullable=True)
    agreed_to_terms = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="pending", index=True)  # 'pending' | 'approved' | 'rejected'
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    reviewer = relationship("User")


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
