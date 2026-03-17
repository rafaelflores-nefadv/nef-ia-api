from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class AdminMeResponse(BaseModel):
    id: UUID
    name: str
    email: str
    role: str
