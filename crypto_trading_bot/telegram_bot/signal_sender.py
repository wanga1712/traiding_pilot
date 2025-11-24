"""
Модуль для автоматической отправки торговых сигналов в Telegram канал.

Отправляет сигналы с информацией о входе, выходе, профите и других параметрах.
"""
from loguru import logger
from typing import Dict, Optional
from datetime import datetime
import requests
import os
from dotenv import load_dotenv


class TelegramSignalSender:
    """
    Класс для отправки торговых сигналов в Telegram канал.
    
    Отправляет структурированные сообщения с информацией о:
    - Инструменте
    - Типе сигнала (BUY/SELL)
    - Ценах входа/выхода
    - Планируемом профите
    - Стоп-лоссе
    - Других параметрах стратегии
    """
    
    def __init__(self, bot_token: Optional[str] = None, channel_id: Optional[str] = None):
        """
        Инициализация отправителя сигналов.
        
        Параметры:
            bot_token (str, optional): Токен Telegram бота. Если не указан, загружается из .env.
            channel_id (str, optional): ID канала. Если не указан, загружается из .env.
        """
        # Загружаем переменные окружения
        load_dotenv('api_keys.env')
        
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.channel_id = channel_id or os.getenv('TELEGRAM_CHAT_ID')
        
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN не установлен. Отправка сигналов будет недоступна.")
        if not self.channel_id:
            logger.warning("TELEGRAM_CHAT_ID не установлен. Отправка сигналов будет недоступна.")
        
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
    
    def send_signal(self, signal_data: Dict) -> bool:
        """
        Отправляет торговый сигнал в Telegram канал.
        
        Параметры:
            signal_data (dict): Словарь с данными сигнала:
                - symbol (str): Символ инструмента (например, 'BTCUSDT')
                - signal_type (str): Тип сигнала ('BUY' или 'SELL')
                - entry_price (float): Цена входа
                - target_price (float): Целевая цена (take profit)
                - stop_loss (float): Стоп-лосс цена
                - timeframe (str): Таймфрейм
                - strategy_name (str): Название стратегии
                - pattern_type (str): Тип паттерна
                - expected_profit_percent (float): Ожидаемая прибыль в процентах
                - risk_reward_ratio (float): Соотношение риск/прибыль
        
        Возвращает:
            bool: True если сигнал отправлен успешно, False в противном случае.
        """
        if not self.bot_token or not self.channel_id:
            logger.error("Не настроены параметры Telegram. Сигнал не отправлен.")
            return False
        
        try:
            # Формируем сообщение
            message = self._format_signal_message(signal_data)
            
            # Отправляем сообщение
            payload = {
                'chat_id': self.channel_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            response = requests.post(self.api_url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info(f"Сигнал для {signal_data.get('symbol')} отправлен в Telegram")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при отправке сигнала в Telegram: {e}")
            return False
    
    def _format_signal_message(self, signal_data: Dict) -> str:
        """
        Форматирует данные сигнала в HTML сообщение для Telegram.
        
        Параметры:
            signal_data (dict): Данные сигнала.
        
        Возвращает:
            str: Отформатированное HTML сообщение.
        """
        symbol = signal_data.get('symbol', 'N/A')
        signal_type = signal_data.get('signal_type', 'N/A')
        entry_price = signal_data.get('entry_price', 0)
        target_price = signal_data.get('target_price', 0)
        stop_loss = signal_data.get('stop_loss', 0)
        timeframe = signal_data.get('timeframe', 'N/A')
        strategy_name = signal_data.get('strategy_name', 'Паттерн')
        pattern_type = signal_data.get('pattern_type', 'N/A')
        expected_profit = signal_data.get('expected_profit_percent', 0)
        risk_reward = signal_data.get('risk_reward_ratio', 0)
        
        # Определяем эмодзи для типа сигнала
        signal_emoji = "🟢" if signal_type == "BUY" else "🔴"
        
        # Форматируем сообщение
        message = f"""
{signal_emoji} <b>ТОРГОВЫЙ СИГНАЛ</b> {signal_emoji}

📊 <b>Инструмент:</b> {symbol}
📈 <b>Сигнал:</b> {signal_type}
⏰ <b>Таймфрейм:</b> {timeframe}
🎯 <b>Стратегия:</b> {strategy_name}
🔷 <b>Паттерн:</b> {pattern_type}

💰 <b>ЦЕНЫ:</b>
├ Вход: ${entry_price:,.2f}
├ Цель: ${target_price:,.2f}
└ Стоп: ${stop_loss:,.2f}

📊 <b>ПАРАМЕТРЫ:</b>
├ Ожидаемая прибыль: {expected_profit:.2f}%
└ Риск/Прибыль: 1:{risk_reward:.2f}

⏳ <b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚠️ <i>Это не финансовая рекомендация. Торгуйте на свой риск.</i>
"""
        return message.strip()
    
    def send_backtest_results(self, backtest_data: Dict) -> bool:
        """
        Отправляет результаты бектестинга в Telegram канал.
        
        Параметры:
            backtest_data (dict): Данные бектестинга:
                - strategy_name (str): Название стратегии
                - total_trades (int): Общее количество сделок
                - winning_trades (int): Количество прибыльных сделок
                - losing_trades (int): Количество убыточных сделок
                - total_profit (float): Общая прибыль
                - win_rate (float): Процент прибыльных сделок
                - max_drawdown (float): Максимальная просадка
                - sharpe_ratio (float): Коэффициент Шарпа
        
        Возвращает:
            bool: True если сообщение отправлено успешно.
        """
        if not self.bot_token or not self.channel_id:
            logger.error("Не настроены параметры Telegram.")
            return False
        
        try:
            message = self._format_backtest_message(backtest_data)
            
            payload = {
                'chat_id': self.channel_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(self.api_url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info("Результаты бектестинга отправлены в Telegram")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при отправке результатов бектестинга: {e}")
            return False
    
    def _format_backtest_message(self, backtest_data: Dict) -> str:
        """
        Форматирует результаты бектестинга в HTML сообщение.
        
        Параметры:
            backtest_data (dict): Данные бектестинга.
        
        Возвращает:
            str: Отформатированное сообщение.
        """
        strategy_name = backtest_data.get('strategy_name', 'N/A')
        total_trades = backtest_data.get('total_trades', 0)
        winning_trades = backtest_data.get('winning_trades', 0)
        losing_trades = backtest_data.get('losing_trades', 0)
        total_profit = backtest_data.get('total_profit', 0)
        win_rate = backtest_data.get('win_rate', 0)
        max_drawdown = backtest_data.get('max_drawdown', 0)
        sharpe_ratio = backtest_data.get('sharpe_ratio', 0)
        
        message = f"""
📊 <b>РЕЗУЛЬТАТЫ БЕКТЕСТИНГА</b>

🎯 <b>Стратегия:</b> {strategy_name}

📈 <b>СТАТИСТИКА:</b>
├ Всего сделок: {total_trades}
├ Прибыльных: {winning_trades} ✅
├ Убыточных: {losing_trades} ❌
└ Винрейт: {win_rate:.2f}%

💰 <b>ПРИБЫЛЬНОСТЬ:</b>
├ Общая прибыль: {total_profit:.2f}%
├ Макс. просадка: {max_drawdown:.2f}%
└ Коэф. Шарпа: {sharpe_ratio:.2f}

⏳ <b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return message.strip()
    
    def test_connection(self) -> bool:
        """
        Проверяет подключение к Telegram API.
        
        Возвращает:
            bool: True если подключение успешно.
        """
        if not self.bot_token or not self.channel_id:
            return False
        
        try:
            test_url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(test_url, timeout=5)
            response.raise_for_status()
            logger.info("Подключение к Telegram API успешно")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к Telegram API: {e}")
            return False


if __name__ == "__main__":
    """
    Тестовый запуск для проверки отправки сигналов.
    """
    sender = TelegramSignalSender()
    
    # Проверяем подключение
    if sender.test_connection():
        # Тестовый сигнал
        test_signal = {
            'symbol': 'BTCUSDT',
            'signal_type': 'BUY',
            'entry_price': 45000.0,
            'target_price': 45900.0,
            'stop_loss': 44550.0,
            'timeframe': '1day',
            'strategy_name': 'Пробой линии поддержки',
            'pattern_type': 'line_breakout',
            'expected_profit_percent': 2.0,
            'risk_reward_ratio': 2.0
        }
        
        sender.send_signal(test_signal)
    else:
        print("Не удалось подключиться к Telegram. Проверьте настройки.")

