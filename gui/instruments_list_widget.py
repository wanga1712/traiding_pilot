"""
Виджет списка инструментов.

Отображает список инструментов с поддержкой двойного клика для выбора.
"""

from PyQt5.QtWidgets import QListWidget, QListWidgetItem
from PyQt5.QtCore import Qt, pyqtSignal
from loguru import logger

from gui.ui_config import UIConfig


class InstrumentsListWidget(QListWidget):
    """
    Виджет списка инструментов с поддержкой двойного клика.
    """
    
    instrument_selected = pyqtSignal(str)  # Сигнал при выборе инструмента
    
    def __init__(self, parent=None):
        """Инициализация списка инструментов."""
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        """Настройка UI списка."""
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {UIConfig.SECONDARY_BACKGROUND_COLOR};
                color: {UIConfig.TEXT_COLOR_PRIMARY};
                border: none;
                font-size: {UIConfig.FONT_SIZE_NORMAL}px;
            }}
            QListWidget::item {{
                padding: 12px;
                border-bottom: 1px solid {UIConfig.TERTIARY_BACKGROUND_COLOR};
                min-height: 40px;
            }}
            QListWidget::item:hover {{
                background-color: {UIConfig.LIST_ITEM_HOVER};
            }}
            QListWidget::item:selected {{
                background-color: {UIConfig.LIST_ITEM_SELECTED};
                color: white;
            }}
        """)
        
        self.itemDoubleClicked.connect(self.on_item_double_clicked)
        
    def load_instruments(self, instruments):
        """
        Загружает список инструментов в виджет.
        
        Параметры:
            instruments: Список объектов Instrument.
        """
        self.clear()
        for instrument in instruments:
            item = QListWidgetItem(instrument.symbol)
            item.setData(Qt.UserRole, instrument.symbol)
            self.addItem(item)
        
        logger.debug(f"Загружено {len(instruments)} инструментов в список")
    
    def on_item_double_clicked(self, item):
        """Обработчик двойного клика по элементу списка."""
        symbol = item.data(Qt.UserRole)
        if symbol:
            logger.info(f"Выбран инструмент: {symbol}")
            self.instrument_selected.emit(symbol)

