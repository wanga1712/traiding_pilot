"""
Отрисовка графиков.

Содержит функции для отрисовки свечей, объемов и DMA линий.
"""

import pandas as pd
import numpy as np
from matplotlib.dates import date2num
from matplotlib.patches import Rectangle
from loguru import logger

from gui.ui_config import UIConfig
from gui.chart_calculators import calculate_candle_width, prepare_plot_payload
from crypto_trading_bot.analytics.dinapoli_dma import DinapoliDMAService


def draw_price(ax_price, payload):
    """
    Отрисовывает свечной график вручную.
    """
    timestamps = payload['timestamps']
    opens = payload['opens']
    closes = payload['closes']
    highs = payload['highs']
    lows = payload['lows']
    colors = payload['colors']
    width_days = payload['width_days']

    for idx, ts in enumerate(timestamps):
        ax_price.plot(
            [ts, ts],
            [lows[idx], highs[idx]],
            color=colors[idx],
            linewidth=0.5,
            alpha=0.8
        )

    for idx, ts in enumerate(timestamps):
        body_bottom = min(opens[idx], closes[idx])
        body_height = abs(closes[idx] - opens[idx])
        if body_height == 0:
            body_height = (highs[idx] - lows[idx]) * 0.1
            if body_height == 0:
                body_height = (highs.max() - lows.min()) * 0.001
        x_pos = ts - width_days / 2
        candle = Rectangle(
            (x_pos, body_bottom),
            width_days,
            body_height,
            facecolor=colors[idx],
            edgecolor=colors[idx],
            linewidth=0.5
        )
        ax_price.add_patch(candle)

    future_space = width_days * 10
    ax_price.set_xlim(timestamps[0] - width_days, timestamps[-1] + future_space)
    ax_price.set_ylim(lows.min() * 0.99, highs.max() * 1.01)


def draw_volume(ax_volume, payload):
    """
    Отрисовывает гистограмму объемов.
    """
    timestamps = payload['timestamps']
    volumes = payload['volumes']
    colors = payload['colors']
    width_days = payload['width_days']

    ax_volume.bar(
        timestamps,
        volumes,
        width=width_days,
        color=colors,
        align='center',
        alpha=0.5
    )
    if volumes.max() > 0:
        ax_volume.set_ylim(0, volumes.max() * 1.2)
    ax_volume.set_xlim(timestamps[0] - width_days, timestamps[-1] + width_days * 10)


def draw_dma_lines(ax_price, instrument_symbol, timeframe_code, df_index):
    """
    Отрисовывает линии DMA на графике цен.
    
    Параметры:
        ax_price: Ось для отрисовки цен.
        instrument_symbol: Символ инструмента.
        timeframe_code: Код таймфрейма.
        df_index: Индекс DataFrame с временными метками.
    """
    try:
        dma_service = DinapoliDMAService()
        
        dma_colors = {
            (3, 3): '#00ff00',
            (7, 5): '#ffff00',
            (25, 5): '#ff00ff'
        }
        
        for period, displacement in DinapoliDMAService.DMA_COMBINATIONS:
            dma_series = dma_service.get_dma_from_db(
                instrument_symbol, timeframe_code, period, displacement
            )
            
            if dma_series is None or dma_series.empty:
                logger.debug(
                    f"DMA {period}x{displacement} не найдена в БД для "
                    f"{instrument_symbol} на {timeframe_code}"
                )
                continue
            
            logger.debug(
                f"DMA {period}x{displacement} найдена: {len(dma_series)} точек, "
                f"диапазон: {dma_series.index[0]} - {dma_series.index[-1]}"
            )
            
            if dma_series is not None and not dma_series.empty:
                # Приводим оба индекса к timezone-naive для сравнения
                dma_index = dma_series.index.copy()
                if dma_index.tz is not None:
                    dma_index = dma_index.tz_localize(None)
                
                df_index_clean = df_index.copy()
                if df_index_clean.tz is not None:
                    df_index_clean = df_index_clean.tz_localize(None)
                
                # Создаем временный Series с очищенным индексом для фильтрации
                dma_series_clean = pd.Series(dma_series.values, index=dma_index)
                
                # Фильтруем данные по диапазону графика
                # Используем >= и <= чтобы включить граничные значения
                dma_filtered = dma_series_clean[
                    (dma_series_clean.index >= df_index_clean[0]) & 
                    (dma_series_clean.index <= df_index_clean[-1])
                ]
                
                # Если после фильтрации данных нет, но есть данные в БД,
                # используем все доступные данные (они могут быть смещены)
                if dma_filtered.empty and len(dma_series_clean) > 0:
                    logger.debug(
                        f"DMA {period}x{displacement} не попадает в диапазон графика "
                        f"({df_index_clean[0]} - {df_index_clean[-1]}), "
                        f"используем все доступные данные ({len(dma_series_clean)} точек)"
                    )
                    dma_filtered = dma_series_clean
                
                if not dma_filtered.empty:
                    # Убеждаемся, что данные отсортированы по времени
                    dma_filtered = dma_filtered.sort_index()
                    timestamps_num = [date2num(ts) for ts in dma_filtered.index]
                    color = dma_colors.get((period, displacement), '#ffffff')
                    ax_price.plot(
                        timestamps_num,
                        dma_filtered.values,
                        color=color,
                        linewidth=1.5,
                        alpha=0.8,
                        label=f'DMA {period}x{displacement}'
                    )
                    
                    logger.debug(f"DMA {period}x{displacement} отрисована: {len(dma_filtered)} точек")
            else:
                logger.debug(f"DMA {period}x{displacement} не найдена в БД для {instrument_symbol} на {timeframe_code}")
                
    except Exception as e:
        logger.error(f"Ошибка при отрисовке DMA: {e}")
        import traceback
        logger.error(traceback.format_exc())

