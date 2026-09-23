import tempfile
import unittest
from pathlib import Path

from pipeline.export import export_all
from pipeline.llm_analyzer import _analyze_with_regex
from pipeline.stt import _detect_language_mode
from pipeline.transcriber import _align_stt_with_diarization


class PipelineUnitTests(unittest.TestCase):
    def test_mixed_language_detection(self):
        text = "Коллеги, начинаем. Келесі аптада есепті дайындау керек."
        self.assertEqual(_detect_language_mode(text, "ru"), "mixed")

    def test_word_level_speaker_alignment(self):
        stt = [{
            "start": 0.0,
            "end": 4.0,
            "text": "Первый ответ Второй ответ",
            "words": [
                {"word": "Первый", "start": 0.0, "end": 0.8},
                {"word": "ответ", "start": 0.8, "end": 1.8},
                {"word": "Второй", "start": 2.1, "end": 2.9},
                {"word": "ответ", "start": 2.9, "end": 4.0},
            ],
        }]
        diarization = [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0},
            {"speaker": "SPEAKER_01", "start": 2.0, "end": 4.1},
        ]
        result = _align_stt_with_diarization(stt, diarization)
        self.assertEqual([item["speaker"] for item in result], ["SPEAKER_00", "SPEAKER_01"])

    def test_fallback_extracts_owner_and_deadline(self):
        text = (
            "Фиксируем поручения. 1. Подготовить финансовое решение. "
            "Ответственный Тимур Болатович. Срок - до 30 сентября. "
            "2. Провести аудит датчиков. Ответственный Нурлан Сагатович. "
            "Срок - до 15 октября. Договорились."
        )
        transcript = {
            "language": "ru",
            "segments": [{"speaker": "SPEAKER_00", "start": 0, "end": 30, "text": text}],
        }
        result = _analyze_with_regex("[00:00] SPEAKER_00: " + text, transcript)
        tasks = result["tasks"]
        self.assertGreaterEqual(len(tasks), 2)
        self.assertTrue(any("Тимур" in item["assignee"] for item in tasks))
        self.assertTrue(any("30 сентября" in item["deadline"] for item in tasks))

    def test_pdf_docx_and_markdown_exports(self):
        result = {
            "source_file": "test.wav",
            "duration": 15,
            "language": "mixed",
            "num_speakers": 2,
            "segments": [
                {"speaker": "Алия", "start": 0, "end": 7, "text": "Есепті дайындаңыз."},
                {"speaker": "Данияр", "start": 7, "end": 15, "text": "До пятницы сделаю."},
            ],
            "analysis": {
                "title": "Рабочее совещание",
                "summary": "Обсуждена подготовка отчёта.",
                "key_decisions": ["Отчёт подготовить до пятницы"],
                "tasks": [{
                    "task": "Подготовить отчёт",
                    "assignee": "Данияр",
                    "deadline": "до пятницы",
                    "priority": "high",
                    "status": "pending",
                }],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            paths = export_all(result, directory)
            for path in paths.values():
                self.assertTrue(Path(path).is_file())
                self.assertGreater(Path(path).stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()
