from sqlmodel import select

from app.models import User
from tests.conftest import PASSWORD, login


def test_first_run_setup_creates_supervisor(make_client, session):
    client = make_client()
    assert client.get("/", follow_redirects=False).headers["location"] == "/setup"
    resp = client.post("/setup", data={"name": "Prof", "email": "Prof@Example.test", "password": PASSWORD, "password2": PASSWORD}, follow_redirects=False)
    assert resp.status_code == 303
    sup = session.exec(select(User)).one()
    assert sup.role == "supervisor" and sup.email == "prof@example.test"
    # setup is closed once a supervisor exists
    assert client.get("/setup", follow_redirects=False).headers["location"] == "/login"


def test_login_and_role_guards(make_client, people):
    client = make_client()
    assert client.get("/supervisor", follow_redirects=False).headers["location"] == "/login"
    bad = client.post("/login", data={"email": "alice@example.test", "password": "wrong"})
    assert "Wrong email or password" in bad.text

    login(client, "alice@example.test")
    assert client.get("/student/week").status_code == 200
    assert client.get("/supervisor").status_code == 403

    sup = login(make_client(), "sup@example.test")
    assert sup.get("/supervisor").status_code == 200
    assert sup.get("/student/week").status_code == 403


def test_invite_flow(make_client, people, session):
    sup = login(make_client(), "sup@example.test")
    sup.post("/supervisor/students", data={"name": "Carol New", "email": "carol@example.test"})
    carol = session.exec(select(User).where(User.email == "carol@example.test")).one()
    assert carol.invite_token and carol.password_hash is None
    assert carol.invite_token in sup.get("/supervisor/students").text

    client = make_client()
    token = carol.invite_token
    short = client.post(f"/invite/{token}", data={"password": "short", "password2": "short"})
    assert "at least" in short.text
    client.post(f"/invite/{token}", data={"password": PASSWORD, "password2": PASSWORD})
    session.refresh(carol)
    assert carol.invite_token is None
    login(client, "carol@example.test")
    # token cannot be reused
    assert "expired" in make_client().get(f"/invite/{token}").text


def test_deactivated_student_is_logged_out(make_client, people, session):
    client = login(make_client(), "bob@example.test")
    sup = login(make_client(), "sup@example.test")
    sup.post(f"/supervisor/students/{people['bob'].id}/toggle")
    assert client.get("/student/week", follow_redirects=False).headers["location"] == "/login"
