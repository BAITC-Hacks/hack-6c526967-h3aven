from .base import SpeakerTurn

class PyannoteDiarization:
    def __init__(self, model: str, token: str | None = None):
        try:
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise RuntimeError("Install pyannote.audio to use local diarization") from exc
        self.pipeline = Pipeline.from_pretrained(model, use_auth_token=token)

    def diarize(self, audio_path: str):
        annotation = self.pipeline(audio_path)
        turns = []
        names = {}
        for segment, _, label in annotation.itertracks(yield_label=True):
            if label not in names: names[label] = f"SPEAKER_{len(names):02d}"
            turns.append(SpeakerTurn(float(segment.start), float(segment.end), names[label]))
        return turns
