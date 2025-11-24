import os
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger

# Загрузка переменных окружения из файла .env
try:
    load_dotenv(dotenv_path=r'C:\Users\wangr\PycharmProjects\pythonProject47\api_keys.env')
except Exception as e:
    logger.error(f"Ошибка при загрузке переменных окружения: {e}")

CONFIG = {
    'API': {
        'API_KEY': os.getenv('HUOBI_API_KEY'),
        'SECRET_KEY': os.getenv('HUOBI_SECRET_KEY'),
        'API_URL': os.getenv('HUOBI_API_URL'),
        'WS_URL': os.getenv('HUOBI_WS_URL')
    },
    # Список инструментов для получения данных
    'TRADE': {
        'START_DATE': datetime(2024, 12, 12),  # Дата начала получения данных (год, месяц, день)
        'TIMEZONE': 'Europe/Moscow'  # Локальный часовой пояс
    }
}