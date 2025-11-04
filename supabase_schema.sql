-- ============================================================================
-- СХЕМА БАЗЫ ДАННЫХ ДЛЯ АНАЛИТИКИ БИТРИКС24
-- ============================================================================
-- Версия: 1.0
-- Дата: 2025-11-03
-- Описание: Полная схема для хранения данных CRM из Битрикс24
-- ============================================================================

-- Удаляем существующие таблицы если есть (осторожно!)
DROP TABLE IF EXISTS deal_patterns CASCADE;
DROP TABLE IF EXISTS activities CASCADE;
DROP TABLE IF EXISTS deals CASCADE;
DROP TABLE IF EXISTS contacts CASCADE;
DROP TABLE IF EXISTS companies CASCADE;
DROP TABLE IF EXISTS leads CASCADE;
DROP TABLE IF EXISTS managers CASCADE;
DROP TABLE IF EXISTS sync_log CASCADE;
DROP TABLE IF EXISTS deal_categories CASCADE;
DROP TABLE IF EXISTS deal_stages CASCADE;
DROP TABLE IF EXISTS lead_statuses CASCADE;

-- ============================================================================
-- 1. СПРАВОЧНИК МЕНЕДЖЕРОВ
-- ============================================================================
CREATE TABLE managers (
    id INTEGER PRIMARY KEY,
    name TEXT,
    last_name TEXT,
    email TEXT,
    active BOOLEAN DEFAULT true,
    is_admin BOOLEAN DEFAULT false,
    work_position TEXT,
    personal_phone TEXT,
    personal_mobile TEXT,
    time_zone TEXT,
    date_register TIMESTAMP,
    last_activity_date TIMESTAMP,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_managers_active ON managers(active);
CREATE INDEX idx_managers_email ON managers(email);

COMMENT ON TABLE managers IS 'Справочник менеджеров (пользователей) из Битрикс24';

-- ============================================================================
-- 1.1 СПРАВОЧНИК ВОРОНОК СДЕЛОК
-- ============================================================================
CREATE TABLE deal_categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sort INTEGER DEFAULT 500,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE deal_categories IS 'Воронки продаж (направления) для сделок';

-- ============================================================================
-- 1.2 СПРАВОЧНИК СТАДИЙ СДЕЛОК
-- ============================================================================
CREATE TABLE deal_stages (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES deal_categories(id),
    status_id TEXT NOT NULL,
    sort INTEGER DEFAULT 500,
    color TEXT,
    semantics TEXT, -- P (процесс), S (успех), F (провал)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_deal_stages_category ON deal_stages(category_id);
CREATE INDEX idx_deal_stages_semantics ON deal_stages(semantics);

COMMENT ON TABLE deal_stages IS 'Стадии сделок с названиями';

-- ============================================================================
-- 1.3 СПРАВОЧНИК СТАТУСОВ ЛИДОВ
-- ============================================================================
CREATE TABLE lead_statuses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sort INTEGER DEFAULT 500,
    color TEXT,
    semantics TEXT, -- P (процесс), S (успех), F (провал)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_lead_statuses_semantics ON lead_statuses(semantics);

COMMENT ON TABLE lead_statuses IS 'Статусы лидов';

-- ============================================================================
-- 2. КОМПАНИИ
-- ============================================================================
CREATE TABLE companies (
    id INTEGER PRIMARY KEY,
    title TEXT,
    company_type TEXT,
    industry TEXT,
    employees INTEGER,
    currency_id TEXT,
    revenue DECIMAL,
    banking_details TEXT,
    phone TEXT,
    email TEXT,
    web TEXT,
    address TEXT,
    assigned_by_id INTEGER REFERENCES managers(id),
    created_by_id INTEGER REFERENCES managers(id),
    date_create TIMESTAMP,
    date_modify TIMESTAMP,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_companies_assigned ON companies(assigned_by_id);
CREATE INDEX idx_companies_created ON companies(date_create);

COMMENT ON TABLE companies IS 'Компании из CRM';

-- ============================================================================
-- 3. КОНТАКТЫ
-- ============================================================================
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY,
    name TEXT,
    last_name TEXT,
    second_name TEXT,
    full_name TEXT,
    post TEXT,
    company_id INTEGER REFERENCES companies(id),
    phone TEXT,
    email TEXT,
    birthdate DATE,
    source_id TEXT,
    source_description TEXT,
    assigned_by_id INTEGER REFERENCES managers(id),
    created_by_id INTEGER REFERENCES managers(id),
    date_create TIMESTAMP,
    date_modify TIMESTAMP,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_contacts_company ON contacts(company_id);
CREATE INDEX idx_contacts_assigned ON contacts(assigned_by_id);
CREATE INDEX idx_contacts_created ON contacts(date_create);
CREATE INDEX idx_contacts_email ON contacts(email);

COMMENT ON TABLE contacts IS 'Контакты (физические лица) из CRM';

-- ============================================================================
-- 4. ЛИДЫ
-- ============================================================================
CREATE TABLE leads (
    id INTEGER PRIMARY KEY,
    title TEXT,
    name TEXT,
    last_name TEXT,
    second_name TEXT,
    company_title TEXT,
    status_id TEXT,
    status_semantic_id TEXT, -- N=новый, P=в работе, S=успешно, F=провал
    source_id TEXT,
    source_description TEXT,
    opportunity DECIMAL,
    currency_id TEXT,
    phone TEXT,
    email TEXT,
    web TEXT,
    assigned_by_id INTEGER REFERENCES managers(id),
    created_by_id INTEGER REFERENCES managers(id),
    date_create TIMESTAMP,
    date_modify TIMESTAMP,
    date_closed TIMESTAMP,
    comments TEXT,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_leads_status ON leads(status_id);
CREATE INDEX idx_leads_semantic ON leads(status_semantic_id);
CREATE INDEX idx_leads_assigned ON leads(assigned_by_id);
CREATE INDEX idx_leads_created ON leads(date_create);
CREATE INDEX idx_leads_closed ON leads(date_closed);

COMMENT ON TABLE leads IS 'Лиды (потенциальные клиенты) из CRM';

-- ============================================================================
-- 5. СДЕЛКИ (главная таблица!)
-- ============================================================================
CREATE TABLE deals (
    id INTEGER PRIMARY KEY,
    title TEXT,
    type_id TEXT,
    stage_id TEXT,
    stage_semantic_id TEXT, -- P=в работе, S=успешно, F=провалено
    category_id INTEGER,
    
    -- Финансы
    opportunity DECIMAL, -- сумма сделки
    currency_id TEXT,
    tax_value DECIMAL,
    
    -- Даты
    begindate TIMESTAMP,
    closedate TIMESTAMP,
    date_create TIMESTAMP,
    date_modify TIMESTAMP,
    
    -- Статусы
    is_new BOOLEAN,
    is_recurring BOOLEAN,
    is_return_customer BOOLEAN,
    is_repeated_approach BOOLEAN,
    closed BOOLEAN,
    
    -- Связи
    company_id INTEGER REFERENCES companies(id),
    contact_id INTEGER REFERENCES contacts(id),
    lead_id INTEGER REFERENCES leads(id),
    assigned_by_id INTEGER REFERENCES managers(id),
    created_by_id INTEGER REFERENCES managers(id),
    modify_by_id INTEGER REFERENCES managers(id),
    
    -- Источник и причины
    source_id TEXT,
    source_description TEXT,
    additional_info TEXT, -- причина проигрыша
    location_id TEXT,
    
    -- UTM метки
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    utm_content TEXT,
    utm_term TEXT,
    
    -- Полные данные
    raw_data JSONB,
    
    -- Служебные
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Индексы для быстрого поиска
CREATE INDEX idx_deals_stage ON deals(stage_id);
CREATE INDEX idx_deals_semantic ON deals(stage_semantic_id);
CREATE INDEX idx_deals_assigned ON deals(assigned_by_id);
CREATE INDEX idx_deals_created ON deals(date_create);
CREATE INDEX idx_deals_closed ON deals(closedate);
CREATE INDEX idx_deals_company ON deals(company_id);
CREATE INDEX idx_deals_contact ON deals(contact_id);
CREATE INDEX idx_deals_opportunity ON deals(opportunity);
CREATE INDEX idx_deals_is_new ON deals(is_new);

COMMENT ON TABLE deals IS 'Сделки - основная таблица для анализа';

-- ============================================================================
-- 6. АКТИВНОСТИ (коммуникации)
-- ============================================================================
CREATE TABLE activities (
    id INTEGER PRIMARY KEY,
    owner_type_id INTEGER, -- 1=лид, 2=сделка, 3=контакт, 4=компания
    owner_id INTEGER, -- ID владельца
    
    -- Тип активности
    type_id INTEGER, -- 1=встреча, 2=звонок, 3=задача, 4=email, 6=sms
    provider_id TEXT,
    provider_type_id TEXT,
    
    -- Направление (для звонков/писем)
    direction INTEGER, -- 0=нет, 1=исходящий, 2=входящий
    
    -- Содержание
    subject TEXT,
    description TEXT,
    description_type INTEGER, -- 1=text, 2=html, 3=bbcode
    
    -- Даты и время
    created TIMESTAMP,
    last_updated TIMESTAMP,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    deadline TIMESTAMP,
    completed TIMESTAMP,
    
    -- Статус
    status INTEGER,
    result_status INTEGER,
    result_stream INTEGER,
    result_value TEXT,
    
    -- Звонки
    call_duration INTEGER, -- в секундах
    call_recording_url TEXT,
    call_transcript TEXT, -- будет заполнено после транскрипции
    
    -- Связи
    responsible_id INTEGER REFERENCES managers(id),
    author_id INTEGER REFERENCES managers(id),
    editor_id INTEGER REFERENCES managers(id),
    
    -- Приоритет и прочее
    priority INTEGER,
    notify_type INTEGER,
    
    -- Полные данные
    raw_data JSONB,
    
    -- Служебные
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Индексы для анализа коммуникаций
CREATE INDEX idx_activities_owner ON activities(owner_type_id, owner_id);
CREATE INDEX idx_activities_type ON activities(type_id);
CREATE INDEX idx_activities_direction ON activities(direction);
CREATE INDEX idx_activities_created ON activities(created);
CREATE INDEX idx_activities_responsible ON activities(responsible_id);
CREATE INDEX idx_activities_completed ON activities(completed);

-- Полнотекстовый поиск по содержимому
CREATE INDEX idx_activities_text ON activities 
    USING gin(to_tsvector('russian', COALESCE(subject, '') || ' ' || COALESCE(description, '')));

COMMENT ON TABLE activities IS 'Все коммуникации: звонки, письма, встречи, задачи';

-- ============================================================================
-- 7. ПАТТЕРНЫ СДЕЛОК (аналитическая таблица)
-- ============================================================================
CREATE TABLE deal_patterns (
    deal_id INTEGER PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
    
    -- Счётчики коммуникаций
    total_activities INTEGER DEFAULT 0,
    calls_count INTEGER DEFAULT 0,
    calls_incoming INTEGER DEFAULT 0,
    calls_outgoing INTEGER DEFAULT 0,
    emails_count INTEGER DEFAULT 0,
    emails_incoming INTEGER DEFAULT 0,
    emails_outgoing INTEGER DEFAULT 0,
    meetings_count INTEGER DEFAULT 0,
    messages_count INTEGER DEFAULT 0,
    tasks_count INTEGER DEFAULT 0,
    
    -- Временные метрики
    avg_response_time INTERVAL, -- среднее время ответа
    first_contact_time INTERVAL, -- время до первого контакта с момента создания
    deal_duration INTERVAL, -- длительность сделки от создания до закрытия
    days_to_close INTEGER, -- дней до закрытия
    
    -- Метрики звонков
    total_call_duration INTEGER, -- общая длительность звонков в секундах
    avg_call_duration INTEGER, -- средняя длительность звонка
    max_call_duration INTEGER, -- максимальная длительность звонка
    
    -- Метрики активности
    touches_count INTEGER, -- количество касаний (уникальных дней с активностями)
    last_activity_date TIMESTAMP,
    longest_silence_days INTEGER, -- самая длинная пауза без коммуникаций
    
    -- Sentiment анализ (будет заполнено ИИ)
    sentiment_score DECIMAL, -- средний sentiment всех коммуникаций (-1 до 1)
    positive_ratio DECIMAL, -- доля позитивных коммуникаций (0 до 1)
    
    -- Предсказания ИИ
    win_probability DECIMAL, -- вероятность выигрыша (0 до 1)
    predicted_close_date DATE, -- предсказанная дата закрытия
    risk_score DECIMAL, -- оценка риска потери сделки (0 до 1)
    
    -- Ключевые слова и темы
    top_keywords TEXT[], -- массив ключевых слов из коммуникаций
    detected_objections TEXT[], -- обнаруженные возражения
    detected_pain_points TEXT[], -- обнаруженные боли клиента
    
    -- Служебные
    calculated_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_patterns_win_prob ON deal_patterns(win_probability);
CREATE INDEX idx_patterns_sentiment ON deal_patterns(sentiment_score);
CREATE INDEX idx_patterns_duration ON deal_patterns(deal_duration);
CREATE INDEX idx_patterns_touches ON deal_patterns(touches_count);

COMMENT ON TABLE deal_patterns IS 'Аналитические паттерны сделок для ИИ-анализа';

-- ============================================================================
-- 8. ЛОГ СИНХРОНИЗАЦИИ
-- ============================================================================
CREATE TABLE sync_log (
    id SERIAL PRIMARY KEY,
    sync_type TEXT NOT NULL, -- 'full', 'incremental', 'manual'
    entity_type TEXT NOT NULL, -- 'deals', 'activities', 'contacts', etc
    started_at TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP,
    status TEXT, -- 'running', 'completed', 'failed'
    records_processed INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB
);

CREATE INDEX idx_sync_log_entity ON sync_log(entity_type);
CREATE INDEX idx_sync_log_started ON sync_log(started_at);
CREATE INDEX idx_sync_log_status ON sync_log(status);

COMMENT ON TABLE sync_log IS 'Журнал синхронизации данных из Битрикс24';

-- ============================================================================
-- ФУНКЦИИ ДЛЯ АВТОМАТИЧЕСКОГО РАСЧЁТА ПАТТЕРНОВ
-- ============================================================================

-- Функция для обновления паттернов сделки
CREATE OR REPLACE FUNCTION update_deal_patterns(p_deal_id INTEGER)
RETURNS void AS $$
DECLARE
    v_deal_created TIMESTAMP;
    v_deal_closed TIMESTAMP;
BEGIN
    -- Получаем даты сделки
    SELECT date_create, closedate 
    INTO v_deal_created, v_deal_closed
    FROM deals 
    WHERE id = p_deal_id;
    
    -- Вставляем или обновляем паттерны
    INSERT INTO deal_patterns (
        deal_id,
        total_activities,
        calls_count,
        calls_incoming,
        calls_outgoing,
        emails_count,
        emails_incoming,
        emails_outgoing,
        meetings_count,
        tasks_count,
        total_call_duration,
        avg_call_duration,
        touches_count,
        last_activity_date,
        deal_duration,
        days_to_close
    )
    SELECT 
        p_deal_id,
        COUNT(*) as total_activities,
        COUNT(*) FILTER (WHERE type_id = 2) as calls_count,
        COUNT(*) FILTER (WHERE type_id = 2 AND direction = 2) as calls_incoming,
        COUNT(*) FILTER (WHERE type_id = 2 AND direction = 1) as calls_outgoing,
        COUNT(*) FILTER (WHERE type_id = 4) as emails_count,
        COUNT(*) FILTER (WHERE type_id = 4 AND direction = 2) as emails_incoming,
        COUNT(*) FILTER (WHERE type_id = 4 AND direction = 1) as emails_outgoing,
        COUNT(*) FILTER (WHERE type_id = 1) as meetings_count,
        COUNT(*) FILTER (WHERE type_id = 3) as tasks_count,
        SUM(call_duration) FILTER (WHERE type_id = 2) as total_call_duration,
        AVG(call_duration) FILTER (WHERE type_id = 2)::INTEGER as avg_call_duration,
        COUNT(DISTINCT DATE(created)) as touches_count,
        MAX(created) as last_activity_date,
        CASE 
            WHEN v_deal_closed IS NOT NULL 
            THEN v_deal_closed - v_deal_created 
            ELSE NULL 
        END as deal_duration,
        CASE 
            WHEN v_deal_closed IS NOT NULL 
            THEN EXTRACT(DAY FROM v_deal_closed - v_deal_created)::INTEGER
            ELSE NULL 
        END as days_to_close
    FROM activities
    WHERE owner_type_id = 2 AND owner_id = p_deal_id
    ON CONFLICT (deal_id) DO UPDATE SET
        total_activities = EXCLUDED.total_activities,
        calls_count = EXCLUDED.calls_count,
        calls_incoming = EXCLUDED.calls_incoming,
        calls_outgoing = EXCLUDED.calls_outgoing,
        emails_count = EXCLUDED.emails_count,
        emails_incoming = EXCLUDED.emails_incoming,
        emails_outgoing = EXCLUDED.emails_outgoing,
        meetings_count = EXCLUDED.meetings_count,
        tasks_count = EXCLUDED.tasks_count,
        total_call_duration = EXCLUDED.total_call_duration,
        avg_call_duration = EXCLUDED.avg_call_duration,
        touches_count = EXCLUDED.touches_count,
        last_activity_date = EXCLUDED.last_activity_date,
        deal_duration = EXCLUDED.deal_duration,
        days_to_close = EXCLUDED.days_to_close,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_deal_patterns IS 'Пересчитывает паттерны для конкретной сделки';

-- ============================================================================
-- ПРЕДСТАВЛЕНИЯ ДЛЯ АНАЛИТИКИ
-- ============================================================================

-- Представление: Сделки с паттернами
CREATE OR REPLACE VIEW v_deals_analytics AS
SELECT 
    d.*,
    p.total_activities,
    p.calls_count,
    p.emails_count,
    p.touches_count,
    p.deal_duration,
    p.days_to_close,
    p.sentiment_score,
    p.win_probability,
    m.name || ' ' || m.last_name as manager_name,
    c.full_name as contact_name,
    co.title as company_name
FROM deals d
LEFT JOIN deal_patterns p ON d.id = p.deal_id
LEFT JOIN managers m ON d.assigned_by_id = m.id
LEFT JOIN contacts c ON d.contact_id = c.id
LEFT JOIN companies co ON d.company_id = co.id;

COMMENT ON VIEW v_deals_analytics IS 'Сделки со всеми паттернами для аналитики';

-- Представление: Топ менеджеров
CREATE OR REPLACE VIEW v_top_managers AS
SELECT 
    m.id,
    m.name || ' ' || m.last_name as manager_name,
    COUNT(DISTINCT d.id) as total_deals,
    COUNT(DISTINCT d.id) FILTER (WHERE d.stage_semantic_id = 'S') as won_deals,
    COUNT(DISTINCT d.id) FILTER (WHERE d.stage_semantic_id = 'F') as lost_deals,
    ROUND(
        COUNT(DISTINCT d.id) FILTER (WHERE d.stage_semantic_id = 'S')::NUMERIC / 
        NULLIF(COUNT(DISTINCT d.id) FILTER (WHERE d.stage_semantic_id IN ('S', 'F')), 0) * 100,
        2
    ) as win_rate,
    SUM(d.opportunity) FILTER (WHERE d.stage_semantic_id = 'S') as total_revenue,
    AVG(p.touches_count) as avg_touches,
    AVG(p.days_to_close) as avg_days_to_close
FROM managers m
LEFT JOIN deals d ON m.id = d.assigned_by_id
LEFT JOIN deal_patterns p ON d.id = p.deal_id
GROUP BY m.id, m.name, m.last_name
ORDER BY won_deals DESC;

COMMENT ON VIEW v_top_managers IS 'Рейтинг менеджеров по эффективности';

-- ============================================================================
-- ПРАВА ДОСТУПА (опционально)
-- ============================================================================

-- Если нужен отдельный пользователь для ETL
-- CREATE USER bitrix24_etl WITH PASSWORD 'your_secure_password';
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO bitrix24_etl;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO bitrix24_etl;

-- ============================================================================
-- ГОТОВО!
-- ============================================================================

SELECT 'Схема базы данных успешно создана!' as status,
       (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public') as tables_count;
