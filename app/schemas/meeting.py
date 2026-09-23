from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class Task(BaseModel):
    id: str
    assignee: str | None = None
    task: str
    deadline: str | None = None
    deadline_source: str | None = None
    source: str
    timestamp: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    status: Literal["needs_review", "confirmed", "done"] = "needs_review"


class Meeting(BaseModel):
    id: str
    filename: str
    meeting_date: date
    status: Literal["uploaded", "processing", "ready", "failed"] = "uploaded"
    transcript: dict | None = None
    speaker_mapping: dict[str, str] = Field(default_factory=dict)
    tasks: list[Task] = Field(default_factory=list)
    summary: str = ""
    key_topics: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    error: str | None = None
