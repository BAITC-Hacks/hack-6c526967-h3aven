"""Offline speaker diarization with account-free and pyannote backends."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional


def diarize_audio(
    audio_path: str,
    hf_token: Optional[str] = None,
    num_speakers: Optional[int] = None,
    min_speakers: int = 2,
    max_speakers: int = 10,
) -> tuple[List[Dict], dict]:
    """Return speaker turns and backend metadata without cloud API calls."""
    if not Path(audio_path).is_file():
        raise FileNotFoundError(f"Аудиофайл не найден: {audio_path}")

    errors: list[str] = []
    try:
        segments = _diarize_account_free(audio_path, num_speakers, min_speakers, max_speakers)
        return segments, {
            "engine": "diarize-cpu",
            "speaker_count": len({item["speaker"] for item in segments}),
            "warning": None,
        }
    except Exception as error:
        errors.append(f"diarize: {error}")

    token = hf_token or os.environ.get("HF_TOKEN")
    if token:
        try:
            segments = _diarize_pyannote(
                audio_path, token, num_speakers, min_speakers, max_speakers
            )
            return segments, {
                "engine": "pyannote",
                "speaker_count": len({item["speaker"] for item in segments}),
                "warning": None,
            }
        except Exception as error:
            errors.append(f"pyannote: {error}")

    warning = "; ".join(errors) or "Модуль диаризации не установлен"
    print(f"[diarization] Реальная диаризация недоступна: {warning}")
    print("[diarization] Включён текстовый fallback; результат требует проверки")
    segments = _diarize_fallback(audio_path)
    return segments, {
        "engine": "text-fallback",
        "speaker_count": 1,
        "warning": warning,
    }


def _diarize_account_free(
    audio_path: str,
    num_speakers: Optional[int],
    min_speakers: int,
    max_speakers: int,
) -> List[Dict]:
    """CPU-only diarization; no HuggingFace account or token is required."""
    from diarize import diarize as run_diarize

    kwargs: dict = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers
    else:
        kwargs["min_speakers"] = min_speakers
        kwargs["max_speakers"] = max_speakers
    print("[diarization] CPU backend: diarize")
    result = run_diarize(audio_path, **kwargs)
    segments = [
        {
            "speaker": str(segment.speaker),
            "start": round(float(segment.start), 2),
            "end": round(float(segment.end), 2),
        }
        for segment in result.segments
        if float(segment.end) > float(segment.start)
    ]
    if not segments:
        raise RuntimeError("движок вернул пустой результат")
    return _normalize_labels(segments)


def _diarize_pyannote(
    audio_path: str,
    token: str,
    num_speakers: Optional[int],
    min_speakers: int,
    max_speakers: int,
) -> List[Dict]:
    from pyannote.audio import Pipeline

    print("[diarization] Backend: pyannote/speaker-diarization-3.1 (CPU)")
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=token
        )
    except TypeError:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=token
        )
    if pipeline is None:
        raise RuntimeError("модель pyannote недоступна или не приняты её условия")

    parameters: dict = {}
    if num_speakers:
        parameters["num_speakers"] = num_speakers
    else:
        parameters.update(min_speakers=min_speakers, max_speakers=max_speakers)
    output = pipeline(audio_path, **parameters)
    annotation = getattr(output, "speaker_diarization", output)

    segments = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        segments.append(
            {
                "speaker": str(speaker),
                "start": round(float(turn.start), 2),
                "end": round(float(turn.end), 2),
            }
        )
    if not segments:
        raise RuntimeError("pyannote вернул пустой результат")
    return _normalize_labels(segments)


def _normalize_labels(segments: List[Dict]) -> List[Dict]:
    labels = list(dict.fromkeys(item["speaker"] for item in segments))
    mapping = {label: f"SPEAKER_{index:02d}" for index, label in enumerate(labels)}
    return [
        {**item, "speaker": mapping[item["speaker"]]}
        for item in sorted(segments, key=lambda value: value["start"])
    ]


def _diarize_fallback(audio_path: str) -> List[Dict]:
    try:
        import wave

        with wave.open(audio_path, "rb") as audio:
            duration = audio.getnframes() / float(audio.getframerate())
    except Exception:
        duration = 0.0
    return [{"speaker": "SPEAKER_00", "start": 0.0, "end": round(duration, 2)}]
