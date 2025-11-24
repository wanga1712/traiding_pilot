from loguru import logger

from crypto_trading_bot.trading.exchange_connection import HuobiConnector


class SpotTrade(HuobiConnector):
    def __init__(self):
        super().__init__()  # Наследуем все атрибуты и методы от HuobiConnector

    def get_balance(self, wallet_type='spot'):
        """Получение баланса счета по типу кошелька"""
        try:
            # Получаем баланс через AccountClient
            account_balance_list = self.account_client.get_account_balance()

            if not account_balance_list:
                logger.warning(f"No account balances found for wallet type '{wallet_type}'.")
                return None

            has_non_zero_balance = False

            for account in account_balance_list:
                if account.type == wallet_type:  # Фильтруем по типу

                    # Проверяем каждый баланс
                    for balance in account.list:
                        balance_value = float(balance.balance)
                        if balance_value > 0:
                            has_non_zero_balance = True
                            logger.info(f"Валюта: {balance.currency}, Баланс: {balance_value}")

                    if not has_non_zero_balance:
                        logger.warning(f"Баланс {wallet_type} кошелька равен 0 для всех валют.")
                    return account  # Возвращаем объект аккаунта с нужным типом

            logger.warning(f"No accounts of type '{wallet_type}' found.")
            return None
        except Exception as e:
            logger.error(f"Error fetching {wallet_type} balance: {str(e)}")
            raise
