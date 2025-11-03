FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bitrix24_etl.py .

RUN mkdir -p /app/logs

CMD ["python", "-u", "bitrix24_etl.py"]