from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()
ALGORITHM = "HS256"


def _truncate_password(password: str) -> str:
    """Truncate password to 72 bytes max (bcrypt limitation)."""
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        encoded = encoded[:72]
    return encoded.decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    password = _truncate_password(password)
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_password = _truncate_password(plain_password)
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_business(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    from app.db.database import get_db
    from app.db.models import Business
    from sqlalchemy.orm import Session

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        business_id: str = payload.get("sub")
        if business_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    db_gen = get_db()
    db: Session = next(db_gen)
    try:
        business = db.query(Business).filter(Business.id == int(business_id)).first()
        if business is None:
            raise credentials_exception
        return business
    finally:
        db.close()
