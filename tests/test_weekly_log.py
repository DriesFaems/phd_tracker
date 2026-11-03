from sqlmodel import select

from app.llm import tasks
from app.llm.client import LLMError
from app.llm.prompts import ExtractedEntry, Extraction
from app.models import Comment, LogEntry, Project, WeeklyLog
from app.weeks import current_week
from tests.conftest import login


def fake_extraction(projects):
    def _chat_json(messages, schema):
        assert "Projects:" in messages[1]["content"]
        return Extraction(
            summary="Good week on the CVC paper, stuck on endogeneity.",
            entries=[
                ExtractedEntry(project_id=projects[0].id, progress="Wrote discussion", next_steps="Send draft", momentum=4),
                ExtractedEntry(project_id=projects[1].id, progress="Tried IV", blockers="Weak instrument", needs_help=True,
                               help_question="Heckman or reframe?", momentum=2),
                ExtractedEntry(project_id=99999, progress="hallucinated project"),  # must be ignored
            ],
        )

    return _chat_json


def test_analyse_review_and_submit(make_client, people, session, monkeypatch):
    projects = people["projects"]
    monkeypatch.setattr(tasks, "chat_json", fake_extraction(projects))
    client = login(make_client(), "alice@example.test")

    client.post("/student/week", data={"week": current_week(), "raw_text": "CVC discussion done. IV is weak.", "action": "analyse"})
    wlog = session.exec(select(WeeklyLog)).one()
    assert wlog.llm_status == "done" and wlog.status == "draft"
    entries = session.exec(select(LogEntry)).all()
    assert {e.project_id for e in entries} == {projects[0].id, projects[1].id}

    review = client.get(f"/student/log/{wlog.id}/review").text
    assert "Wrote discussion" in review and "Heckman or reframe?" in review

    client.post(f"/student/log/{wlog.id}/confirm", data={
        f"progress_{projects[0].id}": "Wrote discussion (edited)", f"momentum_{projects[0].id}": "4",
        f"progress_{projects[1].id}": "Tried IV", f"blockers_{projects[1].id}": "Weak instrument",
        f"help_{projects[1].id}": "on", f"question_{projects[1].id}": "Heckman or reframe?", f"momentum_{projects[1].id}": "2",
    })
    session.expire_all()
    wlog = session.get(WeeklyLog, wlog.id)
    assert wlog.status == "submitted"
    entries = {e.project_id: e for e in session.exec(select(LogEntry))}
    assert entries[projects[0].id].progress == "Wrote discussion (edited)" and entries[projects[0].id].confirmed

    sup = login(make_client(), "sup@example.test")
    dash = sup.get("/supervisor").text
    assert "Heckman or reframe?" in dash and "1 of 2 students logged this week" in dash

    help_entry = entries[projects[1].id]
    resp = sup.post(f"/supervisor/log/{wlog.id}/comment", data={"body": "Try Heckman.", "entry_id": help_entry.id, "resolve": "on"},
                    headers={"HX-Request": "true"})
    assert "Reply sent" in resp.text
    session.expire_all()
    assert session.get(LogEntry, help_entry.id).resolved_at is not None
    assert "Heckman or reframe?" not in sup.get("/supervisor").text

    # the student sees an unread badge, and the reply in their history
    assert 'aria-label="1 unread">1</span>' in client.get("/student/projects").text
    assert "Try Heckman." in client.get("/student/history").text


def test_llm_failure_still_allows_submission(make_client, people, session, monkeypatch):
    def broken(*_):
        raise LLMError("Ollama down")

    monkeypatch.setattr(tasks, "chat_json", broken)
    client = login(make_client(), "alice@example.test")
    client.post("/student/week", data={"week": current_week(), "raw_text": "Did stuff", "action": "submit_raw"})
    wlog = session.exec(select(WeeklyLog)).one()
    assert wlog.status == "submitted" and wlog.llm_status == "failed"
    assert "could not process" in client.get(f"/student/log/{wlog.id}/review").text

    sup = login(make_client(), "sup@example.test")
    assert "AI could not structure" in sup.get("/supervisor").text


