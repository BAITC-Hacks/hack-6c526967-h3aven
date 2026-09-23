#!/usr/bin/env python3
"""
CLI для запуска pipeline транскрибации.

Использование:
    python transcribe.py "Совещание №1.mp3"
    python transcribe.py meeting.mp3 --model medium --language ru
    python transcribe.py meeting.mp4 --num-speakers 3 --device cpu
"""

import argparse
import json
import sys
import os

# Добавляем корень проекта в PATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.transcriber import transcribe
from pipeline.export import export_all


def main():
    parser = argparse.ArgumentParser(
        description="Транскрибация совещания: Audio/Video -> JSON + DOCX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python transcribe.py meeting.mp3
  python transcribe.py meeting.mp3 --model medium --language ru
  python transcribe.py video.mp4 --num-speakers 3 --device cpu
  python transcribe.py meeting.wav --output result.json
        """,
    )

    parser.add_argument("file", help="Путь к аудио/видео файлу (MP3, WAV, MP4)")
    parser.add_argument("--model", "-m", default="large-v3",
        choices=["large-v3", "large-v3-turbo", "large-v2", "medium", "small", "base", "tiny"],
        help="Размер модели Whisper (default: large-v3)")
    parser.add_argument("--language", "-l", default=None,
        help="Язык: 'ru', 'kk', или не указывать для авто-определения")
    parser.add_argument("--device", "-d", default="auto",
        choices=["auto", "cuda", "cpu"],
        help="Устройство: auto / cuda / cpu (default: auto)")
    parser.add_argument("--num-speakers", "-n", type=int, default=None,
        help="Точное число спикеров (если известно)")
    parser.add_argument("--hf-token", default=None,
        help="HuggingFace токен для pyannote (или env HF_TOKEN)")
    parser.add_argument("--output", "-o", default=None,
        help="Путь для сохранения JSON")
    parser.add_argument("--output-dir", default="temp",
        help="Папка для временных файлов (default: temp)")
    parser.add_argument("--no-llm", action="store_true",
        help="Не запускать LLM-анализ")
    parser.add_argument("--ollama-model", default="auto",
        help="Модель Ollama или auto для автоматического выбора")
    parser.add_argument("--no-export", action="store_true",
        help="Не генерировать PDF, DOCX и Markdown")

    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Ошибка: файл не найден: {args.file}")
        sys.exit(1)

    # Запускаем pipeline
    result = transcribe(
        file_path=args.file,
        output_dir=args.output_dir,
        model_size=args.model,
        language=args.language,
        hf_token=args.hf_token,
        num_speakers=args.num_speakers,
        device=args.device,
        run_llm=not args.no_llm,
        ollama_model=args.ollama_model,
    )

    if not args.no_export:
        result.update(export_all(result, args.output_dir))
        print(f"\nPDF:  {result['pdf_path']}")
        print(f"DOCX: {result['docx_path']}")
        print(f"MD:   {result['markdown_path']}")

    # Сохраняем JSON
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"JSON: {args.output}")

    # Выводим краткий отчет
    print(f"\n{'─' * 50}")
    print("Транскрипт:")
    print(f"{'─' * 50}")
    for seg in result["segments"]:
        start_m, start_s = divmod(int(seg["start"]), 60)
        end_m, end_s = divmod(int(seg["end"]), 60)
        print(f"[{start_m:02d}:{start_s:02d} -> {end_m:02d}:{end_s:02d}] "
              f"{seg['speaker']}: {seg['text']}")

    # Выводим поручения
    analysis = result.get("analysis", {})
    tasks = analysis.get("tasks", []) if analysis else []
    if tasks:
        print(f"\n{'─' * 50}")
        print("Поручения:")
        print(f"{'─' * 50}")
        for i, task in enumerate(tasks, 1):
            priority = {"high": "!!!", "medium": "!!", "low": "!"}.get(
                task.get("priority", ""), ""
            )
            print(f"{i}. [{priority}] {task['task']}")
            print(f"   Ответственный: {task.get('assignee', 'Не указан')}")
            print(f"   Срок: {task.get('deadline', 'Не указан')}")

    quality = result.get("quality", {})
    if quality.get("warnings"):
        print("\nТребует проверки:")
        for warning in quality["warnings"]:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
