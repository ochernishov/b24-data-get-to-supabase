#!/usr/bin/env python3
"""
Bitrix24 ETL Service - ФИНАЛЬНАЯ ВЕРСИЯ
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
BITRIX_WEBHOOK = os.getenv('BITRIX_WEBHOOK', '').rstrip('/') + '/'  # Гарантируем слеш в конце
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
SYNC_MODE = os.getenv('SYNC_MODE', 'full')
HOURS_BACK = int(os.getenv('HOURS_BACK', '24'))
SKIP_COMPANIES = os.getenv('SKIP_COMPANIES', 'false').lower() == 'true'
SKIP_CONTACTS = os.getenv('SKIP_CONTACTS', 'false').lower() == 'true'

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
        self.rate_limit_delay = 0.6  # Увеличил до 0.6 после 429 ошибки (Too Many Requests)
        self.created_managers = set()  # Кэш уже созданных менеджеров
        self.pending_managers = []  # Батч для вставки менеджеров
        self.created_companies = set()  # Кэш уже созданных компаний
        self.pending_companies = []  # Батч для вставки компаний
        
    # ==================== УТИЛИТЫ ====================

    def ensure_manager_exists(self, user_id: int):
        """Добавить менеджера в батч (создание отложено до flush)"""
        if not user_id or user_id in self.created_managers:
            return

        manager_data = {
            'id': user_id,
            'name': f'User {user_id}',
            'last_name': None,
            'email': None,
            'work_position': None,
            'personal_phone': None,
            'personal_mobile': None,
            'raw_data': {'ID': user_id, 'note': 'Auto-created on-the-fly'}
        }
        self.pending_managers.append(manager_data)
        self.created_managers.add(user_id)

    def flush_managers(self):
        """Вставить всех накопленных менеджеров в базу"""
        if not self.pending_managers:
            return

        try:
            # Батчами по 50
            for i in range(0, len(self.pending_managers), 50):
                batch = self.pending_managers[i:i+50]
                self.supabase.table('managers').upsert(batch).execute()
            logger.info(f"  ✅ Flushed {len(self.pending_managers)} managers to DB")
            self.pending_managers = []
        except Exception as e:
            logger.error(f"  ❌ Error flushing managers: {e}")
            self.pending_managers = []

    def ensure_company_exists(self, company_id: int):
        """Добавить компанию-заглушку в батч (для отсутствующих компаний)"""
        if not company_id or company_id in self.created_companies:
            return

        company_data = {
            'id': company_id,
            'title': f'Company {company_id}',
            'company_type': None,
            'email': None,
            'phone': None,
            'web': None,
            'address': None,
            'date_create': None,
            'date_modify': None,
            'assigned_by_id': None,
            'created_by_id': None,
            'raw_data': {'ID': company_id, 'note': 'Auto-created stub for missing company'}
        }
        self.pending_companies.append(company_data)
        self.created_companies.add(company_id)

    def flush_companies(self):
        """Вставить всех накопленных компаний-заглушек в базу"""
        if not self.pending_companies:
            return

        try:
            # Батчами по 50
            for i in range(0, len(self.pending_companies), 50):
                batch = self.pending_companies[i:i+50]
                self.supabase.table('companies').upsert(batch).execute()
            logger.info(f"  ✅ Flushed {len(self.pending_companies)} company stubs to DB")
            self.pending_companies = []
        except Exception as e:
            logger.error(f"  ❌ Error flushing companies: {e}")
            self.pending_companies = []

    @staticmethod
    def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        """Безопасное преобразование в int"""
        if value is None or value == '' or value == 'null':
            return default
        try:
            return int(float(value))
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
            if isinstance(value, str):
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

        # Логируем начало запроса
        logger.info(f"  🔄 Starting Bitrix24 request: {method}")

        while True:
            request_params = {**params, 'start': start}
            url = f"{self.bitrix_url}{method}.json"

            try:
                time.sleep(self.rate_limit_delay)
                response = requests.get(url, params=request_params, timeout=30)

                # Обработка 429 Too Many Requests
                if response.status_code == 429:
                    wait_time = 60  # Ждём 60 секунд
                    logger.warning(f"⚠️  429 Too Many Requests! Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue  # Повторяем тот же запрос

                response.raise_for_status()
                data = response.json()

                if 'result' not in data:
                    break

                results = data['result']
                if not results:
                    break

                all_results.extend(results)

                # Логируем прогресс каждые 500 записей
                if len(all_results) % 500 == 0:
                    total = data.get('total', 0)
                    logger.info(f"  ⏳ {method}: loaded {len(all_results)}/{total} records...")

                total = data.get('total', 0)
                if len(all_results) >= total or len(results) < 50:
                    break

                start += 50

            except requests.exceptions.HTTPError as e:
                if '429' in str(e):
                    # Дополнительная обработка 429 если не поймали выше
                    logger.warning(f"⚠️  429 in exception! Waiting 60s...")
                    time.sleep(60)
                    continue
                logger.error(f"❌ HTTP Error in Bitrix24 request {method}: {e}")
                break
            except Exception as e:
                logger.error(f"❌ Error in Bitrix24 request {method}: {e}")
                break

        logger.info(f"  ✅ {method}: completed, total {len(all_results)} records")
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
    
    
    def extract_companies(self) -> int:
        """Извлечь компании"""
        logger.info("📥 Extracting companies...")
        sync_id = self.log_sync_start('companies')

        processed = 0
        try:
            params = {}

            if SYNC_MODE == 'incremental':
                cutoff_time = (datetime.utcnow() - timedelta(hours=HOURS_BACK)).isoformat()
                params['filter'] = {'>DATE_MODIFY': cutoff_time}

            companies = self.bitrix_request('crm.company.list', params)

            batch = []

            for company in companies:
                company_id = self.safe_int(company['ID'])

                # Отметить что эта компания уже загружена (реальная, не заглушка)
                self.created_companies.add(company_id)

                # Создать менеджеров если их нет в базе
                self.ensure_manager_exists(self.safe_int(company.get('ASSIGNED_BY_ID')))
                self.ensure_manager_exists(self.safe_int(company.get('CREATED_BY_ID')))

                # EMAIL и PHONE приходят как массивы
                email_value = None
                if company.get('EMAIL') and isinstance(company['EMAIL'], list) and len(company['EMAIL']) > 0:
                    email_value = company['EMAIL'][0].get('VALUE')

                phone_value = None
                if company.get('PHONE') and isinstance(company['PHONE'], list) and len(company['PHONE']) > 0:
                    phone_value = company['PHONE'][0].get('VALUE')

                company_data = {
                    'id': company_id,
                    'title': company.get('TITLE') or None,
                    'company_type': company.get('COMPANY_TYPE') or None,
                    'email': email_value,
                    'phone': phone_value,
                    'web': company.get('WEB') or None,
                    'address': company.get('ADDRESS') or None,
                    'date_create': self.safe_datetime(company.get('DATE_CREATE')),
                    'date_modify': self.safe_datetime(company.get('DATE_MODIFY')),
                    'assigned_by_id': self.safe_int(company.get('ASSIGNED_BY_ID')),
                    'created_by_id': self.safe_int(company.get('CREATED_BY_ID')),
                    'raw_data': company
                }

                batch.append(company_data)
                processed += 1

                if len(batch) >= 50:
                    self.supabase.table('companies').upsert(batch).execute()
                    logger.info(f"  📊 Companies extracted: {processed}")
                    batch = []

            # Вставить остаток
            if batch:
                self.supabase.table('companies').upsert(batch).execute()

            # Сохранить всех накопленных менеджеров
            self.flush_managers()

            logger.info(f"  ✅ Companies extracted: {processed}")
            self.log_sync_end(sync_id, 'completed', processed)
            return processed

        except Exception as e:
            logger.error(f"  ❌ Error extracting companies: {e}")
            self.flush_managers()  # Сохранить менеджеров даже при ошибке
            self.log_sync_end(sync_id, 'failed', processed)
            return processed

    def extract_contacts(self) -> int:
        """Извлечь контакты"""
        logger.info("📥 Extracting contacts...")
        sync_id = self.log_sync_start('contacts')
        
        processed = 0
        try:
            params = {}
            
            if SYNC_MODE == 'incremental':
                cutoff_time = (datetime.utcnow() - timedelta(hours=HOURS_BACK)).isoformat()
                params['filter'] = {'>DATE_MODIFY': cutoff_time}
            
            contacts = self.bitrix_request('crm.contact.list', params)
            
            batch = []
            
            for contact in contacts:
                # Создать компанию-заглушку если её нет в базе
                company_id = self.safe_int(contact.get('COMPANY_ID'))
                if company_id:
                    self.ensure_company_exists(company_id)

                # Создать менеджеров если их нет
                self.ensure_manager_exists(self.safe_int(contact.get('ASSIGNED_BY_ID')))
                self.ensure_manager_exists(self.safe_int(contact.get('CREATED_BY_ID')))

                # EMAIL и PHONE приходят как массивы
                email_value = None
                if contact.get('EMAIL') and isinstance(contact['EMAIL'], list) and len(contact['EMAIL']) > 0:
                    email_value = contact['EMAIL'][0].get('VALUE')

                phone_value = None
                if contact.get('PHONE') and isinstance(contact['PHONE'], list) and len(contact['PHONE']) > 0:
                    phone_value = contact['PHONE'][0].get('VALUE')

                # Собираем полное имя
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
                    'email': email_value,
                    'phone': phone_value,
                    'post': contact.get('POST') or None,
                    'birthdate': self.safe_datetime(contact.get('BIRTHDATE')),
                    'date_create': self.safe_datetime(contact.get('DATE_CREATE')),
                    'date_modify': self.safe_datetime(contact.get('DATE_MODIFY')),
                    'company_id': company_id,
                    'assigned_by_id': self.safe_int(contact.get('ASSIGNED_BY_ID')),
                    'created_by_id': self.safe_int(contact.get('CREATED_BY_ID')),
                    'source_id': contact.get('SOURCE_ID') or None,
                    'source_description': contact.get('SOURCE_DESCRIPTION') or None,
                    'raw_data': contact
                }
                
                batch.append(contact_data)
                processed += 1

                if len(batch) >= 50:
                    # Флашим заглушки ПЕРЕД вставкой батча
                    self.flush_companies()
                    self.flush_managers()
                    self.supabase.table('contacts').upsert(batch).execute()
                    logger.info(f"  📊 Contacts extracted: {processed}")
                    batch = []

            if batch:
                # Флашим заглушки ПЕРЕД вставкой остатка
                self.flush_companies()
                self.flush_managers()
                self.supabase.table('contacts').upsert(batch).execute()

            # Сохранить накопленные заглушки
            self.flush_companies()
            self.flush_managers()

            logger.info(f"  ✅ Contacts extracted: {processed}")
            self.log_sync_end(sync_id, 'completed', processed)
            return processed

        except Exception as e:
            logger.error(f"  ❌ Error extracting contacts: {e}")
            self.flush_companies()  # Сохранить заглушки даже при ошибке
            self.flush_managers()
            self.log_sync_end(sync_id, 'failed', processed, str(e))
            return processed
    
    def extract_deals(self) -> int:
        """Извлечь сделки"""
        logger.info("📥 Extracting deals...")
        sync_id = self.log_sync_start('deals')
        
        processed = 0
        try:
            params = {}
            
            if SYNC_MODE == 'incremental':
                cutoff_time = (datetime.utcnow() - timedelta(hours=HOURS_BACK)).isoformat()
                params['filter'] = {'>DATE_MODIFY': cutoff_time}
            
            deals = self.bitrix_request('crm.deal.list', params)
            
            batch = []
            
            for deal in deals:
                # Создать менеджеров если их нет в базе
                self.ensure_manager_exists(self.safe_int(deal.get('ASSIGNED_BY_ID')))
                self.ensure_manager_exists(self.safe_int(deal.get('CREATED_BY_ID')))
                self.ensure_manager_exists(self.safe_int(deal.get('MODIFY_BY_ID')))

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

            # Сохранить всех накопленных менеджеров
            self.flush_managers()

            logger.info(f"  ✅ Deals extracted: {processed}")
            self.log_sync_end(sync_id, 'completed', processed)
            return processed

        except Exception as e:
            logger.error(f"  ❌ Error extracting deals: {e}")
            self.flush_managers()  # Сохранить менеджеров даже при ошибке
            self.log_sync_end(sync_id, 'failed', processed, str(e))
            return processed
    
    def extract_activities(self) -> int:
        """Извлечь активности (звонки, встречи, email)"""
        logger.info("📥 Extracting activities...")
        sync_id = self.log_sync_start('activities')
        
        processed = 0
        try:
            params = {}
            
            if SYNC_MODE == 'incremental':
                cutoff_time = (datetime.utcnow() - timedelta(hours=HOURS_BACK)).isoformat()
                params['filter'] = {'>LAST_UPDATED': cutoff_time}
            
            activities = self.bitrix_request('crm.activity.list', params)
            
            batch = []
            
            for activity in activities:
                # Создать менеджеров если их нет в базе
                self.ensure_manager_exists(self.safe_int(activity.get('RESPONSIBLE_ID')))
                self.ensure_manager_exists(self.safe_int(activity.get('AUTHOR_ID')))
                self.ensure_manager_exists(self.safe_int(activity.get('EDITOR_ID')))

                # Длительность звонка
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

            # Сохранить всех накопленных менеджеров
            self.flush_managers()

            logger.info(f"  ✅ Activities extracted: {processed}")
            self.log_sync_end(sync_id, 'completed', processed)
            return processed

        except Exception as e:
            logger.error(f"  ❌ Error extracting activities: {e}")
            self.flush_managers()  # Сохранить менеджеров даже при ошибке
            self.log_sync_end(sync_id, 'failed', processed, str(e))
            return processed
    
    # ==================== РАСЧЁТ ПАТТЕРНОВ ====================
    
    def calculate_patterns(self):
        """Рассчитать аналитические паттерны для сделок"""
        logger.info("🔄 Calculating deal patterns...")
        
        try:
            # Прямой SQL через postgrest
            # Вместо RPC используем прямые UPDATE/INSERT
            
            # Получаем список всех сделок
            deals_response = self.supabase.table('deals').select('id').execute()
            deal_ids = [d['id'] for d in deals_response.data]
            
            if not deal_ids:
                logger.info("  ℹ️ No deals to calculate patterns")
                return
            
            # Для каждой сделки считаем паттерны
            for deal_id in deal_ids:
                # Получаем активности сделки
                activities = self.supabase.table('activities')\
                    .select('*')\
                    .eq('owner_id', deal_id)\
                    .eq('owner_type_id', 2)\
                    .execute()
                
                if not activities.data:
                    continue
                
                # Считаем метрики
                touches_count = len(activities.data)
                calls_count = len([a for a in activities.data if a.get('type_id') == 2])
                emails_count = len([a for a in activities.data if a.get('type_id') == 4])
                meetings_count = len([a for a in activities.data if a.get('type_id') == 1])
                
                call_durations = [a.get('call_duration') for a in activities.data if a.get('call_duration')]
                avg_call_duration = sum(call_durations) / len(call_durations) if call_durations else None
                
                created_dates = [a.get('created') for a in activities.data if a.get('created')]
                first_activity_date = min(created_dates) if created_dates else None
                last_activity_date = max(created_dates) if created_dates else None
                
                # Сохраняем паттерн
                pattern_data = {
                    'deal_id': deal_id,
                    'touches_count': touches_count,
                    'calls_count': calls_count,
                    'emails_count': emails_count,
                    'meetings_count': meetings_count,
                    'avg_call_duration': avg_call_duration,
                    'first_activity_date': first_activity_date,
                    'last_activity_date': last_activity_date
                }
                
                self.supabase.table('deal_patterns').upsert(pattern_data).execute()
            
            logger.info(f"  ✅ Patterns calculated for {len(deal_ids)} deals")
            
        except Exception as e:
            logger.error(f"  ❌ Error calculating patterns: {e}")
    
    # ==================== ОСНОВНЫЕ МЕТОДЫ ====================
    
    def full_sync(self):
        """
        Полная синхронизация всех данных
        Менеджеры создаются автоматически on-the-fly при загрузке companies/deals/activities
        """
        logger.info("=" * 80)
        logger.info("🔄 FULL SYNC STARTED")
        logger.info("=" * 80)

        start_time = time.time()

        # Managers создаются автоматически в процессе загрузки
        companies_count = 0
        if not SKIP_COMPANIES:
            companies_count = self.extract_companies()
        else:
            logger.info("⏭️  Skipping companies extraction (SKIP_COMPANIES=true)")

        contacts_count = 0
        if not SKIP_CONTACTS:
            contacts_count = self.extract_contacts()
        else:
            logger.info("⏭️  Skipping contacts extraction (SKIP_CONTACTS=true)")

        deals_count = self.extract_deals()
        activities_count = self.extract_activities()
        managers_count = len(self.created_managers)
        
        self.calculate_patterns()
        
        duration = time.time() - start_time
        
        logger.info("=" * 80)
        logger.info("✅ FULL SYNC COMPLETED")
        logger.info(f"   Duration: {duration:.2f}s")
        logger.info(f"   Managers: {managers_count}")
        logger.info(f"   Companies: {companies_count}")
        logger.info(f"   Contacts: {contacts_count}")
        logger.info(f"   Deals: {deals_count}")
        logger.info(f"   Activities: {activities_count}")
        logger.info("=" * 80)
    
    def incremental_sync(self):
        """Инкрементальная синхронизация"""
        logger.info("=" * 80)
        logger.info(f"🔄 INCREMENTAL SYNC STARTED (last {HOURS_BACK}h)")
        logger.info("=" * 80)
        
        start_time = time.time()
        
        contacts_count = self.extract_contacts()
        deals_count = self.extract_deals()
        activities_count = self.extract_activities()
        
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