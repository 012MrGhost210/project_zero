"""Streamlit UI: read-only disk usage analytics.

Never writes under scanned paths — analytics only.
"""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from disk_scanner import (
    human_size,
    is_under,
    resolve_existing_dir,
    scan_directory,
    volume_info,
)

st.set_page_config(
    page_title="Мониторинг диска",
    page_icon="💾",
    layout="wide",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.5rem; max-width: 1100px; }
      .readonly-banner {
        background: linear-gradient(90deg, #e8f5e9 0%, #f1f8e9 100%);
        border: 1px solid #a5d6a7;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin-bottom: 1rem;
        color: #1b5e20;
        font-size: 0.95rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Мониторинг использования диска")
st.markdown(
    '<div class="readonly-banner">'
    "<strong>Только чтение.</strong> Приложение анализирует каталоги и ничего "
    "не создаёт, не изменяет, не удаляет, не перемещает и не меняет права. "
    "Очистка и правки файловой системы здесь недоступны."
    "</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Параметры")
    main_raw = st.text_input(
        "Корневой / основной каталог",
        value="/workspace",
        help="Базовый контекст (например, точка монтирования или общий корень).",
        key="main_path",
    )
    selected_raw = st.text_input(
        "Наблюдаемый каталог",
        value="/workspace",
        help="Каталог, который нужно просканировать.",
        key="selected_path",
    )
    top_n = st.slider("Топ N папок и файлов", min_value=5, max_value=50, value=15, step=5)
    refresh_sec = st.slider(
        "Интервал автообновления (сек)",
        min_value=0,
        max_value=120,
        value=15,
        step=5,
        help="0 — без автообновления; нажмите «Обновить сейчас».",
    )
    refresh_now = st.button("Обновить сейчас", type="primary", use_container_width=True)
    st.caption(
        "Сканирование только через os.scandir / pathlib / os.statvfs — без записи."
    )


def _rows_from_path_sizes(items) -> pd.DataFrame:
    rows = [
        {
            "Путь": item.path,
            "Размер": human_size(item.size_bytes),
            "Байты": item.size_bytes,
        }
        for item in items
    ]
    if not rows:
        return pd.DataFrame(columns=["Путь", "Размер", "Байты"])
    return pd.DataFrame(rows)


@st.cache_data(ttl=5, show_spinner=False)
def _cached_scan(path_str: str, top_n: int, bust: float):
    del bust  # cache key only
    target = resolve_existing_dir(path_str)
    return scan_directory(target, top_n=top_n)


if "scan_bust" not in st.session_state:
    st.session_state.scan_bust = time.time()
if refresh_now:
    st.session_state.scan_bust = time.time()
    st.cache_data.clear()

# --- Validate paths ---
main_path = None
selected_path = None
path_error = None

try:
    if main_raw.strip():
        main_path = resolve_existing_dir(main_raw)
except (ValueError, FileNotFoundError, NotADirectoryError, PermissionError) as exc:
    path_error = ("main", str(exc))

try:
    selected_path = resolve_existing_dir(selected_raw)
except (ValueError, FileNotFoundError, NotADirectoryError, PermissionError) as exc:
    path_error = ("selected", str(exc))

if path_error is not None:
    kind, message = path_error
    label = "основного" if kind == "main" else "наблюдаемого"
    lower = message.lower()
    if "не существует" in lower or "не указан" in lower:
        st.warning(f"Некорректный путь {label} каталога: {message}")
    elif "прав" in lower or "доступ" in lower:
        st.error(f"Ошибка доступа к {label} каталогу: {message}")
    else:
        st.error(f"Не удалось открыть {label} каталог: {message}")
    st.info("Укажите существующие каталоги, к которым есть права на чтение.")
    if refresh_sec > 0:
        time.sleep(min(refresh_sec, 5))
        st.rerun()
    st.stop()

assert selected_path is not None

# --- Scan (read-only) ---
with st.spinner("Сканирование (только чтение)…"):
    try:
        result = _cached_scan(str(selected_path), top_n, st.session_state.scan_bust)
    except PermissionError as exc:
        st.error(f"Нет прав на сканирование: {exc}")
        st.stop()
    except OSError as exc:
        st.error(f"Ошибка сканирования: {exc}")
        st.stop()

vol = volume_info(main_path) if main_path is not None else None
related = main_path is not None and (
    is_under(selected_path, main_path) or selected_path == main_path
)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Размер наблюдаемого", human_size(result.total_bytes))
    if related and vol is not None and vol.total_bytes:
        share = result.total_bytes / vol.total_bytes * 100
        st.caption(f"{share:.2f}% от объёма тома")
with col2:
    if vol is not None:
        st.metric("Свободно на томе", human_size(vol.available_bytes))
        st.caption(f"Том: `{main_path}`")
    else:
        st.metric("Свободно на томе", "—")
        st.caption("statvfs недоступен")
with col3:
    if vol is not None:
        used = vol.total_bytes - vol.free_bytes
        pct = (used / vol.total_bytes * 100) if vol.total_bytes else 0
        st.metric("Занято на томе", f"{human_size(used)} ({pct:.0f}%)")
    else:
        st.metric("Занято на томе", "—")
with col4:
    st.metric("Объём тома", human_size(vol.total_bytes) if vol else "—")

if main_path is not None and not related:
    st.caption(
        f"Наблюдаемый путь не лежит внутри основного (`{main_path}`). "
        "Метрики тома относятся к файловой системе основного каталога."
    )

st.caption(
    f"Обновлено: {datetime.now().strftime('%H:%M:%S')} · "
    f"файлов учтено: {result.entries_seen} · "
    f"путь: `{result.target}`"
)

if result.entries_seen == 0 and not result.errors:
    st.info("Каталог пуст или не содержит доступных файлов (симлинки пропускаются).")

if result.errors:
    with st.expander(f"Предупреждения доступа ({len(result.errors)})", expanded=False):
        for err in result.errors:
            st.text(err)

tab_folders, tab_files = st.tabs(["Самые тяжёлые папки", "Самые тяжёлые файлы"])

with tab_folders:
    df_folders = _rows_from_path_sizes(result.folders)
    if df_folders.empty:
        st.write("Нет подпапок для отображения.")
    else:
        st.dataframe(
            df_folders,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Путь": st.column_config.TextColumn("Путь", width="large"),
                "Размер": st.column_config.TextColumn("Размер", width="small"),
                "Байты": st.column_config.NumberColumn("Байты", format="%d"),
            },
        )

with tab_files:
    df_files = _rows_from_path_sizes(result.files)
    if df_files.empty:
        st.write("Нет файлов для отображения.")
    else:
        st.dataframe(
            df_files,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Путь": st.column_config.TextColumn("Путь", width="large"),
                "Размер": st.column_config.TextColumn("Размер", width="small"),
                "Байты": st.column_config.NumberColumn("Байты", format="%d"),
            },
        )

if refresh_sec > 0:
    st.caption(f"Автообновление каждые {refresh_sec} с.")
    time.sleep(refresh_sec)
    st.session_state.scan_bust = time.time()
    st.rerun()
