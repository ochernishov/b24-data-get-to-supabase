# ⚡ Битрикс24 ETL - Быстрый старт

## 📦 Что у вас есть

✅ Полная система ETL для выгрузки данных из Битрикс24
✅ SQL-схема для Supabase PostgreSQL
✅ Docker-контейнеры для автоматической синхронизации
✅ Готовые SQL-запросы для анализа
✅ Примеры интеграции с Claude API для ИИ-анализа

## 🎯 План действий (30 минут)

### 1️⃣ Создайте Supabase проект (5 минут)

1. Зайдите на [supabase.com](https://supabase.com) → Sign up
2. Создайте новый проект (придумайте пароль БД)
3. Перейдите: **SQL Editor** → **New query**
4. Скопируйте содержимое `supabase_schema.sql` → Execute
5. Сохраните:
   - Project URL: https://xxxxx.supabase.co
   - API anon key: eyJhbGc...

### 2️⃣ Распакуйте и настройте проект (3 минуты)

```bash
# Распаковать архив
tar -xzf bitrix24-etl-complete.tar.gz
cd bitrix24-etl

# Создать .env файл
cp .env.example .env
nano .env  # Заполните ваши данные
```

Что заполнить в `.env`:
```
BITRIX_WEBHOOK=https://gsmural.bitrix24.ru/rest/12/120rlt4osdrdtv5a
SUPABASE_URL=<ваш URL из Supabase>
SUPABASE_KEY=<ваш anon key из Supabase>
SYNC_MODE=full  # для первого раза
```

### 3️⃣ Запустите первую выгрузку (10-60 минут)

```bash
# Соберите Docker-образ
docker-compose build

# Запустите полную выгрузку (займёт время в зависимости от объёма данных)
docker-compose up bitrix24-etl
```

Вы увидите процесс:
```
📥 Extracting managers... ✅ 15 managers
📥 Extracting deals... 📊 1250 deals
📥 Extracting activities... 📊 8945 activities
...
```

### 4️⃣ Проверьте данные в Supabase (2 минуты)

Перейдите в Supabase → **Table Editor**

Вы увидите заполненные таблицы:
- `deals` - ваши сделки
- `activities` - все коммуникации
- `contacts` - контакты
- `managers` - менеджеры
- `deal_patterns` - рассчитанные метрики

### 5️⃣ Настройте автоматическую синхронизацию (2 минуты)

```bash
# Измените режим на инкрементальный
nano .env
# Измените: SYNC_MODE=incremental

# Запустите планировщик (будет синхронизировать каждые 6 часов)
docker-compose up -d bitrix24-scheduler

# Проверьте что работает
docker-compose ps
```

## ✅ Готово!

Теперь у вас:
- ✅ Автоматическая выгрузка данных каждые 6 часов
- ✅ Полная история коммуникаций в PostgreSQL
- ✅ Готовая база для ИИ-анализа

---

## 🤖 Следующие шаги: ИИ-анализ

### Быстрый анализ через Claude (прямо сейчас!)

```sql
-- В Supabase SQL Editor выполните:
SELECT 
    d.id,
    d.title,
    d.stage_semantic_id as result,
    d.opportunity,
    p.touches_count,
    p.calls_count,
    p.emails_count,
    p.days_to_close,
    m.name || ' ' || m.last_name as manager
FROM deals d
LEFT JOIN deal_patterns p ON d.id = p.deal_id
LEFT JOIN managers m ON d.assigned_by_id = m.id
WHERE d.stage_semantic_id IN ('S', 'F')  -- S=выиграно, F=проиграно
LIMIT 200;
```

Скопируйте результат и спросите у Claude:
> "Проанализируй эти данные сделок и найди паттерны, которые коррелируют с выигрышем"

### Продвинутый анализ с API

Установите Claude SDK:
```bash
pip install anthropic
```

Используйте пример из README.md раздела "Анализ данных с ИИ"

---

## 📊 Полезные SQL-запросы

### Топ менеджеров
```sql
SELECT * FROM v_top_managers ORDER BY win_rate DESC LIMIT 10;
```

### Средние метрики успешных сделок
```sql
SELECT 
    AVG(touches_count) as avg_touches,
    AVG(calls_count) as avg_calls,
    AVG(days_to_close) as avg_days
FROM deal_patterns p
JOIN deals d ON p.deal_id = d.id
WHERE d.stage_semantic_id = 'S';
```

### Распределение по количеству касаний
```sql
SELECT 
    touches_count,
    COUNT(*) as deals_count,
    COUNT(*) FILTER (WHERE stage_semantic_id = 'S') as won_count
FROM deal_patterns p
JOIN deals d ON p.deal_id = d.id
WHERE touches_count > 0
GROUP BY touches_count
ORDER BY touches_count;
```

---

## 🔧 Команды для управления

```bash
# Просмотр логов
docker-compose logs -f bitrix24-etl

# Ручной запуск синхронизации
docker-compose run bitrix24-etl

# Остановить планировщик
docker-compose stop bitrix24-scheduler

# Полная пересборка
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

---

## 📞 Если что-то не работает

### 1. Проверьте переменные окружения
```bash
docker-compose config
```

### 2. Проверьте доступность Битрикс24
```bash
curl "https://gsmural.bitrix24.ru/rest/12/120rlt4osdrdtv5a/profile.json"
```

### 3. Проверьте подключение к Supabase
В Supabase → SQL Editor:
```sql
SELECT COUNT(*) FROM deals;
```

### 4. Посмотрите логи синхронизации
```sql
SELECT * FROM sync_log ORDER BY started_at DESC LIMIT 10;
```

---

## 🎓 Дополнительно

Полная документация: **README.md**

Файлы проекта:
- `bitrix24_etl.py` - основной ETL-скрипт
- `supabase_schema.sql` - схема БД
- `docker-compose.yml` - конфигурация контейнеров
- `Dockerfile` - образ Python-приложения
- `requirements.txt` - Python-зависимости

---

**Удачи! 🚀**
