"""
Скрипт для проверки структуры таблиц базы данных и их связей.
"""
from crypto_trading_bot.database.db_connection import DatabaseManager
from loguru import logger

def check_database_schema():
    """
    Проверяет структуру таблиц базы данных и их связи.
    """
    try:
        db = DatabaseManager()
        
        # Получаем список всех таблиц
        query_tables = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """
        db.cursor.execute(query_tables)
        tables = [row[0] for row in db.cursor.fetchall()]
        
        print("\n" + "=" * 60)
        print("ТАБЛИЦЫ В БАЗЕ ДАННЫХ")
        print("=" * 60)
        for table in tables:
            print(f"  - {table}")
        print("=" * 60 + "\n")
        
        # Проверяем структуру основных таблиц
        main_tables = ['instruments', 'timeframes', 'price_data']
        
        for table_name in main_tables:
            if table_name not in tables:
                logger.warning(f"Таблица {table_name} не найдена")
                continue
            
            print(f"\n{'=' * 60}")
            print(f"СТРУКТУРА ТАБЛИЦЫ: {table_name}")
            print("=" * 60)
            
            query_columns = """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = %s
                ORDER BY ordinal_position;
            """
            db.cursor.execute(query_columns, (table_name,))
            columns = db.cursor.fetchall()
            
            for col_name, col_type, is_nullable, col_default in columns:
                nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
                default = f" DEFAULT {col_default}" if col_default else ""
                print(f"  {col_name:<25} {col_type:<20} {nullable}{default}")
        
        # Проверяем внешние ключи (связи между таблицами)
        print(f"\n{'=' * 60}")
        print("СВЯЗИ МЕЖДУ ТАБЛИЦАМИ (FOREIGN KEYS)")
        print("=" * 60)
        
        query_fk = """
            SELECT
                tc.table_name, 
                kcu.column_name, 
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name 
            FROM information_schema.table_constraints AS tc 
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
            ORDER BY tc.table_name;
        """
        db.cursor.execute(query_fk)
        foreign_keys = db.cursor.fetchall()
        
        if foreign_keys:
            for fk in foreign_keys:
                table, column, ref_table, ref_column = fk
                print(f"  {table}.{column} -> {ref_table}.{ref_column}")
        else:
            print("  Внешние ключи не найдены (возможно, используются индексы)")
        
        print("=" * 60 + "\n")
        
        # Проверяем данные в таблицах
        print(f"{'=' * 60}")
        print("СТАТИСТИКА ДАННЫХ")
        print("=" * 60)
        
        for table_name in main_tables:
            if table_name not in tables:
                continue
            
            query_count = f"SELECT COUNT(*) FROM {table_name};"
            db.cursor.execute(query_count)
            count = db.cursor.fetchone()[0]
            print(f"  {table_name}: {count} записей")
        
        print("=" * 60 + "\n")
        
        db.close()
        
    except Exception as e:
        logger.error(f"Ошибка при проверке структуры БД: {e}")
        raise


if __name__ == "__main__":
    check_database_schema()

