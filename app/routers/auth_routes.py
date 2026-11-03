from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.auth import authenticate, hash_password, user_for_invite
from app.db import get_session
from app.models import User, utcnow
from app.web import flash, render

router = APIRouter()

MIN_PASSWORD = 10


def _home(user: User) -> str:
    return "/supervisor" if user.role == "supervisor" else "/student/week"


def _has_supervisor(session: Session) -> bool:
    return session.exec(select(User).where(User.role == "supervisor")).first() is not None


@router.get("/")
def index(request: Request, session: Session = Depends(get_session)):
    if not _has_supervisor(session):
        return RedirectResponse("/setup", 303)
    uid = request.session.get("uid")
    user = session.get(User, uid) if uid else None
    return RedirectResponse(_home(user) if user and user.active else "/login", 303)


@router.get("/login")
def login_form(request: Request):
    return render(request, "login.html")


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
    user = authenticate(session, email, password)
    if not user:
        return render(request, "login.html", error="Wrong email or password.", email=email)
    request.session.clear()
    request.session["uid"] = user.id
    user.last_login = utcnow()
    session.add(user)
    session.commit()
    return RedirectResponse(_home(user), 303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


@router.get("/invite/{token}")
def invite_form(token: str, request: Request, session: Session = Depends(get_session)):
    user = user_for_invite(session, token)
    if not user:
        return render(request, "message.html", title="Invite expired", message="This link is invalid or has expired. Ask your supervisor for a new one.")
    return render(request, "set_password.html", invited=user, token=token)


@router.post("/invite/{token}")
def accept_invite(
    token: str,
    request: Request,
    password: str = Form(...),
    password2: str = Form(...),
    session: Session = Depends(get_session),
):
    user = user_for_invite(session, token)
    if not user:
        return render(request, "message.html", title="Invite expired", message="This link is invalid or has expired.")
    error = _password_error(password, password2)
    if error:
        return render(request, "set_password.html", invited=user, token=token, error=error)
    user.password_hash = hash_password(password)
    user.invite_token = None
    user.invite_expires = None
    session.add(user)
    session.commit()
    flash(request, "Password set. You can now log in.")
    return RedirectResponse("/login", 303)


@router.get("/setup")
def setup_form(request: Request, session: Session = Depends(get_session)):
    if _has_supervisor(session):
        return RedirectResponse("/login", 303)
    return render(request, "setup.html")


@router.post("/setup")
def setup(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    session: Session = Depends(get_session),
):
    if _has_supervisor(session):
        return RedirectResponse("/login", 303)
    error = _password_error(password, password2)
    if error:
        return render(request, "setup.html", error=error, name=name, email=email)
    session.add(User(name=name.strip(), email=email.strip().lower(), role="supervisor", password_hash=hash_password(password)))
    session.commit()
    flash(request, "Supervisor account created. Please log in.")
    return RedirectResponse("/login", 303)


def _password_error(password: str, password2: str) -> str | None:
    if password != password2:
        return "Passwords do not match."
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    return None
