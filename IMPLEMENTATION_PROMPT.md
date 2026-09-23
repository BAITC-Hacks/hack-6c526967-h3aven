# Промпт для проверки и продолжения MVP

Ты работаешь с локальным/on-premise проектом транскрибирования совещаний.

Цель текущего этапа:

```text
MP3/WAV/MP4
→ preprocessing
→ local STT
→ local speaker diarization
→ STT + diarization alignment
→ Transcript JSON
→ Python API
→ FastAPI POST /transcribe
```

Работай непосредственно с файлами проекта. Не ограничивайся объяснением архитектуры и псевдокодом. Не добавляй frontend, dashboard, summary, PDF, DOCX, email, reminders, интеграции или README.

Сначала проверь текущую структуру и существующий код. Не ломай рабочие части. Затем проверь pipeline по файлу `PIPELINE_CHECKLIST.md`.

Обязательные требования:

1. MP3 и WAV должны поддерживаться обязательно, MP4 — через FFmpeg.
2. Аудио нужно приводить к WAV/mono/16 kHz либо формату, требуемому моделью.
3. STT должен работать локально через заменяемый backend. Текущий backend — faster-whisper.
4. Diarization должна работать локально через отдельный backend. Текущий backend — pyannote.audio.
5. Итоговый каждый segment обязан содержать `speaker`, `start`, `end`, `text`.
6. Speaker IDs должны иметь формат `SPEAKER_00`, `SPEAKER_01`, `SPEAKER_02`.
7. Основной результат должен соответствовать:

```json
{
  "duration": 245,
  "language": "mixed",
  "segments": []
}
```

8. Должны существовать Python-вызов `transcribe("meeting.mp3")` и endpoint `POST /transcribe`.
9. Ошибки неподдерживаемого, пустого или повреждённого файла, отсутствующего FFmpeg, отсутствующих моделей, нехватки памяти и ошибок diarization должны возвращаться понятно.
10. Runtime не должен зависеть от внешнего cloud speech API. После первоначальной загрузки моделей pipeline должен работать offline.

Порядок работы:

1. Найди текущие проблемы в pipeline.
2. Исправь preprocessing.
3. Проверь STT.
4. Проверь diarization.
5. Проверь alignment на реальном аудио минимум с тремя говорящими.
6. Проверь русский, казахский и mixed RU/KZ фрагменты.
7. Проверь Python API.
8. Проверь FastAPI endpoint.
9. Выполни ручную end-to-end проверку по `PIPELINE_CHECKLIST.md`.
10. В конце сообщи только: какие файлы изменены, какую команду запуска использовал, что реально проверено и какие внешние зависимости ещё нужно установить.

Не подменяй реальный inference выдуманным transcript JSON. Если модель невозможно запустить из-за окружения, явно укажи это и продолжи проверку доступной части pipeline.
