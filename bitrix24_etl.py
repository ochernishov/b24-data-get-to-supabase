#!/usr/bin/env python3
"""
Битрикс24 ETL Service
Автоматическая выгрузка данных из Битрикс24 в Supabase PostgreSQL
"""

import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from supabase import create_client, Client
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bitrix24_etl.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class Bitrix24ETL:
    """ETL сервис для Битрикс24 → Supabase"""
    
    def __init__(
        self,
        bitrix_webhook: str,
        supabase_url: str,
        supabase_key: str,
        rate_limit_delay: float = 0.5  # 2 req/sec = 0.5 sec delay
    ):
        self.bitrix_webhook = bitrix_webhook.rstrip('/')
        self.supabase: Client = create_client(supabase_url, supabase_key)
        self.rate_limit_delay = rate_limit_delay
        
        logger.info("🚀 Bitrix24 ETL Service initialized")
        logger.info(f"   Bitrix24: {self.bitrix_webhook}")
        logger.info(f"   Supabase: {supabase_url}")
    
    def _api_call(
        self, 
        method: str, 
        params: Dict = None,
        retry_count: int = 3
    ) -> Dict[str, Any]:
        """Вызов API Битрикс24 с retry логикой"""
        
        url = f"{self.bitrix_webhook}/{method}.json"
        
        for attempt in range(retry_count):
            try:
                response = requests.get(url, params=params or {}, timeout=30)
                time.sleep(self.rate_limit_delay)
                
                data = response.json()
                
                if 'error' in data:
                    logger.error(f"API Error: {data.get('error_description')}")
                    return None
                
                return data
                
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on attempt {attempt + 1}/{retry_count}")
                if attempt == retry_count - 1:
                    raise
                time.sleep(2 ** attempt)  # exponential backoff
                
            except Exception as e:
                logger.error(f"Error calling {method}: {str(e)}")
                if attempt == retry_count - 1:
                    raise
                time.sleep(2 ** attempt)
        
        return None
    
    def log_sync(
        self, 
        entity_type: str, 
        sync_type: str = 'incremental',
        status: str = 'running'
    ) -> int:
        """Создать запись в логе синхронизации"""
        
        result = self.supabase.table('sync_log').insert({
            'sync_type': sync_type,
            'entity_type': entity_type,
            'status': status,
            'started_at': datetime.now().isoformat()
        }).execute()
        
        return result.data[0]['id']
    
    def update_sync_log(
        self,
        log_id: int,
        status: str,
        records_processed: int = 0,
        records_inserted: int = 0,
        records_updated: int = 0,
        error_message: str = None
    ):
        """Обновить запись в логе синхронизации"""
        
        self.supabase.table('sync_log').update({
            'status': status,
            'finished_at': datetime.now().isoformat(),
            'records_processed': records_processed,
            'records_inserted': records_inserted,
            'records_updated': records_updated,
            'error_message': error_message
        }).eq('id', log_id).execute()
    
    # ========================================================================
    # ВЫГРУЗКА ПОЛЬЗОВАТЕЛЕЙ (МЕНЕДЖЕРОВ)
    # ========================================================================
    
    def extract_managers(self) -> int:
        """Выгрузка всех пользователей"""
        
        logger.info("📥 Extracting managers...")
        log_id = self.log_sync('managers', 'full')
        
        try:
            data = self._api_call('user.get')
            
            if not data or not data.get('result'):
                logger.warning("No managers found")
                self.update_sync_log(log_id, 'completed', 0)
                return 0
            
            users = data['result']
            managers_data = []
            
            for user in users:
                managers_data.append({
                    'id': int(user['ID']),
                    'name': user.get('NAME'),
                    'last_name': user.get('LAST_NAME'),
                    'email': user.get('EMAIL'),
                    'active': user.get('ACTIVE') == 'true',
                    'is_admin': user.get('IS_ADMIN') == 'Y',
                    'work_position': user.get('WORK_POSITION'),
                    'personal_phone': user.get('PERSONAL_PHONE'),
                    'personal_mobile': user.get('PERSONAL_MOBILE'),
                    'time_zone': user.get('TIME_ZONE'),
                    'date_register': user.get('DATE_REGISTER'),
                    'last_activity_date': user.get('LAST_ACTIVITY_DATE'),
                    'raw_data': user
                })
            
            # Upsert в Supabase
            self.supabase.table('managers').upsert(
                managers_data,
                on_conflict='id'
            ).execute()
            
            logger.info(f"✅ Managers extracted: {len(managers_data)}")
            self.update_sync_log(log_id, 'completed', len(managers_data), len(managers_data))
            return len(managers_data)
            
        except Exception as e:
            logger.error(f"❌ Error extracting managers: {str(e)}")
            self.update_sync_log(log_id, 'failed', error_message=str(e))
            return 0
    
    # ========================================================================
    # ВЫГРУЗКА СДЕЛОК
    # ========================================================================
    
    def extract_deals(
        self, 
        start_date: Optional[datetime] = None,
        batch_size: int = 50
    ) -> int:
        """Выгрузка сделок с пагинацией"""
        
        logger.info("📥 Extracting deals...")
        log_id = self.log_sync('deals', 'incremental' if start_date else 'full')
        
        total_extracted = 0
        start = 0
        
        try:
            while True:
                params = {
                    'start': start,
                    'select': ['*', 'UF_*']
                }
                
                if start_date:
                    params['filter'] = {
                        '>=DATE_CREATE': start_date.isoformat()
                    }
                
                data = self._api_call('crm.deal.list', params)
                
                if not data or not data.get('result'):
                    break
                
                deals = data['result']
                
                if not deals:
                    break
                
                # Подготовка данных
                deals_data = []
                for deal in deals:
                    deals_data.append({
                        'id': int(deal['ID']),
                        'title': deal.get('TITLE'),
                        'type_id': deal.get('TYPE_ID'),
                        'stage_id': deal.get('STAGE_ID'),
                        'stage_semantic_id': deal.get('STAGE_SEMANTIC_ID'),
                        'category_id': int(deal.get('CATEGORY_ID', 0)) or None,
                        'opportunity': float(deal.get('OPPORTUNITY', 0)) or None,
                        'currency_id': deal.get('CURRENCY_ID'),
                        'tax_value': float(deal.get('TAX_VALUE', 0)) or None,
                        'begindate': deal.get('BEGINDATE'),
                        'closedate': deal.get('CLOSEDATE'),
                        'date_create': deal.get('DATE_CREATE'),
                        'date_modify': deal.get('DATE_MODIFY'),
                        'is_new': deal.get('IS_NEW') == 'Y',
                        'is_recurring': deal.get('IS_RECURRING') == 'Y',
                        'is_return_customer': deal.get('IS_RETURN_CUSTOMER') == 'Y',
                        'is_repeated_approach': deal.get('IS_REPEATED_APPROACH') == 'Y',
                        'closed': deal.get('CLOSED') == 'Y',
                        'company_id': int(deal.get('COMPANY_ID', 0)) or None,
                        'contact_id': int(deal.get('CONTACT_ID', 0)) or None,
                        'lead_id': int(deal.get('LEAD_ID', 0)) or None,
                        'assigned_by_id': int(deal.get('ASSIGNED_BY_ID', 0)) or None,
                        'created_by_id': int(deal.get('CREATED_BY_ID', 0)) or None,
                        'modify_by_id': int(deal.get('MODIFY_BY_ID', 0)) or None,
                        'source_id': deal.get('SOURCE_ID'),
                        'source_description': deal.get('SOURCE_DESCRIPTION'),
                        'additional_info': deal.get('ADDITIONAL_INFO'),
                        'location_id': deal.get('LOCATION_ID'),
                        'utm_source': deal.get('UTM_SOURCE'),
                        'utm_medium': deal.get('UTM_MEDIUM'),
                        'utm_campaign': deal.get('UTM_CAMPAIGN'),
                        'utm_content': deal.get('UTM_CONTENT'),
                        'utm_term': deal.get('UTM_TERM'),
                        'raw_data': deal
                    })
                
                # Upsert в Supabase
                self.supabase.table('deals').upsert(
                    deals_data,
                    on_conflict='id'
                ).execute()
                
                total_extracted += len(deals)
                logger.info(f"  📊 Deals extracted: {total_extracted}")
                
                # Проверка наличия следующей страницы
                next_cursor = data.get('next')
                if not next_cursor or next_cursor >= data.get('total', 0):
                    break
                
                start = next_cursor
            
            logger.info(f"✅ Total deals extracted: {total_extracted}")
            self.update_sync_log(log_id, 'completed', total_extracted, total_extracted)
            return total_extracted
            
        except Exception as e:
            logger.error(f"❌ Error extracting deals: {str(e)}")
            self.update_sync_log(log_id, 'failed', total_extracted, error_message=str(e))
            return total_extracted
    
    # ========================================================================
    # ВЫГРУЗКА АКТИВНОСТЕЙ (КОММУНИКАЦИЙ)
    # ========================================================================
    
    def extract_activities(
        self,
        start_date: Optional[datetime] = None,
        deal_ids: Optional[List[int]] = None
    ) -> int:
        """Выгрузка активностей"""
        
        logger.info("📥 Extracting activities...")
        log_id = self.log_sync('activities', 'incremental' if start_date else 'full')
        
        total_extracted = 0
        start = 0
        
        try:
            while True:
                params = {
                    'start': start,
                    'select': ['*']
                }
                
                filters = {}
                
                if start_date:
                    filters['>=CREATED'] = start_date.isoformat()
                
                if deal_ids:
                    filters['OWNER_TYPE_ID'] = 2  # 2 = Deal
                    filters['OWNER_ID'] = deal_ids[0] if len(deal_ids) == 1 else deal_ids
                
                if filters:
                    params['filter'] = filters
                
                data = self._api_call('crm.activity.list', params)
                
                if not data or not data.get('result'):
                    break
                
                activities = data['result']
                
                if not activities:
                    break
                
                # Подготовка данных
                activities_data = []
                for activity in activities:
                    activities_data.append({
                        'id': int(activity['ID']),
                        'owner_type_id': int(activity.get('OWNER_TYPE_ID', 0)) or None,
                        'owner_id': int(activity.get('OWNER_ID', 0)) or None,
                        'type_id': int(activity.get('TYPE_ID', 0)) or None,
                        'provider_id': activity.get('PROVIDER_ID'),
                        'provider_type_id': activity.get('PROVIDER_TYPE_ID'),
                        'direction': int(activity.get('DIRECTION', 0)) or None,
                        'subject': activity.get('SUBJECT'),
                        'description': activity.get('DESCRIPTION'),
                        'description_type': int(activity.get('DESCRIPTION_TYPE', 1)),
                        'created': activity.get('CREATED'),
                        'last_updated': activity.get('LAST_UPDATED'),
                        'start_time': activity.get('START_TIME'),
                        'end_time': activity.get('END_TIME'),
                        'deadline': activity.get('DEADLINE'),
                        'completed': activity.get('COMPLETED'),
                        'status': int(activity.get('STATUS', 0)) or None,
                        'result_status': int(activity.get('RESULT_STATUS', 0)) or None,
                        'responsible_id': int(activity.get('RESPONSIBLE_ID', 0)) or None,
                        'author_id': int(activity.get('AUTHOR_ID', 0)) or None,
                        'editor_id': int(activity.get('EDITOR_ID', 0)) or None,
                        'priority': int(activity.get('PRIORITY', 0)) or None,
                        'raw_data': activity
                    })
                
                # Upsert в Supabase
                self.supabase.table('activities').upsert(
                    activities_data,
                    on_conflict='id'
                ).execute()
                
                total_extracted += len(activities)
                logger.info(f"  📊 Activities extracted: {total_extracted}")
                
                # Проверка наличия следующей страницы
                next_cursor = data.get('next')
                if not next_cursor or next_cursor >= data.get('total', 0):
                    break
                
                start = next_cursor
            
            logger.info(f"✅ Total activities extracted: {total_extracted}")
            self.update_sync_log(log_id, 'completed', total_extracted, total_extracted)
            return total_extracted
            
        except Exception as e:
            logger.error(f"❌ Error extracting activities: {str(e)}")
            self.update_sync_log(log_id, 'failed', total_extracted, error_message=str(e))
            return total_extracted
    
    # ========================================================================
    # ВЫГРУЗКА КОНТАКТОВ
    # ========================================================================
    
    def extract_contacts(
        self,
        start_date: Optional[datetime] = None
    ) -> int:
        """Выгрузка контактов"""
        
        logger.info("📥 Extracting contacts...")
        log_id = self.log_sync('contacts', 'incremental' if start_date else 'full')
        
        total_extracted = 0
        start = 0
        
        try:
            while True:
                params = {
                    'start': start,
                    'select': ['*', 'PHONE', 'EMAIL']
                }
                
                if start_date:
                    params['filter'] = {
                        '>=DATE_CREATE': start_date.isoformat()
                    }
                
                data = self._api_call('crm.contact.list', params)
                
                if not data or not data.get('result'):
                    break
                
                contacts = data['result']
                
                if not contacts:
                    break
                
                # Подготовка данных
                contacts_data = []
                for contact in contacts:
                    # Извлечение телефона и email
                    phone = None
                    email = None
                    
                    if contact.get('PHONE'):
                        phones = contact['PHONE']
                        if phones and isinstance(phones, list) and len(phones) > 0:
                            phone = phones[0].get('VALUE')
                    
                    if contact.get('EMAIL'):
                        emails = contact['EMAIL']
                        if emails and isinstance(emails, list) and len(emails) > 0:
                            email = emails[0].get('VALUE')
                    
                    contacts_data.append({
                        'id': int(contact['ID']),
                        'name': contact.get('NAME'),
                        'last_name': contact.get('LAST_NAME'),
                        'second_name': contact.get('SECOND_NAME'),
                        'full_name': f"{contact.get('NAME', '')} {contact.get('LAST_NAME', '')}".strip(),
                        'post': contact.get('POST'),
                        'company_id': int(contact.get('COMPANY_ID', 0)) or None,
                        'phone': phone,
                        'email': email,
                        'birthdate': contact.get('BIRTHDATE'),
                        'source_id': contact.get('SOURCE_ID'),
                        'source_description': contact.get('SOURCE_DESCRIPTION'),
                        'assigned_by_id': int(contact.get('ASSIGNED_BY_ID', 0)) or None,
                        'created_by_id': int(contact.get('CREATED_BY_ID', 0)) or None,
                        'date_create': contact.get('DATE_CREATE'),
                        'date_modify': contact.get('DATE_MODIFY'),
                        'raw_data': contact
                    })
                
                # Upsert в Supabase
                self.supabase.table('contacts').upsert(
                    contacts_data,
                    on_conflict='id'
                ).execute()
                
                total_extracted += len(contacts)
                logger.info(f"  📊 Contacts extracted: {total_extracted}")
                
                # Проверка наличия следующей страницы
                next_cursor = data.get('next')
                if not next_cursor or next_cursor >= data.get('total', 0):
                    break
                
                start = next_cursor
            
            logger.info(f"✅ Total contacts extracted: {total_extracted}")
            self.update_sync_log(log_id, 'completed', total_extracted, total_extracted)
            return total_extracted
            
        except Exception as e:
            logger.error(f"❌ Error extracting contacts: {str(e)}")
            self.update_sync_log(log_id, 'failed', total_extracted, error_message=str(e))
            return total_extracted
    
    # ========================================================================
    # РАСЧЁТ ПАТТЕРНОВ
    # ========================================================================
    
    def calculate_patterns(self, deal_ids: Optional[List[int]] = None):
        """Расчёт аналитических паттернов для сделок"""
        
        logger.info("🔄 Calculating deal patterns...")
        
        try:
            if deal_ids:
                # Обновить конкретные сделки
                for deal_id in deal_ids:
                    self.supabase.rpc('update_deal_patterns', {'p_deal_id': deal_id}).execute()
                    logger.info(f"  ✓ Patterns updated for deal {deal_id}")
            else:
                # Обновить все сделки
                deals = self.supabase.table('deals').select('id').execute()
                
                for deal in deals.data:
                    self.supabase.rpc('update_deal_patterns', {'p_deal_id': deal['id']}).execute()
                
                logger.info(f"✅ Patterns calculated for {len(deals.data)} deals")
                
        except Exception as e:
            logger.error(f"❌ Error calculating patterns: {str(e)}")
    
    # ========================================================================
    # ПОЛНАЯ И ИНКРЕМЕНТАЛЬНАЯ СИНХРОНИЗАЦИЯ
    # ========================================================================
    
    def full_sync(self):
        """Полная синхронизация всех данных"""
        
        logger.info("=" * 80)
        logger.info("🔄 FULL SYNC STARTED")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        
        # 1. Менеджеры
        self.extract_managers()
        
        # 2. Контакты
        self.extract_contacts()
        
        # 3. Сделки
        self.extract_deals()
        
        # 4. Активности
        self.extract_activities()
        
        # 5. Расчёт паттернов
        self.calculate_patterns()
        
        elapsed = datetime.now() - start_time
        logger.info("=" * 80)
        logger.info(f"✅ FULL SYNC COMPLETED in {elapsed}")
        logger.info("=" * 80)
    
    def incremental_sync(self, hours_back: int = 24):
        """Инкрементальная синхронизация (только новые/обновлённые данные)"""
        
        logger.info("=" * 80)
        logger.info(f"🔄 INCREMENTAL SYNC (last {hours_back} hours)")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        start_date = datetime.now() - timedelta(hours=hours_back)
        
        # 1. Менеджеры (можно пропустить, т.к. редко меняются)
        # self.extract_managers()
        
        # 2. Контакты за период
        self.extract_contacts(start_date=start_date)
        
        # 3. Сделки за период
        self.extract_deals(start_date=start_date)
        
        # 4. Активности за период
        self.extract_activities(start_date=start_date)
        
        # 5. Расчёт паттернов для обновлённых сделок
        # Получаем ID обновлённых сделок
        result = self.supabase.table('deals')\
            .select('id')\
            .gte('date_modify', start_date.isoformat())\
            .execute()
        
        if result.data:
            deal_ids = [d['id'] for d in result.data]
            self.calculate_patterns(deal_ids=deal_ids)
        
        elapsed = datetime.now() - start_time
        logger.info("=" * 80)
        logger.info(f"✅ INCREMENTAL SYNC COMPLETED in {elapsed}")
        logger.info("=" * 80)


def main():
    """Главная функция"""
    
    # Читаем переменные окружения
    BITRIX_WEBHOOK = os.getenv('BITRIX_WEBHOOK')
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    SYNC_MODE = os.getenv('SYNC_MODE', 'incremental')  # full или incremental
    
    if not all([BITRIX_WEBHOOK, SUPABASE_URL, SUPABASE_KEY]):
        logger.error("❌ Missing required environment variables!")
        logger.error("   Required: BITRIX_WEBHOOK, SUPABASE_URL, SUPABASE_KEY")
        sys.exit(1)
    
    # Создаём ETL
    etl = Bitrix24ETL(
        bitrix_webhook=BITRIX_WEBHOOK,
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_KEY
    )
    
    # Запускаем синхронизацию
    if SYNC_MODE == 'full':
        etl.full_sync()
    else:
        hours_back = int(os.getenv('HOURS_BACK', 24))
        etl.incremental_sync(hours_back=hours_back)


if __name__ == '__main__':
    main()
