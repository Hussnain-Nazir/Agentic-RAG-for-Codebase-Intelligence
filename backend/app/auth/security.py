import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from jwt import InvalidTokenError

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def require_jwt_secret(secret: str | None) -> str:
    if secret is None or not secret.strip() or secret.strip().lower() == "changeme":
        raise ValueError("JWT_SECRET must be configured with a non-placeholder value")
    return secret


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: uuid.UUID, secret: str | None) -> str:
    signing_secret = require_jwt_secret(secret)
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, signing_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str | None) -> uuid.UUID:
    signing_secret = require_jwt_secret(secret)
    try:
        payload = jwt.decode(token, signing_secret, algorithms=[ALGORITHM])
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise InvalidTokenError("Missing token subject")
        return uuid.UUID(subject)
    except (InvalidTokenError, ValueError, TypeError) as exc:
        raise ValueError("Invalid access token") from exc
