"""Structured meeting analysis through NVIDIA NIM, Ollama, or offline fallback."""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional


SYSTEM_PROMPT = """Ты - локальный ИИ-секретарь совещаний Казахстана.
Транскрипт может содержать русский, казахский и шала-казахский. Понимай оба языка,
не переводи и не искажай ФИО. Опирайся только на транскрипт.

Верни ТОЛЬКО валидный JSON следующей структуры:
{
  "title": "краткое деловое название",
  "date_mentioned": null,
  "languages": ["ru", "kk"],
  "agenda": ["тема"],
  "participants": [{"name": "ФИО", "role": "роль или пустая строка"}],
  "speaker_map": {"SPEAKER_00": "ФИО или SPEAKER_00"},
  "summary": "содержательное саммари в 3-7 предложениях",
  "key_decisions": ["принятое решение"],
  "risks": ["риск или проблема"],
  "tasks": [{
    "task": "конкретное действие с глагола",
    "assignee": "одно ФИО/подразделение или Не указан",
    "deadline": "срок как в речи или Не указан",
    "priority": "high|medium|low",
    "context": "зачем это нужно",
    "evidence": "короткая подтверждающая цитата из транскрипта",
    "source_time": "MM:SS",
    "confidence": 0.0
  }]
}

Правила качества:
1. Извлеки все явные и неявные поручения, но не превращай пожелания в задачи.
2. Ответственного бери из прямого обращения, принятия задачи или явной формулировки.
3. Сохраняй относительные сроки: до пятницы, к среде, на следующей неделе.
4. speaker_map заполняй только при наличии текстового доказательства; не угадывай.
5. Каждое поручение должно иметь evidence и source_time. Не выдумывай факты.
6. Значения пиши по-русски, казахские имена и фразы сохраняй как в транскрипте.
"""

NAME_PATTERN = re.compile(
    r"([А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі-]+(?:\s+"
    r"[А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі-]+(?:ович|евич|ұлы|қызы|овна|евна|қызы|вич|вна))?)"
)
IMPERATIVE = re.compile(
    r"\b(разработать|провести|подготовить|представить|проверить|разобраться|"
    r"разберитесь|проверьте|свяжитесь|согласовать|организовать|привлечь|"
    r"направить|обновить|запросить|запросите|доложить|найти|выполнить|өткізу|"
    r"дайындау|тексеру|келісу|ұсыну)\b",
    re.IGNORECASE,
)


def get_ollama_status(base_url: str = "http://127.0.0.1:11434") -> dict:
    try:
        import requests

        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        response.raise_for_status()
        models = [item.get("name", "") for item in response.json().get("models", [])]
        return {"available": True, "models": [name for name in models if name]}
    except Exception as error:
        return {"available": False, "models": [], "error": str(error)}


def _select_model(requested: Optional[str], available: List[str]) -> Optional[str]:
    if not available:
        return None
    if requested and requested != "auto":
        for candidate in available:
            if candidate == requested or candidate.split(":")[0] == requested.split(":")[0]:
                return candidate
    preferred = [
        "qwen3:4b", "qwen2.5:3b", "qwen2.5:7b", "gemma3:4b",
        "gemma2:2b", "llama3.2:3b", "mistral:7b",
    ]
    for prefix in preferred:
        for candidate in available:
            if candidate.startswith(prefix.split(":")[0]):
                return candidate
    return available[0]


