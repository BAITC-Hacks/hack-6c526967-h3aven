import json
import re
import shutil
import uuid
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from app.config import settings
from app.pipeline.service import transcribe
from app.schemas.meeting import Meeting, Task


class MeetingStore:
    def __init__(self):
        self.root = settings.output_dir / "meetings"
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, meeting_id: str) -> Path:
        return self.root / meeting_id / "meeting.json"

    def save(self, meeting: Meeting) -> Meeting:
        folder = self.path(meeting.id).parent
        folder.mkdir(parents=True, exist_ok=True)
        self.path(meeting.id).write_text(meeting.model_dump_json(indent=2), encoding="utf-8")
        return meeting

    def get(self, meeting_id: str) -> Meeting:
        path = self.path(meeting_id)
        if not path.exists():
            raise KeyError(meeting_id)
        return Meeting.model_validate_json(path.read_text(encoding="utf-8"))

    def create(self, filename: str, meeting_date: date, upload) -> Meeting:
        meeting_id = uuid.uuid4().hex[:12]
        folder = self.path(meeting_id).parent
        folder.mkdir(parents=True)
        source = folder / f"source{Path(filename).suffix.lower()}"
        with source.open("wb") as output:
            shutil.copyfileobj(upload, output)
        return self.save(Meeting(id=meeting_id, filename=filename, meeting_date=meeting_date))

    def source_path(self, meeting_id: str) -> Path:
        files = list(self.path(meeting_id).parent.glob("source.*"))
        if not files:
            raise FileNotFoundError("Uploaded audio is missing")
        return files[0]


store = MeetingStore()


def normalize_deadline(text: str, meeting_date: date) -> tuple[str | None, str | None]:
    value = text.lower()
    patterns = [
        (r"\b(сегодня|бүгін)\b", 0),
        (r"\b(завтра|ертең)\b", 1),
        (r"\b(послезавтра)\b", 2),
        (r"\b(на следующей неделе|келесі аптада)\b", 7),
    ]
    for pattern, offset in patterns:
        match = re.search(pattern, value)
        if match:
            return (meeting_date + timedelta(days=offset)).isoformat(), match.group(1)
    if re.search(r"(до пятницы|жұмаға дейін)", value):
        offset = (4 - meeting_date.weekday()) % 7
        return (meeting_date + timedelta(days=offset)).isoformat(), "до пятницы"
    if re.search(r"(до конца месяца|айдың соңына дейін)", value):
        next_month = meeting_date.replace(day=28) + timedelta(days=4)
        return (next_month - timedelta(days=next_month.day)).isoformat(), "до конца месяца"
    match = re.search(r"\b(?:до\s+)?(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)\b", value)
    if match:
        raw = match.group(1)
        parts = re.split(r"[./-]", raw)
        try:
            year = int(parts[2]) if len(parts) == 3 else meeting_date.year
            if year < 100:
                year += 2000
            return date(year, int(parts[1]), int(parts[0])).isoformat(), raw
        except ValueError:
            pass
    return None, None


COMMAND_RE = re.compile(
    r"(?:(?P<name>[А-ЯӘІҢҒҮҰҚӨҺA-Z][а-яәіңғүұқөһa-z-]{1,30})\s*,?\s*)?"
    r"(?P<verb>подготов(?:ь|ьте)|отправ(?:ь|ьте)|сделай(?:те)?|провед(?:и|ите)|"
    r"проверь(?:те)?|согласуй(?:те)?|дай(?:те)?|аяқта(?:ңыз)?|жіберіңіз|дайындаңыз)"
    r"(?P<body>[^.!?]{0,180})",
    re.IGNORECASE,
)


