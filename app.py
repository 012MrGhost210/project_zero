"""Read-only disk usage monitor (Streamlit). Never writes under scanned paths."""

from __future__ import annotations

import heapq
import os
import time
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Мониторинг диска", layout="wide")

st.title("Мониторинг диска")
st.info(
    "**Только чтение.** Приложение ничего не создаёт, не меняет и не удаляет "
    "в указанных каталогах — только анализ через os.scandir / os.statvfs."
)


def human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def scan(root: Path, top_n: int = 15):
    """Walk root read-only. Returns total, top child folders, top files, errors."""
    errors: list[str] = []
    child_bytes: dict[str, int] = {}
    files_heap: list[tuple[int, str]] = []  # min-heap (size, path)
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
                        # Attribute to immediate child of root
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


with st.sidebar:
    main = st.text_input("Основной каталог (контекст)", value=r"C:\data" if os.name == "nt" else "/workspace")
    watched = st.text_input("Наблюдаемый каталог", value=main)
    top_n = st.number_input("Топ N", min_value=5, max_value=50, value=15, step=5)
    auto = st.checkbox("Автообновление", value=False)
    interval = st.slider("Интервал, сек", 5, 60, 15) if auto else 0
    do_scan = st.button("Сканировать", type="primary") or True

path = Path(watched.strip()).expanduser() if watched.strip() else None
main_path = Path(main.strip()).expanduser() if main.strip() else None

if not path or not path.exists() or not path.is_dir():
    st.warning("Укажите существующий каталог в поле «Наблюдаемый каталог».")
    st.stop()

if not os.access(path, os.R_OK):
    st.error(f"Нет прав на чтение: {path}")
    st.stop()

with st.spinner("Сканирование (только чтение)…"):
    total, folders, files, errors = scan(path, int(top_n))

# Volume free space (read-only), based on main path if given
vol_path = main_path if main_path and main_path.exists() else path
try:
    stv = os.statvfs(vol_path)
    fr = stv.f_frsize or stv.f_bsize
    free = stv.f_bavail * fr
    vol_total = stv.f_blocks * fr
except (OSError, AttributeError):
    free = vol_total = None

c1, c2, c3 = st.columns(3)
c1.metric("Размер каталога", human(total))
c2.metric("Свободно на томе", human(free) if free is not None else "—")
c3.metric("Объём тома", human(vol_total) if vol_total is not None else "—")
st.caption(f"Путь: `{path}`")

t1, t2 = st.tabs(["Тяжёлые папки (1-й уровень)", "Тяжёлые файлы"])
with t1:
    if not folders:
        st.write("Нет данных.")
    else:
        st.table([{"Путь": p, "Размер": human(s), "Байты": s} for p, s in folders])
with t2:
    if not files:
        st.write("Нет данных.")
    else:
        st.table([{"Путь": p, "Размер": human(s), "Байты": s} for s, p in files])

if errors:
    with st.expander(f"Ошибки доступа ({len(errors)})"):
        for e in errors:
            st.text(e)

if interval > 0:
    time.sleep(interval)
    st.rerun()
