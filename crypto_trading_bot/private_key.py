import time
import hmac
import hashlib
from urllib.parse import urlencode

api_key = 'YOUR_API_KEY'
api_secret = 'YOUR_API_SECRET'

# Параметры запроса
params = {
    "api_key": api_key,
    "timestamp": str(int(time.time() * 1000)),  # текущее время в миллисекундах
    "recv_window": "5000"
}

# Сортировка параметров и формирование строки запроса
sorted_params = sorted(params.items())
query_string = urlencode(sorted_params)

# Генерация подписи
message = f"{query_string}&api_key={api_key}&timestamp={params['timestamp']}&recv_window={params['recv_window']}"
signature = hmac.new(api_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()

print("Generated signature:", signature)
