#!/usr/bin/env python3
"""
Bitrix24 ETL Service
Извлекает данные из Bitrix24 CRM и загружает в Supabase PostgreSQL
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import requests
from supabase import create_client, Client

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/bitrix24_etl.log')
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
BITRIX_WEBHOOK = os.getenv('BITRIX_WEBHOOK')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
SYNC_MODE = os.getenv('SYNC_MODE', 'full')  # full или incremental
HOURS_BACK = int(os.getenv('HOURS_BACK', '24'))

# Проверка обязательных переменных
if not all([BITRIX_WEBHOOK, SUPABASE_URL, SUPABASE_KEY]):
    logger.error("❌ Missing required environment variables!")
    logger.error(f"   BITRIX_WEBHOOK: {'✓' if BITRIX_WEBHOOK else '✗'}")
    logger.error(f"   SUPABASE_URL: {'✓' if SUPABASE_URL else '✗'}")
    logger.error(f"   SUPABASE_KEY: {'✓' if SUPABASE_KEY else '✗'}")
    sys.exit(1)


class Bitrix24ETL:
    """ETL сервис для выгрузки данных из Bitrix24 в Supabase"""
    
    def __init__(self):
        self.bitrix_url = BITRIX_WEBHOOK
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        self.rate_limit_delay = 0.5  # Задержка между запросами к API
        
    # ==================== УТИЛИТЫ ====================
    
    @staticmethod
    def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        """Безопасное преобразование в int"""
        if value is None or value == '' or value == 'null':
            return default
        try:
            return int(float(value))  # Сначала в float, потом в int (на случай "123.0")
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
        """Безопасное преобразование в float"""
        if value is None or value == '' or value == 'null':
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def safe_datetime(value: Any) -> Optional[str]:
        """Безопасное преобразование даты в ISO формат"""
        if not value or value == '' or value == 'null':
            return None
        try:
            # Битрикс возвращает даты в формате "2023-01-15T10:30:00+03:00"
            if isinstance(value, str):
                # Убираем 'Z' и заменяем на +00:00 если есть
                value = value.replace('Z', '+00:00')
                dt = datetime.fromisoformat(value)
                return dt.isoformat()
            return None
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def safe_bool(value: Any) -> bool:
        """Безопасное преобразование в bool"""
        if value is None or value == '':
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.upper() in ('Y', 'YES', 'TRUE', '1')
        return bool(value)
    
    def bitrix_request(self, method: str, params: Optional[Dict] = None) -> List[Dict]:
        """Выполнить запрос к Bitrix24 API с пагинацией"""
        all_results = []
        start = 0
        
        if params is None:
            params = {}
        
        while True:
            request_params = {**params, 'start': start}
            url = f"{self.bitrix_url}{method}.json"
            
            try:
                time.sleep(self.rate_limit_delay)
                response = requests.get(url, params=request_params, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                if 'result' not in data:
                    break
                
                results = data['result']
                if not results:
                    break
                
                all_results.extend(results)
                
                # Проверка есть ли еще данные
                total = data.get('total', 0)
                if len(all_results) >= total or len(results) < 50:
                    break
                
                start += 50
                
            except Exception as e:
                logger.error(f"❌ Error in Bitrix24 request {method}: {e}")
                break
        
        return all_results
    
    def log_sync_start(self, entity_type: str) -> int:
        """Записать начало синхронизации"""
        try:
            result = self.supabase.table('sync_log').insert({
                'sync_type': SYNC_MODE,
                'entity_type': entity_type,
                'status': 'running',
                'started_at': datetime.utcnow().isoformat(),
                'records_processed': 0
            }).execute()
            return result.data[0]['id']
        except Exception as e:
            logger.error(f"❌ Error logging sync start: {e}")
            return 0
    
    def log_sync_end(self, sync_id: int, status: str, records: int, error_msg: Optional[str] = None):
        """Записать окончание синхронизации"""
        try:
            self.supabase.table('sync_log').update({
                'status': status,
                'finished_at': datetime.utcnow().isoformat(),
                'records_processed': records,
                'error_message': error_msg
            }).eq('id', sync_id).execute()
        except Exception as e:
            logger.error(f"❌ Error logging sync end: {e}")
    
    # ==================== ИЗВЛЕЧЕНИЕ ДАННЫХ ====================
    
    def extract_managers(self) -> int:
        """Извлечь пользователей (менеджеров)"""
        logger.info("📥 Extracting managers...")
        sync_id = self.log_sync_start('managers')
        
        try:
            users = self.bitrix_request('user.get', {
                'filter': {'ACTIVE': True}
            })
            
            processed = 0
            for user in users:
                user_data = {
                    'id': self.safe_int(user['ID']),
                    'name': user.get('NAME'),
                    'last_name': user.get('LAST_NAME'),
                    'email': user.get('EMAIL'),
                    'work_position': user.get('WORK_POSITION'),
                    'personal_phone': user.get('PERSONAL_PHONE'),
                    'personal_mobile': user.get('PERSONAL_MOBILE'),
                    'raw_data': user
                }
                
                self.supabase.table('managers').upsert(user_data).execute()
                processed += 1
            
            logger.info(f"  ✅ Managers extracted: {processed}")
            self.log_sync_end(sync_id, 'completed', processed)
            return processed
            
        except Exception as e:
            logger.error(f"  ❌ Error extracting managers: {e}")
            self.log_sync_end(sync_id, 'failed', 0, str(e))
            return 0
    
    def extract_contacts(self) -> int:
        """Извлечь контакты"""
        logger.info("📥 Extracting contacts...")
        sync_id = self.log_sync_start('contacts')
        
        try:
            # Параметры запроса с явным указанием полей
            params = {
                'select': [
                    'ID', 'NAME', 'LAST_NAME', 'SECOND_NAME',
                    'EMAIL', 'PHONE', 'POST', 'BIRTHDATE',
                    'DATE_CREATE', 'DATE_MODIFY',
                    'COMPANY_ID', 'ASSIGNED_BY_ID', 'CREATED_BY_ID',
                    'SOURCE_ID', 'SOURCE_DESCRIPTION'
                ]
            }
            
            # Для incremental sync - только обновленные за последние N часов
            if SYNC_MODE == 'incremental':
                cutoff_time = (datetime.utcnow() - timedelta(hours=HOURS_BACK)).isoformat()
                params['filter'] = {'>DATE_MODIFY': cutoff_time}
            
            contacts = self.bitrix_request('crm.contact.list', params)
            
            processed = 0
            batch = []
            
            for contact in contacts:
                # Собираем полное имя из частей
                name_parts = [
                    contact.get('NAME'),
                    contact.get('SECOND_NAME'),
                    contact.get('LAST_NAME')
                ]
                full_name = ' '.join(filter(None, name_parts)) or None
                
                contact_data = {
                    'id': self.safe_int(contact['ID']),
                    'name': contact.get('NAME') or None,
                    'last_name': contact.get('LAST_NAME') or None,
                    'second_name': contact.get('SECOND_NAME') or None,
                    'full_name': full_name,
                    'email': contact.get('EMAIL', [{}])[0].get('VALUE') if contact.get('EMAIL') else None,
                    'phone': contact.get('PHONE', [{}])[0].get('VALUE') if contact.get('PHONE') else None,
                    'post': contact.get('POST') or None,
                    'birthdate': self.safe_datetime(contact.get('BIRTHDATE')),
                    'date_create': self.safe_datetime(contact.get('DATE_CREATE')),
                    'date_modify': self.safe_datetime(contact.get('DATE_MODIFY')),
                    'company_id': self.safe_int(contact.get('COMPANY_ID')),
                    'assigned_by_id': self.safe_int(contact.get('ASSIGNED_BY_ID')),
                    'created_by_id': self.safe_int(contact.get('CREATED_BY_ID')),
                    'source_id': contact.get('SOURCE_ID') or None,
                    'source_description': contact.get('SOURCE_DESCRIPTION') or None,
                    'raw_data': contact
                }
                
                batch.append(contact_data)
                processed += 1
                
                # Батчевая вставка каждые 50 записей
                if len(batch) >= 50:
                    self.supabase.table('contacts').upsert(batch).execute()
                    logger.info(f"  📊 Contacts extracted: {processed}")
                    batch = []
            
            # Вставить остатки
            if batch:
                self.supabase.table('contacts').upsert(batch).execute()
            
            logger.info(f"  ✅ Contacts extracted: {processed}")
            self.log_sync_end(sync_id, 'completed', processed)
            return processed
            
        except Exception as e:
            logger.error(f"  ❌ Error extracting contacts: {e}")
            self.log_sync_end(sync_id, 'failed', processed, str(e))
            return processed
    
    def extract_deals(self) -> int:
        """Извлечь сделки"""
        logger.info("📥 Extracting deals...")
        sync_id = self.log_sync_start('deals')
        
        processed = 0
        try:
            params = {
                'select': [
                    'ID', 'TITLE', 'STAGE_ID', 'STAGE_SEMANTIC_ID',
                    'PROBABILITY', 'OPPORTUNITY', 'CURRENCY_ID',
                    'IS_MANUAL_OPPORTUNITY', 'TAX_VALUE',
                    'COMPANY_ID', 'CONTACT_ID', 'ASSIGNED_BY_ID',
                    'CREATED_BY_ID', 'CLOSED', 'BEGINDATE', 'CLOSEDATE',
                    'DATE_CREATE', 'DATE_MODIFY',
                    'UTM_SOURCE', 'UTM_MEDIUM', 'UTM_CAMPAIGN',
                    'UTM_CONTENT', 'UTM_TERM', 'SOURCE_ID', 'SOURCE_DESCRIPTION'
                ]
            }
            
            if SYNC_MODE == 'incremental':
                cutoff_time = (datetime.utcnow() - timedelta(hours=HOURS_BACK)).isoformat()
                params['filter'] = {'>DATE_MODIFY': cutoff_time}
            
            deals = self.bitrix_request('crm.deal.list', params)
            
            batch = []
            
            for deal in deals:
                deal_data = {
                    'id': self.safe_int(deal['ID']),
                    'title': deal.get('TITLE') or None,
                    'stage_id': deal.get('STAGE_ID') or None,
                    'stage_semantic_id': deal.get('STAGE_SEMANTIC_ID') or None,
                    'probability': self.safe_int(deal.get('PROBABILITY')),
                    'opportunity': self.safe_float(deal.get('OPPORTUNITY')),
                    'currency_id': deal.get('CURRENCY_ID') or 'RUB',
                    'is_manual_opportunity': self.safe_bool(deal.get('IS_MANUAL_OPPORTUNITY')),
                    'tax_value': self.safe_float(deal.get('TAX_VALUE')),
                    'company_id': self.safe_int(deal.get('COMPANY_ID')),
                    'contact_id': self.safe_int(deal.get('CONTACT_ID')),
                    'assigned_by_id': self.safe_int(deal.get('ASSIGNED_BY_ID')),
                    'created_by_id': self.safe_int(deal.get('CREATED_BY_ID')),
                    'closed': self.safe_bool(deal.get('CLOSED')),
                    'begindate': self.safe_datetime(deal.get('BEGINDATE')),
                    'closedate': self.safe_datetime(deal.get('CLOSEDATE')),
                    'date_create': self.safe_datetime(deal.get('DATE_CREATE')),
                    'date_modify': self.safe_datetime(deal.get('DATE_MODIFY')),
                    'utm_source': deal.get('UTM_SOURCE') or None,
                    'utm_medium': deal.get('UTM_MEDIUM') or None,
                    'utm_campaign': deal.get('UTM_CAMPAIGN') or None,
                    'utm_content': deal.get('UTM_CONTENT') or None,
                    'utm_term': deal.get('UTM_TERM') or None,
                    'source_id': deal.get('SOURCE_ID') or None,
                    'source_description': deal.get('SOURCE_DESCRIPTION') or None,
                    'raw_data': deal
                }
                
                batch.append(deal_data)
                processed += 1
                
                if len(batch) >= 50:
                    self.supabase.table('deals').upsert(batch).execute()
                    logger.info(f"  📊 Deals extracted: {processed}")
                    batch = []
            
            if batch:
                self.supabase.table('deals').upsert(batch).execute()
            
            logger.info(f"  ✅ Deals extracted: {processed}")
            self.log_sync_end(sync_id, 'completed', processed)
            return processed
            
        except Exception as e:
            logger.error(f"  ❌ Error extracting deals: {e}")
            self.log_sync_end(sync_id, 'failed', processed, str(e))
            return processed
    
    def extract_activities(self) -> int:
        """Извлечь активности (звонки, встречи, email)"""
        logger.info("📥 Extracting activities...")
        sync_id = self.log_sync_start('activities')
        
        processed = 0
        try:
            params = {
                'select': [
                    'ID', 'OWNER_ID', 'OWNER_TYPE_ID', 'TYPE_ID',
                    'PROVIDER_ID', 'PROVIDER_TYPE_ID',
                    'SUBJECT', 'DESCRIPTION', 'DESCRIPTION_TYPE',
                    'DIRECTION', 'PRIORITY', 'STATUS', 'COMPLETED',
                    'START_TIME', 'END_TIME', 'DEADLINE', 'CREATED', 'LAST_UPDATED',
                    'RESPONSIBLE_ID', 'AUTHOR_ID',
                    'COMMUNICATIONS'
                ]
            }
            
            if SYNC_MODE == 'incremental':
                cutoff_time = (datetime.utcnow() - timedelta(hours=HOURS_BACK)).isoformat()
                params['filter'] = {'>LAST_UPDATED': cutoff_time}
            
            activities = self.bitrix_request('crm.activity.list', params)
            
            batch = []
            
            for activity in activities:
                # Извлекаем длительность звонка если есть
                call_duration = None
                if activity.get('PROVIDER_ID') == 'VOXIMPLANT':
                    call_duration = self.safe_int(activity.get('RESULT_VALUE'))
                
                activity_data = {
                    'id': self.safe_int(activity['ID']),
                    'owner_id': self.safe_int(activity.get('OWNER_ID')),
                    'owner_type_id': self.safe_int(activity.get('OWNER_TYPE_ID')),
                    'type_id': self.safe_int(activity.get('TYPE_ID')),
                    'provider_id': activity.get('PROVIDER_ID') or None,
                    'provider_type_id': activity.get('PROVIDER_TYPE_ID') or None,
                    'subject': activity.get('SUBJECT') or None,
                    'description': activity.get('DESCRIPTION') or None,
                    'description_type': activity.get('DESCRIPTION_TYPE') or None,
                    'direction': self.safe_int(activity.get('DIRECTION')),
                    'priority': self.safe_int(activity.get('PRIORITY')),
                    'status': self.safe_int(activity.get('STATUS')),
                    'completed': self.safe_bool(activity.get('COMPLETED')),
                    'start_time': self.safe_datetime(activity.get('START_TIME')),
                    'end_time': self.safe_datetime(activity.get('END_TIME')),
                    'deadline': self.safe_datetime(activity.get('DEADLINE')),
                    'created': self.safe_datetime(activity.get('CREATED')),
                    'last_updated': self.safe_datetime(activity.get('LAST_UPDATED')),
                    'responsible_id': self.safe_int(activity.get('RESPONSIBLE_ID')),
                    'author_id': self.safe_int(activity.get('AUTHOR_ID')),
                    'call_duration': call_duration,
                    'raw_data': activity
                }
                
                batch.append(activity_data)
                processed += 1
                
                if len(batch) >= 50:
                    self.supabase.table('activities').upsert(batch).execute()
                    logger.info(f"  📊 Activities extracted: {processed}")
                    batch = []
            
            if batch:
                self.supabase.table('activities').upsert(batch).execute()
            
            logger.info(f"  ✅ Activities extracted: {processed}")
            self.log_sync_end(sync_id, 'completed', processed)
            return processed
            
        except Exception as e:
            logger.error(f"  ❌ Error extracting activities: {e}")
            self.log_sync_end(sync_id, 'failed', processed, str(e))
            return processed
    
    # ==================== РАСЧЁТ ПАТТЕРНОВ ====================
    
    def calculate_patterns(self):
        """Рассчитать аналитические паттерны для сделок"""
        logger.info("🔄 Calculating deal patterns...")
        
        try:
            # SQL для расчёта паттернов
            sql = """
            INSERT INTO deal_patterns (
                deal_id,
                touches_count,
                calls_count,
                emails_count,
                meetings_count,
                avg_call_duration,
                first_activity_date,
                last_activity_date,
                days_in_pipeline
            )
            SELECT 
                d.id as deal_id,
                COUNT(a.id) as touches_count,
                COUNT(a.id) FILTER (WHERE a.type_id = 2) as calls_count,
                COUNT(a.id) FILTER (WHERE a.type_id = 4) as emails_count,
                COUNT(a.id) FILTER (WHERE a.type_id = 1) as meetings_count,
                AVG(a.call_duration) FILTER (WHERE a.call_duration > 0) as avg_call_duration,
                MIN(a.created) as first_activity_date,
                MAX(a.created) as last_activity_date,
                EXTRACT(DAY FROM (d.closedate - d.date_create)) as days_in_pipeline
            FROM deals d
            LEFT JOIN activities a ON a.owner_id = d.id AND a.owner_type_id = 2
            GROUP BY d.id
            ON CONFLICT (deal_id) 
            DO UPDATE SET
                touches_count = EXCLUDED.touches_count,
                calls_count = EXCLUDED.calls_count,
                emails_count = EXCLUDED.emails_count,
                meetings_count = EXCLUDED.meetings_count,
                avg_call_duration = EXCLUDED.avg_call_duration,
                first_activity_date = EXCLUDED.first_activity_date,
                last_activity_date = EXCLUDED.last_activity_date,
                days_in_pipeline = EXCLUDED.days_in_pipeline;
            """
            
            self.supabase.rpc('exec_sql', {'sql': sql}).execute()
            logger.info("  ✅ Patterns calculated")
            
        except Exception as e:
            logger.error(f"  ❌ Error calculating patterns: {e}")
    
    # ==================== ОСНОВНЫЕ МЕТОДЫ ====================
    
    def full_sync(self):
        """Полная синхронизация всех данных"""
        logger.info("=" * 80)
        logger.info("🔄 FULL SYNC STARTED")
        logger.info("=" * 80)
        
        start_time = time.time()
        
        # Порядок важен: сначала справочники, потом транзакции
        managers_count = self.extract_managers()
        contacts_count = self.extract_contacts()
        deals_count = self.extract_deals()
        activities_count = self.extract_activities()
        
        # Расчёт паттернов
        self.calculate_patterns()
        
        duration = time.time() - start_time
        
        logger.info("=" * 80)
        logger.info("✅ FULL SYNC COMPLETED")
        logger.info(f"   Duration: {duration:.2f}s")
        logger.info(f"   Managers: {managers_count}")
        logger.info(f"   Contacts: {contacts_count}")
        logger.info(f"   Deals: {deals_count}")
        logger.info(f"   Activities: {activities_count}")
        logger.info("=" * 80)
    
    def incremental_sync(self):
        """Инкрементальная синхронизация (только изменения)"""
        logger.info("=" * 80)
        logger.info(f"🔄 INCREMENTAL SYNC STARTED (last {HOURS_BACK}h)")
        logger.info("=" * 80)
        
        start_time = time.time()
        
        contacts_count = self.extract_contacts()
        deals_count = self.extract_deals()
        activities_count = self.extract_activities()
        
        # Пересчёт паттернов для обновлённых сделок
        self.calculate_patterns()
        
        duration = time.time() - start_time
        
        logger.info("=" * 80)
        logger.info("✅ INCREMENTAL SYNC COMPLETED")
        logger.info(f"   Duration: {duration:.2f}s")
        logger.info(f"   Contacts: {contacts_count}")
        logger.info(f"   Deals: {deals_count}")
        logger.info(f"   Activities: {activities_count}")
        logger.info("=" * 80)


def main():
    """Точка входа"""
    logger.info("🚀 Bitrix24 ETL Service initialized")
    logger.info(f"   Bitrix24: {BITRIX_WEBHOOK[:50]}...")
    logger.info(f"   Supabase: {SUPABASE_URL}")
    logger.info("")
    
    etl = Bitrix24ETL()
    
    if SYNC_MODE == 'full':
        etl.full_sync()
    elif SYNC_MODE == 'incremental':
        etl.incremental_sync()
    else:
        logger.error(f"❌ Unknown SYNC_MODE: {SYNC_MODE}")
        sys.exit(1)
    
    logger.info("🏁 ETL process finished")


if __name__ == '__main__':
    main()