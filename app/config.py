from dataclasses import dataclass
import os
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    stt_model: str = os.getenv("STT_MODEL", "small")
    diarization_model: str = os.getenv("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
    device: str = os.getenv("DEVICE", "cpu")
    compute_type: str = os.getenv("COMPUTE_TYPE", "int8")
    sample_rate: int = int(os.getenv("SAMPLE_RATE", "16000"))
    language_mode: str = os.getenv("LANGUAGE_MODE", "auto")
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "output"))
    hf_token: str | None = os.getenv("HF_TOKEN") or None

settings = Settings()
