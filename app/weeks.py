from datetime import date, timedelta


def week_of(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def current_week() -> str:
    return week_of(date.today())


def week_start(week: str) -> date:
    year, w = week.split("-W")
    return date.fromisocalendar(int(year), int(w), 1)


def shift_week(week: str, n: int) -> str:
    return week_of(week_start(week) + timedelta(weeks=n))


def weeks_between(older: str, newer: str) -> int:
    return (week_start(newer) - week_start(older)).days // 7


def week_label(week: str) -> str:
    start = week_start(week)
    end = start + timedelta(days=6)
    return f"{week} ({start:%d %b} – {end:%d %b})"
