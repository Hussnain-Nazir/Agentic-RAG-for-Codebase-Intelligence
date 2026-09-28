from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    organization_id: int


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ItemUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    owner_id: int
