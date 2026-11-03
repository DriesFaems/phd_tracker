from datetime import date
from html import escape

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, func, select

from app.auth import invite_url, new_invite, require_supervisor
from app.db import get_session
from app.llm import client
from app.llm.tasks import extract_log, open_projects, run_digest, run_feedback_draft
from app.models import PROJECT_STATUSES, AiJob, Comment, LogEntry, Milestone, Project, StageChange, User, WeeklyLog, utcnow
from app.status import SEVERITY, latest_entry, project_status, weeks_since_last_log, worst
from app.threads import comments_by_log, mark_read
from app.web import flash, render
from app.weeks import current_week, shift_week

router = APIRouter(prefix="/supervisor")


def _students(session: Session, include_inactive: bool = False) -> list[User]:
    query = select(User).where(User.role == "student").order_by(User.name)
    if not include_inactive:
        query = query.where(User.active == True)  # noqa: E712
    return list(session.exec(query))


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


# ---------- dashboard ----------


@router.get("")
def dashboard(request: Request, week: str | None = None, user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    week = week if week and week <= current_week() else current_week()
    rows, attention = [], []
    for student in _students(session):
        gap = weeks_since_last_log(session, student.id, week)
        this_log = session.exec(select(WeeklyLog).where(WeeklyLog.student_id == student.id, WeeklyLog.week == week)).first()
        cells = []
        for project in open_projects(session, student.id):
            color, reasons = project_status(session, project, week)
            latest = latest_entry(session, project.id, week)
            cells.append({"project": project, "color": color, "reasons": reasons, "latest": latest})
            if color == "amber":
                attention.append({"kind": "amber", "severity": 1, "student": student, "project": project, "reasons": reasons})
        if gap is None or gap >= 2:
            attention.append({"kind": "missing", "severity": 2, "student": student, "gap": gap})
        if this_log and this_log.llm_status == "failed" and this_log.status == "submitted":
            attention.append({"kind": "llm_failed", "severity": 0, "student": student, "log": this_log})
        rows.append({
            "student": student,
            "cells": cells,
            "color": worst([c["color"] for c in cells]) if cells else "grey",
            "closed": session.exec(select(func.count(Project.id)).where(Project.student_id == student.id, Project.status == "closed")).one(),
            "gap": gap,
            "this_log": this_log,
        })

    help_rows = session.exec(
        select(LogEntry, WeeklyLog, Project, User)
        .join(WeeklyLog, WeeklyLog.id == LogEntry.log_id)
        .join(Project, Project.id == LogEntry.project_id)
        .join(User, User.id == WeeklyLog.student_id)
        .where(LogEntry.needs_help == True, LogEntry.resolved_at.is_(None), WeeklyLog.status == "submitted", User.active == True)  # noqa: E712
        .order_by(WeeklyLog.week)
    ).all()
    help_items = [{"kind": "help", "severity": 3, "entry": e, "log": wl, "project": p, "student": s} for e, wl, p, s in help_rows]
    attention = help_items + sorted(attention, key=lambda a: -a["severity"])
    rows.sort(key=lambda r: (-SEVERITY[r["color"]], r["student"].name))
    submitted = sum(1 for r in rows if r["this_log"] and r["this_log"].status == "submitted")
    return render(
        request, "supervisor/dashboard.html", session, user,
        week=week, prev_week=shift_week(week, -1), next_week=shift_week(week, 1) if week < current_week() else None,
        rows=rows, attention=attention, submitted=submitted,
    )


@router.get("/health", response_class=HTMLResponse)
def health(user: User = Depends(require_supervisor)):
    ok, message = client.health()
    color = "green" if ok else "red"
    label = "Ready" if ok else "Unavailable"
    return f'<div class="value health-value"><span class="dot {color}"></span> {label}</div><div class="sub">{escape(message)}</div>'


# ---------- student detail ----------


@router.get("/student/{student_id}")
def student_detail(student_id: int, request: Request, user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    student = session.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(404)
    week = current_week()
    projects = sorted(
        session.exec(select(Project).where(Project.student_id == student.id).order_by(Project.position, Project.id)),
        key=lambda p: PROJECT_STATUSES.index(p.status),
    )
    project_ids = [p.id for p in projects]
    milestones: dict[int, list[Milestone]] = {}
    for m in session.exec(select(Milestone).where(Milestone.project_id.in_(project_ids)).order_by(Milestone.due_date)):
        milestones.setdefault(m.project_id, []).append(m)
    stage_history: dict[int, list[StageChange]] = {}
    for sc in session.exec(select(StageChange).where(StageChange.project_id.in_(project_ids)).order_by(StageChange.changed_at)):
        stage_history.setdefault(sc.project_id, []).append(sc)
    statuses = {p.id: project_status(session, p, week) for p in projects}

    logs = session.exec(
        select(WeeklyLog).where(WeeklyLog.student_id == student.id, WeeklyLog.status == "submitted").order_by(WeeklyLog.week.desc()).limit(26)
    ).all()
    log_ids = [wl.id for wl in logs]
    entries: dict[int, list[LogEntry]] = {}
    for e in session.exec(select(LogEntry).where(LogEntry.log_id.in_(log_ids))):
        entries.setdefault(e.log_id, []).append(e)
    comments = comments_by_log(session, log_ids)
    unread_ids = {c.id for cs in comments.values() for c, _ in cs if c.read_at is None and c.author_id != user.id}
    mark_read(session, user, log_ids)
    return render(
        request, "supervisor/student.html", session, user,
        student=student, projects=projects, project_map={p.id: p for p in projects}, milestones=milestones,
        stage_history=stage_history, statuses=statuses, logs=logs, entries=entries, comments=comments,
        unread_ids=unread_ids, today=date.today(),
    )


# ---------- feedback ----------


@router.post("/log/{log_id}/comment")
def comment(
    log_id: int,
    request: Request,
    body: str = Form(...),
    entry_id: int | None = Form(None),
    resolve: str | None = Form(None),
    next: str = Form("/supervisor"),
    user: User = Depends(require_supervisor),
    session: Session = Depends(get_session),
):
    wlog = session.get(WeeklyLog, log_id)
    if not wlog:
        raise HTTPException(404)
    entry = session.get(LogEntry, entry_id) if entry_id else None
    if entry and entry.log_id != wlog.id:
        raise HTTPException(400)
    if body.strip():
        session.add(Comment(log_id=wlog.id, entry_id=entry.id if entry else None, author_id=user.id, body=body.strip()))
    if entry and resolve == "on":
        entry.resolved_at = utcnow()
        session.add(entry)
    session.commit()
    if _is_htmx(request):
        done = " and marked as resolved" if entry and resolve == "on" else ""
        return HTMLResponse(f'<div class="att-done" role="status">✓ Reply sent{done}.</div>')
    flash(request, "Feedback sent.")
    return RedirectResponse(next if next.startswith("/supervisor") else "/supervisor", 303)


@router.post("/entry/{entry_id}/resolve")
def resolve(entry_id: int, request: Request, user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    entry = session.get(LogEntry, entry_id)
    if not entry:
        raise HTTPException(404)
    entry.resolved_at = utcnow()
    session.add(entry)
    session.commit()
    if _is_htmx(request):
        return HTMLResponse('<div class="att-done" role="status">✓ Marked as resolved.</div>')
    return RedirectResponse("/supervisor", 303)


@router.post("/log/{log_id}/draft")
def draft_feedback(log_id: int, request: Request, background: BackgroundTasks, user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    if not session.get(WeeklyLog, log_id):
        raise HTTPException(404)
    job = AiJob(user_id=user.id, kind="draft_feedback", ref_id=log_id)
    session.add(job)
    session.commit()
    background.add_task(run_feedback_draft, job.id)
    return render(request, "partials/job.html", job=job, mode="textarea", log_id=log_id)


@router.post("/log/{log_id}/retry")
def retry_extraction(log_id: int, request: Request, background: BackgroundTasks, user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    wlog = session.get(WeeklyLog, log_id)
    if not wlog:
        raise HTTPException(404)
    wlog.llm_status = "pending"
    session.add(wlog)
    session.commit()
    background.add_task(extract_log, wlog.id)
    flash(request, "Re-running AI extraction in the background.")
    return RedirectResponse(request.headers.get("referer") or "/supervisor", 303)


# ---------- digest ----------


@router.get("/digest")
def digest_page(request: Request, job_id: int | None = None, user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    digests = session.exec(select(AiJob).where(AiJob.kind == "digest").order_by(AiJob.created_at.desc()).limit(30)).all()
    selected = next((d for d in digests if d.id == job_id), digests[0] if digests else None)
    return render(request, "supervisor/digest.html", session, user, digests=digests, selected=selected, week=current_week())


@router.post("/digest")
def create_digest(background: BackgroundTasks, week: str = Form(...), user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    job = AiJob(user_id=user.id, kind="digest", week=week if week <= current_week() else current_week())
    session.add(job)
    session.commit()
    background.add_task(run_digest, job.id)
    return RedirectResponse(f"/supervisor/digest?job_id={job.id}", 303)


# ---------- students ----------


@router.get("/students")
def students_page(request: Request, user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    students = _students(session, include_inactive=True)
    invites = {s.id: invite_url(s) for s in students if s.invite_token}
    return render(request, "supervisor/students.html", session, user, students=students, invites=invites, now=utcnow())


@router.post("/students")
def add_student(request: Request, name: str = Form(...), email: str = Form(...), user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    email = email.strip().lower()
    if session.exec(select(User).where(User.email == email)).first():
        flash(request, f"A user with email {email} already exists.", "error")
        return RedirectResponse("/supervisor/students", 303)
    student = User(name=name.strip(), email=email, role="student")
    new_invite(student)
    session.add(student)
    session.commit()
    flash(request, f"Student added. Send {student.name} the invite link shown below.")
    return RedirectResponse("/supervisor/students", 303)


@router.post("/students/{student_id}/{action}")
def student_action(student_id: int, action: str, request: Request, user: User = Depends(require_supervisor), session: Session = Depends(get_session)):
    student = session.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(404)
    if action == "invite":
        new_invite(student)
        flash(request, f"New invite link created for {student.name}.")
    elif action == "toggle":
        student.active = not student.active
        flash(request, f"{student.name} {'re-activated' if student.active else 'deactivated'}.")
    else:
        raise HTTPException(404)
    session.add(student)
    session.commit()
    return RedirectResponse("/supervisor/students", 303)
