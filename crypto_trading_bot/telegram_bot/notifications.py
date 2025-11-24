from datetime import datetime
import pytz

# Дата начала 12 декабря 2024 года в UTC
start_date = datetime(2024, 12, 12, 0, 0, 0)

# Получаем временную зону
timezone = 'Europe/Moscow'
tz = pytz.timezone(timezone)

# Локализуем дату для временной зоны Москвы
localized_start_date = tz.localize(start_date)

# Преобразуем в Unix timestamp
start_timestamp = int(localized_start_date.timestamp())

print(f"Start timestamp для 12 декабря 2024: {start_timestamp}")
