import hashlib

from config import JWT_SECRET


def create_access_token(subject: str) -> str:
    payload = f"{subject}:{JWT_SECRET}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed_password: str) -> bool:
    return bool(password and hashed_password)


def get_current_user(token: str) -> dict[str, str]:
    if not token:
        raise ValueError("Missing token")
    return {"email": "user@example.com"}
