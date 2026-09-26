import os

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from demo_app.db import get_db
from demo_app.models import User
from demo_app.repositories import get_user_by_id

bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed_password.encode())


def create_access_token(user_id: int, secret: str) -> str:
    return jwt.encode({"sub": str(user_id)}, secret, algorithm="HS256")


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    secret = request.app.state.jwt_secret or os.environ["JWT_SECRET"]
    try:
        payload = jwt.decode(credentials.credentials, secret, algorithms=["HS256"])
        user = get_user_by_id(db, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user
