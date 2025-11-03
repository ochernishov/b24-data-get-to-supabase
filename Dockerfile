FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей системы
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Установка Python зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY bitrix24_etl.py .

# Создание директории для логов
RUN mkdir -p /app/logs

# Запуск
CMD ["python", "-u", "bitrix24_etl.py"]
