from typing import Optional
from pydantic import BaseModel


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserProfile(BaseModel):
    id: int
    email: str
    display_name: Optional[str] = None
    gravatar_hash: Optional[str] = None
    is_admin: bool
    profile_photo_url: Optional[str] = None


class AuthResponse(BaseModel):
    token: str
    user: UserProfile
