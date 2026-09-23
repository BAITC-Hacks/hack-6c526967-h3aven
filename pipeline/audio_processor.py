"""Audio normalization for the local meeting pipeline."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


def find_ffmpeg(binary: str = "ffmpeg") -> str | None:
    """Return a system or bundled FFmpeg executable."""
    executable = f"{binary}.exe" if os.name == "nt" else binary
    candidates = [
        shutil.which(binary),
        PROJECT_DIR / executable,
        Path.cwd() / executable,
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def _check_ffmpeg() -> bool:
    return find_ffmpeg() is not None


def process_audio(
    file_path: str,
    output_dir: str = "temp",
    sample_rate: int = 16000,
    channels: int = 1,
) -> str:
    """Convert supported audio/video input to 16 kHz mono PCM WAV."""
    source = Path(file_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Файл не найден: {source}")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg не найден. Поместите ffmpeg.exe в корень проекта "
            "или добавьте FFmpeg в PATH."
        )

    destination_dir = Path(output_dir).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    output_path = destination_dir / f"{source.stem}_16k_mono.wav"

    if output_path.is_file() and output_path.stat().st_mtime >= source.stat().st_mtime:
        print(f"[audio] Используется подготовленный WAV: {output_path}")
        return str(output_path)

    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        str(output_path),
    ]
    print(f"[audio] {source.name} -> WAV {sample_rate} Hz mono")
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"FFmpeg не смог обработать файл: {completed.stderr.strip()}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[audio] Готово: {output_path} ({size_mb:.1f} MB)")
    return str(output_path)
