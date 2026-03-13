from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", truncate_error=False)
bearer_scheme = HTTPBearer()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_business(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    payload = decode_token(credentials.credentials)
    business_id = payload.get("sub")
    if not business_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return business_id


def require_admin(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if credentials.credentials != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return True
