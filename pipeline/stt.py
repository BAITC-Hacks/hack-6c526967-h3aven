"""Local multilingual speech-to-text with GPU and CPU fallback."""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Dict, List, Optional


KAZAKH_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
DEFAULT_PROMPT = (
    "Деловое совещание на русском и казахском языках. "
    "Іскерлік жиналыс, тапсырмалар, жауапты тұлғалар және мерзімдер. "
    "Сохраняй имена, должности, числа и даты точно."
)


def _cuda_profile() -> tuple[bool, float]:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            return False, 0.0
        try:
            import torch

            total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            return True, round(total, 1)
        except Exception:
            return True, 0.0
    except Exception:
        return False, 0.0


def _resolve_runtime(device: str, compute_type: str) -> tuple[str, str, float]:
    has_cuda, vram_gb = _cuda_profile()
    selected_device = device
    if device == "auto":
        selected_device = "cuda" if has_cuda else "cpu"
    if selected_device == "cuda" and not has_cuda:
        selected_device = "cpu"

    selected_compute = compute_type
    if compute_type == "auto":
        if selected_device == "cuda":
            selected_compute = "int8_float16" if 0 < vram_gb < 6 else "float16"
        else:
            selected_compute = "int8"
    return selected_device, selected_compute, vram_gb


def _detect_language_mode(text: str, detected: str) -> str:
    has_kazakh = any(char in KAZAKH_LETTERS for char in text)
    has_russian = any(char in text.lower() for char in "ёыэъщ")
    if has_kazakh and has_russian:
        return "mixed"
    if has_kazakh or detected == "kk":
        return "kk"
    return detected or "unknown"


def _run_whisper(
    audio_path: str,
    model_size: str,
    language: Optional[str],
    device: str,
    compute_type: str,
    beam_size: int,
    vad_filter: bool,
) -> tuple[List[Dict], dict]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    try:
        stream, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=beam_size,
            best_of=max(beam_size, 5),
            vad_filter=vad_filter,
            vad_parameters={
                "min_silence_duration_ms": 450,
                "speech_pad_ms": 250,
            },
            word_timestamps=True,
            condition_on_previous_text=True,
            initial_prompt=DEFAULT_PROMPT,
        )

        segments: List[Dict] = []
        probabilities: list[float] = []
        for segment in stream:
            words = []
            for word in segment.words or []:
                probability = float(word.probability or 0.0)
                probabilities.append(probability)
                words.append(
                    {
                        "word": word.word.strip(),
                        "start": round(float(word.start or segment.start), 2),
                        "end": round(float(word.end or segment.end), 2),
                        "probability": round(probability, 3),
                    }
                )
            text = segment.text.strip()
            if text:
                segments.append(
                    {
                        "start": round(float(segment.start), 2),
                        "end": round(float(segment.end), 2),
                        "text": text,
                        "words": words,
                    }
                )

        full_text = " ".join(item["text"] for item in segments)
        detected = str(info.language or "unknown")
        meta = {
            "language": _detect_language_mode(full_text, detected),
            "detected_language": detected,
            "language_probability": round(float(info.language_probability or 0.0), 3),
            "duration": round(float(info.duration or 0.0), 2),
            "average_word_confidence": round(
                sum(probabilities) / len(probabilities), 3
            ) if probabilities else 0.0,
            "model": model_size,
            "device": device,
            "compute_type": compute_type,
        }
        return segments, meta
    finally:
        del model
        gc.collect()
        if device == "cuda":
            try:
                import torch

                torch.cuda.empty_cache()
            except Exception:
                pass


def transcribe_audio(
    audio_path: str,
    model_size: str = "large-v3",
    language: Optional[str] = None,
    device: str = "auto",
    compute_type: str = "auto",
    beam_size: int = 5,
    vad_filter: bool = True,
) -> tuple[List[Dict], dict]:
    """Transcribe Russian, Kazakh, or mixed speech entirely locally."""
    if not Path(audio_path).is_file():
        raise FileNotFoundError(f"Аудиофайл не найден: {audio_path}")

    selected_device, selected_compute, vram_gb = _resolve_runtime(device, compute_type)
    print(
        f"[stt] Модель {model_size}; {selected_device}/{selected_compute}; "
        f"VRAM={vram_gb or 'n/a'} GB; язык={language or 'auto RU/KK'}"
    )
    try:
        segments, meta = _run_whisper(
            audio_path,
            model_size,
            language,
            selected_device,
            selected_compute,
            beam_size,
            vad_filter,
        )
    except Exception as error:
        if selected_device != "cuda":
            raise
        print(f"[stt] CUDA недоступна или не хватило VRAM: {error}")
        print("[stt] Повтор на CPU/int8")
        segments, meta = _run_whisper(
            audio_path,
            model_size,
            language,
            "cpu",
            "int8",
            min(beam_size, 3),
            vad_filter,
        )
        meta["fallback_reason"] = str(error)

    print(
        f"[stt] {len(segments)} сегментов; язык={meta['language']}; "
        f"confidence={meta['average_word_confidence']:.0%}"
    )
    return segments, meta
