from dataclasses import dataclass
from typing import Protocol

@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: str

class DiarizationBackend(Protocol):
    def diarize(self, audio_path: str) -> list[SpeakerTurn]: ...
