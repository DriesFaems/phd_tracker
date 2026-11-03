import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app import db
from app.auth import LoginRequired
from app.config import BASE_DIR, get_settings
from app.llm.tasks import JOB_RUNNERS, extract_log
from app.models import AiJob, WeeklyLog
from app.routers import ai, auth_routes, student, supervisor
from app.web import render

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def resume_unfinished_work() -> None:
    """Re-queue LLM work that was interrupted by a restart or failed because Ollama was down."""
    import threading

    with Session(db.engine) as session:
        log_ids = session.exec(
            select(WeeklyLog.id).where(WeeklyLog.status == "submitted", WeeklyLog.llm_status.in_(["pending", "failed"]))
        ).all()
        jobs = session.exec(select(AiJob.id, AiJob.kind).where(AiJob.status == "pending")).all()

    def work():
        for log_id in log_ids:
            extract_log(log_id)
        for job_id, kind in jobs:
            JOB_RUNNERS[kind](job_id)

    if log_ids or jobs:
        log.info("Resuming %d log extraction(s) and %d AI job(s)", len(log_ids), len(jobs))
        threading.Thread(target=work, daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.run_migrations()
    resume_unfinished_work()
    yield


def create_app(run_startup: bool = True) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PhD Supervision Tracker", lifespan=lifespan if run_startup else None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site="lax",
        https_only=settings.secure_cookies,
        max_age=60 * 60 * 24 * 30,
    )
    app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
    for r in (auth_routes.router, student.router, supervisor.router, ai.router):
        app.include_router(r)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _: LoginRequired):
        if request.headers.get("HX-Request") == "true":
            return RedirectResponse("/login", 303, headers={"HX-Redirect": "/login"})
        return RedirectResponse("/login", 303)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        titles = {403: "Not allowed", 404: "Not found"}
        response = render(request, "message.html", title=titles.get(exc.status_code, "Error"), message=str(exc.detail))
        response.status_code = exc.status_code
        return response

    return app


app = create_app()
