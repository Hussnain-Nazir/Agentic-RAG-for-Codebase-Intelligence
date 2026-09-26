from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from demo_app.db import get_db
from demo_app.schemas import LoginRequest, RegisterRequest, TokenResponse
from demo_app.security import create_access_token
from demo_app.services import authenticate_user, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict[str, int]:
    user = register_user(db, payload.email, payload.password, payload.organization_id)
    return {"user_id": user.id}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = authenticate_user(db, payload.email, payload.password)
    token = create_access_token(user.id, request.app.state.jwt_secret)
    return TokenResponse(access_token=token)
