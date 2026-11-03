import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import db
from app.auth import hash_password
from app.db import get_session
from app.main import create_app
from app.models import Project, User

PASSWORD = "test-password-1"


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(db, "engine", eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def app(engine):
    application = create_app(run_startup=False)

    def _session():
        with Session(engine) as s:
            yield s

    application.dependency_overrides[get_session] = _session
    return application


@pytest.fixture
def make_client(app):
    def _make():
        return TestClient(app)

    return _make


@pytest.fixture
def people(session):
    sup = User(name="Sue Pervisor", email="sup@example.test", role="supervisor", password_hash=hash_password(PASSWORD))
    alice = User(name="Alice Student", email="alice@example.test", role="student", password_hash=hash_password(PASSWORD))
    bob = User(name="Bob Student", email="bob@example.test", role="student", password_hash=hash_password(PASSWORD))
    session.add_all([sup, alice, bob])
    session.commit()
    projects = [Project(student_id=alice.id, title=t, position=i) for i, t in enumerate(["CVC paper", "Alliance paper", "Experiment"], 1)]
    projects.append(Project(student_id=bob.id, title="Bob's patent paper"))
    session.add_all(projects)
    session.commit()
    return {"sup": sup, "alice": alice, "bob": bob, "projects": projects}


def login(client: TestClient, email: str) -> TestClient:
    resp = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert resp.status_code == 303, resp.text
    return client


def ids_in(html: str, pattern: str) -> list[str]:
    return re.findall(pattern, html)
