import requests
import sqlite3
import time
import schedule
from bs4 import BeautifulSoup
from telegram import Bot
from datetime import datetime
import re
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# ===== КОНФИГУРАЦИЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_NAME = "avito_items.db"

# Проверяем, что переменные заданы
if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    print("❌ ОШИБКА: не установлены TELEGRAM_TOKEN или TELEGRAM_CHAT_ID")
    print("Добавь их в Environment Variables на Render")
    exit(1)

# Параметры поиска
BRANDS = ["Apple", "Samsung", "Dyson", "наушники", "умные часы"]
MIN_PRICE = 1000
MAX_PRICE = 50000

# ===== ИНИЦИАЛИЗАЦИЯ БД =====
def init_db():
    """Создаёшь БД для хранения уже отправленных объявлений"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            title TEXT,
            price INTEGER,
            views INTEGER,
            url TEXT,
            sent_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# ===== ФУНКЦИЯ ПАРСИНГА АВИТО =====
def parse_avito():
    """
    Парсит Авито по критериям.
    На облаке используй VPN если Авито блокирует.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    found_items = []
    
    try:
        # Формируем URL для поиска электроники
        url = "https://www.avito.ru/elektronika"
        params = {
            "pmax": MAX_PRICE,
            "pmin": MIN_PRICE,
            "sort": "date",
            "user": "1"  # только от частных лиц
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        
        if response.status_code != 200:
            print(f"⚠️ Ошибка подключения: {response.status_code}")
            return found_items
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Ищешь объявления
        items = soup.find_all('div', {'itemprop': 'itemListElement'})
        
        for item in items:
            try:
                # Вытягиваешь данные
                title_elem = item.find('h3', {'itemprop': 'name'})
                price_elem = item.find('span', {'itemprop': 'price'})
                link_elem = item.find('a', {'itemprop': 'url'})
                
                if not all([title_elem, price_elem, link_elem]):
                    continue
                
                title = title_elem.get_text(strip=True)
                price_text = price_elem.get_text(strip=True).replace(' ', '').replace('₽', '')
                
                try:
                    price = int(price_text)
                except ValueError:
                    continue
                
                link = link_elem.get('href')
                
                # Проверяешь, подходит ли по брендам
                if not any(brand.lower() in title.lower() for brand in BRANDS):
                    continue
                
                # Вытягиваешь количество просмотров
                views_elem = item.find('span', class_='views-count')
                views = 0
                if views_elem:
                    try:
                        views = int(views_elem.get_text(strip=True).split()[0])
                    except:
                        views = 0
                
                # Формируешь полную ссылку
                if not link.startswith('http'):
                    link = 'https://www.avito.ru' + link
                
                # Вытягиваешь ID из ссылки
                item_id = link.split('_')[-1].split('?')[0]
                
                found_items.append({
                    'id': item_id,
                    'title': title,
                    'price': price,
                    'views': views,
                    'url': link
                })
                
            except Exception as e:
                continue
        
    except Exception as e:
        print(f"❌ Ошибка парсинга: {e}")
    
    return found_items

# ===== ФУНКЦИЯ ПРОВЕРКИ БД =====
def is_item_sent(item_id):
    """Проверяет, отправляли ли мы это объявление уже"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM items WHERE id = ?", (item_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except:
        return False

# ===== ФУНКЦИЯ СОХРАНЕНИЯ В БД =====
def save_item(item):
    """Сохраняет объявление в БД"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO items (id, title, price, views, url, sent_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (item['id'], item['title'], item['price'], item['views'], item['url'], datetime.now()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка сохранения в БД: {e}")

# ===== ФУНКЦИЯ ОТПРАВКИ В ТЕЛЕГРАМ =====
def send_to_telegram(item):
    """Отправляет объявление в Телеграм"""
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        
        message = f"""
🔔 *НОВОЕ ОБЪЯВЛЕНИЕ*

📱 {item['title']}
💰 Цена: {item['price']} ₽
👁 Просмотров: {item['views']}

🔗 [Смотреть объявление]({item['url']})
"""
        
        bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode='Markdown'
        )
        print(f"✅ Отправлено: {item['title']}")
    except Exception as e:
        print(f"❌ Ошибка отправки в Телеграм: {e}")

# ===== ГЛАВНАЯ ФУНКЦИЯ =====
def check_avito():
    """Главная функция - парсит и отправляет новые объявления"""
    print(f"\n⏰ Проверка в {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    items = parse_avito()
    
    if not items:
        print("❌ Объявлений не найдено или Авито заблокировал")
        return
    
    print(f"📊 Найдено объявлений: {len(items)}")
    
    new_count = 0
    for item in items:
        if not is_item_sent(item['id']):
            send_to_telegram(item)
            save_item(item)
            new_count += 1
            time.sleep(1)  # задержка между отправками
    
    print(f"✨ Новых объявлений отправлено: {new_count}")

# ===== РАСПИСАНИЕ =====
def schedule_check():
    """Запускает проверку каждый час"""
    schedule.every(1).hours.do(check_avito)
    
    print("🤖 Бот запущен на Render. Проверка каждый час.")
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# ===== ТОЧКА ЗАПУСКА =====
if __name__ == "__main__":
    print("🚀 Инициализация бота на Render...")
    init_db()
    
    # Первый запуск сразу
    check_avito()
    
    # Потом по расписанию
    try:
        schedule_check()
    except KeyboardInterrupt:
        print("\n⛔ Бот остановлен")
