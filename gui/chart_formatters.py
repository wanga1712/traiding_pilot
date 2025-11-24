"""
Форматирование осей графика.

Содержит функции для форматирования осей X и Y.
"""

from matplotlib.ticker import FuncFormatter
from matplotlib.dates import DateFormatter, AutoDateLocator, num2date, date2num
from loguru import logger


def apply_price_formatter(axis):
    """
    Настраивает форматирование оси Y для отображения полных цен.
    """
    if axis is None:
        return
    axis.ticklabel_format(style='plain', axis='y', useOffset=False)

    def price_formatter(value, _):
        return f"{value:,.2f}".replace(",", " ")

    axis.yaxis.set_major_formatter(FuncFormatter(price_formatter))


def apply_time_axis_formatting(axis, timeframe_code, df):
    """
    Применяет форматирование оси X в зависимости от таймфрейма.
    """
    if '1d' in timeframe_code or '1D' in timeframe_code:
        date_format = DateFormatter('%d %b')
        locator = AutoDateLocator(maxticks=12)
    elif '1w' in timeframe_code or '1mo' in timeframe_code:
        date_format = DateFormatter('%d.%m')
        locator = AutoDateLocator(maxticks=15)
    elif ('1h' in timeframe_code or '2h' in timeframe_code or '4h' in timeframe_code or
          '6h' in timeframe_code or '12h' in timeframe_code):
        date_format = DateFormatter('%d.%m %H:%M')
        locator = AutoDateLocator(maxticks=15)
    else:
        date_format = DateFormatter('%H:%M')
        locator = AutoDateLocator(maxticks=20)

    axis.xaxis.set_major_locator(locator)
    axis.xaxis.set_major_formatter(date_format)

    x_min, x_max = axis.get_xlim()
    try:
        date_min = num2date(x_min)
        date_max = num2date(x_max)
        logger.debug(f"Пределы оси X (даты): {date_min} - {date_max}")

        if date_min.year < 2020 or date_max.year < 2020:
            logger.warning("Даты на оси X неправильные, исправляем...")
            x_min_correct = date2num(df.index[0])
            x_max_correct = date2num(df.index[-1])

            if len(df) > 1:
                time_diffs = df.index.to_series().diff().dropna()
                if len(time_diffs) > 0:
                    avg_time_diff = time_diffs.mean()
                    width_days = avg_time_diff.total_seconds() / 86400.0
                else:
                    width_days = (x_max_correct - x_min_correct) / len(df) if len(df) > 0 else 1.0
            else:
                width_days = (x_max_correct - x_min_correct) if (x_max_correct - x_min_correct) > 0 else 1.0

            future_space = width_days * 10
            axis.set_xlim(x_min_correct, x_max_correct + future_space)
    except Exception as date_err:
        logger.error(f"Ошибка преобразования числовых значений в даты: {date_err}")

