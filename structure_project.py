import os

# Структура проекта
project_structure = {
    "crypto_trading_bot": {
        "data": [],
        "database": ["db_connection.py", "data_export.py", "data_import.py"],
        "indicators": {
            "dinapoli.py": [
                "fibonacci.py",
                "smoothed_sma.py",
                "smoothed_macd.py",
                "smoothed_stochastic.py",
                "predictor.py"
            ],
            "standart.py": [
                "sma.py",
                "rsi.py",
                "macd.py"
            ]
        },
        "strategies": ["moving_average.py", "breakout.py"],
        "backtesting": ["backtest.py", "visualization.py"],
        "trading": ["data_fetcher.py", "auto_trader.py", "portfolio_manager.py"],
        "visualization": ["plot_candlestick.py", "indicators_visualization.py"],
        "telegram_bot": ["notifications.py", "portfolio_bot.py"],
        "utils": ["logging.py", "config_parser.py", "error_handler.py"],
        "tests": ["test_indicators.py", "test_database.py"],
        "requirements.txt": [],
        "config": [],
        "main.py": []
    }
}


def create_structure(base_path, structure):
    for folder, files in structure.items():
        folder_path = os.path.join(base_path, folder)
        os.makedirs(folder_path, exist_ok=True)

        # Если есть вложенные папки (например, для индикаторов), создаем их
        if isinstance(files, dict):
            for subfolder, subfiles in files.items():
                subfolder_path = os.path.join(folder_path, subfolder)
                os.makedirs(subfolder_path, exist_ok=True)
                for file in subfiles:
                    file_path = os.path.join(subfolder_path, file)
                    with open(file_path, 'w') as f:
                        pass  # Создаем пустой файл
        else:
            # Если файлы, создаем их прямо в текущей папке
            for file in files:
                file_path = os.path.join(folder_path, file)
                with open(file_path, 'w') as f:
                    pass  # Создаем пустой файл


# Указываем путь к корневой папке проекта
base_path = "crypto_trading_bot"

# Создаем структуру
create_structure(base_path, project_structure)

print("Структура проекта успешно создана!")
