import hashlib
import hmac
import time
import requests
from urllib.parse import urlencode
from loguru import logger

from crypto_trading_bot.config.config import CONFIG
from huobi.client.account import AccountClient  # Импортируем клиента для работы с учетной записью


class HuobiConnector:
    def __init__(self):
        self.api_key = CONFIG['API']['API_KEY']
        self.secret_key = CONFIG['API']['SECRET_KEY']
        self.base_url = CONFIG['API']['API_URL']
        self.ws_url = CONFIG['API']['WS_URL']
        self.account_client = AccountClient(api_key=self.api_key, secret_key=self.secret_key)  # Client for account

    def _generate_signature(self, params):
        """Генерация подписи для API запроса"""
        try:
            # Сортируем параметры по ключам
            query_string = urlencode(sorted(params.items()))

            # Строка для подписи
            signature_payload = f"GET\n{self.base_url.replace('https://', '')}\n{params['path']}\n{query_string}"

            # Генерация подписи с использованием HMAC
            signature = hmac.new(
                self.secret_key.encode('utf-8'),
                signature_payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest().upper()

            return signature
        except Exception as e:
            logger.error(f"Ошибка при генерации подписи: {e}")
            raise

    def _get(self, path, params):
        """GET запрос к API Huobi"""
        try:
            # Убедитесь, что путь передан в параметрах
            if 'path' not in params:
                raise ValueError("Отсутствует параметр 'path'")

            # Добавляем API ключ в параметры
            params['api_key'] = self.api_key

            # Генерация подписи для запроса
            params['signature'] = self._generate_signature(params)

            # Выполнение GET-запроса
            response = requests.get(f"{self.base_url}{path}", params=params)
            response.raise_for_status()  # Проверка на ошибки HTTP

            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка запроса: {e}")
            raise
        except Exception as e:
            logger.error(f"Ошибка при GET запросе: {e}")
            raise

    def _post(self, path, params):
        """POST запрос к API Huobi"""
        try:
            params['api_key'] = self.api_key
            params['signature'] = self._generate_signature(params)
            response = requests.post(f"{self.base_url}{path}", data=params)
            response.raise_for_status()  # Проверка на ошибки HTTP
            logger.info(f"POST request to {path} successful, status code: {response.status_code}")
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Error in POST request: {e}")
            raise
