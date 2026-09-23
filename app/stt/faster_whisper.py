from .base import STTSegment

class FasterWhisperSTT:
    def __init__(self, model: str, device: str, compute_type: str):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Install faster-whisper to use the local STT backend") from exc
        self.model = WhisperModel(model, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: str):
        segments, info = self.model.transcribe(audio_path, language=None, vad_filter=True)
        return [STTSegment(float(s.start), float(s.end), s.text.strip()) for s in segments if s.text.strip()], info.language
