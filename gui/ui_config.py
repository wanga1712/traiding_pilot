"""
Модуль для хранения всех настроек UI PyQt5.

Этот модуль содержит все настройки, касающиеся:
- Расположения окон (позиция, геометрия)
- Размеров окон и виджетов
- Отображения элементов (видимость, стили)
- Цветов (палитра, темы, стили)

ВСЕ настройки UI должны быть определены здесь, а не в коде виджетов.
"""


class UIConfig:
    """
    Класс для хранения всех настроек UI PyQt5.
    
    Все настройки интерфейса должны быть определены здесь для избежания дублирования
    и централизованного управления стилями приложения.
    """
    
    # ==================== РАЗМЕРЫ ОКОН ====================
    # Главное окно приложения
    # При первом запуске будет полноэкранным
    MAIN_WINDOW_WIDTH = 1920  # По умолчанию (будет переопределено)
    MAIN_WINDOW_HEIGHT = 1080  # По умолчанию (будет переопределено)
    MAIN_WINDOW_MIN_WIDTH = 1200
    MAIN_WINDOW_MIN_HEIGHT = 800
    
    # Панель инструментов (левая)
    INSTRUMENTS_PANEL_WIDTH = 250
    INSTRUMENTS_PANEL_MIN_WIDTH = 200
    
    # Панель графика (правая)
    CHART_PANEL_MIN_WIDTH = 800
    
    # Панель таймфреймов (внизу)
    TIMEFRAME_PANEL_HEIGHT = 60  # Увеличено с 40
    
    # Окно графика
    CHART_WIDGET_WIDTH = 1200
    CHART_WIDGET_HEIGHT = 600
    
    # Панель инструментов
    TOOLBAR_HEIGHT = 60
    TOOLBAR_WIDTH = 200
    
    # Панель сигналов
    SIGNALS_PANEL_WIDTH = 300
    SIGNALS_PANEL_HEIGHT = 400
    
    # Панель настроек
    SETTINGS_PANEL_WIDTH = 250
    SETTINGS_PANEL_HEIGHT = 300
    
    # ==================== ЦВЕТА (TradingView Style) ====================
    # Основные цвета темы (темная тема как у TradingView)
    BACKGROUND_COLOR = "#131722"  # Основной фон (очень темный)
    SECONDARY_BACKGROUND_COLOR = "#1e222d"  # Панели и виджеты
    TERTIARY_BACKGROUND_COLOR = "#2a2e39"  # Границы и разделители
    
    # Цвета текста
    TEXT_COLOR_PRIMARY = "#d1d4dc"  # Основной текст
    TEXT_COLOR_SECONDARY = "#868993"  # Вторичный текст
    TEXT_COLOR_DISABLED = "#5d606b"  # Отключенный текст
    
    # Цвета акцентов (TradingView синий)
    ACCENT_COLOR = "#2962ff"  # Основной акцент (синий TradingView)
    ACCENT_COLOR_HOVER = "#1e53e5"  # При наведении
    ACCENT_COLOR_PRESSED = "#1747cc"  # При нажатии
    
    # Цвета для торговых сигналов
    BUY_SIGNAL_COLOR = "#26a69a"  # Зеленый для покупки
    SELL_SIGNAL_COLOR = "#ef5350"  # Красный для продажи
    NEUTRAL_SIGNAL_COLOR = "#ffa726"  # Оранжевый нейтральный
    
    # Цвета для графиков (TradingView стиль)
    CHART_BACKGROUND_COLOR = "#131722"  # Фон графика
    CHART_GRID_COLOR = "#2a2e39"  # Сетка графика
    CHART_TEXT_COLOR = "#d1d4dc"  # Текст на графике
    
    # Цвета для свечей (TradingView стиль)
    CANDLE_BULLISH_COLOR = "#26a69a"  # Бычьи свечи (зеленый)
    CANDLE_BEARISH_COLOR = "#ef5350"  # Медвежьи свечи (красный)
    
    # Цвета для списка инструментов
    LIST_ITEM_BACKGROUND = "#1e222d"  # Фон элемента списка
    LIST_ITEM_HOVER = "#2a2e39"  # При наведении
    LIST_ITEM_SELECTED = "#2962ff"  # Выбранный элемент
    
    # ==================== СТИЛИ QSS ====================
    # Стиль для главного окна
    MAIN_WINDOW_STYLE = f"""
        QMainWindow {{
            background-color: {BACKGROUND_COLOR};
            color: {TEXT_COLOR_PRIMARY};
        }}
    """
    
    # Стиль для кнопок
    BUTTON_STYLE = f"""
        QPushButton {{
            background-color: {SECONDARY_BACKGROUND_COLOR};
            color: {TEXT_COLOR_PRIMARY};
            border: 1px solid {TERTIARY_BACKGROUND_COLOR};
            border-radius: 4px;
            padding: 12px 24px;
            font-size: 18px;
            min-height: 40px;
        }}
        QPushButton:hover {{
            background-color: {TERTIARY_BACKGROUND_COLOR};
            border-color: {ACCENT_COLOR};
        }}
        QPushButton:pressed {{
            background-color: {ACCENT_COLOR_PRESSED};
        }}
        QPushButton:disabled {{
            background-color: {BACKGROUND_COLOR};
            color: {TEXT_COLOR_DISABLED};
            border-color: {TERTIARY_BACKGROUND_COLOR};
        }}
    """
    
    # Стиль для кнопки покупки
    BUTTON_BUY_STYLE = f"""
        QPushButton {{
            background-color: {BUY_SIGNAL_COLOR};
            color: #000000;
            border: 1px solid {BUY_SIGNAL_COLOR};
            border-radius: 4px;
            padding: 8px 16px;
            font-size: 12px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: #00cc00;
        }}
        QPushButton:pressed {{
            background-color: #00aa00;
        }}
    """
    
    # Стиль для кнопки продажи
    BUTTON_SELL_STYLE = f"""
        QPushButton {{
            background-color: {SELL_SIGNAL_COLOR};
            color: #ffffff;
            border: 1px solid {SELL_SIGNAL_COLOR};
            border-radius: 4px;
            padding: 8px 16px;
            font-size: 12px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: #cc0000;
        }}
        QPushButton:pressed {{
            background-color: #aa0000;
        }}
    """
    
    # Стиль для полей ввода
    LINE_EDIT_STYLE = f"""
        QLineEdit {{
            background-color: {SECONDARY_BACKGROUND_COLOR};
            color: {TEXT_COLOR_PRIMARY};
            border: 1px solid {TERTIARY_BACKGROUND_COLOR};
            border-radius: 4px;
            padding: 6px 12px;
            font-size: 12px;
        }}
        QLineEdit:focus {{
            border-color: {ACCENT_COLOR};
        }}
    """
    
    # Стиль для выпадающих списков
    COMBO_BOX_STYLE = f"""
        QComboBox {{
            background-color: {SECONDARY_BACKGROUND_COLOR};
            color: {TEXT_COLOR_PRIMARY};
            border: 1px solid {TERTIARY_BACKGROUND_COLOR};
            border-radius: 4px;
            padding: 6px 12px;
            font-size: 12px;
        }}
        QComboBox:hover {{
            border-color: {ACCENT_COLOR};
        }}
        QComboBox:focus {{
            border-color: {ACCENT_COLOR};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 6px solid {TEXT_COLOR_PRIMARY};
        }}
    """
    
    # Стиль для таблиц
    TABLE_STYLE = f"""
        QTableWidget {{
            background-color: {BACKGROUND_COLOR};
            color: {TEXT_COLOR_PRIMARY};
            border: 1px solid {TERTIARY_BACKGROUND_COLOR};
            gridline-color: {TERTIARY_BACKGROUND_COLOR};
            font-size: 11px;
        }}
        QTableWidget::item {{
            padding: 4px;
        }}
        QTableWidget::item:selected {{
            background-color: {ACCENT_COLOR};
            color: {TEXT_COLOR_PRIMARY};
        }}
        QHeaderView::section {{
            background-color: {SECONDARY_BACKGROUND_COLOR};
            color: {TEXT_COLOR_PRIMARY};
            padding: 6px;
            border: 1px solid {TERTIARY_BACKGROUND_COLOR};
            font-weight: bold;
        }}
    """
    
    # Стиль для меток
    LABEL_STYLE = f"""
        QLabel {{
            color: {TEXT_COLOR_PRIMARY};
            font-size: 18px;
        }}
    """
    
    # Стиль для меток заголовков
    LABEL_HEADER_STYLE = f"""
        QLabel {{
            color: {TEXT_COLOR_PRIMARY};
            font-size: 22px;
            font-weight: bold;
        }}
    """
    
    # Стиль для панелей
    PANEL_STYLE = f"""
        QWidget {{
            background-color: {SECONDARY_BACKGROUND_COLOR};
            border: 1px solid {TERTIARY_BACKGROUND_COLOR};
            border-radius: 4px;
        }}
    """
    
    # ==================== ШРИФТЫ ====================
    FONT_FAMILY = "Segoe UI"
    # Увеличенные размеры шрифтов для высокого разрешения
    FONT_SIZE_NORMAL = 18  # Было 12
    FONT_SIZE_SMALL = 14    # Было 10
    FONT_SIZE_LARGE = 22    # Было 14
    FONT_SIZE_HEADER = 24  # Было 16
    
    # ==================== ОТСТУПЫ И ПРОМЕЖУТКИ ====================
    MARGIN_SMALL = 5
    MARGIN_MEDIUM = 10
    MARGIN_LARGE = 20
    
    SPACING_SMALL = 5
    SPACING_MEDIUM = 10
    SPACING_LARGE = 15
    
    # ==================== ПОЗИЦИИ ОКОН ====================
    # Позиция главного окна при первом запуске (центр экрана)
    MAIN_WINDOW_X = None  # None означает центрирование
    MAIN_WINDOW_Y = None  # None означает центрирование

