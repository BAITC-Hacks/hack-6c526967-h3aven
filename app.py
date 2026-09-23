"""SÖZDE Streamlit application."""

from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path

import streamlit as st

from pipeline.audio_processor import find_ffmpeg
from pipeline.export import export_all
from pipeline.llm_analyzer import get_ollama_status
from pipeline.transcriber import transcribe


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "temp"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SUPPORTED_TYPES = ["mp3", "wav", "m4a", "mp4", "webm", "ogg", "flac"]
STATUS_LABELS = {
    "pending": "Ожидает",
    "in_progress": "В работе",
    "done": "Выполнено",
    "overdue": "Просрочено",
}
PRIORITY_LABELS = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}


st.set_page_config(
    page_title="SÖZDE | Протокол совещания",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
      :root { --navy:#17324d; --green:#18705f; --ink:#1f2933; --line:#d7dee5; }
      html, body, [class*="css"] { font-family: "Segoe UI", Arial, sans-serif; }
      .block-container { max-width: 1280px; padding-top: 1.4rem; padding-bottom: 3rem; }
      h1, h2, h3 { letter-spacing: 0; color: var(--ink); }
      h1 { font-size: 2rem; }
      h2 { font-size: 1.35rem; }
      h3 { font-size: 1.05rem; }
      [data-testid="stSidebar"] { background:#13283c; }
      [data-testid="stSidebar"] * { color:#f3f6f8; }
      [data-testid="stMetric"] { border-top:3px solid var(--green); padding-top:.65rem; }
      [data-testid="stFileUploader"] { border:1px solid var(--line); border-radius:6px; }
      .product-mark { color:#fff; font-size:1.25rem; font-weight:700; margin:.25rem 0 1rem; }
      .privacy-line { border-left:4px solid var(--green); padding:.65rem .9rem; background:#eef7f4; }
      .transcript-row { border-left:3px solid #507ca5; padding:.55rem .8rem; margin:.35rem 0; background:#f7f9fb; }
      .muted { color:#66727d; font-size:.86rem; }
      .ok { color:#146c43; font-weight:600; }
      .warn { color:#9a5a00; font-weight:600; }
      div[data-testid="stButton"] button { border-radius:6px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _safe_name(value: str) -> str:
    name = Path(value).name
    return "".join(char for char in name if char.isalnum() or char in " ._-№")[:150]


def _persist_result(result: dict) -> None:
    source = Path(result.get("source_file", "meeting")).stem
    path = OUTPUT_DIR / f"{source}_transcript.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["json_path"] = str(path)


def _load_saved_results() -> dict:
    results = {}
    for path in sorted(OUTPUT_DIR.glob("*_transcript.json"), key=lambda item: item.stat().st_mtime):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            value["json_path"] = str(path)
            stem = path.name.removesuffix("_transcript.json")
            for key, suffix in (
                ("pdf_path", ".pdf"), ("docx_path", ".docx"), ("markdown_path", ".md")
            ):
                candidate = OUTPUT_DIR / f"Протокол_{stem}{suffix}"
                if candidate.exists():
                    value[key] = str(candidate)
            results[value.get("source_file", path.name)] = value
        except (OSError, ValueError, TypeError):
            continue
    return results


def _process(source: Path, settings: dict) -> dict:
    progress = st.progress(0, text="Подготовка")

    if settings.get("nvidia_api_key"):
        os.environ["NVIDIA_API_KEY"] = settings["nvidia_api_key"]
        os.environ["NVIDIA_MODEL"] = settings["nvidia_model"]

    def update(value: int, message: str) -> None:
        progress.progress(value, text=message)

    result = transcribe(
        file_path=str(source),
        output_dir=str(OUTPUT_DIR),
        model_size=settings["model"],
        language=settings["language"],
        hf_token=settings["hf_token"] or None,
        num_speakers=settings["num_speakers"] or None,
        device="auto",
        run_llm=True,
        ollama_model=settings["ollama_model"],
        progress_callback=update,
    )
    update(96, "Формирование PDF, DOCX и Markdown")
    result.update(export_all(result, str(OUTPUT_DIR)))
    _persist_result(result)
    progress.progress(100, text="Протокол готов")
    return result


def _downloads(result: dict) -> None:
    columns = st.columns(4)
    download_specs = [
        ("PDF", "pdf_path", "application/pdf"),
        ("DOCX", "docx_path", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("Markdown", "markdown_path", "text/markdown"),
    ]
    for column, (label, key, mime) in zip(columns[:3], download_specs):
        path = result.get(key)
        with column:
            if path and Path(path).is_file():
                st.download_button(
                    label,
                    data=Path(path).read_bytes(),
                    file_name=Path(path).name,
                    mime=mime,
                    use_container_width=True,
                )
    with columns[3]:
        st.download_button(
            "JSON",
            data=json.dumps(result, ensure_ascii=False, indent=2),
            file_name=f"{Path(result.get('source_file', 'meeting')).stem}.json",
            mime="application/json",
            use_container_width=True,
        )


def _metrics(result: dict) -> None:
    analysis = result.get("analysis") or {}
    quality = result.get("quality") or {}
    columns = st.columns(5)
    duration = int(result.get("duration", 0))
    values = [
        ("Длительность", f"{duration // 60}:{duration % 60:02d}"),
        ("Спикеров", result.get("num_speakers", 0)),
        ("Поручений", len(analysis.get("tasks", []))),
        ("С ответственным", quality.get("tasks_with_assignee", 0)),
        ("Со сроком", quality.get("tasks_with_deadline", 0)),
    ]
    for column, (label, value) in zip(columns, values):
        column.metric(label, value)


def _apply_speaker_names(result: dict, mapping: dict) -> None:
    for segment in result.get("segments", []):
        old = segment.get("speaker", "")
        new = mapping.get(old, old).strip()
        if new and new != old:
            segment["speaker_id"] = segment.get("speaker_id", old)
            segment["speaker"] = new
    for task in (result.get("analysis") or {}).get("tasks", []):
        old = task.get("assignee", "")
        if old in mapping and mapping[old].strip():
            task["assignee"] = mapping[old].strip()
    result["num_speakers"] = len({item.get("speaker") for item in result.get("segments", [])})
    result.update(export_all(result, str(OUTPUT_DIR)))
    _persist_result(result)


if "results" not in st.session_state:
    st.session_state.results = _load_saved_results()
if "current_result" not in st.session_state:
    st.session_state.current_result = next(reversed(st.session_state.results.values()), None) if st.session_state.results else None


with st.sidebar:
    st.markdown('<div class="product-mark">SÖZDE</div>', unsafe_allow_html=True)
    page = st.radio(
        "Раздел",
        ["Обработка", "Протокол", "Поручения", "Система"],
        label_visibility="collapsed",
    )
    st.divider()
    with st.expander("Параметры обработки", expanded=False):
        model = st.selectbox(
            "Модель распознавания",
            ["large-v3", "large-v3-turbo", "medium", "small"],
            index=0,
            help="large-v3 запускается в экономном режиме на GPU с 4 ГБ VRAM",
        )
        language_option = st.selectbox(
            "Язык записи",
            [("Авто: русский + казахский", None), ("Русский", "ru"), ("Казахский", "kk")],
            format_func=lambda item: item[0],
        )
        num_speakers = st.number_input("Количество спикеров", 0, 20, 0)
        nvidia_api_key = st.text_input(
            "NVIDIA API key (необязательно)",
            type="password",
            value=os.environ.get("NVIDIA_API_KEY", ""),
            help="Используется только для анализа готового транскрипта через NVIDIA NIM",
        )
        nvidia_model = st.text_input(
            "NVIDIA NIM модель",
            value=os.environ.get("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"),
        )
        ollama_model = st.text_input("Резервная модель Ollama", value="auto")
        hf_token = st.text_input(
            "HF token (необязательно)", type="password", value=os.environ.get("HF_TOKEN", "")
        )
    settings = {
        "model": model,
        "language": language_option[1],
        "num_speakers": int(num_speakers),
        "ollama_model": ollama_model.strip() or "auto",
        "nvidia_api_key": nvidia_api_key.strip(),
        "nvidia_model": nvidia_model.strip() or "meta/llama-3.1-70b-instruct",
        "hf_token": hf_token,
    }
    st.markdown(
        '<div class="muted" style="color:#b8c3cc">HackAlem AI 2026<br/>Локальная обработка данных</div>',
        unsafe_allow_html=True,
    )


if page == "Обработка":
    st.title("SÖZDE")
    st.caption("Автопротоколирование совещаний на русском, казахском и смешанной речи")
    st.markdown(
        '<div class="privacy-line">Аудио распознаётся локально. Без NVIDIA API key весь конвейер работает офлайн.</div>',
        unsafe_allow_html=True,
    )
    st.write("")

    upload_tab, demo_tab = st.tabs(["Загрузить запись", "Демо-записи"])
    source_path = None
    with upload_tab:
        uploaded = st.file_uploader("Аудио или видео", type=SUPPORTED_TYPES)
        if uploaded:
            source_path = OUTPUT_DIR / _safe_name(uploaded.name)
            source_path.write_bytes(uploaded.getbuffer())
            st.audio(str(source_path))
    with demo_tab:
        samples = sorted(PROJECT_DIR.glob("Совещание №*.mp3"))
        if samples:
            sample = st.selectbox("Запись", samples, format_func=lambda item: item.name)
            st.audio(str(sample))
            if st.checkbox("Использовать выбранную демо-запись"):
                source_path = sample
        else:
            st.info("Демо-записи не найдены в корне проекта")

    if source_path and st.button("Сформировать протокол", type="primary", use_container_width=True):
        try:
            with st.status("Обработка записи", expanded=True) as status:
                result = _process(source_path, settings)
                st.session_state.current_result = result
                st.session_state.results[result["source_file"]] = result
                status.update(label="Протокол сформирован", state="complete")
        except Exception as error:
            st.error(f"Обработка не завершена: {error}")
            with st.expander("Технические подробности"):
                st.exception(error)

    result = st.session_state.current_result
    if result:
        st.divider()
        _metrics(result)
        quality = result.get("quality", {})
        for warning in quality.get("warnings", []):
            st.warning(warning)
        st.subheader("Транскрипт")
        for segment in result.get("segments", []):
            start, end = int(segment.get("start", 0)), int(segment.get("end", 0))
            st.markdown(
                f'<div class="transcript-row"><span class="muted">'
                f'[{start // 60:02d}:{start % 60:02d} - {end // 60:02d}:{end % 60:02d}]</span> '
                f'<b>{escape(str(segment.get("speaker", "SPEAKER_00")))}</b><br/>'
                f'{escape(str(segment.get("text", "")))}</div>',
                unsafe_allow_html=True,
            )
        st.subheader("Экспорт")
        _downloads(result)


elif page == "Протокол":
    st.title("Протокол совещания")
    result = st.session_state.current_result
    if not result:
        st.info("Сначала обработайте запись")
    else:
        analysis = result.get("analysis") or {}
        _metrics(result)
        st.subheader("Саммари")
        st.write(analysis.get("summary") or "Саммари не сформировано")

        left, right = st.columns(2)
        with left:
            st.subheader("Повестка")
            for item in analysis.get("agenda", []):
                st.markdown(f"- {item}")
        with right:
            st.subheader("Решения")
            for item in analysis.get("key_decisions", []):
                st.markdown(f"- {item}")

        speakers = list(dict.fromkeys(item.get("speaker") for item in result.get("segments", [])))
        with st.expander("Имена спикеров", expanded=False):
            st.caption("Подтвердите или исправьте метки перед экспортом")
            mapping = {
                speaker: st.text_input(speaker, value=speaker, key=f"speaker_{index}_{speaker}")
                for index, speaker in enumerate(speakers)
            }
            if st.button("Применить имена"):
                _apply_speaker_names(result, mapping)
                st.success("Имена обновлены во всех форматах")

        st.subheader("Поручения")
        tasks = analysis.get("tasks", [])
        if tasks:
            import pandas as pd

            columns = ["task", "assignee", "deadline", "priority", "status", "confidence"]
            frame = pd.DataFrame(tasks)
            for column in columns:
                if column not in frame:
                    frame[column] = ""
            edited = st.data_editor(
                frame[columns],
                use_container_width=True,
                num_rows="dynamic",
                hide_index=True,
                column_config={
                    "task": "Поручение",
                    "assignee": "Ответственный",
                    "deadline": "Срок",
                    "priority": st.column_config.SelectboxColumn(
                        "Приоритет", options=["high", "medium", "low"]
                    ),
                    "status": st.column_config.SelectboxColumn(
                        "Статус", options=list(STATUS_LABELS)
                    ),
                    "confidence": st.column_config.NumberColumn(
                        "Уверенность", min_value=0.0, max_value=1.0, format="%.2f"
                    ),
                },
                key="protocol_task_editor",
            )
            if st.button("Сохранить правки протокола"):
                preserved = {index: task for index, task in enumerate(tasks)}
                updated = []
                for index, item in enumerate(edited.to_dict("records")):
                    original = preserved.get(index, {})
                    updated.append({**original, **item})
                analysis["tasks"] = updated
                result.update(export_all(result, str(OUTPUT_DIR)))
                _persist_result(result)
                st.success("Правки сохранены; документы обновлены")
        else:
            st.info("Поручения не найдены")
        st.subheader("Экспорт")
        _downloads(result)


elif page == "Поручения":
    st.title("Контроль поручений")
    rows = []
    references = []
    for source, result in st.session_state.results.items():
        for index, task in enumerate((result.get("analysis") or {}).get("tasks", [])):
            rows.append({
                "source": source,
                "task": task.get("task", ""),
                "assignee": task.get("assignee", "Не указан"),
                "deadline": task.get("deadline", "Не указан"),
                "priority": task.get("priority", "medium"),
                "status": task.get("status", "pending"),
            })
            references.append((result, index))
    if not rows:
        st.info("Нет поручений для контроля")
    else:
        counts = {
            status: sum(1 for row in rows if row["status"] == status)
            for status in STATUS_LABELS
        }
        columns = st.columns(4)
        for column, status in zip(columns, STATUS_LABELS):
            column.metric(STATUS_LABELS[status], counts[status])

        import pandas as pd

        edited = st.data_editor(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            disabled=["source"],
            column_config={
                "source": "Совещание",
                "task": "Поручение",
                "assignee": "Ответственный",
                "deadline": "Срок",
                "priority": st.column_config.SelectboxColumn(
                    "Приоритет", options=["high", "medium", "low"]
                ),
                "status": st.column_config.SelectboxColumn(
                    "Статус", options=list(STATUS_LABELS)
                ),
            },
            key="dashboard_editor",
        )
        if st.button("Сохранить статусы"):
            for item, (result, task_index) in zip(edited.to_dict("records"), references):
                task = result["analysis"]["tasks"][task_index]
                task.update({key: item[key] for key in ("task", "assignee", "deadline", "priority", "status")})
                _persist_result(result)
            st.success("Статусы сохранены")


elif page == "Система":
    st.title("Готовность системы")
    ollama = get_ollama_status()
    try:
        import ctranslate2

        cuda_count = ctranslate2.get_cuda_device_count()
    except Exception:
        cuda_count = 0
    try:
        import diarize  # noqa: F401

        diarization_ready = True
    except Exception:
        diarization_ready = False

    checks = [
        ("FFmpeg", bool(find_ffmpeg()), find_ffmpeg() or "не найден"),
        ("NVIDIA / CTranslate2", cuda_count > 0, f"CUDA-устройств: {cuda_count}"),
        ("Диаризация", diarization_ready, "CPU, без внешнего API" if diarization_ready else "не установлен пакет diarize"),
        ("NVIDIA NIM", bool(os.environ.get("NVIDIA_API_KEY")), "API key задан" if os.environ.get("NVIDIA_API_KEY") else "необязательно: задаётся в параметрах"),
        ("Ollama", ollama.get("available", False), ", ".join(ollama.get("models", [])) or ollama.get("error", "нет моделей")),
    ]
    for name, ready, detail in checks:
        with st.container(border=True):
            left, right = st.columns([1, 3])
            left.markdown(f"**{name}**")
            right.markdown(
                f'<span class="{"ok" if ready else "warn"}">'
                f'{"Готово" if ready else "Требует настройки"}</span><br/>'
                f'<span class="muted">{escape(str(detail))}</span>',
                unsafe_allow_html=True,
            )
    st.subheader("Контур обработки")
    st.code(
        "Аудио -> FFmpeg -> faster-whisper -> diarize -> NVIDIA NIM / fallback -> PDF/DOCX\n"
        "Аудио остаётся локально | NVIDIA получает только текст и только при заданном ключе",
        language="text",
    )
