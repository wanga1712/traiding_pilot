"""
Модуль для управления схемой базы данных аналитики.

Создает и управляет таблицами для хранения инструментов, таймфреймов и метрик.
"""

from loguru import logger
from typing import List
from crypto_trading_bot.database.db_connection import DatabaseManager


class AnalyticsSchemaManager:
    """
    Менеджер схемы БД для аналитики.
    
    Отвечает за создание и управление таблицами:
    - instruments: инструменты (символы)
    - timeframes: таймфреймы
    - analytics_metrics: рассчитанные метрики
    """
    
    def __init__(self, db_manager: DatabaseManager = None):
        """
        Инициализация менеджера схемы.
        
        Параметры:
            db_manager: Объект DatabaseManager. Если None, создается новый.
        """
        self.db_manager = db_manager or DatabaseManager()
    
    def ensure_schema(self):
        """
        Создает все необходимые таблицы, если они не существуют.
        """
        try:
            self._create_instruments_table()
            self._create_timeframes_table()
            self._create_analytics_metrics_table()
            logger.info("Схема БД для аналитики проверена/создана успешно")
        except Exception as e:
            logger.error(f"Ошибка при создании схемы БД: {e}")
            raise
    
    def _create_instruments_table(self):
        """Создает таблицу instruments, если не существует."""
        query = """
        CREATE TABLE IF NOT EXISTS instruments (
            id SERIAL PRIMARY KEY,
            symbol TEXT UNIQUE NOT NULL,
            name TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
        self.db_manager.execute_query(query)
        logger.debug("Таблица instruments проверена/создана")
    
    def _create_timeframes_table(self):
        """Создает таблицу timeframes, если не существует."""
        query = """
        CREATE TABLE IF NOT EXISTS timeframes (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            seconds INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
        self.db_manager.execute_query(query)
        logger.debug("Таблица timeframes проверена/создана")
    
    def _create_analytics_metrics_table(self):
        """Создает таблицу analytics_metrics, если не существует."""
        query = """
        CREATE TABLE IF NOT EXISTS analytics_metrics (
            id SERIAL PRIMARY KEY,
            instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
            timeframe_id INTEGER NOT NULL REFERENCES timeframes(id) ON DELETE CASCADE,
            metric_type TEXT NOT NULL,
            metric_window INTEGER,
            metric_displacement INTEGER,
            metric_timestamp TIMESTAMPTZ NOT NULL,
            value NUMERIC NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(
                instrument_id, timeframe_id, metric_type,
                metric_window, metric_displacement, metric_timestamp
            )
        );
        
        CREATE INDEX IF NOT EXISTS idx_analytics_metrics_lookup 
        ON analytics_metrics(
            instrument_id, timeframe_id, metric_type,
            metric_window, metric_displacement, metric_timestamp
        );
        """
        self.db_manager.execute_query(query)
        logger.debug("Таблица analytics_metrics проверена/создана")
    
    def ensure_instrument(self, symbol: str) -> int:
        """
        Убеждается, что инструмент существует в БД, возвращает его ID.
        
        Параметры:
            symbol: Символ инструмента (например, 'BTCUSDT').
        
        Возвращает:
            int: ID инструмента.
        """
        # Проверяем, существует ли инструмент
        check_query = "SELECT id FROM instruments WHERE symbol = %s;"
        result = self.db_manager.fetch_one(check_query, (symbol,))
        
        if result:
            return result[0]
        
        # Создаем новый инструмент
        insert_query = """
        INSERT INTO instruments (symbol, name)
        VALUES (%s, %s)
        ON CONFLICT (symbol) DO UPDATE SET updated_at = NOW()
        RETURNING id;
        """
        result = self.db_manager.fetch_one(insert_query, (symbol, symbol))
        if result:
            logger.info(f"Инструмент {symbol} создан/обновлен, ID: {result[0]}")
            return result[0]
        else:
            # Если RETURNING не сработал, получаем ID отдельным запросом
            result = self.db_manager.fetch_one(check_query, (symbol,))
            if result:
                return result[0]
            raise ValueError(f"Не удалось создать/получить инструмент {symbol}")
    
    def ensure_timeframe(self, timeframe_name: str) -> int:
        """
        Убеждается, что таймфрейм существует в БД, возвращает его ID.
        
        Параметры:
            timeframe_name: Название таймфрейма (например, '1d', '1h').
        
        Возвращает:
            int: ID таймфрейма.
        """
        # Получаем структуру таблицы timeframes
        columns = self._get_table_columns('timeframes')
        timeframe_id_column = self._resolve_timeframe_id_column(columns)
        timeframe_name_column = self._resolve_timeframe_name_column(columns)

        # Проверяем наличие таймфрейма по найденной колонке
        check_query = f"SELECT {timeframe_id_column} FROM timeframes WHERE {timeframe_name_column} = %s;"
        result = self.db_manager.fetch_one(check_query, (timeframe_name,))
        if result:
            return result[0]

        # Подготавливаем данные для вставки
        insert_columns = [timeframe_name_column]
        insert_values = [timeframe_name]
        placeholders = ["%s"]

        if 'seconds' in columns:
            insert_columns.append('seconds')
            insert_values.append(self._timeframe_to_seconds(timeframe_name))
            placeholders.append("%s")

        insert_query = f"""
        INSERT INTO timeframes ({', '.join(insert_columns)})
        VALUES ({', '.join(placeholders)})
        RETURNING {timeframe_id_column};
        """

        try:
            with self.db_manager.connection.cursor() as cursor:
                cursor.execute(insert_query, tuple(insert_values))
                inserted = cursor.fetchone()
                self.db_manager.connection.commit()
                if inserted:
                    logger.info(
                        f"Таймфрейм {timeframe_name} создан, ID: {inserted[0]} "
                        f"(колонка: {timeframe_name_column})"
                    )
                    return inserted[0]
        except Exception as insert_error:
            logger.warning(
                f"Не удалось вставить таймфрейм {timeframe_name} "
                f"по колонке {timeframe_name_column}: {insert_error}"
            )
            self.db_manager.connection.rollback()

        # Повторно пытаемся получить ID после возможной вставки другим процессом
        result = self.db_manager.fetch_one(check_query, (timeframe_name,))
        if result:
            return result[0]

        raise ValueError(f"Не удалось создать/получить таймфрейм {timeframe_name}")
    
    def _timeframe_to_seconds(self, timeframe_name: str) -> int:
        """
        Преобразует название таймфрейма в секунды.
        
        Параметры:
            timeframe_name: Название таймфрейма.
        
        Возвращает:
            int: Количество секунд.
        """
        timeframe_name = timeframe_name.lower()
        
        if timeframe_name.endswith('m'):
            minutes = int(timeframe_name[:-1])
            return minutes * 60
        elif timeframe_name.endswith('h'):
            hours = int(timeframe_name[:-1])
            return hours * 3600
        elif timeframe_name.endswith('d'):
            days = int(timeframe_name[:-1])
            return days * 86400
        elif timeframe_name.endswith('w'):
            weeks = int(timeframe_name[:-1])
            return weeks * 604800
        elif timeframe_name.endswith('mo'):
            months = int(timeframe_name[:-2])
            return months * 2592000  # Приблизительно
        else:
            logger.warning(f"Неизвестный формат таймфрейма: {timeframe_name}, возвращаем 0")
            return 0

    def _get_table_columns(self, table_name: str) -> List[str]:
        """
        Возвращает список колонок заданной таблицы.
        """
        query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position;
        """
        rows = self.db_manager.fetch_all(query, (table_name,))
        columns = [row[0] for row in rows] if rows else []
        if not columns:
            raise ValueError(f"Таблица {table_name} не найдена в базе данных")
        return columns

    def _resolve_timeframe_name_column(self, columns: List[str]) -> str:
        """
        Определяет колонку, в которой хранится текстовое представление таймфрейма.
        """
        preferred = ['name', 'interval_name', 'timeframe_name', 'code', 'api_value', 'timeframe']
        for candidate in preferred:
            if candidate in columns:
                return candidate
        if len(columns) > 1:
            return columns[1]
        raise ValueError("Не удалось определить колонку с названием таймфрейма")

    def _resolve_timeframe_id_column(self, columns: List[str]) -> str:
        """
        Определяет колонку, содержащую идентификатор таймфрейма.
        """
        if 'id' in columns:
            return 'id'
        return columns[0]

