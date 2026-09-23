"""
Текстовая диаризация — fallback для синтетических/TTS-аудиозаписей.

Проблема: pyannote.audio не может разделить спикеров, если аудио
сгенерировано одним голосом (TTS/синтетическое). В таком случае
используется текстовый анализ для определения смены спикера.

Алгоритм:
1. Ищем маркеры смены спикера в тексте:
   - Обращения по имени-отчеству: "Гульмира Сериковна, вам слово"
   - Благодарности: "Спасибо." (начало реплики нового спикера)
   - Согласия/подтверждения: "Понятно.", "Согласен.", "Хорошо."
   - Вопросы к конкретному человеку: "что у вас по...?"
2. Разбиваем текст на реплики и присваиваем спикеров.
"""

import re
from typing import List, Dict, Optional


# Паттерны для определения смены спикера
# Имя-отчество в тексте
NAME_PATTERN = re.compile(
    r'([А-ЯЁ][а-яёА-ЯЁ]+(?:\s+[А-ЯЁ][а-яёА-ЯЁ]+)?'
    r'(?:вна|вич|ович|евич|евна|ична))',
    re.UNICODE,
)

# Маркеры начала новой реплики
REPLY_START_MARKERS = [
    "Спасибо.",
    "Понятно.",
    "Согласен.",
    "Хорошо.",
    "Принято.",
    "Сделаем.",
    "Сделаю.",
    "Да.",
    "Нет.",
    "Так.",
    "Отлично.",
    "Договорились.",
]

# Маркеры обращения к другому спикеру (начало реплики руководителя)
ADDRESSING_PATTERNS = [
    r'[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(вна|вич),',  # "Гульмира Сериковна,"
    r'вам\s+слово',
    r'что\s+у\s+вас',
    r'что\s+предлагаете',
    r'как\s+вы\s+можете',
    r'вы\s+курируете',
    r'вы\s+же\s+курируете',
    r'подскажите\s+нам',
]


