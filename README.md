# 🚀 Битрикс24 → Supabase ETL & AI Analytics

Полная система выгрузки, хранения и ИИ-анализа данных из Битрикс24.

## 📋 Содержание

1. [Быстрый старт](#быстрый-старт)
2. [Установка](#установка)
3. [Конфигурация](#конфигурация)
4. [Использование](#использование)
5. [Анализ данных с ИИ](#анализ-данных-с-ии)
6. [Troubleshooting](#troubleshooting)

---

## 🎯 Быстрый старт

### Шаг 1: Создайте Supabase проект

1. Зайдите на [supabase.com](https://supabase.com)
2. Создайте новый проект
3. Перейдите в SQL Editor
4. Скопируйте содержимое файла `supabase_schema.sql`
5. Выполните SQL-скрипт

### Шаг 2: Получите credentials Supabase

1. В Supabase перейдите в **Settings → API**
2. Скопируйте:
   - `Project URL` (например: https://xxxxx.supabase.co)
   - `anon public` ключ

### Шаг 3: Настройте Битрикс24 вебхук

Вы уже сделали это! Ваш вебхук:
```
https://gsmural.bitrix24.ru/rest/12/120rlt4osdrdtv5a
```

✅ Убедитесь, что в настройках прав выбран раздел **CRM (crm)**

### Шаг 4: Запуск на Coolify

#### Вариант А: Через Git (рекомендуется)

1. Создайте Git-репозиторий и загрузите все файлы
2. В Coolify создайте новый сервис → Docker Compose
3. Укажите ваш репозиторий
4. Добавьте переменные окружения (см. `.env.example`)
5. Деплойте!

#### Вариант Б: Прямой деплой файлов

1. Загрузите файлы на сервер:
```bash
scp -r ./* user@your-server:/opt/bitrix24-etl/
```

2. Подключитесь к серверу:
```bash
ssh user@your-server
cd /opt/bitrix24-etl
```

3. Создайте `.env` файл:
```bash
cp .env.example .env
nano .env  # заполните ваши данные
```

4. Запустите первую полную выгрузку:
```bash
# Установите режим полной выгрузки
export SYNC_MODE=full

# Соберите образ
docker-compose build

# Запустите выгрузку
docker-compose up bitrix24-etl
```

5. После завершения запустите планировщик:
```bash
export SYNC_MODE=incremental
docker-compose up -d bitrix24-scheduler
```

---

## 🔧 Конфигурация

### Переменные окружения

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `BITRIX_WEBHOOK` | URL входящего вебхука Битрикс24 | `https://xxx.bitrix24.ru/rest/12/token` |
| `SUPABASE_URL` | URL вашего Supabase проекта | `https://xxxxx.supabase.co` |
| `SUPABASE_KEY` | Anon/Public ключ Supabase | `eyJhbGciOiJIUzI1...` |
| `SYNC_MODE` | Режим: `full` или `incremental` | `incremental` |
| `HOURS_BACK` | Часов назад для инкрементальной выгрузки | `24` |
| `CRON_SCHEDULE` | Расписание cron | `0 */6 * * *` |

### Примеры расписаний

```bash
# Каждый час
CRON_SCHEDULE="0 * * * *"

# Каждые 30 минут
CRON_SCHEDULE="*/30 * * * *"

# Каждый день в 3:00 ночи
CRON_SCHEDULE="0 3 * * *"

# Каждые 6 часов
CRON_SCHEDULE="0 */6 * * *"

# Каждый понедельник в 9:00
CRON_SCHEDULE="0 9 * * 1"
```

---

## 📊 Использование

### Ручной запуск синхронизации

```bash
# Полная выгрузка
docker-compose run -e SYNC_MODE=full bitrix24-etl

# Инкрементальная (последние 24 часа)
docker-compose run -e SYNC_MODE=incremental bitrix24-etl

# Инкрементальная (последние 7 дней)
docker-compose run -e SYNC_MODE=incremental -e HOURS_BACK=168 bitrix24-etl
```

### Просмотр логов

```bash
# Логи ETL
docker-compose logs -f bitrix24-etl

# Логи планировщика
docker-compose logs -f bitrix24-scheduler

# Файловые логи
tail -f logs/bitrix24_etl.log
```

### Мониторинг прогресса

В Supabase перейдите в SQL Editor и выполните:

```sql
-- Статус последних синхронизаций
SELECT 
    entity_type,
    sync_type,
    status,
    records_processed,
    started_at,
    finished_at,
    EXTRACT(EPOCH FROM (finished_at - started_at)) as duration_seconds
FROM sync_log
ORDER BY started_at DESC
LIMIT 20;

-- Количество записей в таблицах
SELECT 
    'deals' as table_name, COUNT(*) as count FROM deals
UNION ALL
SELECT 'activities', COUNT(*) FROM activities
UNION ALL
SELECT 'contacts', COUNT(*) FROM contacts
UNION ALL
SELECT 'managers', COUNT(*) FROM managers;

-- Распределение сделок по годам
SELECT 
    EXTRACT(YEAR FROM date_create) as year,
    COUNT(*) as deals_count,
    SUM(opportunity) as total_revenue
FROM deals
GROUP BY EXTRACT(YEAR FROM date_create)
ORDER BY year DESC;
```

---

## 🤖 Анализ данных с ИИ

После выгрузки данных можно начать анализ с помощью Claude API.

### Установка Claude Python SDK

```bash
pip install anthropic
```

### Пример анализа паттернов

```python
import anthropic
from supabase import create_client

# Подключение к Supabase
supabase = create_client(
    "your-supabase-url",
    "your-supabase-key"
)

# Получение данных
won_deals = supabase.table('v_deals_analytics')\
    .select('*')\
    .eq('stage_semantic_id', 'S')\
    .limit(100)\
    .execute()

lost_deals = supabase.table('v_deals_analytics')\
    .select('*')\
    .eq('stage_semantic_id', 'F')\
    .limit(100)\
    .execute()

# Анализ с Claude
client = anthropic.Anthropic(api_key="your-api-key")

prompt = f"""
Проанализируй данные о выигранных и проигранных сделках.

ВЫИГРАННЫЕ СДЕЛКИ (100 шт):
{won_deals.data}

ПРОИГРАННЫЕ СДЕЛКИ (100 шт):
{lost_deals.data}

Задачи:
1. Найди 10 ключевых различий в паттернах коммуникаций
2. Определи оптимальное количество касаний для закрытия сделки
3. Выяви временные паттерны (когда лучше звонить/писать)
4. Найди корреляции между типами активностей и успехом
5. Дай рекомендации для менеджеров

Ответь структурированно с цифрами и процентами.
"""

message = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4000,
    messages=[
        {"role": "user", "content": prompt}
    ]
)

print(message.content[0].text)
```

### Транскрипция звонков

Для звонков можно использовать Whisper API для получения текста:

```python
import openai
import requests

# Получить звонки с записями
calls = supabase.table('activities')\
    .select('*')\
    .eq('type_id', 2)\
    .not_.is_('call_recording_url', 'null')\
    .is_('call_transcript', 'null')\
    .limit(10)\
    .execute()

for call in calls.data:
    # Скачать запись
    audio_url = call['call_recording_url']
    audio_file = requests.get(audio_url).content
    
    # Транскрибировать
    client = openai.OpenAI()
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="ru"
    )
    
    # Сохранить транскрипт
    supabase.table('activities')\
        .update({'call_transcript': transcript.text})\
        .eq('id', call['id'])\
        .execute()
```

### Sentiment анализ

```python
# После получения транскриптов
activities_with_text = supabase.table('activities')\
    .select('id, deal_id, description, call_transcript')\
    .not_.is_('description', 'null')\
    .execute()

for activity in activities_with_text.data:
    text = activity.get('call_transcript') or activity.get('description')
    
    # Анализ с Claude
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": f"""
            Оцени sentiment этого текста от -1 (очень негативный) до +1 (очень позитивный).
            Ответь только числом.
            
            Текст: {text}
            """
        }]
    )
    
    sentiment = float(response.content[0].text.strip())
    
    # Обновить в базе
    # (добавь поле sentiment в таблицу activities)
```

### Готовые SQL-запросы для анализа

```sql
-- Топ менеджеров по конверсии
SELECT * FROM v_top_managers ORDER BY win_rate DESC LIMIT 10;

-- Средние метрики успешных сделок
SELECT 
    AVG(touches_count) as avg_touches,
    AVG(calls_count) as avg_calls,
    AVG(emails_count) as avg_emails,
    AVG(days_to_close) as avg_days,
    AVG(total_call_duration / 60.0) as avg_call_minutes
FROM deal_patterns p
JOIN deals d ON p.deal_id = d.id
WHERE d.stage_semantic_id = 'S';

-- Распределение выигранных сделок по количеству касаний
SELECT 
    touches_count,
    COUNT(*) as deals_count,
    ROUND(AVG(d.opportunity), 2) as avg_deal_size
FROM deal_patterns p
JOIN deals d ON p.deal_id = d.id
WHERE d.stage_semantic_id = 'S'
GROUP BY touches_count
ORDER BY touches_count;

-- Самые эффективные часы для звонков
SELECT 
    EXTRACT(HOUR FROM created) as hour,
    COUNT(*) as calls_count,
    COUNT(*) FILTER (
        WHERE d.stage_semantic_id = 'S'
    )::FLOAT / COUNT(*) * 100 as success_rate
FROM activities a
JOIN deals d ON a.owner_id = d.id AND a.owner_type_id = 2
WHERE a.type_id = 2
GROUP BY EXTRACT(HOUR FROM created)
ORDER BY success_rate DESC;
```

---

## 🔍 Troubleshooting

### Проблема: ETL не запускается

**Проверьте:**
```bash
# Логи
docker-compose logs bitrix24-etl

# Переменные окружения
docker-compose config

# Доступность Битрикс24 API
curl -s "https://gsmural.bitrix24.ru/rest/12/120rlt4osdrdtv5a/profile.json"
```

### Проблема: Ошибки подключения к Supabase

**Проверьте:**
- Правильность SUPABASE_URL и SUPABASE_KEY
- Выполнена ли инициализация схемы БД (supabase_schema.sql)
- Не заблокирован ли доступ файрволлом

```bash
# Тест подключения к Supabase
curl -H "apikey: YOUR_SUPABASE_KEY" \
     "https://YOUR_PROJECT.supabase.co/rest/v1/managers?select=*&limit=1"
```

### Проблема: Медленная выгрузка

**Причины:**
- Большой объём данных (миллионы записей)
- Лимиты API Битрикс24 (2 req/sec)

**Решения:**
- Используйте инкрементальную синхронизацию
- Запускайте полную выгрузку ночью
- Увеличьте `rate_limit_delay` в коде

### Проблема: Дублирование данных

Используется UPSERT (ON CONFLICT), поэтому дублирование невозможно.
Если видите дубли - проверьте индексы в БД.

---

## 📈 Roadmap

- [x] ETL Битрикс24 → Supabase
- [x] Автоматическая синхронизация
- [x] Расчёт базовых паттернов
- [ ] Транскрипция звонков (Whisper API)
- [ ] Sentiment анализ текстов
- [ ] Предсказание вероятности закрытия сделки
- [ ] Dashboard с визуализацией (Grafana/Metabase)
- [ ] Уведомления в Telegram о критичных событиях
- [ ] Экспорт отчётов в PDF/Excel

---

## 📞 Поддержка

Если возникли вопросы - открывайте Issue в репозитории или пишите мне.

**Автор:** Олег (ГСМ УРАЛ)
**Дата:** 2025-11-03
**Версия:** 1.0

---

## 📄 Лицензия

MIT License - используйте свободно!
