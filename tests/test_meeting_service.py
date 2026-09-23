from datetime import date
import unittest

from app.meeting_service import extract_tasks, normalize_deadline


class MeetingServiceTests(unittest.TestCase):
    def test_normalizes_russian_and_kazakh_deadlines(self):
        meeting_date = date(2026, 9, 23)
        self.assertEqual(normalize_deadline("\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u044c \u0434\u043e \u043f\u044f\u0442\u043d\u0438\u0446\u044b", meeting_date)[0], "2026-09-25")
        self.assertEqual(normalize_deadline("\u0415\u0440\u0442\u0435\u04a3 \u0436\u0456\u0431\u0435\u0440\u0456\u04a3\u0456\u0437", meeting_date)[0], "2026-09-24")
        self.assertEqual(normalize_deadline("\u0410\u0439\u0434\u044b\u04a3 \u0441\u043e\u04a3\u044b\u043d\u0430 \u0434\u0435\u0439\u0456\u043d", meeting_date)[0], "2026-09-30")

    def test_extracts_assignment_without_past_statement(self):
        transcript = {"segments": [
            {"speaker": "SPEAKER_00", "start": 0, "end": 3, "text": "\u0414\u0430\u043d\u0438\u044f\u0440 \u0432\u0447\u0435\u0440\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u043b \u043e\u0442\u0447\u0451\u0442."},
            {"speaker": "SPEAKER_01", "start": 4, "end": 8, "text": "\u0414\u0430\u043d\u0438\u044f\u0440, \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u044c \u0438\u0442\u043e\u0433\u043e\u0432\u044b\u0439 \u043e\u0442\u0447\u0451\u0442 \u0434\u043e \u043f\u044f\u0442\u043d\u0438\u0446\u044b."},
            {"speaker": "SPEAKER_02", "start": 9, "end": 13, "text": "\u041d\u0443\u0440\u043b\u0430\u043d, \u0435\u0440\u0442\u0435\u04a3 \u043a\u043b\u0438\u0435\u043d\u0442\u043a\u0435 \u0444\u0438\u043d\u0430\u043b\u044c\u043d\u044b\u0439 \u0435\u0441\u0435\u043f\u0442\u0456 \u0436\u0456\u0431\u0435\u0440\u0456\u04a3\u0456\u0437."},
        ]}
        tasks = extract_tasks(transcript, {}, date(2026, 9, 23))
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0].assignee, "\u0414\u0430\u043d\u0438\u044f\u0440")
        self.assertEqual(tasks[0].deadline, "2026-09-25")
        self.assertEqual(tasks[1].assignee, "\u041d\u0443\u0440\u043b\u0430\u043d")
        self.assertEqual(tasks[1].deadline, "2026-09-24")