def text_based_diarization(
    segments: List[Dict],
    known_speakers: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Выполняет текстовую диаризацию на основе контекстных маркеров.

    Args:
        segments: сегменты из STT (с полем "text", "start", "end").
        known_speakers: список известных имен спикеров (если есть).

    Returns:
        Обновленные сегменты с корректными speaker labels.
    """
    # Объединяем весь текст для анализа
    full_text = " ".join(seg["text"] for seg in segments)

    # Извлекаем всех упомянутых людей
    all_names = _extract_names(full_text)

    if not all_names:
        return segments  # Не нашли имен — возвращаем как есть

    # Создаём маппинг имен → спикеров
    speaker_map = {}
    # Первый упомянутый = председатель (SPEAKER_00)
    # Остальные — в порядке появления
    for i, name in enumerate(all_names):
        speaker_map[name] = f"SPEAKER_{i:02d}"

    # Разбиваем объединённый текст на реплики
    result = []
    current_speaker = "SPEAKER_00"  # Председатель начинает

    for seg in segments:
        text = seg["text"]
        # Разбиваем сегмент на предложения
        sentences = _split_to_sentences(text)

        sub_segments = []
        current_sub_text = []
        current_sub_start = seg["start"]

        for i_sent, sentence in enumerate(sentences):
            # Проверяем, есть ли обращение к другому спикеру
            addressed = _detect_addressing(sentence, all_names)

            if addressed:
                # Сохраняем текущую реплику
                if current_sub_text:
                    sub_segments.append({
                        "speaker": current_speaker,
                        "text": " ".join(current_sub_text),
                    })
                    current_sub_text = []

                # Текущее предложение — от текущего спикера (он обращается)
                current_sub_text.append(sentence)
                sub_segments.append({
                    "speaker": current_speaker,
                    "text": " ".join(current_sub_text),
                })
                current_sub_text = []

                # Следующая реплика — от адресата
                current_speaker = speaker_map.get(addressed, current_speaker)
                continue

            # Проверяем маркеры начала реплики
            is_reply_start = _is_reply_marker(sentence)
            if is_reply_start and current_sub_text:
                # Это начало ответа — текущий спикер уже другой
                # (адресат, к которому обратились ранее)
                current_sub_text.append(sentence)
                continue

            # Проверяем, не начал ли говорить председатель (маркеры руководителя)
            is_boss = _is_chairman_marker(sentence)
            if is_boss and current_speaker != "SPEAKER_00":
                # Сохраняем текущую реплику
                if current_sub_text:
                    sub_segments.append({
                        "speaker": current_speaker,
                        "text": " ".join(current_sub_text),
                    })
                    current_sub_text = []
                current_speaker = "SPEAKER_00"

            current_sub_text.append(sentence)

        # Последняя реплика
        if current_sub_text:
            sub_segments.append({
                "speaker": current_speaker,
                "text": " ".join(current_sub_text),
            })

        # Распределяем таймкоды пропорционально длине текста
        total_chars = sum(len(s["text"]) for s in sub_segments)
        if total_chars == 0:
            continue

        seg_duration = seg["end"] - seg["start"]
        offset = seg["start"]

        for sub in sub_segments:
            proportion = len(sub["text"]) / total_chars
            duration = seg_duration * proportion
            result.append({
                "speaker": sub["speaker"],
                "start": round(offset, 2),
                "end": round(offset + duration, 2),
                "text": sub["text"],
            })
            offset += duration

    # Объединяем соседние реплики одного спикера
    merged = _merge_consecutive(result)

    return merged


def _extract_names(text: str) -> List[str]:
    """Извлекает уникальные имена-отчества из текста в порядке появления."""
    matches = NAME_PATTERN.findall(text)
    seen = set()
    names = []
    # Первый "спикер" (председатель) не упоминает себя по имени,
    # поэтому первое упомянутое имя — это SPEAKER_01
    for name in matches:
        name = name.strip()
        if name not in seen and len(name) > 5:
            seen.add(name)
            names.append(name)
    return names


def _split_to_sentences(text: str) -> List[str]:
    """Разбивает текст на предложения."""
    # Разделяем по . ? ! но не по числам (15.5) и не по сокращениям
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


def _detect_addressing(sentence: str, known_names: List[str]) -> Optional[str]:
    """
    Определяет, обращается ли говорящий к другому человеку.
    Возвращает имя адресата или None.
    """
    for name in known_names:
        # "Гульмира Сериковна, вам слово"
        # "Тимур Булатович, что у вас"
        if name in sentence:
            for pattern in ADDRESSING_PATTERNS:
                if re.search(pattern, sentence, re.IGNORECASE):
                    return name
            # Если имя + запятая — это обращение
            if f"{name}," in sentence:
                return name
    return None


def _is_reply_marker(sentence: str) -> bool:
    """Проверяет, начинается ли предложение с маркера ответа."""
    for marker in REPLY_START_MARKERS:
        if sentence.startswith(marker):
            return True
    return False


def _is_chairman_marker(sentence: str) -> bool:
    """Проверяет маркеры речи руководителя/председателя."""
    chairman_patterns = [
        r'Фиксируем\s+поручени',
        r'Это\s+недопустимо',
        r'Значит\s+так',
        r'Переходим\s+к',
        r'На\s+этом.*все',
        r'Все\s+свободны',
        r'жду\s+от\s+каждого',
        r'Итого',
        r'Согласен\.\s+Фиксируем',
    ]
    for pattern in chairman_patterns:
        if re.search(pattern, sentence, re.IGNORECASE):
            return True
    return False


def _merge_consecutive(segments: List[Dict]) -> List[Dict]:
    """Объединяет соседние сегменты одного спикера."""
    if not segments:
        return []

    merged = [segments[0].copy()]

    for seg in segments[1:]:
        prev = merged[-1]
        if seg["speaker"] == prev["speaker"]:
            prev["end"] = seg["end"]
            prev["text"] = prev["text"] + " " + seg["text"]
        else:
            merged.append(seg.copy())

    return merged
