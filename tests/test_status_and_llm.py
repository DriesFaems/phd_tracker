from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.llm import client as llm
from app.llm.prompts import Extraction
from app.models import LogEntry, Milestone, Project, WeeklyLog
from app.status import project_status
from app.weeks import current_week, shift_week


def add_log(session, student_id, weeks_ago, entries=()):
    wl = WeeklyLog(student_id=student_id, week=shift_week(current_week(), -weeks_ago), status="submitted", raw_text="x")
    session.add(wl)
    session.commit()
    for project_id, kwargs in entries:
        session.add(LogEntry(log_id=wl.id, project_id=project_id, **kwargs))
    session.commit()
    return wl


@pytest.fixture
def project(session, people):
    p = people["projects"][0]
    p.created_at = datetime.now(timezone.utc) - timedelta(weeks=1)
    session.add(p)
    session.commit()
    return p


def test_grey_without_logs(session, project):
    assert project_status(session, project, current_week())[0] == "grey"


def test_green_when_on_track(session, project):
    add_log(session, project.student_id, 0, [(project.id, {"progress": "did things", "momentum": 4})])
    assert project_status(session, project, current_week()) == ("green", [])


def test_red_on_help_request(session, project):
    add_log(session, project.student_id, 0, [(project.id, {"progress": "x", "needs_help": True})])
    color, reasons = project_status(session, project, current_week())
    assert color == "red" and "asks for help" in reasons


def test_red_when_log_missing_two_weeks(session, project):
    add_log(session, project.student_id, 2, [(project.id, {"progress": "x"})])
    color, reasons = project_status(session, project, current_week())
    assert color == "red" and any("no weekly log" in r for r in reasons)


def test_amber_low_momentum_and_overdue(session, project):
    add_log(session, project.student_id, 1, [(project.id, {"progress": "x", "momentum": 2})])
    add_log(session, project.student_id, 0, [(project.id, {"progress": "y", "momentum": 1})])
    assert project_status(session, project, current_week())[0] == "amber"

    session.add(Milestone(project_id=project.id, title="late", due_date=date.today() - timedelta(days=1)))
    session.commit()
    assert any("overdue" in r for r in project_status(session, project, current_week())[1])


def test_amber_when_project_stalls(session, people):
    p = Project(student_id=people["alice"].id, title="old", created_at=datetime.now(timezone.utc) - timedelta(weeks=6))
    session.add(p)
    session.commit()
    add_log(session, p.student_id, 0, [])  # student logs, but not about this project
    color, reasons = project_status(session, p, current_week())
    assert color == "amber" and any("no progress logged" in r for r in reasons)


class FakeResponse:
    def __init__(self, content):
        self._content = content
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._content}}


def test_chat_json_retries_on_invalid_json(monkeypatch):
    replies = iter(["not json at all", '```json\n{"summary": "ok", "entries": []}\n```'])
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        return FakeResponse(next(replies))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    result = llm.chat_json([{"role": "user", "content": "x"}], Extraction)
    assert result.summary == "ok"
    assert len(calls) == 2 and "format" in calls[0]


def test_chat_strips_think_blocks(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResponse("<think>hmm</think>Hello"))
    assert llm.chat([{"role": "user", "content": "x"}]) == "Hello"


def test_chat_timeout_raises_llm_error(monkeypatch):
    def timeout(*a, **k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(llm.httpx, "post", timeout)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "x"}])


def test_inactive_project_has_no_stall_warnings_but_keeps_help(session, people):
    old = datetime.now(timezone.utc) - timedelta(weeks=6)
    p = Project(student_id=people["alice"].id, title="paused", created_at=old, status="inactive", status_changed_at=old)
    session.add(p)
    session.commit()
    add_log(session, p.student_id, 0, [])
    color, reasons = project_status(session, p, current_week())
    assert color == "grey" and reasons[0].startswith("inactive since")

    add_log(session, p.student_id, 1, [(p.id, {"needs_help": True, "help_question": "?"})])
    assert project_status(session, p, current_week())[0] == "red"


def test_closed_project_is_neutral(session, people):
    p = Project(student_id=people["alice"].id, title="done", status="closed")
    session.add(p)
    session.commit()
    assert project_status(session, p, current_week()) == ("grey", ["closed"])


def test_reactivation_restarts_stall_clock(session, people):
    p = Project(student_id=people["alice"].id, title="back", created_at=datetime.now(timezone.utc) - timedelta(weeks=10),
                status_changed_at=datetime.now(timezone.utc))
    session.add(p)
    session.commit()
    add_log(session, p.student_id, 0, [])
    assert project_status(session, p, current_week())[0] == "green"
