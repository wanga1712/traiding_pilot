"""
Модуль для управления подключением к базе данных PostgreSQL.

Содержит класс DatabaseManager для работы с базой данных.
"""
from loguru import logger
import os
import psycopg2
from dotenv import load_dotenv
from pathlib import Path


class DatabaseManager:
    """
    Класс для управления подключением и взаимодействием с базой данных PostgreSQL.

    Атрибуты:
        connection (psycopg2.extensions.connection): Объект соединения с базой данных.
        cursor (psycopg2.extensions.cursor): Курсор для выполнения SQL-запросов к базе данных.
        db_host (str): Хост базы данных.
        db_name (str): Название базы данных.
        db_user (str): Имя пользователя базы данных.
        db_password (str): Пароль пользователя базы данных.
        db_port (str): Порт подключения к базе данных.
    """

    def __init__(self, env_file_path=None):
        """
        Инициализация объекта DatabaseManager.

        Загружает настройки подключения из файла .env, устанавливает соединение 
        с базой данных и инициализирует курсор.

        Параметры:
            env_file_path (str, optional): Путь к файлу .env с настройками БД.
                Если не указан, используется путь относительно текущего файла.

        Исключения:
            Exception: В случае ошибки подключения к базе данных.
        """
        # Определяем путь к файлу .env (убираем хардкод)
        if env_file_path is None:
            # Путь относительно текущего файла
            current_dir = Path(__file__).parent
            env_file_path = current_dir / "db_credintials.env"
        
        # Загружаем переменные окружения из файла .env
        load_dotenv(dotenv_path=str(env_file_path))

        # Получаем данные для подключения к базе данных
        self.db_host = os.getenv("DB_HOST")
        self.db_name = os.getenv("DB_DATABASE")
        self.db_user = os.getenv("DB_USER")
        self.db_password = os.getenv("DB_PASSWORD")
        self.db_port = os.getenv("DB_PORT")

        try:
            # Проверяем наличие всех необходимых параметров
            if not all([self.db_host, self.db_name, self.db_user, self.db_password, self.db_port]):
                missing = [k for k, v in {
                    'DB_HOST': self.db_host,
                    'DB_DATABASE': self.db_name,
                    'DB_USER': self.db_user,
                    'DB_PASSWORD': self.db_password,
                    'DB_PORT': self.db_port
                }.items() if not v]
                error_msg = f"Отсутствуют параметры подключения к БД: {', '.join(missing)}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Устанавливаем соединение с базой данных
            logger.info(f"Подключение к базе данных {self.db_name} на {self.db_host}:{self.db_port}...")
            self.connection = psycopg2.connect(
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                host=self.db_host,
                port=self.db_port
            )

            # Инициализируем курсор для выполнения операций с базой данных
            self.cursor = self.connection.cursor()
            logger.info(f'Успешно подключился к базе данных {self.db_name}.')
        except psycopg2.OperationalError as e:
            # Специальная обработка ошибок подключения
            error_msg = str(e)
            if "password authentication failed" in error_msg:
                logger.error(f'Ошибка аутентификации: неверный пароль для пользователя {self.db_user}')
                logger.error('Проверьте пароль в файле db_credintials.env')
            elif "could not connect to server" in error_msg:
                logger.error(f'Не удалось подключиться к серверу {self.db_host}:{self.db_port}')
                logger.error('Убедитесь, что PostgreSQL запущен и доступен')
            elif "database" in error_msg.lower() and "does not exist" in error_msg.lower():
                logger.error(f'База данных {self.db_name} не существует')
                logger.error('Создайте базу данных или проверьте имя в db_credintials.env')
            else:
                logger.error(f'Ошибка подключения к базе данных: {error_msg}')
            raise
        except Exception as e:
            # Логируем и выбрасываем исключение в случае ошибки подключения
            logger.exception(f'Неожиданная ошибка при подключении к базе данных: {e}')
            raise

    def fetch_one(self, query, params=None):
        """
        Выполняет SQL-запрос и возвращает одну запись.

        Параметры:
            query (str): SQL-запрос.
            params (tuple, optional): Параметры для подстановки в запрос.

        Возвращает:
            tuple: Первая запись из результата выполнения запроса или None, если записей нет.

        Исключения:
            Exception: В случае ошибки выполнения запроса.
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
                result = cursor.fetchone()
                return result
        except Exception as e:
            logger.error(f"Ошибка выполнения запроса fetch_one: {e}")
            raise

    def fetch_all(self, query, params=None):
        """
        Выполняет SQL-запрос и возвращает все записи.

        Параметры:
            query (str): SQL-запрос.
            params (tuple, optional): Параметры для подстановки в запрос.

        Возвращает:
            list: Список всех записей из результата выполнения запроса.

        Исключения:
            Exception: В случае ошибки выполнения запроса.
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
                result = cursor.fetchall()
                return result
        except Exception as e:
            logger.error(f"Ошибка выполнения запроса fetch_all: {e}")
            raise

    def execute_query(self, query, params=None, commit=True):
        """
        Выполняет SQL-запрос без возврата данных (например, INSERT, UPDATE, DELETE).

        Параметры:
            query (str): SQL-запрос.
            params (tuple, optional): Параметры для подстановки в запрос.
            commit (bool): Если True, автоматически коммитит транзакцию. 
                          Если False, изменения нужно закоммитить вручную.

        Исключения:
            Exception: В случае ошибки выполнения запроса.
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
                if commit:
                    self.connection.commit()
        except Exception as e:
            logger.error(f"Ошибка выполнения запроса: {e}")
            self.connection.rollback()
            raise

    def close(self):
        """
        Закрывает соединение с базой данных.
        """
        if self.connection:
            self.connection.close()
            logger.info("Соединение с базой данных закрыто.")
