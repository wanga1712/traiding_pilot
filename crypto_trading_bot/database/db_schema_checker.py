"""
Утилита для проверки структуры таблиц в базе данных.
"""
from crypto_trading_bot.database.db_connection import DatabaseManager
from loguru import logger


def check_timeframes_table():
    """
    Проверяет структуру таблицы timeframes.
    """
    try:
        db = DatabaseManager()
        
        # Получаем структуру таблицы
        query = """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'timeframes'
            ORDER BY ordinal_position;
        """
        db.cursor.execute(query)
        columns = db.cursor.fetchall()
        
        logger.info("Структура таблицы timeframes:")
        for col_name, col_type in columns:
            logger.info(f"  - {col_name}: {col_type}")
        
        # Пробуем получить данные
        query = "SELECT * FROM timeframes LIMIT 5;"
        db.cursor.execute(query)
        rows = db.cursor.fetchall()
        
        logger.info(f"\nПримеры данных из timeframes (первые 5 строк):")
        for row in rows:
            logger.info(f"  {row}")
        
        db.close()
        return columns
        
    except Exception as e:
        logger.error(f"Ошибка при проверке структуры таблицы: {e}")
        return None


if __name__ == "__main__":
    check_timeframes_table()

