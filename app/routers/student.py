from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.auth import require_student
from app.db import get_session
from app.llm import prompts
from app.llm.tasks import extract_log, open_projects, run_assist
from app.models import PROJECT_STATUSES, STAGES, AiJob, Comment, LogEntry, Milestone, Project, StageChange, User, WeeklyLog, utcnow
from app.threads import comments_by_log, mark_read
from app.web import flash, render
from app.weeks import current_week, shift_week

router = APIRouter(prefix="/student")


def _own_project(session: Session, user: User, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if not project or project.student_id != user.id:
        raise HTTPException(404)
    return project


def _own_log(session: Session, user: User, log_id: int) -> WeeklyLog:
    wlog = session.get(WeeklyLog, log_id)
    if not wlog or wlog.student_id != user.id:
        raise HTTPException(404)
    return wlog


def _valid_week(week: str | None) -> str:
    this = current_week()
    if not week:
        return this
    try:
        shift_week(week, 0)
    except ValueError:
        return this
    return min(week, this)


@router.get("")
def home():
    return RedirectResponse("/student/week", 303)


# ---------- weekly log ----------


@router.get("/week")
def week_page(request: Request, week: str | None = None, user: User = Depends(require_student), session: Session = Depends(get_session)):
    week = _valid_week(week)
    wlog = session.exec(select(WeeklyLog).where(WeeklyLog.student_id == user.id, WeeklyLog.week == week)).first()
    comments = comments_by_log(session, [wlog.id]) if wlog else {}
    if wlog:
        mark_read(session, user, [wlog.id])
    return render(
        request,
        "student/week.html",
        session,
        user,
        week=week,
        prev_week=shift_week(week, -1),
        next_week=shift_week(week, 1) if week < current_week() else None,
        wlog=wlog,
        projects=open_projects(session, user.id),
        comments=comments.get(wlog.id, []) if wlog else [],
    )


@router.post("/week")
def save_week(
    request: Request,
    background: BackgroundTasks,
    week: str = Form(...),
    raw_text: str = Form(""),
    action: str = Form("analyse"),
    user: User = Depends(require_student),
    session: Session = Depends(get_session),
):
    week = _valid_week(week)
    if not raw_text.strip():
        flash(request, "Write a few lines about your week first.", "error")
        return RedirectResponse(f"/student/week?week={week}", 303)
    wlog = session.exec(select(WeeklyLog).where(WeeklyLog.student_id == user.id, WeeklyLog.week == week)).first()
    if not wlog:
        wlog = WeeklyLog(student_id=user.id, week=week)
    wlog.raw_text = raw_text.strip()
    wlog.llm_status = "pending"
    if action == "submit_raw":
        wlog.status = "submitted"
        wlog.submitted_at = wlog.submitted_at or utcnow()
        flash(request, "Log submitted. The AI will structure it in the background.")
    session.add(wlog)
    session.commit()
    background.add_task(extract_log, wlog.id)
    return RedirectResponse(f"/student/week?week={week}#review", 303)


@router.get("/log/{log_id}/review")
def review_partial(log_id: int, request: Request, user: User = Depends(require_student), session: Session = Depends(get_session)):
    wlog = _own_log(session, user, log_id)
    entries = {e.project_id: e for e in session.exec(select(LogEntry).where(LogEntry.log_id == wlog.id))}
    return render(
        request,
        "partials/review.html",
        wlog=wlog,
        projects=open_projects(session, user.id),
        entries=entries,
    )


@router.post("/log/{log_id}/retry")
def retry_extraction(log_id: int, background: BackgroundTasks, user: User = Depends(require_student), session: Session = Depends(get_session)):
    wlog = _own_log(session, user, log_id)
    wlog.llm_status = "pending"
    session.add(wlog)
    session.commit()
    background.add_task(extract_log, wlog.id)
    return RedirectResponse(f"/student/week?week={wlog.week}#review", 303)


@router.post("/log/{log_id}/confirm")
async def confirm_log(log_id: int, request: Request, user: User = Depends(require_student), session: Session = Depends(get_session)):
    wlog = _own_log(session, user, log_id)
    form = await request.form()
    existing = {e.project_id: e for e in session.exec(select(LogEntry).where(LogEntry.log_id == wlog.id))}
    for project in open_projects(session, user.id):
        pid = project.id
        fields = {
            "progress": str(form.get(f"progress_{pid}", "")).strip(),
            "next_steps": str(form.get(f"next_{pid}", "")).strip(),
            "blockers": str(form.get(f"blockers_{pid}", "")).strip(),
            "help_question": str(form.get(f"question_{pid}", "")).strip(),
        }
        needs_help = form.get(f"help_{pid}") == "on"
        momentum_raw = str(form.get(f"momentum_{pid}", ""))
        momentum = int(momentum_raw) if momentum_raw.isdigit() and 1 <= int(momentum_raw) <= 5 else None
        entry = existing.get(pid)
        if not any(fields.values()) and not needs_help:
            if entry and not entry.resolved_at:
                session.delete(entry)
            continue
        entry = entry or LogEntry(log_id=wlog.id, project_id=pid)
        for key, value in fields.items():
            setattr(entry, key, value)
        if needs_help and not entry.needs_help:
            entry.resolved_at = None  # a new help request reopens the item
        entry.needs_help = needs_help
        entry.momentum = momentum
        entry.confirmed = True
        session.add(entry)
    wlog.status = "submitted"
    wlog.submitted_at = wlog.submitted_at or utcnow()
    session.add(wlog)
    session.commit()
    flash(request, "Weekly log submitted. Thanks!")
    return RedirectResponse(f"/student/week?week={wlog.week}", 303)


# ---------- history & comments ----------


@router.get("/history")
def history(request: Request, user: User = Depends(require_student), session: Session = Depends(get_session)):
    logs = session.exec(select(WeeklyLog).where(WeeklyLog.student_id == user.id).order_by(WeeklyLog.week.desc())).all()
    ids = [wl.id for wl in logs]
    entries: dict[int, list[LogEntry]] = {}
    for e in session.exec(select(LogEntry).where(LogEntry.log_id.in_(ids))):
        entries.setdefault(e.log_id, []).append(e)
    comments = comments_by_log(session, ids)
    unread_ids = {c.id for cs in comments.values() for c, _ in cs if c.read_at is None and c.author_id != user.id}
    mark_read(session, user, ids)
    projects = {p.id: p for p in session.exec(select(Project).where(Project.student_id == user.id))}
    return render(
        request, "student/history.html", session, user,
        logs=logs, entries=entries, comments=comments, projects=projects, unread_ids=unread_ids,
    )


@router.post("/log/{log_id}/comment")
def add_comment(log_id: int, request: Request, body: str = Form(...), next: str = Form("/student/history"), user: User = Depends(require_student), session: Session = Depends(get_session)):
    wlog = _own_log(session, user, log_id)
    if body.strip():
        session.add(Comment(log_id=wlog.id, author_id=user.id, body=body.strip()))
        session.commit()
        flash(request, "Reply sent.")
    return RedirectResponse(next if next.startswith("/student") else "/student/history", 303)


# ---------- projects & milestones ----------


@router.get("/projects")
def projects_page(request: Request, user: User = Depends(require_student), session: Session = Depends(get_session)):
    projects = sorted(
        session.exec(select(Project).where(Project.student_id == user.id).order_by(Project.position, Project.id)),
        key=lambda p: PROJECT_STATUSES.index(p.status),
    )
    milestones: dict[int, list[Milestone]] = {}
    for m in session.exec(select(Milestone).where(Milestone.project_id.in_([p.id for p in projects])).order_by(Milestone.due_date)):
        milestones.setdefault(m.project_id, []).append(m)
    return render(request, "student/projects.html", session, user, projects=projects, milestones=milestones, today=date.today())


@router.post("/projects")
def create_project(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    target_journal: str = Form(""),
    stage: str = Form("Idea"),
    user: User = Depends(require_student),
    session: Session = Depends(get_session),
):
    last = session.exec(select(Project.position).where(Project.student_id == user.id).order_by(Project.position.desc())).first()
    project = Project(
        student_id=user.id, title=title.strip(), description=description.strip(),
        target_journal=target_journal.strip(), stage=stage if stage in STAGES else "Idea", position=(last or 0) + 1,
    )
    session.add(project)
    session.commit()
    session.add(StageChange(project_id=project.id, stage=project.stage))
    session.commit()
    flash(request, f"Project '{project.title}' added.")
    return RedirectResponse("/student/projects", 303)


@router.post("/projects/{project_id}")
def update_project(
    project_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    target_journal: str = Form(""),
    stage: str = Form(...),
    position: int = Form(1),
    status: str = Form("active"),
    user: User = Depends(require_student),
    session: Session = Depends(get_session),
):
    project = _own_project(session, user, project_id)
    if stage in STAGES and stage != project.stage:
        project.stage = stage
        session.add(StageChange(project_id=project.id, stage=stage))
    project.title = title.strip()
    project.description = description.strip()
    project.target_journal = target_journal.strip()
    project.position = position
    _set_status(project, status)
    session.add(project)
    session.commit()
    flash(request, "Project updated.")
    return RedirectResponse(f"/student/projects#p{project.id}", 303)


@router.post("/projects/{project_id}/status")
def change_status(project_id: int, request: Request, status: str = Form(...), user: User = Depends(require_student), session: Session = Depends(get_session)):
    project = _own_project(session, user, project_id)
    _set_status(project, status)
    session.add(project)
    session.commit()
    flash(request, f"'{project.title}' is now {project.status}.")
    return RedirectResponse(f"/student/projects#p{project.id}", 303)


def _set_status(project: Project, status: str) -> None:
    if status in PROJECT_STATUSES and status != project.status:
        project.status = status
        project.status_changed_at = utcnow()


@router.post("/projects/{project_id}/milestones")
def add_milestone(
    project_id: int,
    title: str = Form(...),
    due_date: str = Form(""),
    user: User = Depends(require_student),
    session: Session = Depends(get_session),
):
    project = _own_project(session, user, project_id)
    session.add(Milestone(project_id=project.id, title=title.strip(), due_date=date.fromisoformat(due_date) if due_date else None))
    session.commit()
    return RedirectResponse(f"/student/projects#p{project.id}", 303)


@router.post("/milestones/{milestone_id}/{action}")
def milestone_action(milestone_id: int, action: str, user: User = Depends(require_student), session: Session = Depends(get_session)):
    milestone = session.get(Milestone, milestone_id)
    if not milestone:
        raise HTTPException(404)
    _own_project(session, user, milestone.project_id)
    if action == "toggle":
        milestone.done_at = None if milestone.done_at else utcnow()
        session.add(milestone)
    elif action == "delete":
        session.delete(milestone)
    else:
        raise HTTPException(404)
    session.commit()
    return RedirectResponse(f"/student/projects#p{milestone.project_id}", 303)


# ---------- AI assist ----------


@router.get("/assist")
def assist_page(request: Request, user: User = Depends(require_student), session: Session = Depends(get_session)):
    jobs = session.exec(
        select(AiJob).where(AiJob.user_id == user.id, AiJob.kind.startswith("assist_")).order_by(AiJob.created_at.desc()).limit(10)
    ).all()
    return render(request, "student/assist.html", session, user, jobs=jobs, labels=prompts.ASSIST_LABELS)


@router.post("/assist")
def assist(
    request: Request,
    background: BackgroundTasks,
    kind: str = Form(...),
    input_text: str = Form(""),
    user: User = Depends(require_student),
    session: Session = Depends(get_session),
):
    if kind not in prompts.ASSIST_LABELS:
        raise HTTPException(400)
    job = AiJob(user_id=user.id, kind=kind, input_text=input_text.strip(), week=current_week())
    session.add(job)
    session.commit()
    background.add_task(run_assist, job.id)
    return RedirectResponse("/student/assist", 303)
