from dataclasses import dataclass
from typing import Protocol

@dataclass
class STTSegment:
    start: float
    end: float
    text: str

class STTBackend(Protocol):
    def transcribe(self, audio_path: str) -> tuple[list[STTSegment], str | None]: ...
