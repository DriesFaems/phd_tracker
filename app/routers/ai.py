from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.auth import current_user
from app.db import get_session
from app.models import AiJob, User
from app.web import render

router = APIRouter(prefix="/ai")


@router.get("/job/{job_id}")
def job_partial(job_id: int, request: Request, mode: str = "block", log_id: int | None = None, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Polled by HTMX until the job is done; then returns the final result without the poll trigger."""
    job = session.get(AiJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404)
    return render(request, "partials/job.html", job=job, mode=mode if mode in ("block", "textarea") else "block", log_id=log_id)