def analyze_transcript(
    transcript_data: dict,
    ollama_model: str = "auto",
    ollama_url: str = "http://127.0.0.1:11434",
) -> dict:
    """Extract minutes, decisions, tasks, owners, and deadlines locally."""
    transcript_text = _format_transcript_for_llm(transcript_data)
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if nvidia_key and os.getenv("ALLOW_CLOUD_ANALYSIS", "0") == "1":
        try:
            chunks = _chunk_transcript(transcript_text)
            nvidia_model = os.getenv(
                "NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"
            ).strip()
            partials = [
                _analyze_with_nvidia(chunk, nvidia_model, nvidia_key)
                for chunk in chunks
            ]
            result = _merge_results([item for item in partials if item])
            result["analysis_engine"] = f"nvidia-nim:{nvidia_model}"
            return result
        except Exception as error:
            print(f"[llm] NVIDIA NIM не завершил анализ: {error}")

    status = get_ollama_status(ollama_url)
    selected_model = _select_model(ollama_model, status.get("models", []))
    if selected_model:
        try:
            chunks = _chunk_transcript(transcript_text)
            partials = [
                _analyze_with_ollama(chunk, selected_model, ollama_url)
                for chunk in chunks
            ]
            result = _merge_results([item for item in partials if item])
            result["analysis_engine"] = f"ollama:{selected_model}"
            return result
        except Exception as error:
            print(f"[llm] Ollama не завершил анализ: {error}")

    result = _analyze_with_regex(transcript_text, transcript_data)
    result["analysis_engine"] = "deterministic-fallback"
    result["analysis_warning"] = status.get("error", "В Ollama нет подходящей модели")
    return result


def _decode_json_response(content: str, provider: str) -> dict:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            raise ValueError(f"{provider} вернул невалидный JSON")
        data = json.loads(match.group())
    return _validate_and_normalize(data)


def _analyze_with_nvidia(text: str, model: str, api_key: str) -> dict:
    """Analyze one transcript chunk through NVIDIA's OpenAI-compatible NIM API."""
    import requests

    response = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Транскрипт:\n{text}"},
            ],
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": 4096,
            "stream": False,
        },
        timeout=180,
    )
    response.raise_for_status()
    content = response.json().get("choices", [{}])[0].get("message", {}).get(
        "content", ""
    )
    return _decode_json_response(content, "NVIDIA NIM")


def _format_transcript_for_llm(transcript_data: dict) -> str:
    lines = []
    for segment in transcript_data.get("segments", []):
        seconds = int(segment.get("start", 0))
        timestamp = f"{seconds // 60:02d}:{seconds % 60:02d}"
        lines.append(
            f"[{timestamp}] {segment.get('speaker', 'SPEAKER_00')}: "
            f"{segment.get('text', '').strip()}"
        )
    return "\n".join(lines)


def _chunk_transcript(text: str, max_chars: int = 22000) -> List[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [text]


def _analyze_with_ollama(text: str, model: str, base_url: str) -> dict:
    import requests

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Транскрипт:\n{text}"},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.05, "num_predict": 6000, "num_ctx": 16384},
    }
    response = requests.post(
        f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=600
    )
    response.raise_for_status()
    content = response.json().get("message", {}).get("content", "")
    return _decode_json_response(content, "Ollama")


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _validate_and_normalize(result: dict) -> dict:
    normalized = {
        "title": str(result.get("title") or "Протокол совещания"),
        "date_mentioned": result.get("date_mentioned"),
        "languages": [str(item) for item in _as_list(result.get("languages"))],
        "agenda": [str(item) for item in _as_list(result.get("agenda")) if item],
        "participants": [],
        "speaker_map": {},
        "summary": str(result.get("summary") or ""),
        "key_decisions": [
            str(item) for item in _as_list(result.get("key_decisions")) if item
        ],
        "risks": [str(item) for item in _as_list(result.get("risks")) if item],
        "tasks": [],
    }
    for participant in _as_list(result.get("participants")):
        if isinstance(participant, dict) and participant.get("name"):
            normalized["participants"].append(
                {"name": str(participant["name"]), "role": str(participant.get("role") or "")}
            )
    if isinstance(result.get("speaker_map"), dict):
        normalized["speaker_map"] = {
            str(key): str(value)
            for key, value in result["speaker_map"].items()
            if str(key).startswith("SPEAKER_") and value
        }

    for task in _as_list(result.get("tasks")):
        if not isinstance(task, dict):
            continue
        description = str(task.get("task") or task.get("description") or "").strip()
        if not description:
            continue
        try:
            confidence = max(0.0, min(1.0, float(task.get("confidence", 0.75))))
        except (TypeError, ValueError):
            confidence = 0.75
        priority = str(task.get("priority") or "medium").lower()
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        normalized["tasks"].append(
            {
                "task": description,
                "assignee": str(task.get("assignee") or "Не указан"),
                "deadline": str(task.get("deadline") or "Не указан"),
                "priority": priority,
                "context": str(task.get("context") or ""),
                "evidence": str(task.get("evidence") or ""),
                "source_time": str(task.get("source_time") or ""),
                "confidence": round(confidence, 2),
                "status": str(task.get("status") or "pending"),
            }
        )
    normalized["tasks"] = _deduplicate_tasks(normalized["tasks"])
    return normalized


