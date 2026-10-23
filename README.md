# Мониторинг диска (только чтение)

Простое Streamlit-приложение: вводите путь к папке и смотрите её размер, свободное место на томе, топ тяжёлых подпапок и файлов.

**Ничего не пишет** в анализируемые каталоги — только `os.scandir` / `os.statvfs`.

## Запуск (Windows / Linux / macOS)

```bash
pip install -r requirements.txt
streamlit run app.py
```

В браузере откроется UI. В боковой панели укажите пути (например `D:\share\projects` на Windows).

Опционально порт:

```bash
streamlit run app.py --server.port 8507
```

## Файлы

- `app.py` — всё приложение
- `requirements.txt` — зависимость Streamlit
