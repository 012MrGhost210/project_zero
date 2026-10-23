"""Read-only disk usage monitor (Streamlit). Never writes under scanned paths."""

from __future__ import annotations

import heapq
import os
import shutil
import time
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Мониторинг диска", layout="wide")

st.title("Мониторинг диска")
st.info(
    "**Только чтение.** Приложение ничего не создаёт, не меняет и не удаляет "
    "в указанных каталогах — только анализ через os.scandir / shutil.disk_usage."
)


def human(n: float) -> str:
    x = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024 or u == "TB":
            return f"{int(x)} {u}" if u == "B" else f"{x:.1f} {u}"
        x /= 1024
    return f"{x:.1f} TB"


def pct(part: float, whole: float) -> str:
    if not whole or whole <= 0:
        return "—"
    return f"{100.0 * part / whole:.2f}%"


def scan(root: Path, top_n: int = 15):
    """Walk root read-only. Returns total, top child folders, top files, errors."""
    errors: list[str] = []
    child_bytes: dict[str, int] = {}
    files_heap: list[tuple[int, str]] = []
    total = 0
    stack = [root]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        size = entry.stat(follow_symlinks=False).st_size
                        total += size
                        try:
                            rel = Path(entry.path).relative_to(root)
                            key = str(root / rel.parts[0]) if rel.parts else str(root)
                        except ValueError:
                            key = str(current)
                        child_bytes[key] = child_bytes.get(key, 0) + size

                        if len(files_heap) < top_n:
                            heapq.heappush(files_heap, (size, entry.path))
                        elif size > files_heap[0][0]:
                            heapq.heapreplace(files_heap, (size, entry.path))
                    except OSError as e:
                        if len(errors) < 20:
                            errors.append(str(e))
        except OSError as e:
            if len(errors) < 20:
                errors.append(f"{current}: {e}")

    folders = sorted(child_bytes.items(), key=lambda x: x[1], reverse=True)[:top_n]
    files = sorted(files_heap, key=lambda x: x[0], reverse=True)
    return total, folders, files, errors


default_path = r"C:\Users" if os.name == "nt" else str(Path.home())

with st.sidebar:
    main = st.text_input("Основной каталог (контекст / том)", value=default_path)
    watched = st.text_input("Наблюдаемый каталог", value=default_path)
    top_n = st.number_input("Топ N", min_value=5, max_value=50, value=15, step=5)
    auto = st.checkbox("Автообновление", value=False)
    interval = st.slider("Интервал, сек", 5, 60, 15) if auto else 0
    st.button("Обновить")

path = Path(watched.strip()).expanduser() if watched.strip() else None

if not path or not path.exists() or not path.is_dir():
    st.warning("Укажите существующий каталог в поле «Наблюдаемый каталог».")
    st.stop()

if not os.access(path, os.R_OK):
    st.error(f"Нет прав на чтение: {path}")
    st.stop()

with st.spinner("Сканирование (только чтение)…"):
    total, folders, files, errors = scan(path, int(top_n))

vol_path = Path(main.strip()).expanduser() if main.strip() else path
if not vol_path.exists():
    vol_path = path
try:
    usage = shutil.disk_usage(vol_path)
    free, vol_total, vol_used = usage.free, usage.total, usage.used
except OSError:
    free = vol_total = vol_used = None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Размер каталога", human(total))
c2.metric(
    "% от объёма диска",
    pct(total, vol_total) if vol_total else "—",
    help="Доля наблюдаемого каталога от полной ёмкости тома.",
)
c3.metric(
    "% от занятого на диске",
    pct(total, vol_used) if vol_used else "—",
    help="Доля каталога от уже занятого места на томе.",
)
c4.metric("Свободно на томе", human(free) if free is not None else "—")
st.caption(
    f"Путь: `{path}` · том: `{vol_path}`"
    + (f" · объём тома: {human(vol_total)}" if vol_total else "")
)

t1, t2 = st.tabs(["Тяжёлые папки (1-й уровень)", "Тяжёлые файлы"])
with t1:
    if not folders:
        st.write("Нет данных.")
    else:
        st.table(
            [
                {
                    "Путь": p,
                    "Размер": human(s),
                    "% от каталога": pct(s, total),
                    "% от диска": pct(s, vol_total) if vol_total else "—",
                }
                for p, s in folders
            ]
        )
with t2:
    if not files:
        st.write("Нет данных.")
    else:
        st.table(
            [
                {
                    "Путь": p,
                    "Размер": human(s),
                    "% от каталога": pct(s, total),
                    "% от диска": pct(s, vol_total) if vol_total else "—",
                }
                for s, p in files
            ]
        )

if errors:
    with st.expander(f"Ошибки доступа ({len(errors)})"):
        for e in errors:
            st.text(e)

if interval > 0:
    time.sleep(interval)
    st.rerun()
