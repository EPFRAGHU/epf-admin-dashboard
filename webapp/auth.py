import os
import json
from datetime import datetime, timedelta
from typing import Optional, Tuple
import jwt
from werkzeug.security import generate_password_hash, check_password_hash
from fastapi import Request, HTTPException, Depends, Header, Query
from sqlalchemy.orm import Session

from .database import get_db, User, Establishment
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from epf_engine import Project

JWT_SECRET = os.environ.get("JWT_SECRET", "epf-keka-theme-super-secret-jwt-key-2026")
JWT_ALGORITHM = "HS256"
JWT_EXP_DAYS = 7


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def create_access_token(user_id: int, email: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=JWT_EXP_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception:
        return None


async def get_current_user(
    request: Request,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split(" ", 1)[1].strip()
    elif token:
        raw_token = token.strip()
    elif "epf_token" in request.cookies:
        raw_token = request.cookies.get("epf_token")

    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required. Please log in.")

    payload = decode_access_token(raw_token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please log in again.")

    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User account not found.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account has been deactivated.")

    return user


async def get_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Access denied. Superadmin privileges required.")
    return current_user


async def get_active_establishment(
    request: Request,
    establishment_id: Optional[int] = Query(None),
    est_id: Optional[int] = Query(None),
    x_establishment_id: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Tuple[Establishment, Project]:
    target_id = establishment_id or est_id
    if target_id is None and x_establishment_id:
        try:
            target_id = int(x_establishment_id)
        except ValueError:
            target_id = None

    # Fallback to user's first establishment if no establishment_id was explicitly supplied
    if target_id is None:
        first_est = db.query(Establishment).filter(Establishment.user_id == current_user.id).first()
        if first_est:
            target_id = first_est.id
        elif current_user.role == "superadmin":
            # For superadmin, pick any available establishment
            first_any = db.query(Establishment).first()
            if first_any:
                target_id = first_any.id

    if target_id is None:
        raise HTTPException(status_code=404, detail="No establishment found. Please create an establishment first.")

    est = db.query(Establishment).filter(Establishment.id == target_id).first()
    if not est:
        raise HTTPException(status_code=404, detail="Establishment not found.")

    # Ownership check: consultants can only access their own establishments
    if current_user.role != "superadmin" and est.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied. You do not have permission to view this establishment.")

    p = Project()
    if est.data:
        try:
            data_dict = json.loads(est.data)
            p.load_from_dict(data_dict)
        except Exception as e:
            print(f"Error loading project data for establishment {est.id}: {e}")
            p.set_establishment(est.code, est.name, est.address or "", est.coverage_date or "")
    else:
        p.set_establishment(est.code, est.name, est.address or "", est.coverage_date or "")

    return est, p


def save_establishment_project(db: Session, est: Establishment, project: Project):
    est.code = project.code or est.code
    est.name = project.name or est.name
    est.address = project.address or est.address
    est.coverage_date = project.coverage_date or est.coverage_date
    est.data = json.dumps(project.to_dict(), ensure_ascii=False)
    db.commit()
