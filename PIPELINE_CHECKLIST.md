# Pipeline MVP: что проверить

## Цепочка обработки

```text
meeting.mp3 / meeting.wav / meeting.mp4
        ↓
проверка расширения и файла
        ↓
FFmpeg: WAV, mono, 16 kHz
        ↓
local STT: faster-whisper
        ↓
local diarization: pyannote.audio
        ↓
alignment по пересечению временных интервалов
        ↓
Transcript JSON
        ↓
Python API / FastAPI POST /transcribe
```

## Перед запуском

Проверить наличие:

- Python 3.11+;
- FFmpeg в `PATH`;
- установленных пакетов из `requirements.txt`;
- локально скачанной модели faster-whisper;
- локально скачанной модели diarization;
- `HF_TOKEN` только на этапе первоначальной загрузки pyannote-модели.

После загрузки моделей отключить интернет и убедиться, что pipeline продолжает работать локально.

## Ручная проверка pipeline

1. Подготовить реальный файл `meeting.mp3` с русской, казахской и смешанной речью.
2. Запустить:

```powershell
python -c "from app import transcribe; import json; print(json.dumps(transcribe('meeting.mp3'), ensure_ascii=False, indent=2))"
```

3. Проверить, что результат содержит:

```json
{
  "duration": 0,
  "language": "ru|kk|mixed",
  "segments": [
    {
      "speaker": "SPEAKER_00",
      "start": 0.5,
      "end": 4.2,
      "text": "..."
    }
  ]
}
```

4. Проверить вручную:

- duration не меньше последнего сегмента;
- `start < end` у каждого сегмента;
- speaker IDs имеют формат `SPEAKER_00`, `SPEAKER_01`;
- русский текст распознаётся без потери сегментов;
- казахский текст не превращается полностью в русский;
- mixed RU/KZ фраза сохраняется одной фразой, если её временной интервал единый;
- смена говорящего происходит в разумном месте;
- текст не получает speaker другого человека из-за неверного overlap;
- MP4 обрабатывается через извлечение аудио;
- повреждённый или пустой файл возвращает понятную ошибку.

## Проверка HTTP API

Запустить сервер:

```powershell
python run.py
```

Отправить файл:

```powershell
curl.exe -X POST http://127.0.0.1:8000/transcribe -F "file=@meeting.mp3"
```

Проверить:

- HTTP 200 для MP3/WAV/MP4;
- JSON совпадает с Python API;
- HTTP 415 для неподдерживаемого расширения;
- понятная ошибка вместо traceback при проблеме FFmpeg, модели или памяти.

## Проверка offline/on-premise

1. Один раз скачать модели и зависимости.
2. Отключить сеть.
3. Повторно запустить Python API и `POST /transcribe`.
4. Убедиться, что аудио, текст и метаданные не отправляются во внешние cloud API.

## Что пока не проверять

Frontend, dashboard, summary, PDF/DOCX, email, reminders, интеграции Zoom/Teams/Meet и автоматическое определение настоящих имён находятся вне текущего MVP.