def _merge_results(results: List[dict]) -> dict:
    if not results:
        raise ValueError("LLM не вернула ни одного результата")
    merged = _validate_and_normalize(results[0])
    for result in results[1:]:
        current = _validate_and_normalize(result)
        merged["agenda"].extend(current["agenda"])
        merged["participants"].extend(current["participants"])
        merged["key_decisions"].extend(current["key_decisions"])
        merged["risks"].extend(current["risks"])
        merged["tasks"].extend(current["tasks"])
        merged["speaker_map"].update(current["speaker_map"])
        if current["summary"]:
            merged["summary"] = (merged["summary"] + " " + current["summary"]).strip()
    for key in ("agenda", "key_decisions", "risks"):
        merged[key] = list(dict.fromkeys(merged[key]))
    participants = {item["name"]: item for item in merged["participants"]}
    merged["participants"] = list(participants.values())
    merged["tasks"] = _deduplicate_tasks(merged["tasks"])
    return merged


def _deduplicate_tasks(tasks: List[dict]) -> List[dict]:
    unique: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for task in tasks:
        words = re.findall(r"[\w-]+", task.get("task", "").lower())[:7]
        key = (" ".join(words), task.get("assignee", "").lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(task)
    return unique


def _extract_deadline(text: str) -> str:
    patterns = [
        r"\b(?:срок\s*[–—:-]?\s*)?((?:до|к)\s+\d{1,2}\s+[а-яёәғқңөұүһі]+)",
        r"\b((?:до|к)\s+(?:понедельник[а-я]*|вторник[а-я]*|сред[а-я]*|четверг[а-я]*|пятниц[а-я]*))",
        r"\b((?:на|в)\s+(?:этой|текущей|следующей)\s+недел[а-я]*)",
        r"\b(за\s+\d+\s+(?:дн(?:я|ей)|недел[а-я]*))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "Не указан"


def _nearest_name(text: str, before: int) -> str:
    candidates = list(NAME_PATTERN.finditer(text[:before]))
    if not candidates:
        return "Не указан"
    candidate = candidates[-1]
    if before - candidate.end() > 220:
        return "Не указан"
    return candidate.group(1).strip()


def _analyze_with_regex(transcript_text: str, transcript_data: dict) -> dict:
    full_text = " ".join(
        segment.get("text", "") for segment in transcript_data.get("segments", [])
    )
    names = list(dict.fromkeys(match.group(1).strip() for match in NAME_PATTERN.finditer(full_text)))
    tasks: list[dict] = []

    block = re.search(
        r"фиксируем\s+поручения(.+?)(?:договорились|следующее\s+совещание|так,\s*по)",
        full_text,
        re.IGNORECASE,
    )
    if block:
        items = re.split(r"(?=\b\d+\.\s+[А-ЯЁӘҒҚҢӨҰҮҺІ])", block.group(1))
        for item in items:
            item = re.sub(r"^\s*\d+\.\s*", "", item).strip()
            if len(item) < 12:
                continue
            description = re.split(r"\s+[Оо]тветственн(?:ый|ая)\b", item)[0]
            description = re.split(r"\s+[Сс]рок\s*[–—:-]", description)[0].strip(" .")
            assignee_match = re.search(
                r"[Оо]тветственн(?:ый|ая)\s*[–—:-]?\s*(.+?)(?=\.\s*(?:Срок|\d+\.)|$)", item
            )
            assignee = assignee_match.group(1).strip(" .") if assignee_match else "Не указан"
            if assignee == "Не указан" and "юридическ" in item.lower():
                assignee = "Юридический департамент"
            tasks.append(
                _task(
                    description,
                    assignee,
                    _extract_deadline(item),
                    evidence=item[:220],
                    confidence=0.94,
                )
            )

    for segment in transcript_data.get("segments", []):
        text = segment.get("text", "")
        for match in IMPERATIVE.finditer(text):
            sentence_start = max(text.rfind(".", 0, match.start()) + 1, 0)
            sentence_end = text.find(".", match.end())
            if sentence_end < 0:
                sentence_end = min(len(text), match.end() + 220)
            sentence = text[sentence_start:sentence_end].strip(" ,")
            if len(sentence) < 12:
                continue
            assignee = _nearest_name(text, match.start())
            task = _task(
                sentence.capitalize(), assignee, _extract_deadline(sentence),
                evidence=sentence[:220],
                source_time=_format_time(segment.get("start", 0)),
                confidence=0.72 if assignee == "Не указан" else 0.84,
            )
            tasks.append(task)

    decisions = []
    for sentence in re.split(r"(?<=[.!?])\s+", full_text):
        if re.search(r"\b(решили|утвердили|согласовали|договорились)\b", sentence, re.IGNORECASE):
            decisions.append(sentence.strip()[:300])

    agenda = []
    agenda_match = re.search(r"на\s+повестке\s+(.+?)(?:\.|$)", full_text, re.IGNORECASE)
    if agenda_match:
        agenda.append(agenda_match.group(1).strip())
    agenda.extend(
        item.strip() for item in re.findall(r"переходим\s+(?:ко?|к)\s+(.+?)(?:\.|$)", full_text, re.IGNORECASE)
    )

    result = {
        "title": "Протокол совещания",
        "date_mentioned": None,
        "languages": [transcript_data.get("language", "unknown")],
        "agenda": list(dict.fromkeys(agenda)) or ["Рабочие вопросы совещания"],
        "participants": [{"name": name, "role": ""} for name in names],
        "speaker_map": {},
        "summary": _generate_basic_summary(full_text, tasks, names),
        "key_decisions": list(dict.fromkeys(decisions)),
        "risks": [],
        "tasks": _deduplicate_tasks(tasks),
    }
    return _validate_and_normalize(result)


def _task(
    description: str,
    assignee: str,
    deadline: str,
    evidence: str,
    source_time: str = "",
    confidence: float = 0.75,
) -> dict:
    lowered = description.lower()
    priority = "high" if any(
        marker in lowered for marker in ("сроч", "недопустим", "немедлен", "расторг")
    ) else "medium"
    return {
        "task": description.strip(" ."),
        "assignee": assignee or "Не указан",
        "deadline": deadline or "Не указан",
        "priority": priority,
        "context": "",
        "evidence": evidence,
        "source_time": source_time,
        "confidence": confidence,
        "status": "pending",
    }


def _format_time(seconds) -> str:
    value = int(float(seconds or 0))
    return f"{value // 60:02d}:{value % 60:02d}"


def _generate_basic_summary(text: str, tasks: list, participants: list) -> str:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]
    intro = " ".join(sentences[:3])[:450]
    people = ", ".join(participants[:6]) if participants else "не определены"
    return (
        f"Обсуждены рабочие вопросы совещания. {intro} "
        f"Участники: {people}. Зафиксировано поручений: {len(tasks)}."
    ).strip()
