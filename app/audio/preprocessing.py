import shutil
import subprocess
from pathlib import Path
import wave

SUPPORTED = {".mp3", ".wav", ".mp4"}

class AudioError(RuntimeError): pass

def prepare_audio(source: Path, workdir: Path, sample_rate: int) -> Path:
    if source.suffix.lower() not in SUPPORTED:
        raise AudioError(f"Unsupported file type: {source.suffix}")
    if not source.is_file() or source.stat().st_size == 0:
        raise AudioError("Input file is missing or empty")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        if source.suffix.lower() == ".wav":
            try:
                with wave.open(str(source), "rb") as w:
                    if w.getnframes() == 0: raise AudioError("Audio is empty")
                return source
            except wave.Error as exc:
                raise AudioError("Invalid WAV file") from exc
        raise AudioError("FFmpeg is required for MP3/MP4 input")
    target = workdir / "audio.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([ffmpeg, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "wav", str(target)], capture_output=True, text=True)
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        raise AudioError("FFmpeg could not decode the input audio")
    return target
