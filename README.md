# Protokol AI

Локальный ассистент совещаний: загружает аудио, строит транскрипт с diarization, выделяет поручения, формирует summary и экспортирует протокол в PDF/DOCX.

## Возможности

- локальное распознавание MP3/WAV/MP4 через faster-whisper;
- diarization через pyannote.audio и ручное сопоставление `SPEAKER_XX` с именами;
- поручения: суть, ответственный, срок, исходная реплика, timestamp, confidence;
- нормализация «сегодня», «завтра», «до пятницы», «до конца месяца», а также `бүгін`, `ертең`, `жұмаға дейін`, `келесі аптада`;
- локальная Ollama LLM для улучшенного mixed RU/KZ анализа; без неё используются встроенные правила;
- редактирование поручений до экспорта;
- экспорт протокола в PDF и DOCX.

## Архитектура

`browser → FastAPI → FFmpeg → faster-whisper → pyannote → alignment → transcript JSON → Ollama/rules → protocol → PDF/DOCX`

Все данные хранятся в `output/meetings`; внешний cloud API для аудио, транскрипта или LLM не используется.

## Запуск

Нужны Python 3.11+, FFmpeg в `PATH`, а также локально скачанные модели faster-whisper и pyannote. Для первого скачивания pyannote нужен HF token и принятые условия модели.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

Откройте `http://127.0.0.1:8000`, выберите анонимизированную MP3/WAV/MP4 запись, укажите дату и нажмите «Обработать запись». После обработки укажите имена участников, проверьте поручения и скачайте протокол.

Для local LLM установите Ollama и локально загрузите выбранную модель, затем укажите `OLLAMA_MODEL` в `.env`. Без этой настройки приложение продолжает работать на правилах, но хуже понимает сложную смешанную речь.

## API

- `POST /api/meetings` — загрузить запись;
- `POST /api/meetings/{id}/process` — запустить обработку;
- `GET /api/meetings/{id}` — результат;
- `PUT /api/meetings/{id}/speaker-mapping` — сохранить имена;
- `GET /api/meetings/{id}/export/pdf`, `.../docx` — скачать протокол.

## Ограничения и roadmap

Качество зависит от записи и локальных моделей. Поручения отмечаются confidence и требуют подтверждения человеком. Подключения Teams/Zoom/Meet, напоминания, СЭД и dashboard статусов запланированы как следующие этапы.
