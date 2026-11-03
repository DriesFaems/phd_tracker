"""LLM jobs. Each runs in a background thread with its own DB session and stores its result."""

import logging

from sqlmodel import Session, select

from app import db
from app.llm import prompts
from app.llm.client import LLMError, chat, chat_json
from app.models import OPEN_STATUSES, PROJECT_STATUSES, AiJob, LogEntry, Milestone, Project, User, WeeklyLog
from app.status import project_status, weeks_since_last_log
from app.weeks import shift_week

log = logging.getLogger(__name__)


def open_projects(session: Session, student_id: int, statuses=OPEN_STATUSES) -> list[Project]:
    """A student's projects that are not closed: active first, then inactive (paused)."""
    projects = session.exec(
        select(Project).where(Project.student_id == student_id, Project.status.in_(statuses)).order_by(Project.position, Project.id)
    ).all()
    return sorted(projects, key=lambda p: PROJECT_STATUSES.index(p.status))


def extract_log(log_id: int) -> None:
    with Session(db.engine) as session:
        wlog = session.get(WeeklyLog, log_id)
        if not wlog:
            return
        projects = open_projects(session, wlog.student_id)
        previous = session.exec(
            select(WeeklyLog.summary)
            .where(WeeklyLog.student_id == wlog.student_id, WeeklyLog.week < wlog.week, WeeklyLog.summary != "")
            .order_by(WeeklyLog.week.desc())
            .limit(2)
        ).all()
        try:
            result = chat_json(
                prompts.extract_messages(
                    [{"id": p.id, "title": p.title, "stage": p.stage, "status": p.status, "description": p.description} for p in projects],
                    wlog.raw_text,
                    list(previous),
                ),
                prompts.Extraction,
            )
        except LLMError as exc:
            log.warning("Extraction for log %s failed: %s", log_id, exc)
            wlog.llm_status, wlog.llm_error = "failed", str(exc)
            session.add(wlog)
            session.commit()
            return

        valid_ids = {p.id for p in projects}
        for old in session.exec(select(LogEntry).where(LogEntry.log_id == log_id, LogEntry.confirmed == False)):  # noqa: E712
            session.delete(old)
        confirmed_ids = set(
            session.exec(select(LogEntry.project_id).where(LogEntry.log_id == log_id, LogEntry.confirmed == True))  # noqa: E712
        )
        seen = set()
        for e in result.entries:
            if e.project_id not in valid_ids or e.project_id in seen or e.project_id in confirmed_ids:
                continue
            seen.add(e.project_id)
            session.add(
                LogEntry(
                    log_id=log_id,
                    project_id=e.project_id,
                    progress=e.progress,
                    next_steps=e.next_steps,
                    blockers=e.blockers,
                    needs_help=e.needs_help,
                    help_question=e.help_question,
                    momentum=e.momentum,
                )
            )
        wlog.summary = result.summary
        wlog.llm_status, wlog.llm_error = "done", ""
        session.add(wlog)
        session.commit()


def _run_job(job_id: int, build_messages) -> None:
    with Session(db.engine) as session:
        job = session.get(AiJob, job_id)
        if not job:
            return
        try:
            job.output_text = chat(build_messages(session, job))
            job.status = "done"
        except LLMError as exc:
            job.status, job.error = "failed", str(exc)
        session.add(job)
        session.commit()


def describe_student(session: Session, student: User, week: str, weeks_back: int = 1) -> str:
    """Plain-text snapshot of a student's projects and recent logs, used as LLM context."""
    lines = [f"Student: {student.name}"]
    gap = weeks_since_last_log(session, student.id, week)
    if gap is None:
        lines.append("- Has never submitted a weekly log.")
    elif gap >= 1:
        lines.append(f"- Last weekly log was {gap} week(s) ago.")
    logs = session.exec(
        select(WeeklyLog)
        .where(
            WeeklyLog.student_id == student.id,
            WeeklyLog.status == "submitted",
            WeeklyLog.week >= shift_week(week, -weeks_back),
            WeeklyLog.week <= week,
        )
        .order_by(WeeklyLog.week.desc())
    ).all()
    projects = open_projects(session, student.id)
    if not projects:
        lines.append("- Has no open projects yet.")
    for p in projects:
        color, reasons = project_status(session, p, week)
        lines.append(
            f"\nProject: {p.title} ({p.status}, stage: {p.stage}, traffic light: {color}"
            f"{'; ' + '; '.join(reasons) if reasons else ''})"
        )
        for m in session.exec(select(Milestone).where(Milestone.project_id == p.id, Milestone.done_at.is_(None))):
            if m.due_date:
                lines.append(f"  Open milestone: {m.title} due {m.due_date}")
        for wl in logs:
            for e in session.exec(select(LogEntry).where(LogEntry.log_id == wl.id, LogEntry.project_id == p.id)):
                lines.append(
                    f"  [{wl.week}] progress: {e.progress or '-'} | next: {e.next_steps or '-'} | "
                    f"blockers: {e.blockers or '-'} | momentum: {e.momentum or '?'}"
                    + (f" | ASKS FOR HELP: {e.help_question}" if e.needs_help and not e.resolved_at else "")
                )
    for wl in logs:
        if wl.summary:
            lines.append(f"[{wl.week}] overall: {wl.summary}")
        elif wl.llm_status != "done":
            lines.append(f"[{wl.week}] raw log: {wl.raw_text[:1500]}")
    return "\n".join(lines)


def run_digest(job_id: int) -> None:
    def build(session: Session, job: AiJob):
        students = session.exec(select(User).where(User.role == "student", User.active == True).order_by(User.name)).all()  # noqa: E712
        data = "\n\n---\n\n".join(describe_student(session, s, job.week) for s in students) or "No students yet."
        return prompts.digest_messages(job.week, data)

    _run_job(job_id, build)


def run_feedback_draft(job_id: int) -> None:
    def build(session: Session, job: AiJob):
        wlog = session.get(WeeklyLog, job.ref_id)
        student = session.get(User, wlog.student_id)
        parts = [f"Free text:\n{wlog.raw_text}"]
        for e in session.exec(select(LogEntry).where(LogEntry.log_id == wlog.id)):
            project = session.get(Project, e.project_id)
            parts.append(
                f"\nProject {project.title}: progress: {e.progress} | next: {e.next_steps} | "
                f"blockers: {e.blockers} | help question: {e.help_question if e.needs_help else '-'}"
            )
        return prompts.feedback_messages(student.name, "\n".join(parts))

    _run_job(job_id, build)


def run_assist(job_id: int) -> None:
    def build(session: Session, job: AiJob):
        student = session.get(User, job.user_id)
        context = describe_student(session, student, job.week, weeks_back=2)
        return prompts.assist_messages(job.kind, context, job.input_text)

    _run_job(job_id, build)


JOB_RUNNERS = {
    "digest": run_digest,
    "draft_feedback": run_feedback_draft,
    "assist_plan": run_assist,
    "assist_feedback": run_assist,
    "assist_question": run_assist,
}
