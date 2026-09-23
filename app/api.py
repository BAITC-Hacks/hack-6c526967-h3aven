from datetime import date
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from app.export_service import docx_bytes, pdf_bytes
from app.meeting_service import process_meeting, store, update_mapping, update_tasks

app = FastAPI(title="Protokol AI", version="1.0.0")


def meeting_or_404(meeting_id: str):
    try:
        return store.get(meeting_id)
    except KeyError as exc:
        raise HTTPException(404, "Совещание не найдено") from exc


@app.post("/api/meetings")
async def create_meeting(file: UploadFile = File(...), meeting_date: date = Form(default_factory=date.today)):
    if Path(file.filename or "").suffix.lower() not in {".mp3", ".wav", ".mp4"}:
        raise HTTPException(415, "Поддерживаются MP3, WAV и MP4")
    return store.create(file.filename or "meeting", meeting_date, file.file)


@app.post("/api/meetings/{meeting_id}/process")
def process(meeting_id: str):
    meeting_or_404(meeting_id)
    return process_meeting(meeting_id)


@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: str):
    return meeting_or_404(meeting_id)


@app.get("/api/meetings/{meeting_id}/transcript")
def get_transcript(meeting_id: str):
    meeting = meeting_or_404(meeting_id)
    if not meeting.transcript:
        raise HTTPException(409, "Транскрипт ещё не сформирован")
    return meeting.transcript


@app.get("/api/meetings/{meeting_id}/tasks")
def get_tasks(meeting_id: str):
    return meeting_or_404(meeting_id).tasks


@app.put("/api/meetings/{meeting_id}/speaker-mapping")
def set_mapping(meeting_id: str, mapping: dict[str, str]):
    meeting_or_404(meeting_id)
    return update_mapping(meeting_id, mapping)


@app.put("/api/meetings/{meeting_id}/tasks")
def set_tasks(meeting_id: str, tasks: list[dict]):
    meeting_or_404(meeting_id)
    return update_tasks(meeting_id, tasks)


@app.get("/api/meetings/{meeting_id}/export/docx")
def export_docx(meeting_id: str):
    meeting = meeting_or_404(meeting_id)
    if not meeting.transcript:
        raise HTTPException(409, "Сначала обработайте запись")
    return Response(docx_bytes(meeting), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="protocol-{meeting_id}.docx"'})


@app.get("/api/meetings/{meeting_id}/export/pdf")
def export_pdf(meeting_id: str):
    meeting = meeting_or_404(meeting_id)
    if not meeting.transcript:
        raise HTTPException(409, "Сначала обработайте запись")
    return Response(pdf_bytes(meeting), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="protocol-{meeting_id}.pdf"'})


@app.post("/transcribe")
async def transcribe_endpoint(file: UploadFile = File(...)):
    meeting = store.create(file.filename or "meeting", date.today(), file.file)
    return process_meeting(meeting.id).transcript


app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
