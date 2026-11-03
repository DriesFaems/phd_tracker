from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint

STAGES = [
    "Idea",
    "Design",
    "Data collection",
    "Analysis",
    "Writing",
    "Submitted",
    "R&R",
    "Accepted",
]


# active: being worked on; inactive: paused (no stall warnings); closed: finished or abandoned (hidden from logs)
PROJECT_STATUSES = ["active", "inactive", "closed"]
OPEN_STATUSES = ("active", "inactive")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    password_hash: Optional[str] = None
    role: str = "student"  # "student" | "supervisor"
    active: bool = True
    invite_token: Optional[str] = Field(default=None, index=True)
    invite_expires: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
    last_login: Optional[datetime] = None


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="user.id", index=True)
    title: str
    description: str = ""
    stage: str = "Idea"
    target_journal: str = ""
    position: int = 1
    status: str = Field(default="active", index=True)  # see PROJECT_STATUSES
    status_changed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class StageChange(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    stage: str
    changed_at: datetime = Field(default_factory=utcnow)


class Milestone(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    title: str
    due_date: Optional[date] = None
    done_at: Optional[datetime] = None


class WeeklyLog(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("student_id", "week"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="user.id", index=True)
    week: str = Field(index=True)  # ISO week, e.g. "2026-W44"
    raw_text: str = ""
    summary: str = ""
    status: str = "draft"  # "draft" | "submitted"
    llm_status: str = "none"  # "none" | "pending" | "done" | "failed"
    llm_error: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    submitted_at: Optional[datetime] = None


class LogEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    log_id: int = Field(foreign_key="weeklylog.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    progress: str = ""
    next_steps: str = ""
    blockers: str = ""
    needs_help: bool = False
    help_question: str = ""
    momentum: Optional[int] = None  # 1 (stuck) .. 5 (great)
    confirmed: bool = False  # reviewed by the student before submitting
    resolved_at: Optional[datetime] = None  # help request handled by supervisor


class Comment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    log_id: int = Field(foreign_key="weeklylog.id", index=True)
    entry_id: Optional[int] = Field(default=None, foreign_key="logentry.id")
    author_id: int = Field(foreign_key="user.id")
    body: str
    created_at: datetime = Field(default_factory=utcnow)
    read_at: Optional[datetime] = None


class AiJob(SQLModel, table=True):
    """A background LLM request: digests, feedback drafts and student assists."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    kind: str  # "digest" | "draft_feedback" | "assist_plan" | "assist_feedback" | "assist_question"
    ref_id: Optional[int] = None  # e.g. the log a feedback draft is for
    week: str = ""
    input_text: str = ""
    output_text: str = ""
    status: str = "pending"  # "pending" | "done" | "failed"
    error: str = ""
    created_at: datetime = Field(default_factory=utcnow)
