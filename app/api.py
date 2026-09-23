from pathlib import Path
from tempfile import NamedTemporaryFile
from fastapi import FastAPI, File, HTTPException, UploadFile
from app.pipeline.service import transcribe
from app.audio.preprocessing import AudioError

app = FastAPI(title="Local Meeting Transcriber")

@app.post("/transcribe")
async def transcribe_endpoint(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp3", ".wav", ".mp4"}:
        raise HTTPException(415, "Supported formats: MP3, WAV, MP4")
    try:
        with NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(await file.read()); tmp.flush()
            return transcribe(tmp.name)
    except (AudioError, RuntimeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
