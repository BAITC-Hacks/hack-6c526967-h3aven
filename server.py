"""Local FastAPI integration surface for SÖZDE."""

from __future__ import annotations

import asyncio
import os
import shutil
import json
import re
import time
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from pipeline.audio_processor import find_ffmpeg
from pipeline.export import export_all
from pipeline.llm_analyzer import get_ollama_status
from pipeline.transcriber import transcribe


PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env", override=False)
OUTPUT_DIR = PROJECT_DIR / "temp" / "api"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
PROCESS_LOCK = asyncio.Lock()
JOB_TASKS = {}


def _job_write(folder, state):
    draft = folder / "job.tmp"
    draft.write_text(json.dumps(state), encoding="utf-8")
    draft.replace(folder / "job.json")


async def _process_job(folder, source):
    state = dict(id=folder.name, status="queued", stage=0, created_at=time.time())
    _job_write(folder, state)
    try:
        async with PROCESS_LOCK:
            state.update(status="processing", stage=1, started_at=time.time())
            _job_write(folder, state)
            def progress(value, message):
                stage = 1 if value < 15 else 2 if value < 52 else 3 if value < 80 else 4 if value < 94 else 5
                state.update(stage=stage)
                _job_write(folder, state)
            from pipeline.stt import _cuda_profile
            gpu, memory = await asyncio.to_thread(_cuda_profile)
            model = os.getenv("STT_MODEL") or ("large-v3" if gpu and memory >= 6 else "small")
            result = await asyncio.to_thread(
                transcribe, str(source), str(folder), model, None,
                os.getenv("HF_TOKEN") or None, None, os.getenv("DEVICE", "auto"),
                True, os.getenv("OLLAMA_MODEL", "auto"), progress,
            )
            result.update(await asyncio.to_thread(export_all, result, str(folder)))
            _save(folder, result)
            state.update(status="completed", stage=6)
    except asyncio.CancelledError:
        state.update(status="interrupted", error="Server stopped. Please submit the recording again.")
        raise
    except Exception:
        logging.exception("Meeting processing failed: %s", folder.name)
        state.update(status="failed", error="Processing failed. Check system readiness and try again. The server log contains details.")
    finally:
        _job_write(folder, state)
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg", ".flac"}

