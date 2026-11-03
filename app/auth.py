import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.models import User, utcnow

_hasher = PasswordHasher()


class LoginRequired(Exception):
    """Raised for anonymous users; main.py turns it into a redirect to /login."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.exec(select(User).where(User.email == email.strip().lower())).first()
    if user and user.active and verify_password(password, user.password_hash):
        return user
    return None


def new_invite(user: User) -> str:
    user.invite_token = secrets.token_urlsafe(32)
    user.invite_expires = utcnow() + timedelta(days=get_settings().invite_valid_days)
    return user.invite_token


def invite_url(user: User) -> str:
    return f"{get_settings().base_url.rstrip('/')}/invite/{user.invite_token}"


def user_for_invite(session: Session, token: str) -> User | None:
    user = session.exec(select(User).where(User.invite_token == token)).first()
    if user and user.active and user.invite_expires and user.invite_expires > utcnow():
        return user
    return None


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    uid = request.session.get("uid")
    user = session.get(User, uid) if uid else None
    if not user or not user.active:
        request.session.clear()
        raise LoginRequired()
    return user


def require_student(user: User = Depends(current_user)) -> User:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Students only")
    return user


def require_supervisor(user: User = Depends(current_user)) -> User:
    if user.role != "supervisor":
        raise HTTPException(status_code=403, detail="Supervisor only")
    return user
