"""Comment threads on weekly logs."""

from sqlmodel import Session, select

from app.models import Comment, User, utcnow


def comments_by_log(session: Session, log_ids: list[int]) -> dict[int, list[tuple[Comment, User]]]:
    result: dict[int, list[tuple[Comment, User]]] = {}
    if not log_ids:
        return result
    rows = session.exec(
        select(Comment, User).join(User, User.id == Comment.author_id).where(Comment.log_id.in_(log_ids)).order_by(Comment.created_at)
    )
    for comment, author in rows:
        result.setdefault(comment.log_id, []).append((comment, author))
    return result


def mark_read(session: Session, user: User, log_ids: list[int]) -> None:
    if not log_ids:
        return
    unread = session.exec(
        select(Comment).where(Comment.log_id.in_(log_ids), Comment.author_id != user.id, Comment.read_at.is_(None))
    ).all()
    for c in unread:
        c.read_at = utcnow()
        session.add(c)
    if unread:
        session.commit()
