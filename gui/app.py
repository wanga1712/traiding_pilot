from loguru import logger
from flask import Flask, render_template, request


from gui.data_fetcher import DataFetcher
from gui.visualizer import DataVisualizer

# Инициализация Flask
app = Flask(__name__)

# Инициализация DataImport и DataVisualizer
data_fetcher = DataFetcher()
visualizer = DataVisualizer(data_fetcher)


@app.route('/', methods=['GET', 'POST'])
def index():
    try:
        # Логируем старт запроса
        logger.debug("GET or POST request received for /")

        # Получаем инструменты, таймфреймы и типы индикаторов
        instruments = data_fetcher.get_instruments()
        timeframes = data_fetcher.get_timeframes()
        indicator_types = data_fetcher.get_indicator_types()

        if request.method == 'POST':
            # Логируем начало обработки POST-запроса
            logger.debug("POST request received.")

            selected_instrument = request.form['instrument']
            selected_timeframe = request.form['timeframe']
            selected_indicators = request.form.getlist('indicators')  # Список выбранных индикаторов

            # Логируем данные формы
            logger.debug(f"Selected instrument: {selected_instrument}")
            logger.debug(f"Selected timeframe: {selected_timeframe}")
            logger.debug(f"Selected indicators: {selected_indicators}")

            # Находим соответствующий инструмент и таймфрейм
            selected_instrument_obj = next(i for i in instruments if i.symbol == selected_instrument)
            selected_timeframe_obj = next(t for t in timeframes if t.interval_name == selected_timeframe)

            # Получаем ID инструмента и таймфрейма
            instrument_id = selected_instrument_obj.id
            timeframe_id = selected_timeframe_obj.id

            # Логируем ID
            logger.debug(f"Instrument ID: {instrument_id}, Timeframe ID: {timeframe_id}")

            # Получаем изображение графика с учётом выбранных индикаторов
            img_base64 = visualizer.plot_graph(selected_instrument, selected_timeframe, selected_indicators)

            if img_base64:
                logger.debug("Image generated successfully.")
                return render_template(
                    'index.html',
                    instruments=instruments,
                    timeframes=timeframes,
                    indicators=indicator_types,
                    image=img_base64
                )
            else:
                logger.warning("Failed to generate image.")
                return render_template(
                    'index.html',
                    instruments=instruments,
                    timeframes=timeframes,
                    indicators=indicator_types,
                    image=None
                )

        # Для GET-запросов просто отображаем страницу
        return render_template(
            'index.html',
            instruments=instruments,
            timeframes=timeframes,
            indicators=indicator_types
        )

    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        return render_template('index.html', instruments=[], timeframes=[], indicators=[], image=None)


if __name__ == '__main__':
    app.run(debug=True)