def test_students_cannot_touch_each_others_data(make_client, people, session):
    alice_log = WeeklyLog(student_id=people["alice"].id, week=current_week(), raw_text="secret", status="submitted")
    session.add(alice_log)
    session.commit()
    alice_project = people["projects"][0]

    bob = login(make_client(), "bob@example.test")
    assert bob.get(f"/student/log/{alice_log.id}/review").status_code == 404
    assert bob.post(f"/student/log/{alice_log.id}/comment", data={"body": "hi"}).status_code == 404
    assert bob.post(f"/student/projects/{alice_project.id}", data={"title": "hijack", "stage": "Idea"}).status_code == 404
    assert bob.post(f"/student/projects/{alice_project.id}/milestones", data={"title": "x"}).status_code == 404
    assert "secret" not in bob.get("/student/history").text
    assert bob.get("/supervisor/student/%d" % people["alice"].id).status_code == 403
    session.expire_all()
    assert session.get(Project, alice_project.id).title == "CVC paper"
    assert not session.exec(select(Comment)).all()


def test_projects_and_milestones(make_client, people, session):
    client = login(make_client(), "bob@example.test")
    client.post("/student/projects", data={"title": "New paper", "stage": "Design"})
    project = session.exec(select(Project).where(Project.title == "New paper")).one()
    client.post(f"/student/projects/{project.id}", data={"title": "New paper", "stage": "Writing", "position": 2})
    client.post(f"/student/projects/{project.id}/milestones", data={"title": "Draft", "due_date": "2030-01-01"})
    page = client.get("/student/projects").text
    assert "Draft" in page and "Writing" in page


def test_student_assist_and_supervisor_digest(make_client, people, session, monkeypatch):
    seen = []

    def fake_chat(messages):
        seen.append(messages)
        return "**Plan:** finish the draft"

    monkeypatch.setattr(tasks, "chat", fake_chat)
    client = login(make_client(), "alice@example.test")
    client.post("/student/assist", data={"kind": "assist_plan", "input_text": "Deadline Friday"})
    page = client.get("/student/assist").text
    assert "<strong>Plan:</strong> finish the draft" in page
    assert "CVC paper" in seen[0][1]["content"] and "Deadline Friday" in seen[0][1]["content"]

    sup = login(make_client(), "sup@example.test")
    sup.post("/supervisor/digest", data={"week": current_week()})
    assert "finish the draft" in sup.get("/supervisor/digest").text
    assert "Alice Student" in seen[1][1]["content"] and "Bob Student" in seen[1][1]["content"]
    # a student cannot read the supervisor's AI jobs
    assert client.get("/ai/job/2").status_code == 404


def test_project_lifecycle_and_any_number_of_projects(make_client, people, session, monkeypatch):
    seen = []

    def capture(messages, schema):
        seen.append(messages[1]["content"])
        return Extraction()

    monkeypatch.setattr(tasks, "chat_json", capture)
    client = login(make_client(), "bob@example.test")
    for i in range(4):
        client.post("/student/projects", data={"title": f"Extra project {i}", "stage": "Idea"})
    projects = session.exec(select(Project).where(Project.student_id == people["bob"].id).order_by(Project.position)).all()
    assert len(projects) == 5 and [p.position for p in projects][-4:] == [2, 3, 4, 5]

    paused, closed = projects[1], projects[2]
    client.post(f"/student/projects/{paused.id}/status", data={"status": "inactive"})
    client.post(f"/student/projects/{closed.id}/status", data={"status": "closed"})
    session.expire_all()
    assert session.get(Project, paused.id).status == "inactive" and session.get(Project, closed.id).status_changed_at

    client.post("/student/week", data={"week": current_week(), "raw_text": "worked", "action": "analyse"})
    assert "Extra project 0 (inactive" in seen[0] and "Extra project 1" not in seen[0]
    wlog = session.exec(select(WeeklyLog)).one()
    review = client.get(f"/student/log/{wlog.id}/review").text
    assert "Paused projects (1)" in review and "Extra project 1" not in review

    sup = login(make_client(), "sup@example.test")
    dash = sup.get("/supervisor").text
    assert "Extra project 3" in dash and "Extra project 1" not in dash and "+ 1 closed project" in dash
    detail = sup.get(f"/supervisor/student/{people['bob'].id}").text
    assert "4 open, 1 closed" in detail and "Closed projects (1)" in detail
