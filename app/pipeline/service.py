from pathlib import Path
from tempfile import TemporaryDirectory
from app.config import settings
from app.audio.preprocessing import prepare_audio
from app.schemas.transcript import Transcript
from app.stt.faster_whisper import FasterWhisperSTT
from app.diarization.pyannote_backend import PyannoteDiarization
from .alignment import align

def transcribe(path: str | Path, stt=None, diarization=None) -> dict:
    source = Path(path)
    with TemporaryDirectory() as tmp:
        audio = prepare_audio(source, Path(tmp), settings.sample_rate)
        stt = stt or FasterWhisperSTT(settings.stt_model, settings.device, settings.compute_type)
        diarization = diarization or PyannoteDiarization(settings.diarization_model, settings.hf_token)
        words, language = stt.transcribe(str(audio))
        turns = diarization.diarize(str(audio))
        duration = max([x.end for x in words] + [x.end for x in turns] + [0.0])
        normalized = "mixed" if language not in {"ru", "kk"} else language
        return Transcript(duration=duration, language=normalized, segments=align(words, turns)).model_dump()
