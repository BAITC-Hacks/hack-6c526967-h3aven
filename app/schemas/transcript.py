from typing import Literal
from pydantic import BaseModel, Field

Language = Literal["ru", "kk", "mixed"]

class Segment(BaseModel):
    speaker: str = Field(pattern=r"^SPEAKER_\d{2}$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str

class Transcript(BaseModel):
    duration: float = Field(ge=0)
    language: Language
    segments: list[Segment]
