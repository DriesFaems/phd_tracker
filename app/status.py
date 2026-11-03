"""Traffic-light rules for the supervisor dashboard."""

from datetime import date, timedelta

from sqlmodel import Session, select

from app.models import LogEntry, Milestone, Project, WeeklyLog
from app.weeks import week_of, weeks_between

MISSING_LOG_WEEKS = 2  # red when the last log is this many weeks old
STALL_WEEKS = 3  # amber when a project got no update for this many weeks
LOW_MOMENTUM = 2  # amber when the last two entries are at or below this
NO_STALL_STAGES = {"Submitted", "Accepted"}  # waiting on journals is not stalling

SEVERITY = {"red": 3, "amber": 2, "grey": 1, "green": 0}


def last_log_week(session: Session, student_id: int, week: str) -> str | None:
    return session.exec(
        select(WeeklyLog.week)
        .where(WeeklyLog.student_id == student_id, WeeklyLog.status == "submitted", WeeklyLog.week <= week)
        .order_by(WeeklyLog.week.desc())
    ).first()


def weeks_since_last_log(session: Session, student_id: int, week: str) -> int | None:
    last = last_log_week(session, student_id, week)
    return None if last is None else weeks_between(last, week)


def _entries(session: Session, project_id: int, week: str):
    return session.exec(
        select(LogEntry, WeeklyLog.week)
        .join(WeeklyLog, WeeklyLog.id == LogEntry.log_id)
        .where(LogEntry.project_id == project_id, WeeklyLog.status == "submitted", WeeklyLog.week <= week)
        .order_by(WeeklyLog.week.desc())
    ).all()


def project_status(session: Session, project: Project, week: str) -> tuple[str, list[str]]:
    if project.status == "closed":
        return "grey", ["closed"]
    red, amber = [], []
    gap = weeks_since_last_log(session, project.student_id, week)
    entries = _entries(session, project.id, week)

    if any(e.needs_help and not e.resolved_at for e, _ in entries):
        red.append("asks for help")
    if project.status == "inactive":
        # Paused projects only raise help requests; no stall or momentum warnings.
        paused = "inactive"
        if project.status_changed_at:
            paused += f" since {project.status_changed_at:%d %b %Y}"
        return ("red", red + [paused]) if red else ("grey", [paused])
    if gap is not None and gap >= MISSING_LOG_WEEKS:
        red.append(f"no weekly log for {gap} weeks")

    recent = [e.momentum for e, _ in entries[:2] if e.momentum is not None]
    if len(recent) == 2 and all(m <= LOW_MOMENTUM for m in recent):
        amber.append("low momentum two weeks in a row")
    overdue = session.exec(
        select(Milestone).where(
            Milestone.project_id == project.id, Milestone.done_at.is_(None), Milestone.due_date < date.today()
        )
    ).all()
    if overdue:
        amber.append(f"{len(overdue)} overdue milestone{'s' if len(overdue) > 1 else ''}")
    if gap is not None and project.stage not in NO_STALL_STAGES:
        # The stall clock starts at creation, the last logged progress, or the last (re)activation.
        candidates = [week_of(project.created_at.date())]
        if project.status_changed_at:
            candidates.append(week_of(project.status_changed_at.date()))
        last_update = next((w for e, w in entries if e.progress.strip()), None)
        if last_update:
            candidates.append(last_update)
        reference = max(candidates)
        if weeks_between(reference, week) >= STALL_WEEKS:
            amber.append(f"no progress logged for {weeks_between(reference, week)} weeks")

    if red:
        return "red", red + amber
    if amber:
        return "amber", amber
    if gap is None:
        return "grey", ["no weekly logs yet"]
    return "green", []


def latest_entry(session: Session, project_id: int, week: str) -> tuple[LogEntry, str] | None:
    rows = _entries(session, project_id, week)
    return rows[0] if rows else None


def worst(colors: list[str]) -> str:
    return max(colors, key=lambda c: SEVERITY[c]) if colors else "grey"


def due_soon(session: Session, project_id: int, days: int = 14) -> list[Milestone]:
    return list(
        session.exec(
            select(Milestone)
            .where(
                Milestone.project_id == project_id,
                Milestone.done_at.is_(None),
                Milestone.due_date <= date.today() + timedelta(days=days),
            )
            .order_by(Milestone.due_date)
        )
    )

