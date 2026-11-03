"""Template rendering helpers shared by all routers."""

import html
import re
from datetime import datetime, timedelta, timezone

import markdown as md
from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlmodel import Session, func, select

from app.config import BASE_DIR
from app.models import PROJECT_STATUSES, STAGES, Comment, User, WeeklyLog
from app.weeks import current_week, week_label, week_start

templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


def render_markdown(text: str) -> Markup:
    # LLM output can echo student text, so escape raw HTML before rendering markdown.
    rendered = md.markdown(html.escape(text or "", quote=False), extensions=["sane_lists", "nl2br"])
    rendered = re.sub(r'href="(?!https?://)[^"]*"', 'href="#"', rendered)
    return Markup(rendered)


def initials(name: str) -> str:
    parts = [p for p in (name or "?").split() if p]
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def time_ago(value: datetime | None) -> str:
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - value).total_seconds()
    if seconds < 60:
        return "just now"
    for unit, size in (("minute", 60), ("hour", 3600), ("day", 86400)):
        n = int(seconds // size)
        if unit == "minute" and n < 60 or unit == "hour" and n < 24 or unit == "day" and n < 14:
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return value.astimezone().strftime("%d %b %Y")


def week_range(week: str) -> str:
    start = week_start(week)
    end = start + timedelta(days=6)
    return f"{start:%d %b} – {end:%d %b}"


templates.env.filters["markdown"] = render_markdown
templates.env.filters["week_label"] = week_label
templates.env.filters["week_range"] = week_range
templates.env.filters["week_num"] = lambda w: "Week " + w.split("-W")[1].lstrip("0")
templates.env.filters["localtime"] = lambda v: v.astimezone() if isinstance(v, datetime) else v
templates.env.filters["initials"] = initials
templates.env.filters["ucfirst"] = lambda s: s[:1].upper() + s[1:] if s else s
templates.env.filters["ago"] = time_ago
templates.env.filters["firstname"] = lambda n: (n or "").split(" ")[0]
templates.env.globals["STAGES"] = STAGES
templates.env.globals["PROJECT_STATUSES"] = PROJECT_STATUSES
templates.env.globals["MOMENTUM"] = {1: "Stuck", 2: "Slow", 3: "Steady", 4: "Good", 5: "Great"}


def unread_count(session: Session, user: User) -> int:
    query = select(func.count(Comment.id)).join(WeeklyLog, WeeklyLog.id == Comment.log_id).where(
        Comment.read_at.is_(None), Comment.author_id != user.id
    )
    if user.role == "student":
        query = query.where(WeeklyLog.student_id == user.id)
    return session.exec(query).one()


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append({"message": message, "kind": kind})


def render(request: Request, name: str, session: Session | None = None, user: User | None = None, **ctx):
    ctx.update(
        user=user,
        unread=unread_count(session, user) if (session and user) else 0,
        flashes=request.session.pop("flash", []),
        this_week=current_week(),
        path=request.url.path,
    )
    return templates.TemplateResponse(request, name, ctx)
