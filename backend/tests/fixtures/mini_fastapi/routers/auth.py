from fastapi import APIRouter, HTTPException

from auth.security import create_access_token, verify_password

router = APIRouter(prefix="/auth")


@router.post("/login")
def login(email: str, password: str) -> dict[str, str]:
    user = {"email": email, "hashed_password": "stored-hash"}
    if not verify_password(password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": create_access_token(user["email"])}
