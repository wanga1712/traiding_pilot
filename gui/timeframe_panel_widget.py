"""
Виджет панели выбора таймфрейма.

Отображает кнопки для выбора таймфрейма графика.
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import pyqtSignal
from loguru import logger

from gui.ui_config import UIConfig


class TimeframePanelWidget(QWidget):
    """
    Панель выбора таймфрейма.
    """
    
    timeframe_changed = pyqtSignal(str)  # Сигнал при изменении таймфрейма
    
    def __init__(self, parent=None):
        """Инициализация панели таймфреймов."""
        super().__init__(parent)
        self.current_timeframe = "1d"
        self.setup_ui()
        
    def setup_ui(self):
        """Настройка UI панели."""
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)
        
        label = QLabel("Таймфрейм:")
        label.setStyleSheet(f"color: {UIConfig.TEXT_COLOR_PRIMARY}; font-size: {UIConfig.FONT_SIZE_NORMAL}px;")
        layout.addWidget(label)
        
        timeframes = [
            ("1m", "1m"), ("3m", "3m"), ("5m", "5m"), ("15m", "15m"), ("30m", "30m"),
            ("1h", "1h"), ("2h", "2h"), ("4h", "4h"), ("6h", "6h"), ("12h", "12h"),
            ("1d", "1D"), ("1w", "1W"), ("1mo", "1M")
        ]
        
        for code, label_text in timeframes:
            btn = QPushButton(label_text)
            btn.setCheckable(True)
            btn.setMinimumSize(60, 50)
            btn.clicked.connect(lambda checked, c=code: self.on_timeframe_clicked(c))
            
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {UIConfig.SECONDARY_BACKGROUND_COLOR};
                    color: {UIConfig.TEXT_COLOR_PRIMARY};
                    border: 1px solid {UIConfig.TERTIARY_BACKGROUND_COLOR};
                    border-radius: 4px;
                    font-size: {UIConfig.FONT_SIZE_NORMAL}px;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background-color: {UIConfig.TERTIARY_BACKGROUND_COLOR};
                }}
                QPushButton:checked {{
                    background-color: {UIConfig.ACCENT_COLOR};
                    color: white;
                    border-color: {UIConfig.ACCENT_COLOR};
                }}
            """)
            
            layout.addWidget(btn)
            setattr(self, f"btn_{code}", btn)
        
        layout.addStretch()
        self.setLayout(layout)
        self.set_timeframe("1d")
        self.setStyleSheet(f"background-color: {UIConfig.SECONDARY_BACKGROUND_COLOR};")
    
    def set_timeframe(self, timeframe_code: str):
        """
        Устанавливает активный таймфрейм.
        
        Параметры:
            timeframe_code: Код таймфрейма.
        """
        for code in ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w", "1mo"]:
            btn = getattr(self, f"btn_{code}", None)
            if btn:
                btn.setChecked(False)
        
        btn = getattr(self, f"btn_{timeframe_code}", None)
        if btn:
            btn.setChecked(True)
            self.current_timeframe = timeframe_code
    
    def on_timeframe_clicked(self, timeframe_code: str):
        """Обработчик клика по кнопке таймфрейма."""
        self.set_timeframe(timeframe_code)
        logger.info(f"Выбран таймфрейм: {timeframe_code}")
        self.timeframe_changed.emit(timeframe_code)