def extract_tasks(transcript: dict, mapping: dict[str, str], meeting_date: date) -> list[Task]:
    tasks: list[Task] = []
    for segment in transcript.get("segments", []):
        text = segment.get("text", "").strip()
        match = COMMAND_RE.search(text)
        if not match:
            continue
        deadline, deadline_source = normalize_deadline(text, meeting_date)
        speaker = segment.get("speaker", "")
        # A name at the beginning followed by a comma is the most reliable
        # assignment signal.  It also handles mixed-language phrases where
        # the imperative verb appears far from the name.
        leading = text.split(",", 1)[0].strip() if "," in text else ""
        is_name = re.fullmatch(r"[А-ЯӘІҢҒҮҰҚӨҺA-Z][а-яәіңғүұқөһa-z-]{1,30}", leading or "")
        assignee = leading if is_name else match.group("name") or mapping.get(speaker)
        task_text = (match.group("verb") + match.group("body")).strip(" ,.-")
        task_text = re.sub(r"\s+(до|бүгін|завтра|ертең|послезавтра|на следующей|келесі).*$", "", task_text, flags=re.I)
        confidence = 0.86 if assignee and deadline else 0.68 if assignee else 0.48
        tasks.append(Task(
            id=uuid.uuid4().hex[:8], assignee=assignee, task=task_text[:1].upper() + task_text[1:],
            deadline=deadline, deadline_source=deadline_source, source=text,
            timestamp=float(segment.get("start", 0)), confidence=confidence,
        ))
    return tasks


def make_summary(transcript: dict, tasks: list[Task]) -> tuple[str, list[str], list[str]]:
    segments = transcript.get("segments", [])
    statements = [item.get("text", "").strip() for item in segments if item.get("text", "").strip()]
    topics = statements[:3]
    decisions = [line for line in statements if re.search(r"\b(решили|утвердили|келістік|шешім)\b", line, re.I)][:3]
    if not statements:
        return "Транскрипт не содержит реплик.", [], []
    task_text = f" Выявлено поручений: {len(tasks)}." if tasks else " Явных поручений не выявлено."
    return " ".join(statements[:3]) + task_text, topics, decisions


def local_llm_analysis(transcript: dict, meeting_date: date) -> dict | None:
    """Uses only a self-hosted Ollama endpoint and never sends meeting data to cloud."""
    if not settings.ollama_model:
        return None
    payload = {
        "model": settings.ollama_model, "stream": False, "format": "json",
        "messages": [{"role": "system", "content": "Extract meeting tasks from Russian, Kazakh or mixed speech. Return JSON with summary, key_topics, decisions, tasks. Every task needs assignee, task, deadline ISO or null, deadline_source, source, timestamp, confidence 0..1. Do not turn completed past statements into tasks."}, {"role": "user", "content": json.dumps({"meeting_date": meeting_date.isoformat(), "transcript": transcript}, ensure_ascii=False)}],
    }
    try:
        request = urllib.request.Request(f"{settings.ollama_url.rstrip('/')}/api/chat", data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(json.loads(response.read().decode())["message"]["content"])
    except Exception:
        return None


def process_meeting(meeting_id: str) -> Meeting:
    meeting = store.get(meeting_id)
    meeting.status = "processing"
    meeting.error = None
    store.save(meeting)
    try:
        meeting.transcript = transcribe(store.source_path(meeting_id))
        analysis = local_llm_analysis(meeting.transcript, meeting.meeting_date)
        if analysis:
            meeting.tasks = [Task(id=uuid.uuid4().hex[:8], **task) for task in analysis.get("tasks", [])]
            meeting.summary = analysis.get("summary", "")
            meeting.key_topics = analysis.get("key_topics", [])
            meeting.decisions = analysis.get("decisions", [])
        else:
            meeting.tasks = extract_tasks(meeting.transcript, meeting.speaker_mapping, meeting.meeting_date)
            meeting.summary, meeting.key_topics, meeting.decisions = make_summary(meeting.transcript, meeting.tasks)
        meeting.status = "ready"
    except Exception as exc:
        meeting.status = "failed"
        meeting.error = str(exc)
    return store.save(meeting)


def update_mapping(meeting_id: str, mapping: dict[str, str]) -> Meeting:
    meeting = store.get(meeting_id)
    meeting.speaker_mapping = {key: value.strip() for key, value in mapping.items() if value.strip()}
    if meeting.transcript:
        meeting.tasks = extract_tasks(meeting.transcript, meeting.speaker_mapping, meeting.meeting_date)
        meeting.summary, meeting.key_topics, meeting.decisions = make_summary(meeting.transcript, meeting.tasks)
    return store.save(meeting)


def update_tasks(meeting_id: str, tasks: list[dict]) -> Meeting:
    meeting = store.get(meeting_id)
    meeting.tasks = [Task.model_validate(task) for task in tasks]
    meeting.summary, meeting.key_topics, meeting.decisions = make_summary(meeting.transcript or {}, meeting.tasks)
    return store.save(meeting)
