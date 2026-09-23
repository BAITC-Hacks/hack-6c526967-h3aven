from app.schemas.transcript import Segment
from app.stt.base import STTSegment
from app.diarization.base import SpeakerTurn

def align(stt_segments: list[STTSegment], turns: list[SpeakerTurn]) -> list[Segment]:
    result = []
    for item in stt_segments:
        overlaps = [(max(0.0, min(item.end, t.end) - max(item.start, t.start)), t) for t in turns]
        best = max(overlaps, key=lambda x: x[0], default=(0.0, None))
        speaker = best[1].speaker if best[1] is not None and best[0] > 0 else "SPEAKER_00"
        result.append(Segment(speaker=speaker, start=item.start, end=item.end, text=item.text))
    return result
