#!/usr/bin/env python3
"""
Анализатор данных Битрикс24
Проверяет доступность методов и считает объёмы данных
"""

import requests
import json
from datetime import datetime
from typing import Dict, Any, List

class Bitrix24Analyzer:
    def __init__(self, webhook_url: str):
        self.webhook = webhook_url.rstrip('/')
        
    def check_method(self, method: str, params: Dict = None) -> Dict[str, Any]:
        """Проверка доступности метода и получение данных"""
        try:
            url = f"{self.webhook}/{method}.json"
            response = requests.get(url, params=params or {}, timeout=30)
            data = response.json()
            
            if 'error' in data:
                return {
                    'method': method,
                    'available': False,
                    'error': data.get('error_description', data.get('error'))
                }
            
            total = data.get('total', 0)
            results = data.get('result', [])
            
            return {
                'method': method,
                'available': True,
                'total': total,
                'returned': len(results) if isinstance(results, list) else 0,
                'sample': results[:1] if isinstance(results, list) and results else None
            }
        except requests.exceptions.Timeout:
            return {
                'method': method,
                'available': False,
                'error': 'Timeout (30s)'
            }
        except Exception as e:
            return {
                'method': method,
                'available': False,
                'error': str(e)
            }
    
    def get_date_range_counts(self, method: str, date_field: str = 'DATE_CREATE') -> Dict[int, int]:
        """Получение количества записей по годам"""
        years = {}
        for year in [2021, 2022, 2023, 2024, 2025]:
            params = {
                'filter': {
                    f'>={date_field}': f'{year}-01-01',
                    f'<{date_field}': f'{year+1}-01-01'
                }
            }
            result = self.check_method(method, params)
            if result['available']:
                years[year] = result['total']
        return years
    
    def analyze(self) -> Dict[str, Any]:
        """Полный анализ Битрикс24"""
        
        print("=" * 80)
        print("АНАЛИЗ БИТРИКС24 ДЛЯ ETL И ИИ-АНАЛИТИКИ")
        print("=" * 80)
        print(f"Вебхук: {self.webhook}")
        print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        print()
        
        # 1. Проверка основных методов CRM
        print("1️⃣  ПРОВЕРКА ДОСТУПНОСТИ МЕТОДОВ CRM")
        print("-" * 80)
        
        methods = {
            'Сделки': 'crm.deal.list',
            'Активности': 'crm.activity.list',
            'Контакты': 'crm.contact.list',
            'Компании': 'crm.company.list',
            'Лиды': 'crm.lead.list',
            'Таймлайн': 'crm.timeline.list',
            'Звонки': 'crm.activity.list',
            'Email': 'crm.activity.list',
        }
        
        results = {}
        
        # Проверка сделок
        print("Сделки (crm.deal.list)...", end=' ')
        deals = self.check_method('crm.deal.list')
        results['deals'] = deals
        if deals['available']:
            print(f"✅ {deals['total']:,} записей")
        else:
            print(f"❌ {deals.get('error')}")
        
        # Проверка всех активностей
        print("Активности - ВСЕ (crm.activity.list)...", end=' ')
        activities = self.check_method('crm.activity.list')
        results['activities_all'] = activities
        if activities['available']:
            print(f"✅ {activities['total']:,} записей")
        else:
            print(f"❌ {activities.get('error')}")
        
        # Разбивка активностей по типам
        if activities['available']:
            activity_types = {
                '📞 Звонки': 2,
                '✉️ Email': 4,
                '📅 Встречи': 1,
                '✅ Задачи': 3,
            }
            
            for name, type_id in activity_types.items():
                params = {'filter': {'TYPE_ID': type_id}}
                result = self.check_method('crm.activity.list', params)
                results[f'activities_type_{type_id}'] = result
                if result['available']:
                    print(f"  {name}: {result['total']:,} записей")
        
        # Контакты
        print("Контакты (crm.contact.list)...", end=' ')
        contacts = self.check_method('crm.contact.list')
        results['contacts'] = contacts
        if contacts['available']:
            print(f"✅ {contacts['total']:,} записей")
        else:
            print(f"❌ {contacts.get('error')}")
        
        # Компании
        print("Компании (crm.company.list)...", end=' ')
        companies = self.check_method('crm.company.list')
        results['companies'] = companies
        if companies['available']:
            print(f"✅ {companies['total']:,} записей")
        else:
            print(f"❌ {companies.get('error')}")
        
        # Лиды
        print("Лиды (crm.lead.list)...", end=' ')
        leads = self.check_method('crm.lead.list')
        results['leads'] = leads
        if leads['available']:
            print(f"✅ {leads['total']:,} записей")
        else:
            print(f"❌ {leads.get('error')}")
        
        print()
        
        # 2. Проверка телефонии
        print("2️⃣  ПРОВЕРКА ТЕЛЕФОНИИ")
        print("-" * 80)
        
        print("Статистика звонков (voximplant.statistic.get)...", end=' ')
        calls_stats = self.check_method('voximplant.statistic.get')
        results['calls_stats'] = calls_stats
        if calls_stats['available']:
            print(f"✅ Доступна")
        else:
            print(f"❌ {calls_stats.get('error', 'Недоступна')}")
        
        print()
        
        # 3. Проверка пользователей
        print("3️⃣  ПРОВЕРКА ПОЛЬЗОВАТЕЛЕЙ")
        print("-" * 80)
        
        print("Пользователи (user.get)...", end=' ')
        users = self.check_method('user.get')
        results['users'] = users
        if users['available']:
            print(f"✅ {users['total']:,} пользователей")
        else:
            print(f"❌ {users.get('error')}")
        
        print()
        
        # 4. Анализ по годам
        if deals['available'] and deals['total'] > 0:
            print("4️⃣  РАСПРЕДЕЛЕНИЕ СДЕЛОК ПО ГОДАМ")
            print("-" * 80)
            print("Подсчёт сделок по годам (это займёт ~10 секунд)...")
            
            years_data = self.get_date_range_counts('crm.deal.list', 'DATE_CREATE')
            for year, count in sorted(years_data.items()):
                if count > 0:
                    bar = '█' * min(50, count // 100)
                    print(f"{year}: {count:>6,} {bar}")
            
            results['deals_by_year'] = years_data
            print()
        
        # 5. Оценка времени выгрузки
        print("5️⃣  ОЦЕНКА ВРЕМЕНИ ПОЛНОЙ ВЫГРУЗКИ")
        print("-" * 80)
        
        total_records = 0
        
        if deals['available']:
            total_records += deals['total']
            print(f"Сделки: {deals['total']:,} записей")
        
        if activities['available']:
            total_records += activities['total']
            print(f"Активности: {activities['total']:,} записей")
        
        if contacts['available']:
            total_records += contacts['total']
            print(f"Контакты: {contacts['total']:,} записей")
        
        # Лимиты Битрикс24: 2 req/sec, 50 записей за запрос
        # Консервативно: 80 записей в секунду
        records_per_sec = 80
        
        total_seconds = total_records / records_per_sec
        total_minutes = total_seconds / 60
        total_hours = total_minutes / 60
        
        print()
        print(f"📊 ВСЕГО ЗАПИСЕЙ: {total_records:,}")
        print(f"⏱️  Ожидаемое время: ~{total_minutes:.0f} минут ({total_hours:.1f} часов)")
        print()
        
        # Рекомендации
        print("6️⃣  РЕКОМЕНДАЦИИ")
        print("-" * 80)
        
        if total_hours > 12:
            print("⚠️  Данных МНОГО! Рекомендуется:")
            print("   • Разбить выгрузку на части (по годам)")
            print("   • Использовать параллельную выгрузку")
            print("   • Запускать выгрузку ночью")
        elif total_hours > 4:
            print("📋 Средний объём данных:")
            print("   • Выгрузка займёт несколько часов")
            print("   • Рекомендуется запускать в фоне")
        else:
            print("✅ Объём данных небольшой, выгрузка быстрая")
        
        print()
        
        # 7. Пример структуры данных
        if deals['available'] and deals.get('sample'):
            print("7️⃣  ПРИМЕР СТРУКТУРЫ СДЕЛКИ")
            print("-" * 80)
            sample_deal = deals['sample'][0]
            
            # Показываем ключевые поля
            key_fields = ['ID', 'TITLE', 'STAGE_ID', 'OPPORTUNITY', 'CURRENCY_ID', 
                         'DATE_CREATE', 'CLOSEDATE', 'ASSIGNED_BY_ID', 'SOURCE_ID']
            
            for field in key_fields:
                if field in sample_deal:
                    value = sample_deal[field]
                    if isinstance(value, str) and len(value) > 60:
                        value = value[:60] + '...'
                    print(f"  {field}: {value}")
            
            print()
            print("  [Полная структура сохранена в raw_data]")
        
        print()
        print("=" * 80)
        print("✅ АНАЛИЗ ЗАВЕРШЁН")
        print("=" * 80)
        
        return results


if __name__ == '__main__':
    # Ваш вебхук
    WEBHOOK_URL = "https://gsmural.bitrix24.ru/rest/12/120rlt4osdrdtv5a/"
    
    analyzer = Bitrix24Analyzer(WEBHOOK_URL)
    results = analyzer.analyze()
    
    # Сохраняем результаты в JSON
    with open('bitrix24_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print()
    print("📄 Результаты сохранены в bitrix24_analysis.json")
