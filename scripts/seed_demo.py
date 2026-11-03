"""Fill an EMPTY database with demo data: 1 supervisor, 3 students with 1-4 projects each, several weeks of logs.

Usage:  .venv\\Scripts\\python -m scripts.seed_demo
Only for local testing; it refuses to run if users already exist.
"""

from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from app import db
from app.auth import hash_password
from app.models import Comment, LogEntry, Milestone, Project, StageChange, User, WeeklyLog
from app.weeks import current_week, shift_week, week_start

DEMO_PASSWORD = "demo-password-123"

STUDENTS = [
    ("Anna Peeters", "anna@example.test", [
        ("Corporate venturing and ambidexterity", "Multiple case study of 8 CVC units", "Writing", "Strategic Management Journal"),
        ("Alliance governance in deep tech", "Panel data on 400 biotech alliances", "Analysis", "Organization Science"),
        ("Effectual decision-making of scientists", "Think-aloud experiments with academic founders", "Design", "Journal of Business Venturing"),
        ("Master thesis spin-off paper", "Short paper from master thesis data", "Writing", "", "closed"),
    ]),
    ("Ben Schmidt", "ben@example.test", [
        ("Open innovation and patent quality", "Patent data, diff-in-diff around policy change", "Data collection", "Research Policy"),
    ]),
    ("Chiara Rossi", "chiara@example.test", [
        ("Trust repair after alliance failure", "Process study, longitudinal interviews", "Data collection", "Academy of Management Journal"),
        ("Contracts and relational governance", "Survey of 250 R&D partnerships", "Analysis", "Strategic Management Journal"),
        ("AI adoption in startups", "Mixed methods", "Idea", "", "inactive"),
    ]),
]

# (weeks ago, text, entries per project index: (progress, next, blockers, needs_help, question, momentum))
LOGS = {
    "anna@example.test": [
        (3, "Worked on the CVC paper discussion and ran first models for the alliance paper.", {
            0: ("Rewrote discussion section around ambidexterity tensions", "Send full draft", "", False, "", 4),
            1: ("First regression models run; results in expected direction", "Robustness checks", "", False, "", 4),
        }),
        (2, "Full CVC draft almost ready. Alliance robustness checks ongoing.", {
            0: ("Completed introduction and discussion", "Polish and send draft", "", False, "", 4),
            1: ("Robustness checks with alternative measures", "Write results section", "Endogeneity concerns from a reviewer at a conference", False, "", 3),
        }),
        (1, "Sent CVC draft. Stuck on endogeneity in alliance paper.", {
            0: ("Sent full draft to supervisor", "Wait for feedback", "", False, "", 4),
            1: ("Tried an IV approach but instrument is weak", "Decide on identification strategy", "Weak instrument (F=4)", True,
                "Should I go for a Heckman two-step or reframe the paper as descriptive?", 2),
            2: ("Read 5 papers on effectuation experiments", "Draft experimental design", "", False, "", 3),
        }),
    ],
    "ben@example.test": [
        (4, "Downloaded PATSTAT data, cleaning ongoing.", {
            0: ("Downloaded PATSTAT extract and started cleaning", "Finish cleaning", "Server is slow", False, "", 3),
        }),
        (3, "Still cleaning data, teaching took most of the week.", {
            0: ("Some cleaning, mostly teaching", "Continue cleaning", "Teaching load", False, "", 2),
        }),
    ],
    "chiara@example.test": [
        (1, "Six interviews done for trust repair study; survey analysis started.", {
            0: ("Conducted 6 interviews with alliance managers", "Transcribe and code", "", False, "", 4),
            1: ("Cleaned survey data, first descriptives", "CFA for measurement model", "", False, "", 4),
        }),
        (0, "Coding interviews, and CFA shows poor fit for relational governance scale.", {
            0: ("Coded 4 interviews, first codebook", "Code remaining interviews", "", False, "", 4),
            1: ("Ran CFA; relational governance scale has poor fit (CFI .82)", "Fix measurement model", "Poor model fit", True,
                "Can I drop two items from the established scale, or do I need to justify a new scale?", 2),
        }),
    ],
}


def main() -> None:
    db.run_migrations()
    with Session(db.engine) as session:
        if session.exec(select(User)).first():
            print("Database already has users; not seeding.")
            return
        sup = User(name="Demo Supervisor", email="supervisor@example.test", role="supervisor", password_hash=hash_password(DEMO_PASSWORD))
        session.add(sup)
        session.commit()
        created = datetime.combine(week_start(shift_week(current_week(), -8)), datetime.min.time(), tzinfo=timezone.utc)
        for name, email, projects in STUDENTS:
            student = User(name=name, email=email, role="student", password_hash=hash_password(DEMO_PASSWORD))
            session.add(student)
            session.commit()
            pids = []
            for i, (title, desc, stage, journal, *rest) in enumerate(projects, start=1):
                status = rest[0] if rest else "active"
                p = Project(student_id=student.id, title=title, description=desc, stage=stage, target_journal=journal, position=i,
                            created_at=created, status=status, status_changed_at=created + timedelta(weeks=2) if status != "active" else None)
                session.add(p)
                session.commit()
                session.add(StageChange(project_id=p.id, stage=stage, changed_at=created))
                pids.append(p.id)
            session.add(Milestone(project_id=pids[0], title="Full draft to supervisor", due_date=date.today() + timedelta(days=10)))
            if len(pids) > 1:
                session.add(Milestone(project_id=pids[1], title="Results section", due_date=date.today() - timedelta(days=5)))
            for weeks_ago, text, entries in LOGS[email]:
                week = shift_week(current_week(), -weeks_ago)
                submitted = datetime.combine(week_start(week) + timedelta(days=4), datetime.min.time(), tzinfo=timezone.utc)
                wl = WeeklyLog(student_id=student.id, week=week, raw_text=text, summary=text, status="submitted", llm_status="done", submitted_at=submitted)
                session.add(wl)
                session.commit()
                for idx, (prog, nxt, block, help_, q, mom) in entries.items():
                    session.add(LogEntry(log_id=wl.id, project_id=pids[idx], progress=prog, next_steps=nxt, blockers=block,
                                         needs_help=help_, help_question=q, momentum=mom, confirmed=True))
                if weeks_ago == 2 and email == "anna@example.test":
                    session.add(Comment(log_id=wl.id, author_id=sup.id, body="Great progress on the discussion. Looking forward to the full draft!"))
            session.commit()
    print(f"Seeded demo data. Logins: supervisor@example.test, anna@/ben@/chiara@example.test (password in {__file__}).")


if __name__ == "__main__":
    main()
