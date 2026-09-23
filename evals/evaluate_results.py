"""Offline quality check for the supplied hackathon recordings."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


EXPECTED = {
    "Совещание №1": [
        "стратегию закупа сырья",
        "совещание с проектным институтом",
        "финансовое решение",
        "юридическую проверку",
        "сводный отчёт",
        "разобраться с подрядчиком",
        "аудит датчиков",
        "внеплановый инструктаж",
        "согласовать бюджет",
        "заключение юристов",
    ],
    "Совещание №2": [
        "претензию поставщику",
        "альтернативного поставщика",
        "совещание с подрядчиками",
        "справку по итогам",
        "дополнительные группы",
        "уведомление подрядчикам",
        "обновить шаблон договора",
    ],
}


def tokens(value: str) -> set[str]:
    return {
        word for word in re.findall(r"[а-яёәғқңөұүһіa-z]+", value.lower())
        if len(word) > 3
    }


def similar(left: str, right: str) -> float:
    first, second = tokens(left), tokens(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first)


def evaluate(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    source = Path(data.get("source_file", path.stem)).stem
    expected = EXPECTED.get(source, [])
    tasks = (data.get("analysis") or {}).get("tasks", [])
    matched = [
        item for item in expected
        if any(similar(item, task.get("task", "")) >= 0.45 for task in tasks)
    ]
    owner_rate = (
        sum(task.get("assignee") not in (None, "", "Не указан") for task in tasks) / len(tasks)
        if tasks else 0.0
    )
    deadline_rate = (
        sum(task.get("deadline") not in (None, "", "Не указан") for task in tasks) / len(tasks)
        if tasks else 0.0
    )
    recall = len(matched) / len(expected) if expected else 0.0
    return {
        "source": source,
        "expected_tasks": len(expected),
        "extracted_tasks": len(tasks),
        "task_recall": round(recall, 3),
        "owner_coverage": round(owner_rate, 3),
        "deadline_coverage": round(deadline_rate, 3),
        "matched": matched,
        "missing": [item for item in expected if item not in matched],
        "quality_score": round((recall * 0.6 + owner_rate * 0.2 + deadline_rate * 0.2) * 100, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path, help="Pipeline JSON result")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