app = FastAPI(
    title="SÖZDE API",
    description="Локальная транскрибация RU/KK, диаризация и протокол поручений",
    version="2.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8501", "http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _safe_filename(value: str) -> str:
    name = Path(value or "meeting.wav").name
    return "".join(char for char in name if char.isalnum() or char in " ._-№")[:150]


async def _run_pipeline(*args):
    async with PROCESS_LOCK:
        return await asyncio.to_thread(transcribe, *args)


@app.post("/transcribe")
async def api_transcribe(
    file: UploadFile = File(..., description="Аудио/видео совещания"),
    model: str = Form("large-v3", pattern=r"^(tiny|base|small|medium|large-v3)$"),
    language: Optional[str] = Form(None, pattern=r"^(ru|kk)?$"),
    num_speakers: Optional[int] = Form(None, ge=1, le=20),
    device: str = Form("auto", pattern=r"^(auto|cpu|cuda)$"),
    ollama_model: str = Form("auto"),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Неподдерживаемый формат: {suffix}")

    meeting_dir = OUTPUT_DIR / f"meeting_{os.urandom(6).hex()}"
    meeting_dir.mkdir(parents=True, exist_ok=False)
    source = meeting_dir / _safe_filename(file.filename or f"meeting{suffix}")
    written = 0
    try:
        with source.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Файл больше 500 МБ")
                handle.write(chunk)

        if written == 0:
            raise HTTPException(400, "Recording is empty")
        result = await _run_pipeline(
            str(source),
            str(meeting_dir),
            model,
            language or None,
            os.getenv("HF_TOKEN") or None,
            num_speakers,
            device,
            True,
            ollama_model,
        )
        result.update(await asyncio.to_thread(export_all, result, str(meeting_dir)))
        _save(meeting_dir, result)
        return _public_result(meeting_dir, result)
    except HTTPException:
        shutil.rmtree(meeting_dir, ignore_errors=True)
        raise
    except Exception as error:
        raise HTTPException(500, str(error)) from error
    finally:
        await file.close()


@app.post("/jobs", status_code=202)
async def create_job(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        await file.close()
        raise HTTPException(400, "Choose a supported audio or video recording.")
    folder = OUTPUT_DIR / f"meeting_{os.urandom(6).hex()}"
    folder.mkdir()
    source = folder / ((_safe_filename(Path(file.filename or "recording").stem)[:100] or "recording") + suffix)
    size = 0
    try:
        with source.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Maximum recording size is 500 MB.")
                handle.write(chunk)
        if not size:
            raise HTTPException(400, "The recording is empty.")
        _job_write(folder, dict(id=folder.name, status="queued", stage=0, created_at=time.time()))
        task = asyncio.create_task(_process_job(folder, source))
        JOB_TASKS[folder.name] = task
        task.add_done_callback(lambda done: JOB_TASKS.pop(folder.name, None))
        return {"id": folder.name}
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        await file.close()


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    if not re.fullmatch(r"meeting_[0-9a-f]{12}", job_id):
        raise HTTPException(404, "Job not found")
    folder = OUTPUT_DIR / job_id
    saved = folder / "job.json"
    if not saved.is_file():
        raise HTTPException(404, "Job not found")
    state = json.loads(saved.read_text(encoding="utf-8"))
    if state["status"] in {"queued", "processing"} and job_id not in JOB_TASKS:
        state.update(status="interrupted", error="The server restarted. Please submit the recording again.")
    return state


@app.get("/health")
def health_check():
    try:
        import ctranslate2

        cuda_devices = ctranslate2.get_cuda_device_count()
    except Exception:
        cuda_devices = 0
    ollama = get_ollama_status()
    return {
        "status": "ok",
        "offline_processing": os.getenv("ALLOW_CLOUD_ANALYSIS", "0") != "1",
        "cloud_analysis_enabled": os.getenv("ALLOW_CLOUD_ANALYSIS", "0") == "1",
        "nvidia_key_configured": bool(os.getenv("NVIDIA_API_KEY")),
        "hf_token_configured": bool(os.getenv("HF_TOKEN")),
        "ffmpeg": bool(find_ffmpeg()),
        "cuda_devices": cuda_devices,
        "ollama": ollama,
    }


@app.get("/capabilities")
def capabilities():
    return {
        "input": ["mp3", "wav", "m4a", "mp4", "webm", "ogg", "flac"],
        "languages": ["ru", "kk", "mixed"],
        "features": [
            "speech_to_text", "speaker_diarization", "speaker_name_resolution",
            "summary", "decisions", "tasks", "owners", "deadlines",
            "pdf", "docx", "markdown", "json",
        ],
    }


def _meeting(meeting_id: str) -> Path:
    if not re.fullmatch(r"meeting_[0-9a-f]{12}", meeting_id):
        raise HTTPException(404, "Meeting not found")
    folder = OUTPUT_DIR / meeting_id
    if not (folder / "result.json").is_file():
        raise HTTPException(404, "Meeting not found")
    return folder


def _save(folder: Path, result: dict) -> None:
    target = folder / "result.json"
    draft = folder / "result.tmp"
    draft.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    draft.replace(target)


def _public_result(folder: Path, result: dict) -> dict:
    return {
        **{key: value for key, value in result.items() if not key.endswith("_path")},
        "id": folder.name,
        "downloads": {kind: f"/meetings/{folder.name}/download/{kind}" for kind in ("json", "pdf", "docx", "markdown")},
    }


@app.get("/meetings")
def meetings():
    results = []
    for saved in sorted(OUTPUT_DIR.glob("meeting_*/result.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            results.append(_public_result(saved.parent, json.loads(saved.read_text(encoding="utf-8"))))
        except (ValueError, OSError):
            continue
    return results


@app.get("/meetings/{meeting_id}")
def meeting(meeting_id: str):
    folder = _meeting(meeting_id)
    return _public_result(folder, json.loads((folder / "result.json").read_text(encoding="utf-8")))


class ProtocolEdit(BaseModel):
    summary: str
    tasks: list[dict] = Field(default_factory=list)
    speaker_names: dict[str, str] = Field(default_factory=dict)


@app.put("/meetings/{meeting_id}")
def update_meeting(meeting_id: str, edit: ProtocolEdit):
    folder = _meeting(meeting_id)
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    names = {old: new.strip() for old, new in edit.speaker_names.items() if new.strip()}
    for segment in result.get("segments", []):
        segment["speaker"] = names.get(segment["speaker"], segment["speaker"])
    analysis = result.setdefault("analysis", {}) or {}
    result["analysis"] = analysis
    analysis.update(summary=edit.summary, tasks=edit.tasks)
    for task in analysis["tasks"]:
        task["assignee"] = names.get(task.get("assignee"), task.get("assignee", ""))
    for person in analysis.get("participants", []):
        person["name"] = names.get(person.get("name"), person.get("name", ""))
    analysis["speaker_map"] = {key: names.get(value, value) for key, value in analysis.get("speaker_map", {}).items()}
    result["num_speakers"] = len({s["speaker"] for s in result.get("segments", [])})
    result.update(export_all(result, str(folder)))
    _save(folder, result)
    return _public_result(folder, result)


@app.get("/meetings/{meeting_id}/download/{kind}")
def download(meeting_id: str, kind: str):
    folder = _meeting(meeting_id)
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    if kind not in {"json", "pdf", "docx", "markdown"}:
        raise HTTPException(404, "Unknown format")
    target = folder / "result.json" if kind == "json" else Path(result.get(f"{kind}_path", "")).resolve()
    if not target.is_file() or not target.resolve().is_relative_to(folder.resolve()):
        raise HTTPException(404, "Export not found")
    return FileResponse(target, filename=target.name)


@app.get("/samples")
def samples():
    return [p.name for p in PROJECT_DIR.glob("*.mp3")]


@app.get("/samples/{name}")
def sample(name: str):
    if name not in samples():
        raise HTTPException(404, "Sample not found")
    return FileResponse(PROJECT_DIR / name, media_type="audio/mpeg")


@app.get("/")
def frontend():
    return FileResponse(PROJECT_DIR / "fronttt.html")


@app.get("/fronttt.css")
def frontend_css():
    return FileResponse(PROJECT_DIR / "fronttt.css", media_type="text/css")


@app.get("/fronttt.js")
def frontend_js():
    return FileResponse(PROJECT_DIR / "fronttt.js", media_type="text/javascript")


app.mount("/assets", StaticFiles(directory=PROJECT_DIR / "assets"), name="assets")
