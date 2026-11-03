"""All prompt templates live here so they are easy to tune."""

from pydantic import BaseModel, Field


class ExtractedEntry(BaseModel):
    project_id: int
    progress: str = ""
    next_steps: str = ""
    blockers: str = ""
    needs_help: bool = False
    help_question: str = ""
    momentum: int | None = Field(default=None, ge=1, le=5)


class Extraction(BaseModel):
    summary: str = ""
    entries: list[ExtractedEntry] = []


EXTRACT_SYSTEM = """You help a PhD supervisor follow up on their students.
You receive a PhD student's free-text weekly progress log and the list of their research projects.
Split the log into structured information per project.

Rules:
- Only use information that is in the log. Do not invent progress.
- Match text to projects by title, topic or description. Work that fits no project goes into the summary.
- A student can have any number of projects. Projects marked "inactive" are paused; only include them if the log mentions them.
- Leave fields empty ("") when the log says nothing about them. Only include projects that the log mentions.
- progress: what was concretely done this week (1-3 short sentences). If the student says they did not
  work on a project, leave progress empty and put the reason in blockers.
- next_steps: what the student plans next.
- blockers: what slows the student down or where they are stuck.
- needs_help: true only if the student is stuck or explicitly asks for supervisor input.
- help_question: if needs_help, phrase one clear question the supervisor can answer quickly.
- momentum: 1 = stuck / no progress, 2 = slow, 3 = steady, 4 = good, 5 = excellent.
- summary: one or two sentences about the student's week overall.
Write in the same language as the log. Answer with JSON only."""


def extract_messages(projects: list[dict], raw_text: str, previous: list[str]) -> list[dict]:
    project_lines = "\n".join(
        f"- id {p['id']}: {p['title']} ({p.get('status', 'active')}, stage: {p['stage']}) — {p['description']}" for p in projects
    )
    context = ""
    if previous:
        context = "\n\nFor context, summaries of the student's previous weeks:\n" + "\n".join(f"- {s}" for s in previous)
    return [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": f"Projects:\n{project_lines}{context}\n\nThis week's log:\n\"\"\"\n{raw_text}\n\"\"\""},
    ]


DIGEST_SYSTEM = """You are the assistant of a busy PhD supervisor. Write a concise weekly digest in Markdown
that lets the supervisor understand in 5 minutes how all their PhD students are doing.

Structure:
## Needs your attention
Bullet list of students/projects that are stuck, ask for help, have low momentum, missed their log, or have overdue milestones. Be specific.
## Per student
For each student a `### Name` heading, then one short bullet per active project (mention paused/inactive projects only
if something happened or they have been paused long), and one line
**Talking points:** with 1-3 concrete questions or suggestions for the next meeting.

Be factual and brief. Do not invent anything beyond the data given.
Refer to students by first name; do not guess pronouns from names (use "they" if needed)."""


def digest_messages(week: str, data: str) -> list[dict]:
    return [
        {"role": "system", "content": DIGEST_SYSTEM},
        {"role": "user", "content": f"Week {week}. Data per student:\n\n{data}"},
    ]


FEEDBACK_SYSTEM = """You draft feedback from a PhD supervisor to their student about the student's weekly log.
The supervisor will edit your draft before sending. Write in a warm, direct and constructive tone,
in the first person as the supervisor, in the language of the log. Keep it short (80-150 words):
acknowledge concrete progress, answer or address any help question as far as possible,
and give one or two concrete suggestions for next week. No greeting line or signature."""


def feedback_messages(student_name: str, log_text: str) -> list[dict]:
    return [
        {"role": "system", "content": FEEDBACK_SYSTEM},
        {"role": "user", "content": f"Student: {student_name}\n\nWeekly log and structured entries:\n{log_text}"},
    ]


ASSIST_SYSTEMS = {
    "assist_plan": """You are a supportive academic coach for a PhD student in management research.
Based on their projects and recent progress, propose a realistic plan for next week:
3-5 prioritized, concrete tasks with an estimate of effort, and point out one risk to watch. Use Markdown.""",
    "assist_feedback": """You are an experienced reviewer for top management journals (AMJ, SMJ, ASQ, Org Science).
Give constructive feedback on the text the PhD student provides: what works, the 3 most important
improvements (clarity of argument, contribution, logic, writing), and a suggested rewrite of the weakest sentence. Use Markdown.""",
    "assist_question": """You help a PhD student ask their busy supervisor for help efficiently.
Turn the student's description of where they are stuck into a short message for the supervisor:
context in 1-2 sentences, what they already tried, and 1-2 precise questions that can be answered quickly
(ideally yes/no or a choice between options). Use the student's language.""",
}

ASSIST_LABELS = {
    "assist_plan": "Help me plan next week",
    "assist_feedback": "Feedback on a piece of text",
    "assist_question": "Turn my stuck point into a clear question",
}


def assist_messages(kind: str, project_context: str, user_text: str) -> list[dict]:
    return [
        {"role": "system", "content": ASSIST_SYSTEMS[kind]},
        {"role": "user", "content": f"My projects and recent progress:\n{project_context}\n\nMy input:\n{user_text}"},
    ]
