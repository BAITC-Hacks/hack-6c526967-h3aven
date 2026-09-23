"""End-to-end local meeting processing pipeline."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pipeline.audio_processor import process_audio
from pipeline.diarization import diarize_audio
from pipeline.llm_analyzer import analyze_transcript as llm_analyze
from pipeline.stt import transcribe_audio
from pipeline.text_diarization import text_based_diarization


ProgressCallback = Optional[Callable[[int, str], None]]


def _progress(callback: ProgressCallback, value: int, message: str) -> None:
    print(f"[pipeline] {value}% {message}")
    if callback:
        callback(value, message)


def transcribe(
    file_path: str,
    output_dir: str = "temp",
    model_size: str = "large-v3",
    language: Optional[str] = None,
    hf_token: Optional[str] = None,
    num_speakers: Optional[int] = None,
    device: str = "auto",
    run_llm: bool = True,
    ollama_model: str = "auto",
    progress_callback: ProgressCallback = None,
) -> dict:
    """Run audio normalization, STT, diarization, analysis, and persistence."""
    started = time.time()
    source = Path(file_path).resolve()
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    _progress(progress_callback, 5, "Подготовка аудио")
    processed_path = process_audio(str(source), output_dir=str(destination))

    _progress(progress_callback, 15, "Распознавание русской и казахской речи")
    stt_segments, stt_meta = transcribe_audio(
        processed_path,
        model_size=model_size,
        language=language,
        device=device,
    )
    if not stt_segments:
        raise RuntimeError("В записи не обнаружена распознаваемая речь")

    _progress(progress_callback, 52, "Разделение по спикерам")
    diar_segments, diarization_meta = diarize_audio(
        processed_path,
        hf_token=hf_token,
        num_speakers=num_speakers,
    )

    _progress(progress_callback, 70, "Совмещение текста с голосовыми сегментами")
    combined = _align_stt_with_diarization(stt_segments, diar_segments)
    unique_speakers = set(segment["speaker"] for segment in combined)
    if len(unique_speakers) <= 1:
        text_segments = text_based_diarization(combined)
        text_speakers = set(segment["speaker"] for segment in text_segments)
        if len(text_speakers) > len(unique_speakers):
            combined = text_segments
            unique_speakers = text_speakers
            diarization_meta["engine"] += "+text-context"
            diarization_meta["speaker_count"] = len(text_speakers)

    transcript_result = {
        "source_file": source.name,
        "duration": stt_meta.get("duration", 0),
        "language": stt_meta.get("language", "unknown"),
        "detected_language": stt_meta.get("detected_language", "unknown"),
        "language_probability": stt_meta.get("language_probability", 0),
        "average_word_confidence": stt_meta.get("average_word_confidence", 0),
        "model": stt_meta.get("model", model_size),
        "inference_device": stt_meta.get("device", device),
        "num_speakers": len(unique_speakers),
        "diarization": diarization_meta,
        "segments": combined,
    }

    analysis = None
    if run_llm:
        _progress(progress_callback, 80, "Извлечение решений и поручений")
        analysis = llm_analyze(transcript_result, ollama_model=ollama_model)
        speaker_map = analysis.get("speaker_map", {}) if analysis else {}
        if speaker_map:
            _apply_speaker_map(combined, speaker_map)
            transcript_result["num_speakers"] = len(
                {segment["speaker"] for segment in combined}
            )

    result = {
        **transcript_result,
        "analysis": analysis,
        "quality": _build_quality_report(transcript_result, analysis),
        "pipeline_version": "2.0",
        "processing_seconds": round(time.time() - started, 2),
    }

    _progress(progress_callback, 94, "Сохранение структурированного протокола")
    json_path = destination / f"{source.stem}_transcript.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    result["json_path"] = str(json_path)
    _progress(progress_callback, 100, "Готово")
    return result


def _apply_speaker_map(segments: List[Dict], speaker_map: dict) -> None:
    for segment in segments:
        original = segment.get("speaker", "SPEAKER_00")
        candidate = str(speaker_map.get(original, original)).strip()
        if candidate and candidate != original and not candidate.startswith("SPEAKER_"):
            segment["speaker_id"] = original
            segment["speaker"] = candidate


def _build_quality_report(transcript: dict, analysis: Optional[dict]) -> dict:
    warnings = []
    diarization = transcript.get("diarization", {})
    if diarization.get("warning"):
        warnings.append("Диаризация работает в резервном режиме")
    if transcript.get("average_word_confidence", 1) < 0.65:
        warnings.append("Низкая средняя уверенность распознавания речи")
    tasks = (analysis or {}).get("tasks", [])
    missing_assignee = sum(
        1 for task in tasks if task.get("assignee") in (None, "", "Не указан")
    )
    missing_deadline = sum(
        1 for task in tasks if task.get("deadline") in (None, "", "Не указан")
    )
    if missing_assignee:
        warnings.append(f"Поручений без ответственного: {missing_assignee}")
    if missing_deadline:
        warnings.append(f"Поручений без срока: {missing_deadline}")
    return {
        "status": "review" if warnings else "ready",
        "warnings": warnings,
        "tasks_total": len(tasks),
        "tasks_with_assignee": len(tasks) - missing_assignee,
        "tasks_with_deadline": len(tasks) - missing_deadline,
    }


def _align_stt_with_diarization(
    stt_segments: List[Dict], diar_segments: List[Dict]
) -> List[Dict]:
    if not diar_segments:
        return [
            {
                "speaker": "SPEAKER_00",
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"],
            }
            for segment in stt_segments
        ]

    combined = []
    for segment in stt_segments:
        words = segment.get("words", [])
        if words and len(words) > 1:
            combined.extend(_group_words_by_speaker(words, diar_segments))
        else:
            combined.append(
                {
                    "speaker": _find_speaker_for_interval(
                        segment["start"], segment["end"], diar_segments
                    ),
                    "start": segment["start"],
                    "end": segment["end"],
                    "text": segment["text"],
                }
            )
    return _merge_consecutive_segments(combined)


def _find_speaker_for_interval(
    start: float, end: float, diar_segments: List[Dict]
) -> str:
    midpoint = start + (end - start) / 2
    containing = [
        segment for segment in diar_segments
        if segment["start"] <= midpoint <= segment["end"]
    ]
    if containing:
        return max(containing, key=lambda item: item["end"] - item["start"])["speaker"]

    best_speaker = "SPEAKER_00"
    best_overlap = 0.0
    for segment in diar_segments:
        overlap = max(0.0, min(end, segment["end"]) - max(start, segment["start"]))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = segment["speaker"]
    return best_speaker


def _group_words_by_speaker(words: List[Dict], diar_segments: List[Dict]) -> List[Dict]:
    groups: list[dict] = []
    current: Optional[dict] = None
    for word in words:
        speaker = _find_speaker_for_interval(word["start"], word["end"], diar_segments)
        if current is None or current["speaker"] != speaker:
            if current:
                groups.append(current)
            current = {
                "speaker": speaker,
                "start": word["start"],
                "end": word["end"],
                "text": word["word"],
            }
        else:
            current["end"] = word["end"]
            current["text"] = f"{current['text']} {word['word']}".strip()
    if current:
        groups.append(current)
    return groups


def _merge_consecutive_segments(segments: List[Dict]) -> List[Dict]:
    if not segments:
        return []
    merged = [segments[0].copy()]
    for segment in segments[1:]:
        previous = merged[-1]
        if (
            segment["speaker"] == previous["speaker"]
            and segment["start"] - previous["end"] < 1.2
        ):
            previous["end"] = segment["end"]
            previous["text"] = f"{previous['text']} {segment['text']}".strip()
        else:
            merged.append(segment.copy())
    return merged
